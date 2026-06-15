"""Skills: packages of task instructions the agent can load on demand.

Skills come from two roots: **stock** skills bundled with the app under ``stock_skills/``
(read-only, shipped with the code) and **workspace** skills the user authors in the
mounted workspace under ``Easel/Skills/`` (a sibling of the wiki). Each is one folder
per skill containing a ``SKILL.md`` body plus an optional ``references/`` folder. A
workspace skill shadows a stock skill with the same slug, giving users an escape hatch to
customize a built-in. The agent sees only a compact index of enabled skills and pulls a
full skill in with ``read_skill``. Per-skill on/off state is slug-keyed and kept in
``Easel/Skills/_state.json`` (so it covers stock skills too).
"""

from pathlib import Path
import json

from tools import threat_patterns
from tools.workspace import (
    WorkspacePathError,
    resolve_in_workspace,
    workspace_available,
)


SKILLS_RELROOT = "Easel/Skills"
STOCK_SKILLS_ROOT = Path(__file__).resolve().parent.parent / "stock_skills"
RESERVED_PREFIX = "_"
MAX_SKILL_CHARS = 50 * 1024
MAX_REFERENCES_LISTED = 50


def build_skills_index() -> str:
    """Return the compact, enabled-only index injected into the system prompt.

    Each line is ``- <slug> — <description>``. Skills that are disabled or missing a
    description are excluded (the agent has nothing meaningful to match on). Returns an
    empty string when there are no usable skills, so the caller can omit the block.
    """
    lines = [
        f"- {skill['slug']} — {skill['description']}"
        for skill in list_skills()
        if skill["enabled"] and skill["valid"]
    ]
    return "\n".join(lines)


def list_skills() -> list[dict]:
    """Return every skill folder (stock + workspace) for the Skills page.

    Each entry is ``{slug, name, description, enabled, valid, source, refs}`` where
    ``source`` is ``"stock"`` or ``"workspace"`` and ``refs`` is a manifest of reference
    files. Invalid skills (missing SKILL.md or description) are included with
    ``valid=False`` so the UI can flag them. Workspace skills shadow stock skills with the
    same slug.
    """
    disabled = _load_disabled()
    skills: list[dict] = []
    for slug, (source, entry) in sorted(_iter_skill_dirs().items()):
        s_slug, name, description, valid = _skill_meta(entry)
        skills.append(
            {
                "slug": s_slug,
                "name": name,
                "description": description,
                "enabled": s_slug not in disabled,
                "valid": valid,
                "source": source,
                "refs": _reference_entries(entry),
            }
        )
    return skills


