"""The engine: clean a book, split it into chapters and chunks, retrieve, answer with a voice.

The steps are the ones from the course project. Everything on top (voices, the spoiler
limit, the mood of the room) is a thin layer over the same retriever and the same chain.
"""
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from seance import backends
from seance.books import BOOKS, NARRATOR

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB = ROOT / "chroma_db"

load_dotenv(os.environ.get("SEANCE_ENV_FILE", ROOT / ".env"))

# all-MiniLM-L6-v2 reads at most 256 tokens; measured over all eight books, 800 characters
# stay under that limit, while 1200 would hide up to 10 % of the text from the search.
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
TOP_K = 6
CONTEXT_CHARS = 700
HISTORY_MESSAGES = 4

# Anchor sentences for the mood of a passage. Comparing a passage with these reuses the
# embedding model, so the room can react to the text without any extra call to the LLM.
MOODS = {
    "dread": ("terror and dread, a horrible fear in the darkness of the night", "#7a1f35"),
    "sorrow": ("grief, tears, mourning, loneliness and despair", "#2c4f8a"),
    "fury": ("rage, violence, a raging storm, anger and revenge", "#b8391f"),
    "wonder": ("wonder, magic and awe at a strange and marvellous sight", "#6a4bd8"),
    "joy": ("joy, laughter, friendship and a warm happy celebration", "#d9a521"),
    "calm": ("a quiet and peaceful scene, a calm and careful explanation", "#2f8a6f"),
}


def normalise(text):
    """Straight quotes and single spaces, so that quotes can be compared with the book."""
    for curly, plain in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"')):
        text = text.replace(curly, plain)
    return re.sub(r"\s+", " ", text)


def clean_text(raw):
    """Keep the book between the Gutenberg markers and join the wrapped lines of paragraphs."""
    start = re.search(r"\*\*\* START OF.*?\*\*\*", raw).end()
    end = re.search(r"\*\*\* END OF", raw).start()
    body = raw[start:end].strip()
    body = re.sub(r"\[Illustration[^\]]*\]", "", body)
    body = re.sub(r"\[Footnote[^\]]*\]", "", body)
    body = re.sub(r"\[\d+\]", "", body)  # would be confused with our own citations
    body = re.sub(r"(?<=\w)\(\d+\)", "", body)
    body = re.sub(r"_([^_]+)_", r"\1", body)
    body = re.sub(r"(?<!\n)\n(?!\n)", " ", body)
    body = re.sub(r"[ \t]+\n", "\n", body)
    return re.sub(r"\n{3,}", "\n\n", body)


@dataclass
class Chapter:
    index: int
    title: str
    start: int
    end: int


def find_chapters(text, spec):
    """Find headings as whole paragraphs. Everything before the first one is front matter."""
    heading = re.compile(spec["heading"])
    stop = re.compile(spec["stop"]) if spec.get("stop") else None
    part = re.compile(spec["part"]) if spec.get("part") else None
    paragraphs = [(m.start(), m.group(0).strip()) for m in re.finditer(r"[^\n]+", text)]
    found, current_part, book_end = [], "", len(text)
    for i, (pos, para) in enumerate(paragraphs):
        if stop and stop.fullmatch(para) and found:
            book_end = pos
            break
        if part and (m := part.fullmatch(para)):
            current_part = f"Part {m.group(1)}, "
            continue
        if not heading.fullmatch(para):
            continue
        title = re.sub(r"\s+", " ", para).rstrip(".")
        only = spec.get("title_next_only")
        if spec.get("title_next") and (not only or re.match(only, para)) and i + 1 < len(paragraphs):
            title = f"{title}: {paragraphs[i + 1][1][:70].rstrip('.')}"
        found.append((pos, current_part + title.replace("--", ": ")))
    chapters = []
    for n, (pos, title) in enumerate(found):
        end = found[n + 1][0] if n + 1 < len(found) else book_end
        chapters.append(Chapter(n + 1, title, pos, end))
    return chapters


