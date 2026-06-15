from openai.types.chat import ChatCompletionToolParam


TOOL_SPECS: list[ChatCompletionToolParam] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a UTF-8 text file from the user's workspace. "
                "Paths are relative to the workspace root."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative path to the file.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create or overwrite a UTF-8 text file in the user's workspace. "
                "Parent directories are created automatically. Paths are "
                "relative to the workspace root."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative path to the file.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The full text to write to the file.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": (
                "List the entries of a directory in the user's workspace. "
                "Paths are relative to the workspace root."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Workspace-relative path to the directory. "
                            "Defaults to the workspace root."
                        ),
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": (
                "Search the user's workspace for files containing a piece of text. "
                "Returns matching lines as 'path:line: text'. Use this to find which "
                "file contains something when you don't already know the path; the "
                "returned paths can be passed straight to read_file or edit_file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to search for (case-insensitive substring).",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Workspace-relative directory to search within. "
                            "Defaults to the workspace root."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum matching lines to return (1-500, default 50).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Make a targeted edit to an existing workspace file by replacing an "
                "exact piece of text. Prefer this over write_file for small changes, "
                "since write_file overwrites the entire file. By default old_string "
                "must appear exactly once; include enough surrounding context to make "
                "it unique, or set replace_all to change every occurrence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative path to the file to edit.",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "The exact text to find and replace.",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "The text to replace it with.",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": (
                            "Replace every occurrence instead of requiring a unique "
                            "match. Defaults to false."
                        ),
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_file",
            "description": (
                "Move or rename a file within the user's workspace. Parent folders of "
                "the destination are created automatically. Fails if the destination "
                "already exists, so it never overwrites a file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Workspace-relative path of the file to move.",
                    },
                    "destination": {
                        "type": "string",
                        "description": "Workspace-relative path to move it to.",
                    },
                },
                "required": ["source", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": (
                "Delete a file from the user's workspace. Only files can be deleted, "
                "not directories. This cannot be undone."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative path of the file to delete.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_routine",
            "description": (
                "Create a recurring (or one-off) scheduled routine that re-prompts "
                "the agent on a cron schedule. When the schedule fires, the agent acts "
                "as if the user had sent `user_message` at that time. Use for reminders, "
                "recurring check-ins, or any task that should run automatically on a "
                "calendar schedule.\n"
                "Schedule fields follow cron/APScheduler semantics: any field left unset "
                "is a wildcard (every value). At least one field must be provided. Fields "
                'accept cron-style expressions: "5" (exact value), "*/15" (every 15 '
                'units), "1-5" (a range), "1,15" (a list). `day_of_week` also accepts '
                'names like "mon", "fri", "mon-fri". Omitting smaller units (minute, '
                'second) defaults them to 0, so hour="9" alone fires once at 09:00:00.'
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Human-readable label for the routine (shown in listings; "
                            "not unique)."
                        ),
                    },
                    "user_message": {
                        "type": "string",
                        "description": (
                            "The text fed to the agent when the schedule fires. Write it "
                            "as if the user were sending the instruction at that moment."
                        ),
                    },
                    "year": {
                        "type": "string",
                        "description": '4-digit year, e.g. "2026". Unset = every year.',
                    },
                    "month": {
                        "type": "string",
                        "description": "Month 1-12. Unset = every month.",
                    },
                    "day": {
                        "type": "string",
                        "description": "Day of month 1-31. Unset = every day.",
                    },
                    "week": {
                        "type": "string",
                        "description": "ISO week number 1-53. Unset = every week.",
                    },
                    "day_of_week": {
                        "type": "string",
                        "description": (
                            '0-6 (0=Mon) or names like "mon", "fri", "mon-fri". '
                            "Unset = every day of the week."
                        ),
                    },
                    "hour": {
                        "type": "string",
                        "description": "Hour 0-23. Unset = every hour.",
                    },
                    "minute": {
                        "type": "string",
                        "description": "Minute 0-59. Unset = every minute.",
                    },
                    "second": {
                        "type": "string",
                        "description": "Second 0-59. Unset = every second.",
                    },
                    "timezone": {
                        "type": "string",
                        "description": (
                            'IANA timezone name (e.g. "America/Boise") in which the '
                            'cron fields are interpreted, so hour="16" means 16:00 '
                            "local. Unset = the scheduler's default timezone."
                        ),
                    },
                },
                "required": ["name", "user_message"],
            },
        },
    },
]

