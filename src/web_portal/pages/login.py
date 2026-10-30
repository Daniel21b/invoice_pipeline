"""Google sign-in for explicitly approved invoice reviewers."""

import sys
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.web_portal.authentication import (
    AccessDenied,
    configured,
    current_reviewer,
    logout,
)

st.set_page_config(
    page_title="Sign in - Invoice Portal", page_icon="lock", layout="centered"
)
st.title("Invoice Portal")
st.write("Sign in with your approved Google account to upload and review invoices.")
if not configured(st):
    st.info(
        "Google sign-in is awaiting configuration. Contact the project owner for access."
    )
    st.caption("Owner setup: docs/GOOGLE_OAUTH_SETUP.md")
    st.stop()
try:
    reviewer = current_reviewer(st)
except AccessDenied as exc:
    st.warning(str(exc))
    if st.button("Sign out / use another account"):
        logout(st)
    st.stop()
if reviewer:
    st.switch_page("app.py")
    st.stop()
if st.button("Continue with Google", type="primary", use_container_width=True):
    st.login("google")
st.caption(
    "Only approved accounts can access invoices. No Gmail or Drive access is requested."
)
