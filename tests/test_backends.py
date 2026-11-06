"""The start page's choice of backend. Nothing here calls a model."""
import pytest

from seance import backends


def test_all_three_are_offered():
    assert [c["id"] for c in backends.choices()] == ["claude", "codex", "groq"]


def test_choose_switches_while_running(monkeypatch):
    monkeypatch.setenv("SEANCE_LLM", "claude")
    monkeypatch.setattr(backends, "ready", lambda name=None: None)
    backends.choose("groq")
    assert backends.backend() == "groq"


def test_a_choice_that_cannot_run_changes_nothing(monkeypatch):
    monkeypatch.setenv("SEANCE_LLM", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(backends.shutil, "which", lambda name: None)
    with pytest.raises(ValueError):
        backends.choose("claude")
    assert backends.backend() == "groq"


def test_unknown_backend_is_refused():
    with pytest.raises(ValueError):
        backends.choose("gemini")
