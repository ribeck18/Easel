"""Tests for the workspace file tools: search, edit, move, delete."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools.filesystem as filesystem  # noqa: E402
import tools.workspace as workspace  # noqa: E402
from tools.filesystem import (  # noqa: E402
    delete_file,
    edit_file,
    move_file,
    search_files,
)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    # resolve_in_workspace reads workspace.WORKSPACE_ROOT; search_files holds its
    # own imported reference, so both bindings must point at the temp workspace.
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(filesystem, "WORKSPACE_ROOT", tmp_path)
    return tmp_path


# --- search_files ---------------------------------------------------------


def test_search_finds_match_with_path_and_line(ws):
    (ws / "notes.md").write_text("alpha\nbudget is 100\ngamma\n", encoding="utf-8")
    out = search_files(query="budget")
    assert "notes.md:2: budget is 100" in out


def test_search_is_case_insensitive(ws):
    (ws / "a.txt").write_text("Hello World\n", encoding="utf-8")
    assert "a.txt:1:" in search_files(query="hello world")


def test_search_skips_binary_files(ws):
    (ws / "data.bin").write_bytes(b"\xff\xfe\x00query\x00")
    (ws / "ok.txt").write_text("query here\n", encoding="utf-8")
    out = search_files(query="query")
    assert "ok.txt:1:" in out
    assert "data.bin" not in out


def test_search_respects_max_results(ws):
    (ws / "many.txt").write_text("hit\n" * 10, encoding="utf-8")
    out = search_files(query="hit", max_results=3)
    assert out.count("many.txt:") == 3
    assert "limit" in out


def test_search_no_matches(ws):
    (ws / "a.txt").write_text("nothing here\n", encoding="utf-8")
    assert search_files(query="absent") == "No matches for 'absent'."


def test_search_empty_query_errors(ws):
    assert search_files(query="").startswith("Error:")


def test_search_skips_dotdirs(ws):
    hidden = ws / ".git"
    hidden.mkdir()
    (hidden / "config").write_text("secret token\n", encoding="utf-8")
    assert search_files(query="token") == "No matches for 'token'."


# --- edit_file ------------------------------------------------------------


def test_edit_unique_replacement(ws):
    target = ws / "f.txt"
    target.write_text("the quick brown fox", encoding="utf-8")
    out = edit_file(path="f.txt", old_string="quick", new_string="slow")
    assert "Made 1 replacement" in out
    assert target.read_text(encoding="utf-8") == "the slow brown fox"


def test_edit_replace_all(ws):
    target = ws / "f.txt"
    target.write_text("a a a", encoding="utf-8")
    out = edit_file(path="f.txt", old_string="a", new_string="b", replace_all=True)
    assert "Made 3 replacement" in out
    assert target.read_text(encoding="utf-8") == "b b b"


def test_edit_non_unique_without_replace_all_errors(ws):
    target = ws / "f.txt"
    target.write_text("a a a", encoding="utf-8")
    out = edit_file(path="f.txt", old_string="a", new_string="b")
    assert "not unique" in out
    assert target.read_text(encoding="utf-8") == "a a a"


def test_edit_not_found_errors(ws):
    (ws / "f.txt").write_text("hello", encoding="utf-8")
    assert "was not found" in edit_file(
        path="f.txt", old_string="absent", new_string="x"
    )


def test_edit_identical_strings_errors(ws):
    (ws / "f.txt").write_text("hello", encoding="utf-8")
    assert "identical" in edit_file(path="f.txt", old_string="h", new_string="h")


def test_edit_missing_file_errors(ws):
    assert "no file found" in edit_file(
        path="nope.txt", old_string="a", new_string="b"
    )


def test_edit_blocks_traversal(ws):
    out = edit_file(path="../escape.txt", old_string="a", new_string="b")
    assert "outside the workspace" in out


# --- move_file ------------------------------------------------------------


def test_move_renames_file(ws):
    (ws / "old.txt").write_text("data", encoding="utf-8")
    out = move_file(source="old.txt", destination="new.txt")
    assert "Moved" in out
    assert not (ws / "old.txt").exists()
    assert (ws / "new.txt").read_text(encoding="utf-8") == "data"


def test_move_creates_parent_dirs(ws):
    (ws / "old.txt").write_text("data", encoding="utf-8")
    move_file(source="old.txt", destination="sub/dir/new.txt")
    assert (ws / "sub" / "dir" / "new.txt").exists()


def test_move_refuses_existing_destination(ws):
    (ws / "old.txt").write_text("a", encoding="utf-8")
    (ws / "taken.txt").write_text("b", encoding="utf-8")
    out = move_file(source="old.txt", destination="taken.txt")
    assert "already exists" in out
    assert (ws / "old.txt").exists()
    assert (ws / "taken.txt").read_text(encoding="utf-8") == "b"


def test_move_missing_source_errors(ws):
    assert "no file found" in move_file(source="nope.txt", destination="x.txt")


# --- delete_file ----------------------------------------------------------


def test_delete_removes_file(ws):
    (ws / "f.txt").write_text("x", encoding="utf-8")
    out = delete_file(path="f.txt")
    assert "Deleted" in out
    assert not (ws / "f.txt").exists()


def test_delete_refuses_directory(ws):
    (ws / "sub").mkdir()
    out = delete_file(path="sub")
    assert "is a directory" in out
    assert (ws / "sub").is_dir()


def test_delete_missing_file_errors(ws):
    assert "no file found" in delete_file(path="nope.txt")
