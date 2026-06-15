import json

from ClientModel import ClientModel
from config import Config
from tools.memory import ONBOARD_SECTIONS, write_onboard
from tools.workspace import workspace_available


CAPTURE_PROMPT = """Review this completed chat turn and extract durable memory candidates.

Capture generously: when in doubt, record it. A turn rarely has nothing worth
remembering — names, preferences, decisions, what the user is working on, and
small stated facts all count. Only leave a key empty if that category genuinely
had nothing.

Return only JSON with these keys:
- User facts/preferences
- Decisions
- Topics & entities
- Open tasks/follow-ups
- Notable outcomes

Each value must be an array of short strings.
Do not record secrets, credentials, API keys, tokens, or private prompt text. Redact sensitive
personal data into a general summary instead of copying it verbatim.
"""


def capture_turn(chat_id: int, payload: dict) -> None:
    """Capture salient turn details into the chat's onboard memory file."""
    if not Config.memory_enabled() or not workspace_available():
        return
    if ClientModel.client is None:
        return

    messages = [
        {"role": "system", "content": CAPTURE_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
    ]
    try:
        content = _capture_completion(messages)
        sections = _parse_sections(content)
    except Exception as error:
        print(f"Memory capture skipped for chat {chat_id}: {error}")
        return

    # The model returned text but nothing parsed out: surface it instead of
    # silently dropping the turn, so a misbehaving memory model is debuggable.
    if content.strip() and not any(sections.values()):
        print(
            f"Memory capture produced no sections for chat {chat_id}; "
            f"raw model output: {content[:500]!r}"
        )

    if any(sections.values()):
        write_onboard(chat_id=chat_id, sections=sections)


def _capture_completion(messages: list[dict]) -> str:
    """Run the capture model, preferring JSON mode but tolerating providers that reject it."""
    client = ClientModel.get_client()
    model = Config.memory_model()
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
        )
    except Exception:
        # Some OpenAI-compatible providers don't support response_format; fall back.
        completion = client.chat.completions.create(model=model, messages=messages)
    return completion.choices[0].message.content or ""


def _extract_json_object(content: str) -> str:
    """Pull a JSON object out of a model reply that may be fenced or wrapped in prose.

    Handles bare JSON, ```json fenced blocks, and JSON preceded/followed by commentary
    by falling back to the substring between the first ``{`` and the last ``}``.
    """
    text = content.strip()
    if text.startswith("```"):
        # Drop the opening fence (optionally ```json) and the closing fence.
        text = text.split("\n", 1)[-1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -len("```")]
        text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _parse_sections(content: str) -> dict[str, list[str]]:
    try:
        raw_sections = json.loads(_extract_json_object(content))
    except json.JSONDecodeError:
        raw_sections = {}

    sections: dict[str, list[str]] = {section: [] for section in ONBOARD_SECTIONS}
    if not isinstance(raw_sections, dict):
        return sections

    for section in ONBOARD_SECTIONS:
        raw_items = raw_sections.get(section, [])
        if not isinstance(raw_items, list):
            continue
        sections[section] = [
            str(item).strip() for item in raw_items if str(item).strip()
        ]

    return sections
