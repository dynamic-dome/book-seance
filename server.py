"""The séance room: a small FastAPI server around the engine.

Run from the project folder:

    uv run uvicorn server:app --host 127.0.0.1 --port 8642
"""
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from seance.books import BOOKS, NARRATOR
from seance.core import Library, answer, find_voice

STATIC = Path(__file__).parent / "static"

library = Library()


@asynccontextmanager
async def lifespan(app):
    # Loading the embedding model takes about ten seconds, so do it before the first visitor
    threading.Thread(target=lambda: library.embeddings, daemon=True).start()
    yield


app = FastAPI(title="Book Séance", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class Turn(BaseModel):
    role: str
    content: str = Field(max_length=2000)


class Ask(BaseModel):
    book: str
    voice: str = "book"
    question: str = Field(min_length=1, max_length=500)
    limit: int | None = None
    history: list[Turn] = []


class Round(BaseModel):
    book: str
    voices: list[str] = Field(min_length=2, max_length=2)
    question: str = Field(min_length=1, max_length=500)
    limit: int | None = None


def check_book(slug):
    if slug not in BOOKS:
        raise HTTPException(404, "Unknown book")


def run(call):
    """Turn the two failures a visitor can meet into messages they can act on."""
    if not os.environ.get("GROQ_API_KEY"):
        raise HTTPException(503, "No GROQ_API_KEY found. Put your key into the .env file and restart the server.")
    try:
        return call()
    except KeyError:
        raise HTTPException(404, "Unknown voice")
    except Exception as exc:
        if type(exc).__name__ == "RateLimitError":
            raise HTTPException(429, "The free Groq plan needs a breather. Wait a minute and ask again.")
        raise HTTPException(502, f"The model could not answer ({type(exc).__name__}). Try again.")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/books")
def books():
    shelf = []
    for slug, spec in BOOKS.items():
        shelf.append({
            "slug": slug, "title": spec["title"], "author": spec["author"], "year": spec["year"],
            "theme": spec["theme"],
            "voices": [{k: v[k] for k in ("id", "name", "role", "quote", "theme")} for v in spec["voices"]],
        })
    return {"books": shelf, "narrator": {k: NARRATOR[k] for k in ("id", "name", "role", "quote", "theme")}}


@app.post("/api/books/{slug}/open")
def open_book(slug: str):
    """Embeds the book on first use, which takes a few seconds; later calls return at once."""
    check_book(slug)
    library.store(slug)
    book = library.book(slug)
    return {"chapters": [{"index": c.index, "title": c.title} for c in book.chapters]}


@app.post("/api/ask")
def ask(req: Ask):
    check_book(req.book)
    history = [t.model_dump() for t in req.history]
    return run(lambda: answer(library, req.book, req.voice, req.question, limit=req.limit, history=history))


@app.post("/api/round")
def round_table(req: Round):
    """Two voices on one question: the second one hears the first and has its own passages."""
    check_book(req.book)

    def both():
        first = answer(library, req.book, req.voices[0], req.question, limit=req.limit)
        second = answer(library, req.book, req.voices[1], req.question, limit=req.limit,
                        other=find_voice(req.book, req.voices[0]), other_said=first["answer"])
        return {"replies": [first, second]}

    return run(both)
