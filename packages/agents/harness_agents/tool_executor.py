"""
ToolExecutor — file I/O, shell commands, code search.

Layer 1 of the three-layer harness-agents architecture.
Standalone module: no imports from harness-cook SDK core (packages/core).

Provides:
  - ToolCall / ToolResult dataclasses
  - ToolExecutor class with 6 built-in tools
  - Dynamic tool registration via register_tool()
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


# ═══════════════════════════════════════════════════════════
#  Data types
# ═══════════════════════════════════════════════════════════

@dataclass
class ToolCall:
    """A single tool invocation request.

    Mirrors the OpenAI function-calling convention so that
    AgentRuntime can pass LLM tool_calls straight through.
    """
    tool_name: str
    args: Dict[str, Any]
    id: str = ""


@dataclass
class ToolResult:
    """Outcome of executing a ToolCall.

    success=True  → output holds the result string.
    success=False → error holds the exception message.
    """
    success: bool
    output: str = ""
    error: Optional[str] = None
    tool_name: str = ""
    duration_ms: int = 0


# ═══════════════════════════════════════════════════════════
#  Built-in tool handlers
# ═══════════════════════════════════════════════════════════

def _handle_read_file(args: Dict[str, Any]) -> str:
    """Read a file and return its content.

    Args:
        path    – file path (absolute or relative)
        offset  – 1-indexed start line (optional, default 1)
        limit   – max lines to return (optional, default whole file)
    """
    path = Path(args["path"])
    offset = int(args.get("offset", 1))
    limit = args.get("limit")

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    # 1-indexed → 0-indexed slice
    start = max(offset - 1, 0)
    end = start + int(limit) if limit is not None else len(lines)
    selected = lines[start:end]

    # Reconstruct with line numbers
    numbered = []
    for i, line in enumerate(selected, start=start + 1):
        numbered.append(f"{i}|{line}")

    return "\n".join(numbered)


def _handle_write_file(args: Dict[str, Any]) -> str:
    """Write content to a file, creating parent dirs if needed.

    Args:
        path    – file path
        content – full text to write
    """
    path = Path(args["path"])
    content = args["content"]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    lines = content.splitlines()
    return f"Written {len(lines)} lines to {path}"


def _handle_search_code(args: Dict[str, Any]) -> str:
    """Search for a regex pattern in files under a directory.

    Args:
        path       – root directory to search (optional, default cwd)
        pattern    – regex pattern to search for
        file_glob  – glob filter e.g. '*.py' (optional)
    """
    pattern = args["pattern"]
    root = Path(args.get("path", "."))
    file_glob = args.get("file_glob")

    if not root.exists():
        raise FileNotFoundError(f"Path not found: {root}")

    regex = re.compile(pattern)

    matches: List[str] = []
    files_scanned = 0

    if file_glob:
        paths = sorted(root.rglob(file_glob))
    else:
        paths = sorted(root.rglob("*"))

    for candidate in paths:
        if not candidate.is_file():
            continue
        # Skip binary-ish files by extension
        if candidate.suffix in (
            ".pyc", ".so", ".dll", ".exe", ".bin",
            ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico",
            ".zip", ".tar", ".gz", ".whl",
        ):
            continue

        try:
            text = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        files_scanned += 1
        for line_no, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{candidate}:{line_no}: {line}")

    header = f"Scanned {files_scanned} files, {len(matches)} matches for '{pattern}'"
    if matches:
        return header + "\n" + "\n".join(matches[:200])
    return header + "\n(no matches found)"


def _handle_run_command(args: Dict[str, Any]) -> str:
    """Execute a shell command via subprocess.

    Args:
        command – shell command string
        timeout – max seconds to wait (optional, default 30)
        cwd     – working directory (optional, default cwd)
    """
    command = args["command"]
    timeout = int(args.get("timeout", 30))
    cwd = args.get("cwd", os.getcwd())

    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )

    parts: List[str] = []
    if result.stdout:
        parts.append(result.stdout)
    if result.stderr:
        parts.append(f"[stderr]\n{result.stderr}")

    parts.append(f"[exit_code={result.returncode}]")

    output = "\n".join(parts)
    # Truncate very long outputs
    if len(output) > 10000:
        output = output[:10000] + "\n... (truncated)"

    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, command, output
        )

    return output


def _handle_list_files(args: Dict[str, Any]) -> str:
    """List files in a directory, optionally filtered by glob.

    Args:
        path    – directory path (optional, default cwd)
        pattern – glob filter e.g. '*.py' (optional)
    """
    root = Path(args.get("path", "."))
    pattern = args.get("pattern")

    if not root.exists():
        raise FileNotFoundError(f"Path not found: {root}")
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    if pattern:
        entries = sorted(root.glob(pattern))
    else:
        entries = sorted(root.iterdir())

    lines: List[str] = []
    for entry in entries:
        kind = "D" if entry.is_dir() else "F"
        size = ""
        if entry.is_file():
            try:
                size = f"  ({entry.stat().st_size} bytes)"
            except OSError:
                size = ""
        lines.append(f"[{kind}] {entry.name}{size}")

    if not lines:
        return f"Empty directory: {root}"

    return f"{root} — {len(lines)} entries\n" + "\n".join(lines)


def _handle_edit_file(args: Dict[str, Any]) -> str:
    """Find-and-replace edit in a file.

    Args:
        path       – file path
        old_string – exact text to find (must be unique in the file)
        new_string – replacement text
    """
    path = Path(args["path"])
    old_string = args["old_string"]
    new_string = args["new_string"]

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")

    content = path.read_text(encoding="utf-8")

    count = content.count(old_string)
    if count == 0:
        raise ValueError(f"old_string not found in {path}")
    if count > 1:
        raise ValueError(
            f"old_string appears {count} times in {path} — must be unique"
        )

    new_content = content.replace(old_string, new_string)
    path.write_text(new_content, encoding="utf-8")

    old_lines = old_string.splitlines()
    new_lines = new_string.splitlines()
    return (
        f"Edited {path}: replaced {len(old_lines)} lines "
        f"with {len(new_lines)} lines"
    )


# ═══════════════════════════════════════════════════════════
#  Tool schemas (OpenAI function-calling style)
# ═══════════════════════════════════════════════════════════

BUILTIN_TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "read_file": {
        "name": "read_file",
        "description": "Read a file and return its content with line numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative file path.",
                },
                "offset": {
                    "type": "integer",
                    "description": "1-indexed start line (default 1).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of lines to return.",
                },
            },
            "required": ["path"],
        },
    },
    "write_file": {
        "name": "write_file",
        "description": "Write content to a file, creating parent dirs if needed.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path to write.",
                },
                "content": {
                    "type": "string",
                    "description": "Full text content to write.",
                },
            },
            "required": ["path", "content"],
        },
    },
    "search_code": {
        "name": "search_code",
        "description": "Search for a regex pattern in files under a directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for.",
                },
                "path": {
                    "type": "string",
                    "description": "Root directory to search (default: cwd).",
                },
                "file_glob": {
                    "type": "string",
                    "description": "Glob filter e.g. '*.py'.",
                },
            },
            "required": ["pattern"],
        },
    },
    "run_command": {
        "name": "run_command",
        "description": "Execute a shell command and return stdout/stderr.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max seconds to wait (default 30).",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for the command.",
                },
            },
            "required": ["command"],
        },
    },
    "list_files": {
        "name": "list_files",
        "description": "List files and subdirectories in a directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path (default: cwd).",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob filter e.g. '*.py'.",
                },
            },
            "required": [],
        },
    },
    "edit_file": {
        "name": "edit_file",
        "description": "Find-and-replace edit in a file. old_string must be unique.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path to edit.",
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact text to find (must be unique in file).",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text.",
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
}

# Handler mapping: tool_name → callable
BUILTIN_TOOL_HANDLERS: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "read_file":    _handle_read_file,
    "write_file":   _handle_write_file,
    "search_code":  _handle_search_code,
    "run_command":  _handle_run_command,
    "list_files":   _handle_list_files,
    "edit_file":    _handle_edit_file,
}


# ═══════════════════════════════════════════════════════════
#  ToolExecutor
# ═══════════════════════════════════════════════════════════

class ToolExecutor:
    """Execute tool calls from the ReAct loop.

    Built-in tools handle file I/O, shell commands, and code search.
    Additional tools can be registered dynamically via register_tool().
    """

    BUILT_IN_TOOLS: Dict[str, Callable[[Dict[str, Any]], str]] = BUILTIN_TOOL_HANDLERS

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable[[Dict[str, Any]], str]] = dict(
            self.BUILT_IN_TOOLS
        )
        self._schemas: Dict[str, Dict[str, Any]] = dict(BUILTIN_TOOL_SCHEMAS)

    # ── core execution ────────────────────────────────────

    def execute(self, call: ToolCall) -> ToolResult:
        """Execute a ToolCall and return a ToolResult.

        Catches all exceptions so the ReAct loop never crashes
        on a bad tool call — errors become ToolResult(success=False).
        """
        start = time.monotonic()

        handler = self._handlers.get(call.tool_name)
        if handler is None:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                success=False,
                error=f"Unknown tool: {call.tool_name}",
                tool_name=call.tool_name,
                duration_ms=elapsed_ms,
            )

        try:
            output = handler(call.args)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                success=True,
                output=output,
                tool_name=call.tool_name,
                duration_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                success=False,
                error=str(exc),
                tool_name=call.tool_name,
                duration_ms=elapsed_ms,
            )

    # ── tool discovery ────────────────────────────────────

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return tool definitions for the ReAct system prompt.

        Each definition includes name, description, and parameters schema
        formatted for inclusion in the agent's prompt.
        """
        defs = []
        for name, schema in self._schemas.items():
            defs.append({
                "name": name,
                "description": schema.get("description", ""),
                "parameters": schema.get("parameters", {}),
            })
        # Also include dynamically registered tools
        for name, handler in self._handlers.items():
            if name not in self._schemas:
                defs.append({
                    "name": name,
                    "description": "Dynamically registered tool",
                    "parameters": {},
                })
        return defs

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Return tool schemas in OpenAI function-calling format.

        Each entry: {name, description, parameters}.
        """
        return list(self._schemas.values())

    # ── dynamic registration ──────────────────────────────

    def register_tool(
        self,
        name: str,
        handler: Callable[[Dict[str, Any]], str],
        schema: Dict[str, Any],
    ) -> None:
        """Register a custom tool at runtime.

        Args:
            name    – tool name (must not collide with built-ins)
            handler – callable taking args dict, returning str output
            schema  – OpenAI-style function schema dict
        """
        if name in self._handlers and name in self.BUILT_IN_TOOLS:
            raise ValueError(
                f"Cannot override built-in tool: {name}"
            )
        self._handlers[name] = handler
        self._schemas[name] = schema