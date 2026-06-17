from datetime import datetime
from pathlib import Path
import hashlib
import os
import shutil
import threading

from dotenv import load_dotenv, set_key

from tools.workspace import resolve_in_workspace, workspace_available
from paths import data_dir


ROOT = data_dir()
ENV_PATH = ROOT / ".env"
AGENTS_PATH = ROOT / "agents.md"

# Core memory now lives inside the user's mounted workspace so it is visible and
# editable as plain Markdown in an Obsidian vault (Memory v2). It is therefore only
# available when a workspace is mounted.
CORE_MEMORY_RELPATH = "Easel/Memory/MEMORY.md"
USER_MEMORY_RELPATH = "Easel/Memory/USER.md"

DEFAULT_MAX_TOOL_CALLS = 55
IDLE_TIMEOUT_MINUTES = 15
LEAVE_GRACE_MINUTES = 2
SWEEPER_INTERVAL_SECONDS = 60
MAX_CONSOLIDATION_ATTEMPTS = 3
STALE_IN_PROGRESS_MINUTES = 30
CORE_MEMORY_BUDGET_CHARS = 6000
WIKI_INDEX_INJECT_BUDGET_CHARS = 3000
SKILLS_INDEX_INJECT_BUDGET_CHARS = 2000
CONSOLIDATOR_TOOL_BUDGET = 30

_CORE_MEMORY_WRITE_LOCK = threading.Lock()


class CoreMemoryUnavailable(Exception):
    """Raised when core memory is touched but no workspace is mounted."""


class CoreMemoryDrift(Exception):
    """Raised when a core memory file changed on disk since it was last read.

    The on-disk version is backed up to ``<file>.bak.<timestamp>`` before this is
    raised, so the external edit is never lost.
    """


class CoreMemoryOverBudget(Exception):
    """Raised when a core memory write would exceed ``CORE_MEMORY_BUDGET_CHARS``."""

    def __init__(self, current: int, limit: int) -> None:
        self.current = current
        self.limit = limit
        super().__init__(
            f"Core memory write is {current} chars but the limit is {limit}."
        )


# Shown when the user has not written their own agents.md yet.
DEFAULT_AGENTS_MD = (
    "# Agents\n\n"
    "You are a helpful AI Assistant, tasked with helping the user learn, grow, and complete important tasks.\n"
)


