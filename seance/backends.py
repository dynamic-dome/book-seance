"""Who writes the answer. Choose with SEANCE_LLM in .env: groq (default), claude or codex.

groq talks to the API. claude and codex run the logged-in command-line tools on this
machine, so they use your own subscription and need no API key. They are for your own
machine only: subscriptions are personal, so do not put a public site in front of them.
"""
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

GROQ_MODEL = "openai/gpt-oss-20b"
TIMEOUT = 120


@dataclass
class Reply:
    content: str
    usage_metadata: dict = field(default_factory=dict)


def backend():
    return os.environ.get("SEANCE_LLM", "groq").strip().lower()


def ready():
    """Returns a message a person can act on if the chosen backend cannot run, else None."""
    name = backend()
    if name == "groq":
        return None if os.environ.get("GROQ_API_KEY") else "No GROQ_API_KEY found. Put your key into the .env file and restart the server."
    if name in ("claude", "codex"):
        return None if shutil.which(name) else f"The {name} command was not found on this machine."
    return f"Unknown SEANCE_LLM value: {name}. Use groq, claude or codex."


def split(messages):
    """The command-line tools take one system text and one prompt, not a list of messages."""
    system = "\n".join(m.content for m in messages if isinstance(m, SystemMessage))
    lines = []
    for m in messages:
        if isinstance(m, SystemMessage):
            continue
        lines.append(("Reader: " if isinstance(m, HumanMessage) else "You: ") + m.content)
    return system, "\n\n".join(lines)


def ask_groq(messages):
    # low reasoning: measured 163 instead of 531 to 800 output tokens for the same question,
    # which matters with a free plan of about 8,000 tokens per minute
    llm = ChatGroq(model=GROQ_MODEL, temperature=0, max_tokens=1000, max_retries=5, reasoning_effort="low")
    reply = llm.invoke(messages)
    return Reply(reply.content, reply.usage_metadata or {})


def ask_claude(messages):
    system, prompt = split(messages)
    cmd = [
        shutil.which("claude"), "-p", "--model", os.environ.get("SEANCE_CLAUDE_MODEL", "haiku"),
        "--output-format", "json", "--system-prompt", system,
        # no hooks, no tools, no MCP servers: it only has to write one answer
        "--settings", '{"disableAllHooks": true}', "--tools", "", "--strict-mcp-config",
        "--permission-mode", "bypassPermissions", "--max-turns", "1",
        "--disable-slash-commands", "--no-session-persistence",
        # the user's own settings would bring along things like their language
        "--setting-sources", "project",
    ]
    # an API key in the environment would replace the subscription login
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    with tempfile.TemporaryDirectory(prefix="seance_") as cwd:
        run = subprocess.run(cmd, input=prompt.encode("utf-8"), capture_output=True, timeout=TIMEOUT, cwd=cwd, env=env)
    # read the output first: the exit code alone does not tell why a run failed
    try:
        data = json.loads(run.stdout.decode("utf-8"))
    except ValueError:
        raise RuntimeError("claude returned no JSON") from None
    if isinstance(data, list):  # this version prints all events; the last one is the result
        data = next((e for e in reversed(data) if e.get("type") == "result"), {})
    if data.get("is_error") or "result" not in data:
        raise RuntimeError(f"claude reported an error: {str(data.get('result', ''))[:160]}")
    usage = data.get("usage") or {}
    return Reply(data.get("result", ""), {"total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)})


def ask_codex(messages):
    system, prompt = split(messages)
    with tempfile.TemporaryDirectory(prefix="seance_") as cwd:
        out = Path(cwd) / "answer.txt"
        cmd = [
            shutil.which("codex"), "exec", "-",
            "-s", "read-only", "-c", 'approval_policy="never"', "-c", 'model_reasoning_effort="low"',
            "--skip-git-repo-check", "--ephemeral", "-C", cwd, "-o", str(out),
        ]
        if os.environ.get("SEANCE_CODEX_MODEL"):
            cmd += ["-m", os.environ["SEANCE_CODEX_MODEL"]]
        # encoded by hand: text=True would send cp1252 on Windows, and codex expects UTF-8
        subprocess.run(cmd, input=f"{system}\n\n{prompt}".encode("utf-8"), capture_output=True, timeout=TIMEOUT, cwd=cwd)
        if not out.exists():
            raise RuntimeError("codex wrote no answer")
        return Reply(out.read_text(encoding="utf-8"))


def ask(messages):
    return {"groq": ask_groq, "claude": ask_claude, "codex": ask_codex}[backend()](messages)
