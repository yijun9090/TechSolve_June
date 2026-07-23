"""Claude LLM configuration for the AI Operations Assistant.

Loads the API key from the environment (never hard-coded) and returns a
configured ChatAnthropic instance for use by the LangChain DataFrame agent.
"""

import os

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

# Loads variables from a local .env file into the process environment, if one
# exists (see .env.example). Real env vars already set take precedence and
# are never overwritten.
load_dotenv()

DEFAULT_MODEL = "claude-sonnet-4-6"

# Low temperature: this assistant does data analysis over a fixed dataframe,
# not creative writing. We want consistent, repeatable numbers for the same
# question, not varied phrasing/reasoning paths. Verified live that
# claude-sonnet-4-6 accepts a custom temperature (unlike claude-sonnet-5,
# which rejects any override with a 400 error and only runs at 1.0 — worth
# re-checking live if this DEFAULT_MODEL is ever changed again).
ANALYTICAL_TEMPERATURE = 0.1


def get_api_key() -> str:
    """Reads the Claude API key from the environment. Checks CLAUDE_API_KEY
    first (the name used in this project's .env.example), then falls back to
    ANTHROPIC_API_KEY (the LangChain/Anthropic SDK's own default var name),
    so either naming convention works without code changes."""
    api_key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No Claude API key found. Set CLAUDE_API_KEY or ANTHROPIC_API_KEY "
            "in your environment, or copy .env.example to .env and fill it in."
        )
    return api_key


def get_claude_llm(model: str = DEFAULT_MODEL, temperature: float = ANALYTICAL_TEMPERATURE) -> ChatAnthropic:
    """Returns a configured ChatAnthropic instance. Reusable across the app —
    call this once per session rather than re-instantiating per question."""
    api_key = get_api_key()
    return ChatAnthropic(
        model=model,
        temperature=temperature,
        api_key=api_key,
    )
