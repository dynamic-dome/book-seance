"""Fast checks without any model: the shelf has to match the real books."""
import pytest

from seance.books import BOOKS
from seance.core import Book, normalise, search_queries

EXPECTED_CHAPTERS = {
    "oz": 24,
    "frankenstein": 28,
    "sherlock": 12,
    "timemachine": 17,
    "pinocchio": 36,
    "penguins": 5,
    "climate": 12,
    "tombrown": 18,
}


@pytest.fixture(scope="module", params=sorted(BOOKS))
def book(request):
    return Book(request.param)


def test_chapter_count(book):
    assert len(book.chapters) == EXPECTED_CHAPTERS[book.slug], [c.title for c in book.chapters]


def test_chapters_are_ordered_and_cover_the_book(book):
    starts = [c.start for c in book.chapters]
    assert starts == sorted(starts)
    assert all(c.end > c.start for c in book.chapters)


def test_every_quote_is_in_the_book(book):
    text = normalise(book.text).lower()
    for voice in BOOKS[book.slug]["voices"]:
        assert normalise(voice["quote"]).lower() in text, voice["name"]


def test_nothing_of_the_licence_or_markup_is_left(book):
    last = book.chapters[-1]
    assert "Project Gutenberg" not in book.text[last.start:last.end]
    assert "[Illustration" not in book.text


def test_chunks_carry_chapter_and_a_true_position(book):
    chunks = book.chunks()
    assert chunks
    for doc in chunks[:: max(1, len(chunks) // 40)]:
        start = doc.metadata["start_index"]
        assert book.text[start:start + len(doc.page_content)] == doc.page_content
        chapter = book.chapters[doc.metadata["chapter"] - 1]
        assert chapter.start <= start < chapter.end


def test_search_names_the_voice_only_when_the_question_says_you():
    tin = next(v for v in BOOKS["oz"]["voices"] if v["id"] == "tin")
    assert search_queries(tin, "Did the Wizard give you a heart?") == [
        "Did the Wizard give you a heart?",
        "Did the Wizard give Tin Woodman a heart?",
    ]
    assert search_queries(tin, "Where is Kansas?") == ["Where is Kansas?"]