class Book:
    """One cleaned book with its chapters and chunks. Needs no model, so it is cheap to test."""

    def __init__(self, slug):
        self.slug = slug
        self.spec = BOOKS[slug]
        # encoding is required on Windows: the default there is cp1252 and the books are UTF-8
        raw = (DATA / self.spec["file"]).read_text(encoding="utf-8")
        self.text = clean_text(raw)
        self.chapters = find_chapters(self.text, self.spec)

    def chunks(self):
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, add_start_index=True
        )
        docs = []
        for ch in self.chapters:
            doc = Document(
                page_content=self.text[ch.start:ch.end],
                metadata={"title": self.spec["title"], "author": self.spec["author"],
                          "chapter": ch.index, "chapter_title": ch.title},
            )
            for piece in splitter.split_documents([doc]):
                # start_index counts from the chapter; the reader needs the place in the book
                piece.metadata["start_index"] += ch.start
                docs.append(piece)
        return docs


class Library:
    """Holds the embedding model and one Chroma collection per book."""

    def __init__(self, db_path=DB):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._embeddings = None
        self._books = {}
        self._stores = {}
        self._moods = None

    @property
    def embeddings(self):
        if self._embeddings is None:
            self._embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        return self._embeddings

    def book(self, slug):
        if slug not in self._books:
            self._books[slug] = Book(slug)
        return self._books[slug]

    def store(self, slug):
        """Open the collection of a book and embed it only if it is not complete yet."""
        with self._lock:
            if slug in self._stores:
                return self._stores[slug]
            # The chunk settings are part of the name: Chroma's upsert would keep stale chunks
            # with higher numbers after a change to a larger chunk size.
            name = f"{slug}-{CHUNK_SIZE}-{CHUNK_OVERLAP}"
            store = Chroma(collection_name=name, embedding_function=self.embeddings, persist_directory=self.db_path)
            chunks = self.book(slug).chunks()
            if store._collection.count() != len(chunks):
                store.add_documents(chunks, ids=[f"{slug}-{i}" for i in range(len(chunks))])
            self._stores[slug] = store
            return store

    def retrieve(self, slug, query, limit=None, k=TOP_K, chapters=None):
        conditions = []
        if limit:
            conditions.append({"chapter": {"$lte": int(limit)}})
        if chapters:
            conditions += [{"chapter": {"$gte": chapters[0]}}, {"chapter": {"$lte": chapters[1]}}]
        kwargs = {"k": k}
        if len(conditions) == 1:
            kwargs["filter"] = conditions[0]
        elif conditions:
            kwargs["filter"] = {"$and": conditions}
        return self.store(slug).as_retriever(search_kwargs=kwargs).invoke(query)

    def mood(self, texts):
        """Which anchor sentence is the passage closest to? Vectors are compared by cosine."""
        if not texts:
            return None
        if self._moods is None:
            self._moods = dict(zip(MOODS, self.embeddings.embed_documents([v[0] for v in MOODS.values()])))
        vectors = self.embeddings.embed_documents(texts)
        n = len(vectors[0])
        mean = [sum(v[i] for v in vectors) / len(vectors) for i in range(n)]
        norm = sum(x * x for x in mean) ** 0.5 or 1.0
        scores = {}
        for name, anchor in self._moods.items():
            a_norm = sum(x * x for x in anchor) ** 0.5 or 1.0
            scores[name] = sum(x * y for x, y in zip(mean, anchor)) / (norm * a_norm)
        best = max(scores, key=scores.get)
        return {"name": best, "color": MOODS[best][1], "score": round(scores[best], 3)}


def find_voice(slug, voice_id):
    if voice_id in (None, "", "book"):
        return NARRATOR
    for v in BOOKS[slug]["voices"]:
        if v["id"] == voice_id:
            return v
    raise KeyError(voice_id)


def search_queries(voice, question):
    """'Did the Wizard give you a heart?' has no Tin Woodman in it, so also search with the name."""
    aliases = voice.get("aliases") or []
    if not aliases or not re.search(r"\b(you|your|yours|yourself)\b", question, flags=re.I):
        return [question]
    name = aliases[0]
    named = re.sub(r"\byour\b", f"{name}'s", question, flags=re.I)
    named = re.sub(r"\b(you|yourself|yours)\b", name, named, flags=re.I)
    return [question, named]


