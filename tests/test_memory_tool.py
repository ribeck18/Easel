"""Tests for the agent-callable `memory` write tool (add/replace/remove)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import tools.memory as memory_tools  # noqa: E402
import tools.workspace as workspace  # noqa: E402
from tools.memory import memory  # noqa: E402


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path)
    # MemoryEvent logging hits the real /app/data DB; stub it out for unit tests.
    monkeypatch.setattr(memory_tools, "_record_memory_write", lambda *a, **k: None)
    return tmp_path


def _user_md(vault):
    path = vault / "Easel" / "Memory" / "USER.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_add_creates_bullet(vault):
    out = memory(action="add", target="user", content="prefers dark mode")
    assert out.startswith("Saved.")
    assert "- prefers dark mode" in _user_md(vault)


def test_add_normalizes_existing_dash(vault):
    memory(action="add", target="user", content="- already dashed")
    assert "- already dashed" in _user_md(vault)
    assert "- - already dashed" not in _user_md(vault)


def test_duplicate_add_is_noop(vault):
    memory(action="add", target="user", content="likes tea")
    out = memory(action="add", target="user", content="likes tea")
    assert "Already present" in out
    assert _user_md(vault).count("likes tea") == 1


def test_replace_unique(vault):
    memory(action="add", target="user", content="uses VS Code")
    out = memory(action="replace", target="user", old_text="VS Code",
                 content="uses Neovim")
    assert out.startswith("Updated.")
    body = _user_md(vault)
    assert "Neovim" in body and "VS Code" not in body


def test_replace_ambiguous_refuses(vault):
    memory(action="add", target="user", content="likes green tea")
    memory(action="add", target="user", content="likes black tea")
    out = memory(action="replace", target="user", old_text="tea", content="likes coffee")
    assert "matched 2 entries" in out
    # Nothing changed.
    assert "green tea" in _user_md(vault) and "black tea" in _user_md(vault)


def test_replace_no_match_shows_nearest(vault):
    memory(action="add", target="user", content="enjoys hiking")
    out = memory(action="replace", target="user", old_text="swimming",
                 content="enjoys cycling")
    assert "no entry matched" in out
    assert "hiking" in out  # nearest suggestion


def test_remove(vault):
    memory(action="add", target="user", content="temporary note")
    out = memory(action="remove", target="user", old_text="temporary")
    assert out.startswith("Removed.")
    assert "temporary note" not in _user_md(vault)


def test_over_budget_message(vault, monkeypatch):
    monkeypatch.setattr(config, "CORE_MEMORY_BUDGET_CHARS", 30)
    out = memory(action="add", target="memory", content="x" * 60)
    assert "doesn't fit" in out
    assert "consolidate" in out


def test_invalid_target_and_action(vault):
    assert "target must be" in memory(action="add", target="bogus", content="x")
    assert "action must be" in memory(action="bogus", target="user", content="x")


def test_unavailable_without_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path / "missing")
    out = memory(action="add", target="user", content="x")
    assert "no workspace is mounted" in out
