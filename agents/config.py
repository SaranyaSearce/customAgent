"""
agent/config.py — Central configuration for the coding agent.
Loads settings from environment variables / .env file.
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class AgentConfig:
    # --- LLM settings ---
    api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    model: str = field(default_factory=lambda: os.getenv("AGENT_MODEL", "claude-haiku-4-5"))
    max_tokens: int = field(default_factory=lambda: int(os.getenv("AGENT_MAX_TOKENS", "200")))

    # --- Loop safety ---
    max_iterations: int = field(
        default_factory=lambda: int(os.getenv("AGENT_MAX_ITERATIONS", "50"))
    )
    max_context_tokens: int = 180_000   # Start compacting before hitting the limit

    # --- Filesystem sandbox ---
    work_dir: str = field(default_factory=lambda: os.path.abspath(os.getenv("AGENT_WORK_DIR", ".")))

    # --- Tools that require user confirmation before executing ---
    confirm_tools: tuple = ("bash", "write_file", "edit_file")

    # --- Logging ---
    log_dir: str = "logs"

    def validate(self) -> None:
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Add it to your .env file or export it as an environment variable."
            )