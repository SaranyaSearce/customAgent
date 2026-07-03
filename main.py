"""
main.py — CLI entry point for the coding agent.

Usage:
    python main.py                         # interactive REPL
    python main.py --task "write a ..."    # one-shot task
    python main.py --resume logs/session_X.jsonl  # resume a session
    python main.py --work-dir /path/to/project    # set working directory
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.prompt import Confirm, Prompt

from agents.config import AgentConfig
from harness.agent_loop import AgentHarness

console = Console()


# ── Confirmation callback ─────────────────────────────────────────────────────

def interactive_confirm(tool_name: str, inputs: dict) -> bool:
    """Ask the user to approve/deny a sensitive tool call."""
    import json
    console.print(f"\n[bold yellow]⚠  Agent wants to run: [white]{tool_name}[/white][/bold yellow]")
    console.print(f"[dim]{json.dumps(inputs, indent=2)[:500]}[/dim]")
    return Confirm.ask("Allow?", default=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--task", "-t", default=None, help="Run a single task and exit.")
@click.option("--work-dir", "-d", default=".", help="Working directory for the agent (default: current dir).")
@click.option("--resume", "-r", default=None, help="Path to a session .jsonl file to resume.")
@click.option("--no-confirm", is_flag=True, default=False, help="Skip confirmation prompts for sensitive tools.")
@click.option("--model", "-m", default=None, help="Override the model (e.g. claude-opus-4-6).")
def main(task, work_dir, resume, no_confirm, model):
    """
    🤖 Coding Agent — powered by Claude

    An interactive coding assistant that can read, write, and edit files
    and run shell commands on your behalf.
    """
    console.print(
        "\n[bold green]🤖 Coding Agent[/bold green] [dim]powered by Claude[/dim]\n"
        f"   Working directory: [cyan]{os.path.abspath(work_dir)}[/cyan]\n"
        "   Type [bold]/help[/bold] for commands, [bold]/exit[/bold] to quit.\n"
    )

    # ── Build config ──────────────────────────────────────────────────────────
    config = AgentConfig(work_dir=os.path.abspath(work_dir))
    if model:
        config.model = model
    if no_confirm:
        config.confirm_tools = ()   # disable confirmation for all tools

    # ── Build agent ───────────────────────────────────────────────────────────
    try:
        config.validate()
    except ValueError as e:
        console.print(f"[bold red]Configuration error:[/bold red] {e}")
        sys.exit(1)

    confirm_fn = None if no_confirm else interactive_confirm
    agent = AgentHarness(config=config, confirm_fn=confirm_fn)

    # ── Resume a previous session ─────────────────────────────────────────────
    if resume:
        try:
            from agents.history import History
            agent.history = History.load(resume)
            console.print(f"[dim]Resumed session from {resume} ({len(agent.history)} messages)[/dim]\n")
        except Exception as e:
            console.print(f"[bold red]Could not load session:[/bold red] {e}")
            sys.exit(1)

    # ── One-shot mode ─────────────────────────────────────────────────────────
    if task:
        agent.chat(task)
        _print_summary(agent)
        return

    # ── Interactive REPL ──────────────────────────────────────────────────────
    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]You[/bold cyan]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        stripped = user_input.strip()
        if not stripped:
            continue

        # ── Built-in slash commands ───────────────────────────────────────────
        if stripped.startswith("/"):
            if _handle_command(stripped, agent):
                continue
            else:
                break
            continue

        # ── Send to agent ─────────────────────────────────────────────────────
        try:
            agent.chat(stripped)
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
        except Exception as e:
            console.print(f"[bold red]Agent error:[/bold red] {e}")

    _print_summary(agent)


def _handle_command(cmd: str, agent: AgentHarness) -> bool:
    """Handle slash commands. Returns True to continue, False to exit."""
    parts = cmd.split(None, 1)
    name = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if name in ("/exit", "/quit", "/q"):
        console.print("[dim]Goodbye.[/dim]")
        return False

    elif name == "/reset":
        agent.reset()
        console.print("[dim]Conversation cleared.[/dim]")

    elif name == "/save":
        path = arg.strip() or f"logs/session_{agent.logger.session_id}.json"
        agent.history.save(path)
        console.print(f"[dim]Session saved to {path}[/dim]")

    elif name == "/compact":
        agent.history.compact(keep_last=10)
        console.print(f"[dim]History compacted. {len(agent.history)} messages remain.[/dim]")

    elif name == "/status":
        console.print(
            f"[dim]"
            f"  Iterations: {agent.iteration} | "
            f"  History messages: {len(agent.history)} | "
            f"  Est. tokens: {agent.history.estimated_tokens():,} | "
            f"  Total in: {agent.total_input_tokens:,} | "
            f"  Total out: {agent.total_output_tokens:,}"
            f"[/dim]"
        )

    elif name == "/help":
        console.print(
            "[bold]Commands:[/bold]\n"
            "  /reset       — clear conversation history\n"
            "  /save [path] — save session to file\n"
            "  /compact     — compact history to save context space\n"
            "  /status      — show token/iteration stats\n"
            "  /exit        — quit\n"
        )

    else:
        console.print(f"[dim]Unknown command: {name}. Type /help for available commands.[/dim]")

    return True


def _print_summary(agent: AgentHarness) -> None:
    console.print(
        f"\n[dim]Session complete — "
        f"{agent.iteration} iterations | "
        f"{agent.total_input_tokens + agent.total_output_tokens:,} total tokens[/dim]"
    )


if __name__ == "__main__":
    main()