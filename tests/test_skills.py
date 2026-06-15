"""Tests for the skills layer: discovery, index, read_skill, toggling, path guards."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools.workspace as workspace  # noqa: E402
import tools.skills as skills  # noqa: E402


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path)
    # Point the stock root at an empty temp dir by default so tests that don't opt in
    # to stock skills see only their workspace skills.
    monkeypatch.setattr(skills, "STOCK_SKILLS_ROOT", tmp_path / "stock_empty")
    return tmp_path


@pytest.fixture()
def stock(tmp_path, monkeypatch):
    root = tmp_path / "stock_skills"
    root.mkdir()
    monkeypatch.setattr(skills, "STOCK_SKILLS_ROOT", root)
    return root


def _write_skill(root, slug, *, description="A test skill.", refs=None, body="Do the thing."):
    skill_dir = root / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    front = "---\n"
    front += f"name: {slug.title()}\n"
    if description is not None:
        front += f"description: {description}\n"
    front += "---\n"
    (skill_dir / "SKILL.md").write_text(front + f"# {slug}\n{body}\n", encoding="utf-8")
    for rel, content in (refs or {}).items():
        ref_path = skill_dir / "references" / rel
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        ref_path.write_text(content, encoding="utf-8")
    return skill_dir


def _make_skill(vault, slug, **kwargs):
    return _write_skill(vault / "Easel" / "Skills", slug, **kwargs)


def _make_stock(stock, slug, **kwargs):
    return _write_skill(stock, slug, **kwargs)


def test_index_lists_enabled_valid_skills(vault):
    _make_skill(vault, "grill-me", description="Drill the user.")
    index = skills.build_skills_index()
    assert "- grill-me — Drill the user." in index


def test_index_excludes_invalid_skill(vault):
    _make_skill(vault, "broken", description=None)
    assert skills.build_skills_index() == ""
    listed = {s["slug"]: s for s in skills.list_skills()}
    assert listed["broken"]["valid"] is False  # still shown in UI


def test_read_skill_returns_body_and_reference_manifest(vault):
    _make_skill(vault, "grill-me", refs={"checklist.md": "- a\n", "examples/good.md": "ok\n"})
    out = skills.read_skill("grill-me")
    assert "Do the thing." in out
    assert "checklist.md" in out
    assert "examples/good.md" in out


def test_read_skill_reads_named_reference(vault):
    _make_skill(vault, "grill-me", refs={"checklist.md": "- only point\n"})
    assert "only point" in skills.read_skill("grill-me", reference="checklist.md")


def test_disabled_skill_excluded_from_index_and_refused(vault):
    _make_skill(vault, "grill-me")
    skills.set_skill_enabled("grill-me", False)
    assert skills.build_skills_index() == ""
    assert skills.read_skill("grill-me") == "Skill 'grill-me' is disabled."
    # Re-enabling restores it.
    skills.set_skill_enabled("grill-me", True)
    assert "grill-me" in skills.build_skills_index()


def test_toggle_persists_to_state_file(vault):
    _make_skill(vault, "grill-me")
    skills.set_skill_enabled("grill-me", False)
    state = (vault / "Easel" / "Skills" / "_state.json").read_text(encoding="utf-8")
    assert "grill-me" in state


def test_reserved_underscore_entries_ignored(vault):
    _make_skill(vault, "grill-me")
    skills.set_skill_enabled("grill-me", False)  # creates _state.json
    slugs = {s["slug"] for s in skills.list_skills()}
    assert "_state" not in slugs


def test_reference_path_blocks_traversal(vault):
    _make_skill(vault, "grill-me", refs={"checklist.md": "x"})
    assert skills.reference_path("grill-me", "../SKILL.md") is None
    assert "outside the skill" in skills.read_skill("grill-me", reference="../SKILL.md")


def test_unknown_skill_is_not_found(vault):
    assert skills.read_skill("nope") == "Error: no skill named 'nope'."


def test_no_workspace_and_no_stock_soft_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path / "absent")
    monkeypatch.setattr(skills, "STOCK_SKILLS_ROOT", tmp_path / "absent_stock")
    assert skills.list_skills() == []
    assert skills.build_skills_index() == ""
    assert skills.read_skill("grill-me") == "Error: no skill named 'grill-me'."


# ── stock (bundled) skills ───────────────────────────────────────────────────────


def test_stock_skill_appears_in_index(vault, stock):
    _make_stock(stock, "grill-me", description="Drill the user.")
    assert "- grill-me — Drill the user." in skills.build_skills_index()


def test_stock_skill_is_readable(vault, stock):
    _make_stock(stock, "grill-me", body="Built-in body.")
    assert "Built-in body." in skills.read_skill("grill-me")


def test_stock_skill_carries_source(vault, stock):
    _make_stock(stock, "grill-me")
    sources = {s["slug"]: s["source"] for s in skills.list_skills()}
    assert sources["grill-me"] == "stock"


def test_workspace_overrides_stock_by_slug(vault, stock):
    _make_stock(stock, "grill-me", body="STOCK")
    _make_skill(vault, "grill-me", body="WORKSPACE")
    assert "WORKSPACE" in skills.read_skill("grill-me")
    listed = {s["slug"]: s for s in skills.list_skills()}
    assert listed["grill-me"]["source"] == "workspace"  # workspace shadows stock
    assert len([s for s in skills.list_skills() if s["slug"] == "grill-me"]) == 1


def test_stock_and_workspace_skills_coexist(vault, stock):
    _make_stock(stock, "pr-review")
    _make_skill(vault, "my-skill")
    slugs = {s["slug"] for s in skills.list_skills()}
    assert {"pr-review", "my-skill"} <= slugs


def test_disabling_stock_skill_persists(vault, stock):
    _make_stock(stock, "grill-me")
    skills.set_skill_enabled("grill-me", False)
    assert skills.build_skills_index() == ""
    assert skills.read_skill("grill-me") == "Skill 'grill-me' is disabled."


def test_stock_reference_is_readable_and_guarded(vault, stock):
    _make_stock(stock, "pr-review", refs={"checklist.md": "- check it\n"})
    assert "check it" in skills.read_skill("pr-review", reference="checklist.md")
    assert skills.reference_path("pr-review", "../SKILL.md") is None


def test_stock_skills_work_without_workspace(monkeypatch, tmp_path, stock):
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path / "absent")
    _make_stock(stock, "grill-me", description="Drill the user.")
    assert "- grill-me — Drill the user." in skills.build_skills_index()
    assert "Do the thing." in skills.read_skill("grill-me")
