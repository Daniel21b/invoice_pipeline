"""Google OIDC identity and explicit portal authorization.

Streamlit/Authlib validates the OIDC callback, state, nonce and token signature.
This module authorizes that trusted identity; session-state flags are not credentials.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import time
import math


class AccessDenied(ValueError):
    pass


@dataclass(frozen=True)
class Reviewer:
    email: str
    name: str
    subject: str
    user_id: int


def authorize(
    claims: Mapping, reviewers: Mapping, now: float | None = None
) -> Reviewer:
    """Require verified Google identity, an unexpired token and a configured user ID."""
    now = time.time() if now is None else now
    if claims.get("iss") not in {"https://accounts.google.com", "accounts.google.com"}:
        raise AccessDenied("Google identity required.")
    if claims.get("email_verified") is not True or not claims.get("sub"):
        raise AccessDenied("A verified Google email is required.")
    expiry = claims.get("exp")
    if (
        isinstance(expiry, bool)
        or not isinstance(expiry, (int, float))
        or not math.isfinite(expiry)
        or expiry <= now
    ):
        raise AccessDenied("Your sign-in has expired. Sign out and sign in again.")
    email = str(claims.get("email", "")).strip().lower()
    allowed = {str(key).strip().lower(): value for key, value in reviewers.items()}
    if any(type(value) is not int or value < 1 for value in allowed.values()):
        raise AccessDenied("Reviewer configuration requires positive integer user IDs.")
    user_id = allowed.get(email)
    if type(user_id) is not int or user_id < 1:
        raise AccessDenied("This Google account is not approved for invoice access.")
    if len(set(allowed.values())) != len(allowed):
        raise AccessDenied("Reviewer configuration must use distinct user IDs.")
    return Reviewer(
        email, str(claims.get("name") or email), str(claims["sub"]), user_id
    )


def configured(st) -> bool:
    try:
        auth = st.secrets["auth"]
        google = auth["google"]
        return bool(
            auth["redirect_uri"]
            and auth["cookie_secret"]
            and google["client_id"]
            and google["client_secret"]
            and google["server_metadata_url"]
            == "https://accounts.google.com/.well-known/openid-configuration"
            and st.secrets["access"]["reviewers"]
        )
    except (KeyError, FileNotFoundError):
        return False


def clear_identity(st):
    # Clear invoice records and widget state as well as legacy authentication flags.
    st.session_state.clear()


def current_reviewer(st):
    if not configured(st) or not getattr(st.user, "is_logged_in", False):
        if any(
            key in st.session_state
            for key in ("authenticated", "google_subject", "email")
        ):
            clear_identity(st)
        return None
    try:
        reviewer = authorize(dict(st.user), st.secrets["access"]["reviewers"])
    except AccessDenied:
        if any(
            key in st.session_state
            for key in ("authenticated", "google_subject", "email")
        ):
            clear_identity(st)
        raise
    if st.session_state.get("google_subject") not in (None, reviewer.subject):
        clear_identity(st)
    st.session_state.update(
        authenticated=True,
        email=reviewer.email,
        full_name=reviewer.name,
        user_id=reviewer.user_id,
        role="admin",
        google_subject=reviewer.subject,
    )
    return reviewer


def logout(st):
    clear_identity(st)
    st.logout()
    st.stop()


def require_reviewer(st):
    try:
        reviewer = current_reviewer(st)
    except AccessDenied:
        reviewer = None
    if reviewer is None:
        st.switch_page("pages/login.py")
        st.stop()
    return reviewer
