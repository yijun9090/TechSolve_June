"""AI Operations Assistant — natural-language Q&A over the ticket data via a
LangChain pandas DataFrame agent wired to Claude (utils/agent.py).
"""

import streamlit as st

from utils import load_data, render_sidebar_filters
from utils.agent import AgentQuestionError, ask_operations_question, create_operations_agent

st.set_page_config(page_title="AI Agent — TechSolve", page_icon="🤖", layout="wide")
st.title("🤖 AI Operations Assistant")
st.caption(
    "Ask natural-language questions about support tickets. The assistant analyses "
    "the data currently in scope (respects the sidebar filters) — it does not "
    "clean, modify, or write back to the dataset."
)

df_all = load_data()
df = render_sidebar_filters(df_all)

if df.empty:
    st.warning("No tickets match the current filters. Adjust the sidebar to give the assistant data to analyse.")
    st.stop()

# ---------------------------------------------------------------- agent setup
# Rebuilding the agent re-embeds a sample of the dataframe into its prompt,
# which is wasted work if nothing changed since the last Streamlit rerun (a
# rerun happens on every widget interaction, including each chat message).
# Cache it in session_state, keyed by a signature of the filtered data, and
# only rebuild when that signature actually changes.
filter_signature = (len(df), tuple(sorted(df["category_group"].unique())), df["ticket_created_date"].min(), df["ticket_created_date"].max())

if st.session_state.get("agent_signature") != filter_signature:
    with st.spinner("Setting up the AI assistant for the current filter selection..."):
        try:
            st.session_state.agent = create_operations_agent(df)
            st.session_state.agent_signature = filter_signature
        except RuntimeError as e:
            st.error(f"⚠️ Couldn't start the AI assistant: {e}")
            st.info("Copy `.env.example` to `.env` in the project root and add your Claude API key, then reload this page.")
            st.stop()

agent = st.session_state.agent

st.info(f"Analysing **{len(df):,}** tickets currently in scope (of {len(df_all):,} total in the dataset).")

# ---------------------------------------------------------------- chat history
if "agent_chat_history" not in st.session_state:
    st.session_state.agent_chat_history = []

EXAMPLE_QUESTIONS = [
    "What are the top ticket issues?",
    "Which issues have the longest resolution time?",
    "How has ticket volume changed?",
    "What operational improvements should we consider?",
]

st.subheader("Try an example question")
cols = st.columns(len(EXAMPLE_QUESTIONS))
example_clicked = None
for col, q in zip(cols, EXAMPLE_QUESTIONS):
    if col.button(q, width="stretch"):
        example_clicked = q

st.divider()

# Replay prior turns — errors are rendered distinctly from real answers so a
# failed question never reads as if the agent gave an actual (wrong) answer.
for turn in st.session_state.agent_chat_history:
    with st.chat_message("user"):
        st.markdown(turn["question"])
    with st.chat_message("assistant"):
        if turn.get("is_error"):
            st.error(turn["answer"])
        else:
            st.markdown(turn["answer"])

# New input: either typed or an example button click
typed_question = st.chat_input("Ask a question about support tickets")
question = example_clicked or typed_question

if question and question.strip():
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Analysing the ticket data..."):
            try:
                answer = ask_operations_question(agent, question, df)
                is_error = False
            except AgentQuestionError as e:
                answer = str(e)
                is_error = True
            except ValueError as e:
                answer = str(e)
                is_error = True

        if is_error:
            st.error(answer)
        else:
            st.markdown(answer)

    st.session_state.agent_chat_history.append({"question": question, "answer": answer, "is_error": is_error})

if st.session_state.agent_chat_history and st.button("Clear conversation"):
    st.session_state.agent_chat_history = []
    st.rerun()
