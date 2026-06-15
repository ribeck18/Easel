import json

from tools import filesystem, memory, skills, routines


# Maps a tool name to its implementation. Keep in sync with definitions.py.
_DISPATCH = {
    "read_file": filesystem.read_file,
    "write_file": filesystem.write_file,
    "list_directory": filesystem.list_directory,
    "search_files": filesystem.search_files,
    "edit_file": filesystem.edit_file,
    "move_file": filesystem.move_file,
    "delete_file": filesystem.delete_file,
    "search_memory": memory.search_memory,
    "read_wiki_note": memory.read_wiki_note,
    "search_chat_history": memory.search_chat_history,
    "read_chat_history": memory.read_chat_history,
    "memory": memory.memory,
    "read_skill": skills.read_skill,
    "create_routine": routines.create_routine,
}


def execute(tool_name: str, arguments_json: str, context: dict | None = None) -> str:
    """Run a tool by name and return the result as a model-visible string.

    Tool failures (bad arguments, missing files, blocked paths) are returned as
    error strings rather than raised, so the agent loop can hand them back to
    the model to recover from instead of crashing the request.

    Args:
        tool_name: The name of the tool to run, as chosen by the model.
        arguments_json: The raw JSON arguments string from the tool call.
        context: Server-side context (currently ``{"chat_id": int}``) injected into
            tools that need it. The model cannot supply these fields, so they are forced
            here rather than taken from the model's arguments.

    Returns:
        The tool's output, or an error string describing what went wrong.
    """
    implementation = _DISPATCH.get(tool_name)
    if implementation is None:
        return f"Error: unknown tool '{tool_name}'."

    try:
        arguments = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as error:
        return f"Error: could not parse arguments for '{tool_name}': {error}."

    if not isinstance(arguments, dict):
        return f"Error: arguments for '{tool_name}' must be a JSON object."

    if context is not None:
        chat_id = context.get("chat_id")
        if tool_name == "search_chat_history":
            arguments["current_chat_id"] = chat_id
        elif tool_name == "memory":
            arguments["chat_id"] = chat_id

    try:
        return implementation(**arguments)
    except TypeError as error:
        return f"Error: invalid arguments for '{tool_name}': {error}."