def skill_detail(slug: str) -> dict | None:
    """Return full detail for the Skills detail page, or None if the slug is unknown.

    Unlike ``read_skill`` this is the user-facing read: it returns the raw SKILL.md body
    (no sanitization, no disabled gating) since the user is viewing their own content.
    """
    found = _iter_skill_dirs().get((slug or "").strip())
    if found is None:
        return None
    source, skill_dir = found
    s_slug, name, description, valid = _skill_meta(skill_dir)
    body = ""
    body_path = _find_skill_md(skill_dir)
    if body_path is not None:
        try:
            _, body = _split_frontmatter(body_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            body = ""
    return {
        "slug": s_slug,
        "name": name,
        "description": description,
        "enabled": s_slug not in _load_disabled(),
        "valid": valid,
        "source": source,
        "body": body,
        "references": _reference_entries(skill_dir),
    }


def reference_path(slug: str, path: str) -> Path | None:
    """Resolve a reference file to an absolute path, or None if blocked/missing.

    The path is clamped inside the skill's ``references/`` folder so traversal escapes are
    rejected. Used by the raw-stream API endpoint.
    """
    skill_dir = _skill_dir(slug)
    if skill_dir is None:
        return None
    refs_root = (skill_dir / "references").resolve()
    candidate = (skill_dir / "references" / path).resolve()
    if candidate != refs_root and not candidate.is_relative_to(refs_root):
        return None
    return candidate if candidate.is_file() else None


def set_skill_enabled(slug: str, enabled: bool) -> bool:
    """Persist a per-skill on/off state into ``_state.json``. Returns the new state."""
    if not workspace_available():
        raise WorkspacePathError(
            "No workspace is mounted, so skills cannot be toggled."
        )
    root = _skills_root()
    root.mkdir(parents=True, exist_ok=True)
    disabled = _load_disabled()
    if enabled:
        disabled.discard(slug)
    else:
        disabled.add(slug)
    _state_path().write_text(
        json.dumps({"disabled": sorted(disabled)}, indent=2), encoding="utf-8"
    )
    return enabled


def read_skill(slug: str, reference: str | None = None) -> str:
    """Load a skill's body (and reference manifest), or a single reference file.

    With no ``reference`` the SKILL.md body is returned followed by a list of reference
    paths to open on demand. With ``reference`` the named file under ``references/`` is
    returned as text. Disabled skills are refused explicitly; output is sanitized for the
    model and capped in size.
    """
    slug = (slug or "").strip()
    if not slug:
        return "Error: read_skill requires a skill slug."

    skill_dir = _skill_dir(slug)
    if skill_dir is None:
        return f"Error: no skill named '{slug}'."
    if slug in _load_disabled():
        return f"Skill '{slug}' is disabled."

    if reference is not None:
        return _read_reference(skill_dir, slug, reference)

    body_path = _find_skill_md(skill_dir)
    if body_path is None:
        return f"Error: skill '{slug}' has no SKILL.md."
    try:
        _, body = _split_frontmatter(_read_text_capped(body_path))
    except UnicodeDecodeError:
        return f"Error: skill '{slug}' SKILL.md is not a UTF-8 text file."
    except OSError as error:
        return f"Error: could not read skill '{slug}': {error}."

    out = body.strip()
    refs = _reference_manifest(skill_dir)
    if refs:
        listing = "\n".join(f"- {ref}" for ref in refs)
        out += "\n\n## References (open with read_skill, reference=<path>)\n" + listing
    return threat_patterns.sanitize_for_model(out, source=f"skill:{slug}")


# ── internals ──────────────────────────────────────────────────────────────────


def _read_reference(skill_dir: Path, slug: str, reference: str) -> str:
    refs_root = (skill_dir / "references").resolve()
    candidate = (skill_dir / "references" / reference).resolve()
    if candidate != refs_root and not candidate.is_relative_to(refs_root):
        return f"Error: reference '{reference}' is outside the skill and was blocked."
    if not candidate.is_file():
        return f"Error: no reference '{reference}' in skill '{slug}'."
    try:
        text = _read_text_capped(candidate)
    except UnicodeDecodeError:
        return f"Error: reference '{reference}' is not a UTF-8 text file."
    except OSError as error:
        return f"Error: could not read reference '{reference}': {error}."
    return threat_patterns.sanitize_for_model(text, source=f"skill:{slug}")


def _skills_root() -> Path:
    return resolve_in_workspace(SKILLS_RELROOT)


def _stock_skills_root() -> Path:
    return STOCK_SKILLS_ROOT


def _iter_skill_dirs() -> dict[str, tuple[str, Path]]:
    """Map slug -> ``(source, dir)``, scanning stock then workspace.

    Workspace skills shadow stock skills with the same slug (the workspace root is scanned
    last and overwrites the dict entry). Underscore-prefixed and non-directory entries are
    skipped in both roots. Either root may be absent — a missing workspace simply yields
    the stock skills, and vice versa.
    """
    found: dict[str, tuple[str, Path]] = {}
    for source, root in (("stock", _stock_skills_root()), ("workspace", _skills_root())):
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith(RESERVED_PREFIX):
                continue
            found[entry.name] = (source, entry)
    return found


def _state_path() -> Path:
    return _skills_root() / "_state.json"


def _load_disabled() -> set[str]:
    path = _state_path()
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    disabled = data.get("disabled", []) if isinstance(data, dict) else []
    return {str(slug) for slug in disabled}


def _skill_dir(slug: str) -> Path | None:
    """Resolve a slug to its skill directory (workspace shadowing stock), or None.

    Traversal-safe by construction: only directory names enumerated from the roots can
    match, so a slug like ``../foo`` resolves to no key.
    """
    slug = (slug or "").strip()
    if not slug or slug.startswith(RESERVED_PREFIX):
        return None
    found = _iter_skill_dirs().get(slug)
    return found[1] if found else None


def _find_skill_md(skill_dir: Path) -> Path | None:
    """Return the SKILL.md path, matched case-insensitively."""
    for entry in skill_dir.iterdir():
        if entry.is_file() and entry.name.lower() == "skill.md":
            return entry
    return None


def _skill_meta(skill_dir: Path) -> tuple[str, str, str, bool]:
    """Return ``(slug, name, description, valid)`` from a skill's frontmatter."""
    slug = skill_dir.name
    body_path = _find_skill_md(skill_dir)
    if body_path is None:
        return slug, _title_from_slug(slug), "", False
    try:
        meta, _ = _split_frontmatter(body_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, OSError):
        meta = {}
    name = meta.get("name") or _title_from_slug(slug)
    description = meta.get("description", "")
    return slug, name, description, bool(description)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a leading ``---`` YAML frontmatter block from the body.

    Only flat ``key: value`` lines are parsed (enough for name/description). A missing or
    unterminated block yields ``({}, text)``.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta: dict = {}
    body_start = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            body_start = index + 1
            break
        if ":" in lines[index]:
            key, _, value = lines[index].partition(":")
            meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    if body_start is None:
        return {}, text
    return meta, "\n".join(lines[body_start:]).lstrip("\n")


def _reference_manifest(skill_dir: Path) -> list[str]:
    """Return reference files as ``references/``-relative posix paths (nested allowed)."""
    refs_dir = skill_dir / "references"
    if not refs_dir.is_dir():
        return []
    items: list[str] = []
    for entry in sorted(refs_dir.rglob("*")):
        if entry.is_file():
            items.append(entry.relative_to(refs_dir).as_posix())
        if len(items) >= MAX_REFERENCES_LISTED:
            break
    return items


def _reference_entries(skill_dir: Path) -> list[dict]:
    """Return reference files as ``{name, ext, path}`` for the API/UI."""
    entries: list[dict] = []
    for rel in _reference_manifest(skill_dir):
        ext = rel.rsplit(".", 1)[-1].lower() if "." in rel.rsplit("/", 1)[-1] else ""
        entries.append({"name": rel.rsplit("/", 1)[-1], "ext": ext, "path": rel})
    return entries


def _read_text_capped(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if len(text) > MAX_SKILL_CHARS:
        return text[:MAX_SKILL_CHARS] + "\n\n(…truncated)"
    return text


def _title_from_slug(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip().title() or slug
