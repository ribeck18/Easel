"""Prompt-injection / memory-poisoning scanner for the memory subsystem.

Pure functions, no I/O. Modeled on Hermes Agent's ``threat_patterns.py``. This is
defense-in-depth alongside ``scrub_secrets`` (which redacts credentials): this module
catches content that tries to *instruct* the model when it is later re-injected from
memory or surfaced by a search tool.

Two surfaces use it:

- **Write path** — before persisting onboard/wiki/core files, flagged spans are replaced
  with a ``[BLOCKED: ...]`` placeholder so injection text never lands in a file that gets
  re-injected into a future system prompt.
- **Read path** — when core memory is injected, or when a search/read tool returns stored
  content, the returned string is sanitized the same way. The on-disk/DB content is left
  intact so the user can still inspect and remove it via the Memory UI.

Invisible/zero-width Unicode is *stripped* rather than placeholder-replaced (there is
nothing meaningful to show the user), but is still reported as a match.
"""

from dataclasses import dataclass
import re


PLACEHOLDER_TEMPLATE = "[BLOCKED: {category} content removed]"

# Anchored injection phrases. Kept deliberately specific (multi-word, anchored) so normal
# prose that merely mentions "system" or "instructions" does not trip the scanner.
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above|preceding)\s+(instructions|prompts?|rules|messages)",
    r"disregard\s+(all\s+)?(your\s+|the\s+|previous\s+|prior\s+)*(instructions|system\s+prompt|rules)",
    r"forget\s+(everything|all)\s+(you\s+)?(were\s+told|know|above)",
    r"you\s+are\s+now\s+(a|an|the|in)\b",
    r"new\s+(system\s+)?instructions?\s*[:\-]",
    r"do\s+not\s+(tell|inform|mention\s+to|reveal\s+to)\s+the\s+user",
    r"(?:enter|activate|enable)\s+(?:DAN|developer|jailbreak|god)\s+mode",
    r"pretend\s+(that\s+)?you\s+(are|have)\b",
    r"override\s+(your\s+)?(system\s+prompt|previous\s+instructions|safety)",
]

# Lines that imitate chat-template / role structure inside remembered free text.
_ROLE_SPOOF_PATTERNS = [
    r"(?im)^\s*(system|assistant|developer)\s*:",
    r"<\|\s*(im_start|im_end|system|user|assistant)\s*\|>",
    r"\[/?INST\]",
    r"(?im)^\s*#{1,6}\s*system\b",
    r"<\s*/?\s*(system|assistant)\s*>",
]

# Attempts to make remembered text drive an outbound data leak.
_EXFILTRATION_PATTERNS = [
    r"(?i)(send|post|upload|forward|exfiltrate|leak|email)\b.{0,40}\b(https?://|www\.)",
    r"!\[[^\]]*\]\(\s*https?://[^)]*[?&][^)]*\)",  # markdown image w/ query payload
    r"(?i)\b(curl|wget|fetch)\s+https?://",
    r"(?i)(send|share|give)\s+(me\s+)?(your|the)\s+(api\s+keys?|credentials|secrets?|password)",
]

# Invisible / control characters that can smuggle hidden instructions.
_INVISIBLE_RANGES = (
    (0x200B, 0x200F),  # zero-width space .. RLM
    (0x2060, 0x2064),  # word joiner .. invisible plus
    (0x202A, 0x202E),  # bidi embedding/override controls
    (0x2066, 0x2069),  # bidi isolate controls
    (0xFEFF, 0xFEFF),  # BOM / zero-width no-break space
    (0xE0000, 0xE007F),  # Unicode tag block
)

_INVISIBLE_RE = re.compile(
    "[" + "".join(f"\\U{lo:08X}-\\U{hi:08X}" for lo, hi in _INVISIBLE_RANGES) + "]"
)

_COMPILED: list[tuple[str, re.Pattern]] = (
    [("injection", re.compile(p, re.IGNORECASE)) for p in _INJECTION_PATTERNS]
    + [("role_spoof", re.compile(p)) for p in _ROLE_SPOOF_PATTERNS]
    + [("exfiltration", re.compile(p)) for p in _EXFILTRATION_PATTERNS]
)


@dataclass(frozen=True)
class ThreatMatch:
    """One scanner hit: what fired, and the offending span (clipped)."""

    category: str  # "injection" | "exfiltration" | "invisible_unicode" | "role_spoof"
    pattern: str
    excerpt: str


def _clip(text: str, limit: int = 80) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def scan_text(text: str) -> list[ThreatMatch]:
    """Return every threat match in ``text`` (empty list means clean)."""
    if not text:
        return []

    matches: list[ThreatMatch] = []
    for category, pattern in _COMPILED:
        for found in pattern.finditer(text):
            matches.append(
                ThreatMatch(
                    category=category,
                    pattern=pattern.pattern,
                    excerpt=_clip(found.group(0)),
                )
            )

    for found in _INVISIBLE_RE.finditer(text):
        matches.append(
            ThreatMatch(
                category="invisible_unicode",
                pattern="invisible_unicode",
                excerpt=f"U+{ord(found.group(0)):04X}",
            )
        )

    return matches


def is_clean(text: str) -> bool:
    """Return whether ``text`` contains no threat patterns."""
    return not scan_text(text)


def sanitize_for_model(text: str, source: str = "memory") -> str:
    """Neutralize threats in ``text`` for safe re-injection into the model.

    Invisible characters are stripped; injection/role-spoof/exfiltration spans are
    replaced with a ``[BLOCKED: ...]`` placeholder. ``source`` is accepted for caller
    clarity/logging and does not change behavior.
    """
    if not text:
        return text

    # Strip invisibles first so they cannot hide inside a later replacement.
    cleaned = _INVISIBLE_RE.sub("", text)

    # Replace from the end so earlier match offsets stay valid as we splice.
    spans: list[tuple[int, int, str]] = []
    for category, pattern in _COMPILED:
        for found in pattern.finditer(cleaned):
            spans.append(
                (found.start(), found.end(), PLACEHOLDER_TEMPLATE.format(category=category))
            )

    if not spans:
        return cleaned

    spans.sort(key=lambda s: s[0])
    merged: list[tuple[int, int, str]] = []
    for start, end, placeholder in spans:
        if merged and start < merged[-1][1]:
            # Overlapping matches: keep the widest span, one placeholder.
            prev_start, prev_end, prev_ph = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end), prev_ph)
            continue
        merged.append((start, end, placeholder))

    result = cleaned
    for start, end, placeholder in reversed(merged):
        result = result[:start] + placeholder + result[end:]
    return result
