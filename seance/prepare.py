"""Embed all books once, so that no visitor has to wait: uv run python -m seance.prepare"""
import sys
import time

from seance.books import BOOKS
from seance.core import Library

sys.stdout.reconfigure(encoding="utf-8")

library = Library()
for slug, spec in BOOKS.items():
    started = time.time()
    store = library.store(slug)
    print(f"{spec['title']}: {store._collection.count()} chunks, {time.time() - started:.0f} s")
