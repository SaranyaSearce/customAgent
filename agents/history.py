"""
agent/history.py — Manages conversation message history.

Handles appending turns, context window size estimation,
and compaction (summarising old turns when history grows too large).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Types matching Anthropic's messages API ──────────────────────────────────
Message = dict[str, Any]   # {"role": "user"|"assistant", "content": str | list}


@dataclass
class History:
    messages: list[Message] = field(default_factory=list)

    # ── Append helpers ────────────────────────────────────────────────────────

    def add_user(self, text: str) -> None:
        """Add a plain-text user message."""
        self.messages.append({"role": "user", "content": text})

    def add_assistant_raw(self, content: list[dict]) -> None:
        """Append the raw content blocks returned by the API as an assistant turn."""
        self.messages.append({"role": "assistant", "content": content})

    def add_tool_results(self, results: list[dict]) -> None:
        """
        Append tool results as a user turn (Anthropic's convention:
        tool results are sent as role='user' with type='tool_result').
        """
        self.messages.append({"role": "user", "content": results})

    # ── Context size estimation ───────────────────────────────────────────────

    def estimated_tokens(self) -> int:
        """
        Rough estimate: 1 token ≈ 4 characters.
        Good enough to decide when to compact.
        """
        raw = json.dumps(self.messages)
        return len(raw) // 4

    # ── Compaction (keeps the last N turns, prepends a summary) ──────────────

    def compact(self, keep_last: int = 10, summary: str = "") -> None:
        """
        Drop older messages, keep the most recent `keep_last` turns.
        Optionally prepend a summary message so context isn't entirely lost.
        """
        if len(self.messages) <= keep_last:
            return

        dropped = self.messages[: len(self.messages) - keep_last]
        self.messages = self.messages[-keep_last:]

        if summary:
            self.messages.insert(
                0,
                {
                    "role": "user",
                    "content": (
                        f"[Context compacted — earlier conversation summary]\n{summary}"
                    ),
                },
            )
        else:
            count = len(dropped)
            self.messages.insert(
                0,
                {
                    "role": "user",
                    "content": f"[Context compacted — {count} earlier messages removed to save space]",
                },
            )

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.messages, f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "History":
        with open(path, "r", encoding="utf-8") as f:
            messages = json.load(f)
        return cls(messages=messages)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self.messages)

    def last_assistant_text(self) -> str:
        """Extract plain text from the last assistant message (if any)."""
        for msg in reversed(self.messages):
            if msg["role"] == "assistant":
                content = msg["content"]
                if isinstance(content, str):
                    return content
                # content is a list of blocks
                return " ".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
        return ""