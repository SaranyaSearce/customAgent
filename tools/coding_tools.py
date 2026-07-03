"""
tools/coding_tools.py — All tools available to the coding agent.

Each tool is:
  1. A Python function that does the actual work.
  2. A JSON schema dict (TOOL_SCHEMAS) that gets passed to the Anthropic API.

The ToolRegistry ties them together and dispatches calls by name.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
from pathlib import Path
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────────────────────────────────────

def _safe_path(work_dir: str, path: str) -> str:
    """Resolve path and ensure it stays inside work_dir."""
    resolved = os.path.realpath(os.path.join(work_dir, path))
    work_resolved = os.path.realpath(work_dir)
    if not resolved.startswith(work_resolved):
        raise PermissionError(
            f"Path '{path}' resolves outside the working directory. "
            f"You are sandboxed to: {work_dir}"
        )
    return resolved


def read_file(path: str, work_dir: str = ".") -> str:
    safe = _safe_path(work_dir, path)
    if not os.path.exists(safe):
        return f"ERROR: File not found: {path}"
    if os.path.isdir(safe):
        return f"ERROR: '{path}' is a directory, not a file."
    try:
        with open(safe, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        return f"ERROR reading file: {e}"


def write_file(path: str, content: str, work_dir: str = ".") -> str:
    safe = _safe_path(work_dir, path)
    Path(safe).parent.mkdir(parents=True, exist_ok=True)
    with open(safe, "w", encoding="utf-8") as f:
        f.write(content)
    return f"OK: Written {len(content)} chars to {path}"


def edit_file(path: str, old_str: str, new_str: str, work_dir: str = ".") -> str:
    """Replace the FIRST occurrence of old_str with new_str in the file."""
    safe = _safe_path(work_dir, path)
    if not os.path.exists(safe):
        return f"ERROR: File not found: {path}"
    with open(safe, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    if old_str not in content:
        return (
            f"ERROR: The string to replace was not found in {path}.\n"
            "Tip: read_file first and copy the exact text you want to replace."
        )
    count = content.count(old_str)
    if count > 1:
        return (
            f"ERROR: old_str appears {count} times in {path}. "
            "Make old_str more specific so it matches exactly once."
        )
    new_content = content.replace(old_str, new_str, 1)
    with open(safe, "w", encoding="utf-8") as f:
        f.write(new_content)
    return f"OK: Edit applied to {path}"


def bash(command: str, work_dir: str = ".", timeout: int = 30) -> str:
    """Run a shell command and return stdout + stderr."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n" if output else "") + "[stderr]\n" + result.stderr
        if not output:
            output = "(no output)"
        if result.returncode != 0:
            output = f"[exit code {result.returncode}]\n" + output
        return output.strip()
    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {timeout}s"
    except Exception as e:
        return f"ERROR running command: {e}"


def list_directory(path: str = ".", work_dir: str = ".") -> str:
    safe = _safe_path(work_dir, path)
    if not os.path.exists(safe):
        return f"ERROR: Directory not found: {path}"
    if not os.path.isdir(safe):
        return f"ERROR: '{path}' is a file, not a directory."
    lines = []
    for entry in sorted(os.scandir(safe), key=lambda e: (not e.is_dir(), e.name)):
        prefix = "📁 " if entry.is_dir() else "📄 "
        lines.append(prefix + entry.name)
    return "\n".join(lines) if lines else "(empty directory)"


def glob_search(pattern: str, work_dir: str = ".") -> str:
    matches = glob.glob(os.path.join(work_dir, pattern), recursive=True)
    matches = [os.path.relpath(m, work_dir) for m in matches]
    if not matches:
        return f"No files matched pattern: {pattern}"
    return "\n".join(sorted(matches))