class Config:
    """App configuration backed by the same ``.env`` (in the app data dir) used for the model.

    Mirrors the static-accessor style of ``ClientModel`` so tool settings live
    alongside the API keys and model selection in one place.
    """

    @staticmethod
    def _ensure_env() -> None:
        ROOT.mkdir(parents=True, exist_ok=True)
        if not ENV_PATH.exists():
            open(ENV_PATH, "w").close()

    @staticmethod
    def tools_enabled() -> bool:
        """Return whether file tools are offered to the model (default off)."""
        load_dotenv(ENV_PATH, override=True)
        return os.getenv("TOOLS_ENABLED", "false").lower() == "true"

    @staticmethod
    def set_tools_enabled(enabled: bool) -> None:
        """Persist the global tools on/off toggle."""
        Config._ensure_env()
        set_key(ENV_PATH, "TOOLS_ENABLED", "true" if enabled else "false")

    @staticmethod
    def max_tool_calls() -> int:
        """Return the per-turn cap on tool calls (default 10)."""
        load_dotenv(ENV_PATH, override=True)
        raw = os.getenv("MAX_TOOL_CALLS")
        if raw is None:
            return DEFAULT_MAX_TOOL_CALLS
        try:
            return int(raw)
        except ValueError:
            return DEFAULT_MAX_TOOL_CALLS

    @staticmethod
    def memory_enabled() -> bool:
        """Return whether memory capture and retrieval are enabled."""
        load_dotenv(ENV_PATH, override=True)
        return os.getenv("MEMORY_ENABLED", "false").lower() == "true"

    @staticmethod
    def set_memory_enabled(enabled: bool) -> None:
        """Persist the global memory on/off toggle."""
        Config._ensure_env()
        set_key(ENV_PATH, "MEMORY_ENABLED", "true" if enabled else "false")

    @staticmethod
    def skills_enabled() -> bool:
        """Return whether skills are offered to the model (default off)."""
        load_dotenv(ENV_PATH, override=True)
        return os.getenv("SKILLS_ENABLED", "false").lower() == "true"

    @staticmethod
    def set_skills_enabled(enabled: bool) -> None:
        """Persist the global skills on/off toggle."""
        Config._ensure_env()
        set_key(ENV_PATH, "SKILLS_ENABLED", "true" if enabled else "false")

    @staticmethod
    def memory_model() -> str:
        """Return the model used for background memory work.

        ``MEMORY_MODEL`` is honored only while the Provider it was configured against
        is still active (model identifiers are Provider-specific). If it is blank, has
        no Provider binding, or was bound to a now-inactive Provider, fall back to the
        Active Provider's own model so background work never runs a model the active
        endpoint doesn't recognize.
        """
        from ClientModel import ClientModel
        from providers import ProviderStore

        load_dotenv(ENV_PATH, override=True)
        model = os.getenv("MEMORY_MODEL")
        bound_id = os.getenv("MEMORY_MODEL_PROVIDER_ID")
        active = ProviderStore.get_active()
        if model and active is not None and bound_id == active["id"]:
            return model
        return ClientModel.get_model()

    @staticmethod
    def set_memory_model(model: str) -> None:
        """Persist the memory model, bound to the currently-active Provider.

        A blank model clears both the model and its Provider binding (falls back to the
        Active Provider's model). A non-blank model records the active Provider's id so
        it is only used while that Provider stays active.
        """
        from providers import ProviderStore

        Config._ensure_env()
        set_key(ENV_PATH, "MEMORY_MODEL", model)
        if model:
            active = ProviderStore.get_active()
            set_key(ENV_PATH, "MEMORY_MODEL_PROVIDER_ID", active["id"] if active else "")
        else:
            set_key(ENV_PATH, "MEMORY_MODEL_PROVIDER_ID", "")

    @staticmethod
    def get_memory_model_setting() -> str:
        """Return the explicitly configured memory model, if any."""
        load_dotenv(ENV_PATH, override=True)
        return os.getenv("MEMORY_MODEL", "")

    @staticmethod
    def get_core_memory(kind: str) -> str:
        """Return MEMORY.md or USER.md content, or empty text if unavailable.

        Core memory lives in the workspace, so an unmounted workspace yields ``""``
        rather than an error (the read path stays soft).
        """
        if not workspace_available():
            return ""
        path = _core_memory_path(kind)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    @staticmethod
    def get_core_memory_with_fingerprint(kind: str) -> tuple[str, str]:
        """Return ``(content, fingerprint)`` for drift-checked writes.

        The fingerprint is a sha256 of the current on-disk content (or of ``""`` when
        the file is absent), so a later ``set_core_memory`` can detect an external edit.
        """
        content = Config.get_core_memory(kind)
        return content, _fingerprint(content)

    @staticmethod
    def set_core_memory(
        kind: str, content: str, expected_fingerprint: str | None = None
    ) -> None:
        """Atomically write MEMORY.md or USER.md into the workspace.

        Args:
            kind: ``"memory"`` or ``"user"``.
            content: The full new file content.
            expected_fingerprint: When given, the on-disk file must still hash to this
                value or the write aborts (the user hand-edited it). Pass ``None`` for
                the Settings save path, where the user is the editor and wins outright.

        Raises:
            CoreMemoryUnavailable: No workspace is mounted.
            CoreMemoryDrift: The file changed on disk since it was read (a backup of the
                on-disk version is written first).
            CoreMemoryOverBudget: The content exceeds ``CORE_MEMORY_BUDGET_CHARS``.
        """
        from tools.memory import scrub_secrets
        from tools import threat_patterns

        if not workspace_available():
            raise CoreMemoryUnavailable(
                "No workspace is mounted, so core memory cannot be written."
            )

        safe = scrub_secrets(content)
        # Write-path injection redaction: never persist instruction-shaped text into a
        # file that is re-injected into future system prompts.
        safe = threat_patterns.sanitize_for_model(safe, source=f"core:{kind}")

        if len(safe) > CORE_MEMORY_BUDGET_CHARS:
            raise CoreMemoryOverBudget(
                current=len(safe), limit=CORE_MEMORY_BUDGET_CHARS
            )

        path = _core_memory_path(kind)
        with _CORE_MEMORY_WRITE_LOCK:
            if expected_fingerprint is not None:
                on_disk = path.read_text(encoding="utf-8") if path.exists() else ""
                if _fingerprint(on_disk) != expected_fingerprint:
                    _backup_core_file(path)
                    raise CoreMemoryDrift(
                        f"{path.name} was modified outside the app since it was read."
                    )

            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_suffix(path.suffix + ".tmp")
            temp_path.write_text(safe, encoding="utf-8")
            os.replace(temp_path, path)

    @staticmethod
    def get_agents_md() -> str:
        """Return the user-editable agents.md content, or a default template."""
        if not AGENTS_PATH.exists():
            return DEFAULT_AGENTS_MD
        return AGENTS_PATH.read_text(encoding="utf-8")

    @staticmethod
    def set_agents_md(content: str) -> None:
        """Persist the user-editable agents.md content."""
        ROOT.mkdir(parents=True, exist_ok=True)
        AGENTS_PATH.write_text(content, encoding="utf-8")


def _core_memory_path(kind: str) -> Path:
    if kind == "memory":
        return resolve_in_workspace(CORE_MEMORY_RELPATH)
    if kind == "user":
        return resolve_in_workspace(USER_MEMORY_RELPATH)
    raise ValueError("Core memory kind must be 'memory' or 'user'.")


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _backup_core_file(path: Path) -> None:
    """Copy a core memory file aside before an aborted drift write, if it exists."""
    if not path.exists():
        return
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{timestamp}")
    shutil.copy2(path, backup)
