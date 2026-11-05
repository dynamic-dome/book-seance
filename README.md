# Book Séance

Talk to the people inside a book. Every voice answers only from retrieved passages, and every answer shows the passage it stands on.

Built on top of the Book RAG project with a coding agent: the engine follows the seven project steps, everything else is a layer above the same retriever and chain.

## What it does

- **Eight books, eight rooms.** Each book has its own colours, fonts and weather: snow at Cape Adare, lightning in Ingolstadt, a turning clock in the year 802,701.
- **Voices with their own theme.** Pick the Scarecrow and straw falls, pick the Tin Woodman and the room turns to steel.
- **The room reacts to the text.** Each retrieved passage is compared with six mood sentences using the same embedding model, so the colour and the weather follow the passage without any extra call to the LLM.
- **Check every answer.** The right page opens the book at the passage, with the text around it. Click a number in the answer to jump there.
- **Honest refusals.** If the passages hold nothing relevant, a voice says "I did not know that at the time."
- **A candle as a spoiler limit.** Tell the room how far you have read, and later chapters no longer exist for the search.
- **Two voices.** Let a second voice answer the first, each with its own passages.

## Setup

You need [uv](https://docs.astral.sh/uv/) and a free key from [console.groq.com/keys](https://console.groq.com/keys), or a logged-in Claude Code or Codex CLI (see below).

```bash
uv sync
cp .env.example .env              # then paste your key after GROQ_API_KEY=
uv run python -m seance.prepare   # embeds all eight books once, about two minutes
```

## Run

The full séance:

```bash
uv run uvicorn server:app --host 127.0.0.1 --port 8642
```

Then open <http://127.0.0.1:8642>.

The small version, with the same engine in Streamlit:

```bash
uv run streamlit run app_streamlit.py
```

## Choose who writes the answers

Set `SEANCE_LLM` in `.env` and restart the server. The search stays local and identical in every case.

| `SEANCE_LLM` | Needs | Speed per answer | Note |
|---|---|---|---|
| `groq` (default) | a Groq key | 1 to 2 seconds | `gpt-oss-20b`, the course model; the free plan allows about six answers per minute |
| `claude` | a logged-in Claude Code | 5 to 15 seconds | uses your Claude subscription, `SEANCE_CLAUDE_MODEL` picks the model (default `haiku`) |
| `codex` | a logged-in Codex CLI | 13 to 19 seconds | uses your ChatGPT subscription |

`claude` and `codex` are for your own machine. Subscriptions are personal, so if other people use this, each of them runs it with their own account or key.

## How it is built

| File | What it holds |
|---|---|
| `seance/core.py` | The engine: clean, find chapters, chunk, embed, retrieve, answer, check citations, read the mood |
| `seance/books.py` | The shelf as plain data: books, voices, quotes, themes |
| `seance/backends.py` | Who writes the answer: Groq or a subscription tool |
| `server.py`, `static/index.html` | FastAPI and the séance room |
| `app_streamlit.py` | The Streamlit version |
| `tests/` | Checks against the real books: chapters, verbatim quotes, true positions |

To add a book, put the text into `data/` and add one entry to `seance/books.py`.

## Known limits

- **"Cites the passage" means the answer names a passage, not that the passage proves it.** The model can still misread one, so check it on the right page.
- **The search finds passages about a person, not what that person knows.** A voice may borrow a line that someone else said.
- **A refusal can be wrong.** If the search misses the scene, the voice says it does not know, and it sounds just as convincing.
- **Questions about a whole book are hard.** Six passages cannot sum up a character's development.
- **The free Groq plan allows about 8,000 tokens per minute.** That is about six answers per minute, or three rounds with two voices.

Run it locally only. A public version would spend your Groq limit on strangers.

## Credits

- Books: [Project Gutenberg](https://www.gutenberg.org/), public domain in the United States, files unchanged, see `data/README.md`.
- Models: `openai/gpt-oss-20b` on Groq by default, `sentence-transformers/all-MiniLM-L6-v2` for the search.
- Fonts: open fonts from Google Fonts under the SIL Open Font License, stored in `static/fonts/`.
