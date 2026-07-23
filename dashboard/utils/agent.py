"""LangChain pandas DataFrame agent — the "brain" of the AI Operations
Assistant. Wraps the Claude LLM (utils/claude_config.py) around the ticket
dataframe so it can answer natural-language operations questions by writing
and running its own pandas code against the data.

This module never cleans, mutates, or writes back to the dataframe — it only
reads it. Analysis (filtering/grouping/aggregation) happens inside the
agent's own generated code, scoped to the in-memory dataframe it's given.
"""

import re

import anthropic
import pandas as pd
from langchain_experimental.agents import create_pandas_dataframe_agent

from .claude_config import get_claude_llm


class AgentQuestionError(Exception):
    """Raised when a question fails to get an answer, with a message that's
    already safe to show the user directly (via st.error). Kept distinct from
    a normal successful answer so the Streamlit page can render them
    differently instead of an error silently looking like a real answer."""

# Matches phrasing the agent uses when it claims a number is the FULL dataset
# size (not a category sub-count) — e.g. "across all 101,688 tickets", "total
# of 100,851 tickets", "100,851 tickets in the dataset", "the full dataset of
# 101,540 tickets". Deliberately scoped to these total-claiming phrasings, not
# any "N tickets" mention, so it never touches a legitimate category count
# like "10,228 Bug Report tickets".
#
# This list grows by observed failure, not by design — every branch here is a
# phrasing the model was actually caught using in testing that produced a
# wrong number. It is NOT exhaustive: an LLM can phrase "the total is N" in
# more ways than any fixed regex can enumerate, so this is a best-effort net
# for the common cases, not a hard guarantee. See the module docstring note
# below ask_operations_question for how this is disclosed.
_TOTAL_TICKETS_PATTERN = re.compile(
    r"(?:across all|total of|out of)\s+\*{0,2}[\d,]{3,}\*{0,2}\s+tickets\*{0,2}"
    r"|\*{0,2}[\d,]{3,}\*{0,2}\s+tickets\*{0,2}\s+in the dataset"
    r"|(?:full\s+|entire\s+|whole\s+)?dataset of\s+\*{0,2}[\d,]{3,}\*{0,2}\s+tickets\*{0,2}",
    re.IGNORECASE,
)

_NUMBER_IN_PHRASE = re.compile(r"[\d,]{3,}")

# Columns the agent should treat as authoritative. Mirrors CLAUDE.md's data
# conventions from the cleaning pipeline (m2_clean.py) — the agent can see
# every column in the dataframe, so it has to be told explicitly which ones
# are safe to reason about.
TRUSTED_COLUMNS = (
    "resolution_time_hours, first_response_time_hours, sla_breached_calc, "
    "sla_target_hours, category_group, category_clean, account_type, "
    "tenure_months_calc, previous_tickets_calc, csat_valid, status, priority, "
    "team, region, escalated, is_national_holiday, is_regional_anniversary, "
    "is_public_holiday, is_duplicate, ticket_created_date, monthly_contract_value"
)

# Present in the dataframe but demoted as unreliable during cleaning — the
# agent must not use these for analysis, only redirect to the trustworthy
# replacement if a user asks about them.
UNRELIABLE_COLUMNS = (
    "customer_segment_unreliable (use account_type instead), "
    "customer_tenure_months_unreliable (use tenure_months_calc instead), "
    "previous_tickets_unreliable (use previous_tickets_calc instead), "
    "resolution_notes_unreliable, issue_description_unreliable, "
    "sla_breached_source (use sla_breached_calc instead), "
    "ticket_resolved_date_unreliable (use resolution_time_hours for durations), "
    "raw csat_score (use csat_valid instead), raw category (use category_clean/category_group instead)"
)