def grep_search(pattern: str, path: str = ".", work_dir: str = ".") -> str:
    safe = _safe_path(work_dir, path)
    results = []
    search_root = safe if os.path.isdir(safe) else os.path.dirname(safe)
    try:
        re_pattern = re.compile(pattern)
    except re.error as e:
        return f"ERROR: Invalid regex pattern: {e}"
    for root, dirs, files in os.walk(search_root):
        # Skip hidden dirs and common noise
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git")]
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if re_pattern.search(line):
                            rel = os.path.relpath(fpath, work_dir)
                            results.append(f"{rel}:{i}: {line.rstrip()}")
                            if len(results) >= 100:
                                results.append("… (truncated at 100 matches)")
                                return "\n".join(results)
            except Exception:
                continue
    return "\n".join(results) if results else f"No matches for: {pattern}"


# ─────────────────────────────────────────────────────────────────────────────
# JSON schemas for the Anthropic API
# ─────────────────────────────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "read_file",
        "description": "Read the full contents of a file. Always read a file before editing it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file."}
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file with the given content. Prefer edit_file for existing files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to write to."},
                "content": {"type": "string", "description": "Full file content."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Make a targeted edit to an existing file by replacing old_str with new_str. "
            "old_str must match exactly once in the file. Read the file first to get the exact text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_str": {"type": "string", "description": "Exact text to replace (must appear exactly once)."},
                "new_str": {"type": "string", "description": "Replacement text."},
            },
            "required": ["path", "old_str", "new_str"],
        },
    },
    {
        "name": "bash",
        "description": "Run a shell command in the working directory. Returns stdout and stderr.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute."},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30).", "default": 30},
            },
            "required": ["command"],
        },
    },
    {
        "name": "list_directory",
        "description": "List the files and subdirectories in a directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to directory (default '.').", "default": "."}
            },
            "required": [],
        },
    },
    {
        "name": "glob_search",
        "description": "Find files matching a glob pattern (e.g. '**/*.py', 'src/*.ts').",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern relative to working directory."}
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep_search",
        "description": "Search for a regex pattern across files. Returns matching lines with file:line references.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for."},
                "path": {"type": "string", "description": "File or directory to search in (default '.').", "default": "."},
            },
            "required": ["pattern"],
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Tool Registry — dispatch by name
# ─────────────────────────────────────────────────────────────────────────────

class ToolRegistry:
    def __init__(self, work_dir: str = "."):
        self.work_dir = work_dir
        self._dispatch = {
            "read_file": self._read_file,
            "write_file": self._write_file,
            "edit_file": self._edit_file,
            "bash": self._bash,
            "list_directory": self._list_directory,
            "glob_search": self._glob_search,
            "grep_search": self._grep_search,
        }

    def schemas(self) -> list[dict]:
        return TOOL_SCHEMAS

    def execute(self, name: str, inputs: dict[str, Any]) -> str:
        fn = self._dispatch.get(name)
        if fn is None:
            return f"ERROR: Unknown tool '{name}'"
        try:
            return fn(**inputs)
        except TypeError as e:
            return f"ERROR: Bad arguments for tool '{name}': {e}"
        except PermissionError as e:
            return f"PERMISSION ERROR: {e}"
        except Exception as e:
            return f"ERROR in tool '{name}': {e}"

    # ── Wrappers (inject work_dir) ────────────────────────────────────────────

    def _read_file(self, path: str) -> str:
        return read_file(path, self.work_dir)

    def _write_file(self, path: str, content: str) -> str:
        return write_file(path, content, self.work_dir)

    def _edit_file(self, path: str, old_str: str, new_str: str) -> str:
        return edit_file(path, old_str, new_str, self.work_dir)

    def _bash(self, command: str, timeout: int = 30) -> str:
        return bash(command, self.work_dir, timeout)

    def _list_directory(self, path: str = ".") -> str:
        return list_directory(path, self.work_dir)

    def _glob_search(self, pattern: str) -> str:
        return glob_search(pattern, self.work_dir)

    def _grep_search(self, pattern: str, path: str = ".") -> str:
        return grep_search(pattern, path, self.work_dir)