def retrieve_for(library, slug, voice, question, limit=None):
    """Search with every phrasing and merge the hits in turns, so that both get a say."""
    queries = search_queries(voice, question)
    lists = [library.retrieve(slug, q, limit=limit, k=TOP_K) for q in queries]
    # Some voices tell a part of the book themselves; there "I" really means them.
    own = voice.get("own")
    if own and not (limit and limit < own[0]):
        lists.insert(0, library.retrieve(slug, queries[0], limit=limit, k=TOP_K, chapters=own))
    merged, seen = [], set()
    for rank in range(TOP_K):
        for hits in lists:
            if rank < len(hits) and hits[rank].metadata["start_index"] not in seen:
                seen.add(hits[rank].metadata["start_index"])
                merged.append(hits[rank])
    return merged[:TOP_K]


def system_prompt(spec, voice, other=None):
    lines = [
        voice["persona"],
        f"You appear in, or wrote, \"{spec['title']}\" by {spec['author']} ({spec['year']}).",
        "",
        "Rules:",
        "1. You know only what is in the numbered passages. Never use anything else you know about this book, its films or its time.",
        "2. If the passages touch the topic at all, answer from what they say, even if they cover only part of the question.",
        f"   Only if they have nothing to do with the question, reply with exactly: {voice['refusal']}",
        "3. Cite the passage behind every claim, for example [2].",
        "4. Use at most three sentences, and always answer in English.",
        "5. A passage may be told by, or about, someone else. You may speak of it as something you saw or heard, but do not claim another person's words or feelings as your own.",
    ]
    if voice["id"] != "book":
        lines.append("6. Speak in the first person, in your own voice.")
    if other:
        lines.append(f"7. {other['name']} has just answered. React to them directly, but stay with your own passages.")
    return "\n".join(lines)


def generate(messages):
    """The model returned an empty text once in ten calls during testing, so ask a second time."""
    for _ in range(2):
        reply = backends.ask(messages)
        if reply.content.strip():
            return reply
    return reply


def passage_view(book, doc, number, cited):
    start = doc.metadata["start_index"]
    end = start + len(doc.page_content)
    return {
        "n": number,
        "chapter": doc.metadata["chapter"],
        "chapter_title": doc.metadata["chapter_title"],
        "start": start,
        "text": doc.page_content,
        "before": book.text[max(0, start - CONTEXT_CHARS):start],
        "after": book.text[end:end + CONTEXT_CHARS],
        "cited": cited,
    }


def answer(library, slug, voice_id, question, limit=None, history=None, other=None, other_said=None):
    """One turn: retrieve, generate, then check what the answer actually cited."""
    spec = BOOKS[slug]
    book = library.book(slug)
    voice = find_voice(slug, voice_id)
    docs = retrieve_for(library, slug, voice, question, limit=limit)
    passages = "\n\n".join(f"[{i + 1}] {d.page_content}" for i, d in enumerate(docs))

    messages = [SystemMessage(system_prompt(spec, voice, other))]
    for turn in (history or [])[-HISTORY_MESSAGES:]:
        cls = HumanMessage if turn.get("role") == "user" else AIMessage
        messages.append(cls(turn.get("content", "")))
    prompt = f"Passages:\n\n{passages}\n\nQuestion: {question}"
    if other_said:
        prompt += f"\n\n{other['name']} said: {other_said}"
    messages.append(HumanMessage(prompt))

    reply = generate(messages)
    text = reply.content.strip()
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", text) if 1 <= int(n) <= len(docs)}
    refused = normalise(voice["refusal"]).lower() in normalise(text).lower()
    if not text:
        status = "silent"
    elif refused:
        status = "refused"
    elif cited:
        status = "grounded"
    else:
        status = "uncited"
    used = [d.page_content for i, d in enumerate(docs) if i + 1 in cited]
    usage = reply.usage_metadata or {}
    return {
        "voice": voice["id"],
        "voice_name": voice["name"],
        "answer": text or "The spirits are silent. Try asking again.",
        "status": status,
        "passages": [passage_view(book, d, i + 1, i + 1 in cited) for i, d in enumerate(docs)],
        "mood": library.mood(used or [d.page_content for d in docs[:2]]),
        "tokens": usage.get("total_tokens"),
    }
