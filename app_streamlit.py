"""The small version of the séance: same engine and themes, plain Streamlit layout.

Run from the project folder:

    uv run streamlit run app_streamlit.py
"""
import re

import streamlit as st

from seance.books import BOOKS, NARRATOR
from seance.core import Library, answer


# Streamlit reruns this script on every click, so the models must survive between runs.
@st.cache_resource(show_spinner="Binding the pages…")
def get_library():
    return Library()


@st.cache_resource(show_spinner="Binding the pages…")
def open_book(slug):
    library = get_library()
    library.store(slug)
    return library.book(slug)


st.set_page_config(page_title="Book Séance", layout="wide")

slug = st.sidebar.selectbox("Book", list(BOOKS), format_func=lambda s: BOOKS[s]["title"])
spec = BOOKS[slug]
voices = spec["voices"] + [NARRATOR]
voice = st.sidebar.radio("Summon a voice", voices, format_func=lambda v: v["name"])
book = open_book(slug)
titles = [c.title for c in book.chapters]
read_to = st.sidebar.select_slider("How far have you read?", options=list(range(1, len(titles) + 1)),
                                   value=len(titles), format_func=lambda n: f"{n} of {len(titles)}")
limit = None if read_to == len(titles) else read_to
st.sidebar.caption(f"Up to: {titles[read_to - 1]}" if limit else "The whole book. Spoilers are in play.")

theme = {**spec["theme"], **voice["theme"]}
st.markdown(
    f"""<style>
    .stApp {{ background: {theme['bg']}; color: {theme['ink']}; }}
    [data-testid="stSidebar"] {{ background: {theme['panel']}; }}
    [data-testid="stSidebar"] * {{ color: {theme['ink']}; }}
    h1, h2, h3 {{ color: {theme['accent']} !important; font-family: Georgia, serif; }}
    [data-testid="stChatMessage"] {{ background: {theme['panel']}; }}
    [data-testid="stChatMessage"] * {{ color: {theme['ink']}; }}
    mark {{ background: {theme['accent']}33; color: {theme['ink']}; }}
    header {{ background: transparent !important; }}
    [data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {{ background: {theme['bg']}; }}
    [data-testid="stChatInput"], [data-testid="stChatInput"] > div {{ background: {theme['panel']}; border-color: {theme['rule']}; }}
    [data-testid="stChatInput"] textarea {{ color: {theme['ink']}; background: transparent; }}
    [data-testid="stSidebar"] [data-baseweb="select"] > div {{ background: {theme['panel2']}; border-color: {theme['rule']}; }}
    [data-testid="stMain"] h2, [data-testid="stMain"] p, [data-testid="stCaptionContainer"] {{ color: {theme['ink']}; }}
    [data-testid="stExpander"] {{ background: {theme['panel']}; border-color: {theme['rule']}; }}
    [data-testid="stExpander"] * {{ color: {theme['ink']}; }}
    [data-testid="stExpander"] summary {{ background: {theme['panel2']}; }}
    </style>""",
    unsafe_allow_html=True,
)

key = f"talk-{slug}-{voice['id']}"
talk = st.session_state.setdefault(key, [])

left, right = st.columns([3, 2], gap="large")
with left:
    st.title(voice["name"])
    st.caption(f"{spec['theme']['room']} · {voice['role']}")
    if voice["quote"] and not talk:
        st.markdown(f"> *{voice['quote']}*")
    for turn in talk:
        with st.chat_message("user" if turn["role"] == "user" else "assistant"):
            st.write(turn["content"])

question = st.chat_input("Ask something…")
if question:
    with left, st.spinner("The candle flickers…"):
        try:
            result = answer(get_library(), slug, voice["id"], question, limit=limit, history=talk)
        except Exception as exc:
            st.error(f"The model could not answer ({type(exc).__name__}). Wait a minute and try again.")
            st.stop()
    talk += [{"role": "user", "content": question}, {"role": "ai", "content": result["answer"]}]
    st.session_state[f"last-{key}"] = result
    st.rerun()

with right:
    st.subheader("The book")
    last = st.session_state.get(f"last-{key}")
    if not last:
        st.write("Ask a question and the book turns to the passage.")
    else:
        if last["status"] == "refused":
            st.info("The book is silent on this. These passages came closest.")
        elif last["status"] == "uncited":
            st.warning("No citation given. Do not trust this without checking.")
        if last["mood"]:
            st.caption(f"The room feels {last['mood']['name']}.")
        for p in last["passages"]:
            mark = "cited" if p["cited"] else "retrieved"
            with st.expander(f"[{p['n']}] {p['chapter_title']} ({mark})", expanded=p["cited"]):
                safe = re.sub(r"[<>]", "", p["text"])
                st.markdown(f"<mark>{safe}</mark>", unsafe_allow_html=True)
