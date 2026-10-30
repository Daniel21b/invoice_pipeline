"""Real Streamlit execution; no AWS, database or Google credentials required."""

from pathlib import Path
from unittest.mock import patch
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "page",
    [None, "01_Analytics.py", "02_Invoice_Details.py", "03_Extraction_Review.py"],
)
def test_missing_configuration_denies_each_page_before_services(page):
    app = AppTest.from_file(str(ROOT / "src/web_portal/app.py")).run()
    if page:
        app.switch_page("pages/" + page).run()
    assert not app.exception
    assert "awaiting configuration" in app.info[0].value
    assert not app.text_input


def test_google_button_uses_native_oidc_redirect():
    app = AppTest.from_file(str(ROOT / "src/web_portal/pages/login.py"))
    app.secrets["auth"] = {
        "redirect_uri": "http://localhost:8501/oauth2callback",
        "cookie_secret": "test-only",
        "google": {
            "client_id": "test",
            "client_secret": "test",
            "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
        },
    }
    app.secrets["access"] = {"reviewers": {"owner@example.com": 42}}
    app.run()
    assert not app.exception
    with patch("streamlit.login") as login:
        app.button[0].click().run()
        assert not app.exception
        login.assert_called_once_with("google")