SYSTEM_PREFIX = f"""You are an Operations Analytics Assistant.

You analyse only the provided support ticket dataframe.

Your responsibilities:
- Analyse ticket trends
- Identify high-volume issues
- Evaluate resolution performance
- Find operational risks
- Provide recommendations

Rules:
- Do not invent information.
- Only use dataframe columns.
- Explain calculations clearly.
- Answer from an Operations Manager perspective.
- When restating a number in your final answer (a count, a percentage, an
  average), copy it exactly from your code's printed output. Never retype,
  round, or recall it from memory — this has caused transcription errors
  before (e.g. writing "101,001" when the code printed "100851").
- Be efficient with tool calls, especially for questions that combine several
  metrics (e.g. "recommendations", which needs volume + resolution time + SLA
  + backlog together). Compute several related stats in ONE code block rather
  than one metric per call, and never recompute a stat you already have the
  answer to — you have a limited number of tool calls, and re-deriving the
  same number twice has caused you to run out before reaching a final answer.
  Plan the 2-4 code blocks you actually need before running any of them, then
  move straight to your final written answer once you have them.

Trusted columns (use these for analysis): {TRUSTED_COLUMNS}.

Unreliable columns (present in the data, but never use for analysis — if asked
about one, say it was found unreliable during data cleaning and point to its
trustworthy replacement instead): {UNRELIABLE_COLUMNS}.

When answering:
1. State the numbers you calculated, not just a conclusion.
2. Note the row count / time period your calculation covers.
3. Keep the answer focused and business-readable — you're speaking to an
   Operations Manager, not another engineer.
"""


def create_operations_agent(df: pd.DataFrame, verbose: bool = False):
    """Builds and returns a LangChain pandas DataFrame agent wired to Claude.

    Raises RuntimeError if the LLM can't be configured (e.g. missing API key —
    surfaced from claude_config.get_claude_llm()).
    """
    llm = get_claude_llm()
    agent = create_pandas_dataframe_agent(
        llm=llm,
        df=df,
        agent_type="tool-calling",  # native tool-calling suits Claude better
        # than the default text-parsing ReAct style.
        prefix=SYSTEM_PREFIX,
        verbose=verbose,
        # Required acknowledgment: this agent executes LLM-generated Python
        # against the dataframe via a REPL tool under the hood. Accepted here
        # because this is a single-user local app with no untrusted multi-
        # tenant input, and the dataframe is read-only analytics data (no
        # writes, no filesystem/network access exposed to the agent).
        allow_dangerous_code=True,
        # Open-ended synthesis questions (e.g. "give recommendations", which
        # has to pull together volume + resolution + SLA + backlog) can need
        # more exploration than a single-metric lookup — observed hitting the
        # default 15 in Step 6 testing with zero answer produced. Raised to
        # give more headroom before the cap is hit at all.
        #
        # NOTE: early_stopping_method="generate" was tried here to get a
        # best-effort answer if the cap IS hit, instead of AgentExecutor's
        # default "force" (which returns a bare "stopped due to iteration
        # limit" string with no answer). Verified it does NOT work for this
        # agent_type: "generate" is only implemented for the legacy Agent
        # subclass, not the Runnable-based tool-calling agent this project
        # uses — it raises ValueError("Got unsupported early_stopping_method
        # `generate`") immediately. Left at the default "force" instead.
        max_iterations=25,
        max_execution_time=120,
        # Needed so a manual "synthesize from what you found" fallback is
        # possible if the iteration cap IS hit — see
        # _synthesize_from_intermediate_steps() below.
        return_intermediate_steps=True,
    )
    return agent


def _flatten_output(output) -> str:
    """Claude's tool-calling responses can come back as a plain string OR a
    list of content blocks (e.g. [{'type': 'text', 'text': '...'}]) depending
    on the response shape. Observed directly in testing — a raw list was
    returned to the Streamlit UI before this normalization was added.
    Flattens either shape into plain text."""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts = [block.get("text", "") for block in output if isinstance(block, dict) and block.get("type") == "text"]
        if parts:
            return "\n".join(parts)
    return str(output)


def _correct_total_ticket_claims(text: str, actual_row_count: int) -> str:
    """Guards against an observed hallucination: even with an explicit prompt
    instruction not to, the agent's prose sometimes states a wrong "total
    tickets" figure (e.g. "101,688" or "101,001") while its own printed code
    output correctly showed 100,851. A prompt instruction alone did not fix
    this in testing — this regex-based guard rewrites any "total dataset"
    claim to match the real row count of the dataframe actually being
    analysed (not hardcoded, since the dashboard may pass a filtered subset)."""

    def _replace(match: re.Match) -> str:
        whole = match.group(0)
        num_match = _NUMBER_IN_PHRASE.search(whole)
        if not num_match:
            return whole
        claimed = int(num_match.group(0).replace(",", ""))
        if claimed == actual_row_count:
            return whole
        # Swap just the number in place — preserves whatever wording
        # surrounds it (markdown bold, "full"/"entire" qualifiers, etc.)
        # instead of having to reconstruct the phrase from scratch.
        return whole[: num_match.start()] + f"{actual_row_count:,}" + whole[num_match.end():]

    return _TOTAL_TICKETS_PATTERN.sub(_replace, text)


