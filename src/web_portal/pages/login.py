"""
Login Page - Admin Only Authentication

Single admin user authentication using Streamlit Secrets.
No database user management - credentials stored in .streamlit/secrets.toml
"""

import streamlit as st

# Page configuration
st.set_page_config(
    page_title="Login - Invoice Portal",
    page_icon="lock",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Hide sidebar on login page
st.markdown("""
    <style>
        [data-testid="stSidebar"] {display: none;}
        [data-testid="stSidebarNav"] {display: none;}
    </style>
""", unsafe_allow_html=True)


def verify_admin_credentials(email: str, password: str) -> dict:
    """
    Verify credentials against Streamlit secrets.

    Returns:
        dict with success status and user info
    """
    try:
        admin_email = st.secrets["admin"]["email"]
        admin_password = st.secrets["admin"]["password"]
        admin_name = st.secrets["admin"].get("full_name", "Administrator")

        if email.lower().strip() == admin_email.lower().strip() and password == admin_password:
            return {
                "success": True,
                "email": admin_email,
                "full_name": admin_name,
                "role": "admin"
            }
        else:
            return {"success": False, "error": "Invalid email or password"}

    except KeyError as e:
        st.error("Configuration error: Admin credentials not found in secrets.")
        return {"success": False, "error": "Configuration error"}
    except Exception as e:
        return {"success": False, "error": "Authentication failed"}


# Check if already logged in
if st.session_state.get("authenticated"):
    st.switch_page("app.py")

# Page title
st.title("Invoice Portal")
st.markdown("Administrator access only.")

# Login form
st.header("Sign In")

with st.form("login_form"):
    email = st.text_input("Email", placeholder="admin@company.com")
    password = st.text_input("Password", type="password", placeholder="Enter your password")

    submit = st.form_submit_button("Sign In", use_container_width=True, type="primary")

if submit:
    if not email or not password:
        st.error("Please enter both email and password.")
    else:
        result = verify_admin_credentials(email, password)

        if result["success"]:
            # Set session state
            st.session_state["authenticated"] = True
            st.session_state["email"] = result["email"]
            st.session_state["full_name"] = result["full_name"]
            st.session_state["role"] = result["role"]
            st.session_state["user_id"] = 1  # Admin ID

            st.success(f"Welcome, {result['full_name']}!")
            st.switch_page("app.py")
        else:
            st.error(result["error"])

# Footer
st.divider()
st.caption("Invoice Portal v8.0 | Admin Access Only")
