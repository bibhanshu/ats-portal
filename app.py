"""Talent Acquisition Portal - Streamlit entry point.

Run locally with:   streamlit run app.py

This file does three things on every run:
1. picks up the action the user just took on screen (if any) and hands it to logic.py,
2. reads the current data from the database through db.py,
3. sends that data to the screens in frontend/index.html.
"""
import os
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import db
import logic
import seed

st.set_page_config(page_title="Talent Acquisition Portal", page_icon=":busts_in_silhouette:",
                   layout="wide", initial_sidebar_state="collapsed")

# The portal fills the whole browser window; Streamlit's own header and margins are hidden.
st.markdown("""
<style>
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], #MainMenu, footer {display: none !important;}
.stApp, [data-testid="stAppViewContainer"] {background: #F4F6F8;}
.block-container, [data-testid="stMainBlockContainer"] {padding: 0 !important; max-width: 100% !important;}
[data-testid="stVerticalBlock"] {gap: 0 !important;}
[data-testid="stElementContainer"]:has(style) {display: none !important;}
[data-testid="stMain"], section.main {overflow: hidden !important;}
iframe {height: 100vh !important; height: 100dvh !important; width: 100% !important; border: 0; display: block;}
</style>
""", unsafe_allow_html=True)

portal = components.declare_component("ats_portal", path=str(Path(__file__).parent / "frontend"))


def setting(name, default=""):
    """Read a setting from the environment or from Streamlit secrets."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        return str(st.secrets[name])
    except Exception:
        return default


@st.cache_resource(show_spinner="Connecting to the database...")
def get_engine():
    engine = db.make_engine(setting("DATABASE_URL") or None)
    db.init_db(engine)
    if setting("SEED_SAMPLE_DATA", "true").strip().lower() not in ("false", "0", "no"):
        with engine.begin() as conn:
            if db.get_meta(conn, "seeded") is None:
                if not db.read_state(conn)["R"]:
                    seed.load_sample_data(conn)
                db.set_meta(conn, "seeded", "1")
                db.bump_version(conn)
    return engine


@st.cache_resource
def _shared_cache():
    return {"ver": None, "data": None, "at": 0.0}


def current_data(engine):
    """Data for the screens. Re-read from the database only when something changed."""
    cache = _shared_cache()
    with engine.connect() as conn:
        ver = db.get_meta(conn, "ver")
        if cache["data"] is None or cache["ver"] != ver or time.time() - cache["at"] > 120:
            cache.update(data=db.read_state(conn), ver=ver, at=time.time())
    return cache["data"], cache["ver"]


try:
    engine = get_engine()
except Exception as e:
    st.error("The portal could not connect to its database. Check the DATABASE_URL value in the app's "
             "secrets (the password must replace [YOUR-PASSWORD]), and that the Supabase project is not paused.")
    st.caption(type(e).__name__ + ": " + str(e)[:300])
    st.stop()

# 1. The action the user just took, if it is a new one.
ack = None
action = st.session_state.get("ats")
if isinstance(action, dict) and action.get("nonce") and action["nonce"] != st.session_state.get("last_nonce"):
    st.session_state["last_nonce"] = action["nonce"]
    ack = logic.handle(engine, action)

# 2. Current data, then 3. draw the screens.
try:
    data, ver = current_data(engine)
except Exception as e:
    st.error("The portal could not read from its database. If the Supabase project was paused, restore it "
             "from the Supabase dashboard and refresh this page.")
    st.caption(type(e).__name__ + ": " + str(e)[:300])
    st.stop()

portal(data=data, ver=ver, ack=ack, key="ats", default=None)