# Exact literal string this LangChain version's tool-calling AgentExecutor
# returns when it hits max_iterations/max_execution_time (verified against
# the installed langchain_classic source — see agent.py line ~301). Used to
# detect the "gave up empty-handed" case so it can be salvaged instead of
# shown to the user as-is.
_MAX_ITERATIONS_MESSAGE = "Agent stopped due to max iterations."


def _synthesize_from_intermediate_steps(question: str, intermediate_steps: list) -> str:
    """Manual equivalent of LangChain's early_stopping_method="generate",
    which isn't available for this agent type (verified — see
    create_operations_agent's comment). Hitting the iteration cap on complex
    synthesis questions (e.g. "give recommendations") was observed directly
    in testing to be caused by the agent redundantly recomputing the same
    stats 2-3 times rather than running out of genuinely new analysis — so by
    the time it stops, it usually already has everything needed for a real
    answer. This makes one direct follow-up call asking Claude to write that
    answer from what was already computed, instead of surfacing the bare
    "stopped due to max iterations" message with no answer at all."""
    steps_text = []
    for action, observation in intermediate_steps:
        tool_input = getattr(action, "tool_input", "")
        steps_text.append(f"Code run:\n{tool_input}\nResult:\n{observation}")
    evidence = "\n\n".join(steps_text) if steps_text else "(no analysis was completed)"

    llm = get_claude_llm()
    synthesis_prompt = (
        f"{SYSTEM_PREFIX}\n\n"
        f"You were asked: \"{question}\"\n\n"
        "You ran out of tool-call budget before writing a final answer. Below "
        "is everything you already computed — do not run any more analysis, "
        "just write your final answer now using only these numbers:\n\n"
        f"{evidence}"
    )
    response = llm.invoke(synthesis_prompt)
    return _flatten_output(response.content)


def ask_operations_question(agent, question: str, df: pd.DataFrame) -> str:
    """Runs a single natural-language question through the agent and returns
    the text answer. `df` is the same dataframe the agent is analysing —
    used only to sanity-check any "total tickets" claim in the answer, never
    passed to the LLM directly.

    Raises:
        ValueError: the question was empty/whitespace-only.
        AgentQuestionError: the question could not be answered, for any
            reason from a bad API key to a malformed multi-step analysis.
            The exception message is already user-facing — display it
            directly (e.g. st.error(str(e))) rather than as a normal answer.
    """
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")

    try:
        result = agent.invoke({"input": question})
    except anthropic.AuthenticationError:
        raise AgentQuestionError(
            "Your Claude API key was rejected. Check that it's valid and set "
            "correctly in `.env`, then reload the page."
        )
    except anthropic.RateLimitError:
        raise AgentQuestionError(
            "Rate limit reached on the Claude API. Wait a moment and try again."
        )
    except (anthropic.APIConnectionError, anthropic.APITimeoutError):
        raise AgentQuestionError(
            "Couldn't reach the Claude API — check your network connection and try again."
        )
    except anthropic.InternalServerError:
        raise AgentQuestionError(
            "Claude's API is having issues right now (this is on Anthropic's "
            "side, not the dashboard). Try again in a moment."
        )
    except Exception as e:
        raise AgentQuestionError(
            "Sorry, I couldn't complete that analysis. This can happen with "
            "complex multi-step questions — try rephrasing, or break it into a "
            f"simpler question.\n\n*Technical detail: {e}*"
        )

    output = result.get("output")
    if output is None:
        raise AgentQuestionError("The agent did not return an answer. Try rephrasing your question.")

    if output == _MAX_ITERATIONS_MESSAGE:
        intermediate_steps = result.get("intermediate_steps") or []
        if not intermediate_steps:
            raise AgentQuestionError(
                "This question needed more analysis than the assistant could complete. "
                "Try breaking it into smaller, more specific questions."
            )
        try:
            output = _synthesize_from_intermediate_steps(question, intermediate_steps)
        except Exception as e:
            raise AgentQuestionError(
                "This question needed more analysis than the assistant could complete, "
                f"and the fallback summary also failed.\n\n*Technical detail: {e}*"
            )

    text = _flatten_output(output)
    return _correct_total_ticket_claims(text, len(df))
