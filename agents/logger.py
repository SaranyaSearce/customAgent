"""
agent/logger.py — Structured logger for agent events.

Writes JSON-lines to a log file and pretty-prints to the terminal
using Rich so you can follow what the agent is doing in real time.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

console = Console()


class AgentLogger:
    def __init__(self, log_dir: str = "logs", session_id: str | None = None):
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"session_{self.session_id}.jsonl"

    # ── Internal ──────────────────────────────────────────────────────────────

    def _write(self, event: str, data: dict[str, Any]) -> None:
        record = {
            "ts": datetime.now().isoformat(),
            "session": self.session_id,
            "event": event,
            **data,
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    # ── Public log methods ────────────────────────────────────────────────────

    def user_message(self, text: str) -> None:
        self._write("user_message", {"text": text})
        console.print(Panel(Text(text, style="white"), title="[bold cyan]You", border_style="cyan"))

    def assistant_text(self, text: str) -> None:
        self._write("assistant_text", {"text": text})
        console.print(Panel(Text(text, style="white"), title="[bold green]Agent", border_style="green"))

    def tool_call(self, name: str, inputs: dict) -> None:
        self._write("tool_call", {"tool": name, "inputs": inputs})
        body = json.dumps(inputs, indent=2)
        console.print(
            Panel(
                Syntax(body, "json", theme="monokai", word_wrap=True),
                title=f"[bold yellow]⚙ Tool Call: {name}",
                border_style="yellow",
            )
        )

    def tool_result(self, name: str, result: str, is_error: bool = False) -> None:
        self._write("tool_result", {"tool": name, "result": result, "is_error": is_error})
        style = "red" if is_error else "magenta"
        label = "✗ Error" if is_error else "✓ Result"
        console.print(
            Panel(
                Text(result[:2000] + ("…" if len(result) > 2000 else ""), style="white"),
                title=f"[bold {style}]{label}: {name}",
                border_style=style,
            )
        )

    def system(self, msg: str) -> None:
        self._write("system", {"msg": msg})
        console.print(f"[dim]  ⚡ {msg}[/dim]")

    def warning(self, msg: str) -> None:
        self._write("warning", {"msg": msg})
        console.print(f"[bold orange1]  ⚠ {msg}[/bold orange1]")

    def error(self, msg: str) -> None:
        self._write("error", {"msg": msg})
        console.print(f"[bold red]  ✗ {msg}[/bold red]")

    def usage(self, input_tokens: int, output_tokens: int) -> None:
        self._write("usage", {"input_tokens": input_tokens, "output_tokens": output_tokens})
        console.print(
            f"[dim]  📊 Tokens — in: {input_tokens:,}  out: {output_tokens:,}[/dim]"
        )