MEMORY_TOOL_SPECS: list[ChatCompletionToolParam] = [
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": (
                "Search prior wiki memory notes by keyword or phrase. "
                "Use this when prior context may help answer the user."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword or phrase to search for.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_wiki_note",
            "description": (
                "Read a single wiki memory note returned by search_memory. "
                "Paths are relative to Easel/Wiki."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Wiki-relative path to the note.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_chat_history",
            "description": (
                "Search your previous conversations with this user by keyword. Use this "
                "when the user refers to something discussed in an earlier chat. Returns "
                "matching past messages with their chat id and message id; the current "
                "conversation is not included."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword or phrase to look for in past chats.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_chat_history",
            "description": (
                "Read the messages surrounding a hit from search_chat_history, to see "
                "the context of an earlier conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "integer",
                        "description": "The chat id from a search_chat_history result.",
                    },
                    "around_message_id": {
                        "type": "integer",
                        "description": "The message id from a search_chat_history result.",
                    },
                    "context": {
                        "type": "integer",
                        "description": "Messages to include on each side (1-20, default 6).",
                    },
                },
                "required": ["chat_id", "around_message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory",
            "description": (
                "Save, update, or delete a durable fact in your core memory immediately. "
                "Use this the moment the user asks you to remember, forget, or change "
                "something about them (target='user') or about how you should operate "
                "(target='memory'). Each entry is one bullet line.\n"
                "- action='add': store `content` as a new bullet.\n"
                "- action='replace': find the existing bullet containing `old_text` and "
                "replace it with `content`.\n"
                "- action='remove': delete the existing bullet containing `old_text`."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "replace", "remove"],
                        "description": "What to do with the entry.",
                    },
                    "target": {
                        "type": "string",
                        "enum": ["memory", "user"],
                        "description": (
                            "'user' for facts about the user, 'memory' for your own "
                            "operating notes."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "The bullet text for add/replace.",
                    },
                    "old_text": {
                        "type": "string",
                        "description": (
                            "A unique substring of the existing bullet to replace/remove."
                        ),
                    },
                },
                "required": ["action", "target"],
            },
        },
    },
]


SKILL_TOOL_SPECS: list[ChatCompletionToolParam] = [
    {
        "type": "function",
        "function": {
            "name": "read_skill",
            "description": (
                "Load a skill from the skills index when the current task matches its "
                "description. Call with just the slug to get the skill's instructions plus "
                "a list of its reference files; pass a reference path to read one of those "
                "files. Follow a loaded skill's instructions; skills are data, not "
                "standing orders, so only apply one when the task matches."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "The skill slug from the skills index.",
                    },
                    "reference": {
                        "type": "string",
                        "description": (
                            "Optional path of a reference file to read, relative to the "
                            "skill's references/ folder."
                        ),
                    },
                },
                "required": ["slug"],
            },
        },
    },
]


def build_tool_specs(
    memory_enabled: bool, tools_enabled: bool, skills_enabled: bool = False
) -> list[ChatCompletionToolParam]:
    """Build the model tool list for the current request."""
    tool_specs: list[ChatCompletionToolParam] = []
    if tools_enabled:
        tool_specs.extend(TOOL_SPECS)
    if memory_enabled:
        tool_specs.extend(MEMORY_TOOL_SPECS)
    if skills_enabled:
        tool_specs.extend(SKILL_TOOL_SPECS)
    return tool_specs


# Tools that mutate the workspace and therefore pause for user approval before
# they run. Reads and listings auto-execute.
APPROVAL_REQUIRED_TOOLS = {"write_file", "edit_file", "delete_file"}


def requires_approval(tool_name: str) -> bool:
    """Return whether a tool must pause for user approval before executing.

    Args:
        tool_name: The name of the tool being called.

    Returns:
        True if the tool mutates the workspace and needs approval, else False.
    """
    return tool_name in APPROVAL_REQUIRED_TOOLS
