from pathlib import Path
from types import SimpleNamespace
import pytest
from src.web_portal.authentication import (
    AccessDenied,
    authorize,
    current_reviewer,
    require_reviewer,
    logout,
)

CLAIMS = {
    "iss": "https://accounts.google.com",
    "sub": "google-123",
    "email": "Owner@example.com",
    "email_verified": True,
    "exp": 2000,
    "name": "Owner",
}


def test_verified_allowlisted_account_maps_to_explicit_user():
    user = authorize(CLAIMS, {"owner@example.com": 42}, now=1000)
    assert (user.email, user.user_id, user.subject) == (
        "owner@example.com",
        42,
        "google-123",
    )


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://evil.example"},
        {"email_verified": False},
        {"email_verified": "true"},
        {"sub": ""},
        {"exp": 1000},
        {"exp": None},
        {"exp": float("nan")},
        {"email": "other@example.com"},
    ],
)
def test_invalid_or_unapproved_identity_is_denied(change):
    with pytest.raises(AccessDenied):
        authorize({**CLAIMS, **change}, {"owner@example.com": 42}, now=1000)


@pytest.mark.parametrize(
    "reviewers",
    [
        {},
        {"owner@example.com": True},
        {"owner@example.com": 0},
        {"owner@example.com": 1, "other@example.com": 1},
        {"owner@example.com": {}},
    ],
)
def test_invalid_configuration_fails_closed(reviewers):
    with pytest.raises(AccessDenied):
        authorize(CLAIMS, reviewers, now=1000)


class User(dict):
    is_logged_in = True


class Stop(Exception):
    pass


def app(logged_in=True):
    user = User({**CLAIMS, "exp": 9999999999})
    user.is_logged_in = logged_in
    st = SimpleNamespace(
        user=user,
        session_state={},
        secrets={
            "auth": {
                "redirect_uri": "http://localhost:8501/oauth2callback",
                "cookie_secret": "test",
                "google": {
                    "client_id": "test",
                    "client_secret": "test",
                    "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
                },
            },
            "access": {"reviewers": {"owner@example.com": 42}},
        },
    )
    st.stop = lambda: (_ for _ in ()).throw(Stop())
    st.switch_page = lambda path: setattr(st, "redirect", path)
    st.logout = lambda: setattr(st, "logged_out", True)
    return st


def test_legacy_session_flag_cannot_bypass_google_login():
    st = app(False)
    st.session_state.update(authenticated=True, user_id=1, invoice="private")
    with pytest.raises(Stop):
        require_reviewer(st)
    assert st.redirect == "pages/login.py"
    assert not st.session_state


def test_allowlist_removal_revokes_access_on_next_rerun():
    st = app()
    assert current_reviewer(st).user_id == 42
    st.secrets["access"]["reviewers"] = {"other@example.com": 2}
    with pytest.raises(Stop):
        require_reviewer(st)
    assert not st.session_state


def test_logout_clears_invoice_state_and_identity_cookie():
    st = app()
    current_reviewer(st)
    st.session_state["invoice"] = "private"
    with pytest.raises(Stop):
        logout(st)
    assert not st.session_state and st.logged_out


def test_login_button_state_not_cleared_on_unauthenticated_reruns():
    st = app(False)
    st.session_state["google_button"] = True
    assert current_reviewer(st) is None
    assert st.session_state["google_button"]


def test_all_data_pages_gate_before_database_or_aws_clients():
    root = Path(__file__).resolve().parents[2] / "src/web_portal"
    for path in [root / "app.py", *root.glob("pages/0*.py")]:
        source = path.read_text()
        gate = source.index("require_reviewer(st)")
        for operation in ("get_db_manager()", "boto3.client("):
            if operation in source:
                assert gate < source.index(operation), path
