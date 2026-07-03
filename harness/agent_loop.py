"""
harness/agent_loop.py — The core agent harness.

This is the heart of the agent: it runs the tool-use loop,
manages history and context, and coordinates between the LLM,
tools, and the user.

Loop lifecycle:
  1. Add user message to history
  2. Call Claude with tools
  3. Parse response:
     a. If stop_reason == "end_turn"  → done, return final text
     b. If stop_reason == "tool_use"  → execute tool(s), add results, go to 2
     c. Anything else                 → treat as done
  4. Circuit-breaker: stop if max_iterations exceeded
"""

from __future__ import annotations

import time
from typing import Any, Callable

import anthropic

from agents.config import AgentConfig
from agents.history import History
from agents.logger import AgentLogger
from agents.system_prompt import SYSTEM_PROMPT
from tools.coding_tools import ToolRegistry


class AgentHarness:
    def __init__(
        self,
        config: AgentConfig | None = None,
        confirm_fn: Callable[[str, dict], bool] | None = None,
    ):
        """
        Args:
            config:      AgentConfig instance (uses defaults if None).
            confirm_fn:  Optional callable(tool_name, inputs) -> bool.
                         If provided, called before running tools in `confirm_tools`.
                         Return True to proceed, False to skip.
        """
        self.config = config or AgentConfig()
        self.config.validate()

        self.client = anthropic.Anthropic(api_key=self.config.api_key)
        self.registry = ToolRegistry(work_dir=self.config.work_dir)
        self.logger = AgentLogger(log_dir=self.config.log_dir)
        self.confirm_fn = confirm_fn

        # Session state
        self.history = History()
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.iteration = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def chat(self, user_message: str) -> str:
        """
        Send a user message and run the agent loop until a final answer
        is produced. Returns the final assistant text.
        """
        self.logger.user_message(user_message)
        self.history.add_user(user_message)
        return self._run_loop()

    def reset(self) -> None:
        """Clear conversation history and counters (start fresh)."""
        self.history = History()
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.iteration = 0
        self.logger.system("Session reset.")

    # ── Core loop ─────────────────────────────────────────────────────────────

    def _run_loop(self) -> str:
        while True:
            self.iteration += 1

            # ── Circuit breaker ───────────────────────────────────────────────
            if self.iteration > self.config.max_iterations:
                msg = f"Stopped: reached max iterations ({self.config.max_iterations})."
                self.logger.warning(msg)
                return msg

            # ── Context compaction check ──────────────────────────────────────
            estimated = self.history.estimated_tokens()
            if estimated > self.config.max_context_tokens:
                self.logger.system(
                    f"Context ~{estimated:,} tokens — compacting history..."
                )
                self.history.compact(keep_last=20)

            # ── Call the API ──────────────────────────────────────────────────
            self.logger.system(f"Iteration {self.iteration} — calling Claude...")
            response = self._call_api()

            # ── Track token usage ─────────────────────────────────────────────
            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens
            self.logger.usage(response.usage.input_tokens, response.usage.output_tokens)

            # ── Add assistant response to history ─────────────────────────────
            content_blocks = [block.model_dump() for block in response.content]
            self.history.add_assistant_raw(content_blocks)

            # ── Extract text blocks for display ──────────────────────────────
            text_parts = [
                block.text
                for block in response.content
                if hasattr(block, "text") and block.text
            ]
            if text_parts:
                self.logger.assistant_text("\n".join(text_parts))

            # ── Check stop reason ─────────────────────────────────────────────
            if response.stop_reason == "end_turn":
                return self.history.last_assistant_text()

            if response.stop_reason != "tool_use":
                # Unexpected stop reason — treat as done
                self.logger.warning(f"Unexpected stop_reason: {response.stop_reason}")
                return self.history.last_assistant_text()

            # ── Execute tool calls ────────────────────────────────────────────
            tool_use_blocks = [
                block for block in response.content if block.type == "tool_use"
            ]

            tool_results = []
            for tool_block in tool_use_blocks:
                result_content = self._execute_tool(tool_block)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": result_content,
                })

            self.history.add_tool_results(tool_results)

    # ── API call ──────────────────────────────────────────────────────────────

    def _call_api(self, retries: int = 3, backoff: float = 2.0):
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                return self.client.messages.create(
                    model=self.config.model,
                    max_tokens=self.config.max_tokens,
                    system=SYSTEM_PROMPT,
                    tools=self.registry.schemas(),
                    messages=self.history.messages,
                )
            except anthropic.RateLimitError as e:
                wait = backoff * attempt
                self.logger.warning(f"Rate limit hit (attempt {attempt}). Retrying in {wait}s...")
                time.sleep(wait)
                last_error = e
            except anthropic.APIStatusError as e:
                if e.status_code >= 500:
                    wait = backoff * attempt
                    self.logger.warning(f"Server error {e.status_code} (attempt {attempt}). Retrying in {wait}s...")
                    time.sleep(wait)
                    last_error = e
                else:
                    raise
        raise last_error  # type: ignore

    # ── Tool execution ────────────────────────────────────────────────────────

    def _execute_tool(self, tool_block: Any) -> str:
        name = tool_block.name
        inputs = dict(tool_block.input)

        self.logger.tool_call(name, inputs)

        # ── Confirmation gate ─────────────────────────────────────────────────
        if name in self.config.confirm_tools and self.confirm_fn is not None:
            approved = self.confirm_fn(name, inputs)
            if not approved:
                msg = f"Tool '{name}' was declined by the user."
                self.logger.system(msg)
                return f"CANCELLED: {msg}"

        # ── Execute ───────────────────────────────────────────────────────────
        result = self.registry.execute(name, inputs)
        is_error = result.startswith("ERROR") or result.startswith("PERMISSION ERROR")
        self.logger.tool_result(name, result, is_error=is_error)
        return result