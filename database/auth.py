"""
User authentication and authorization - Phase 7

Handles login, session management, role-based access control.
Uses secure password hashing and JWT tokens for API calls.
"""

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

import streamlit as st
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class AuthManager:
    """Handles user authentication and session management."""

    # Configuration (override via environment variables in production)
    SECRET_KEY = "change-this-secret-key-in-production"  # Use env var in production
    ALGORITHM = "HS256"
    SESSION_TIMEOUT_HOURS = 24

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash password using SHA256.
        Note: For production, consider upgrading to bcrypt.
        """
        return hashlib.sha256(password.encode()).hexdigest()

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """Verify password against stored hash."""
        return AuthManager.hash_password(password) == hashed

    @staticmethod
    def create_session_token() -> str:
        """Generate cryptographically secure session token."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def register_user(
        session: Session,
        email: str,
        password: str,
        full_name: str,
        role: str = "operator"
    ) -> dict:
        """
        Register a new user.

        Args:
            session: Database session
            email: User email (must be unique)
            password: Plain text password (will be hashed)
            full_name: User's display name
            role: One of 'admin', 'accountant', 'operator'

        Returns:
            Dict with success status and user_id or error message
        """
        try:
            # Check if user already exists
            existing = session.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": email.lower().strip()}
            ).fetchone()

            if existing:
                return {"success": False, "error": "Email already registered"}

            # Validate role
            valid_roles = ["admin", "accountant", "operator"]
            if role not in valid_roles:
                return {"success": False, "error": f"Invalid role. Must be one of: {valid_roles}"}

            # Hash password and insert user
            hashed = AuthManager.hash_password(password)

            result = session.execute(
                text("""
                    INSERT INTO users (email, hashed_password, full_name, role)
                    VALUES (:email, :password, :full_name, :role)
                    RETURNING id
                """),
                {
                    "email": email.lower().strip(),
                    "password": hashed,
                    "full_name": full_name.strip(),
                    "role": role
                }
            )

            session.commit()
            user_id = result.fetchone()[0]

            logger.info(f"User registered: {email} (ID: {user_id}, Role: {role})")
            return {"success": True, "user_id": user_id}

        except Exception as e:
            session.rollback()
            logger.error(f"Registration failed for {email}: {str(e)}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def login_user(
        session: Session,
        email: str,
        password: str,
        ip_address: str = None
    ) -> dict:
        """
        Authenticate user and create session.

        Args:
            session: Database session
            email: User email
            password: Plain text password
            ip_address: Client IP for audit logging

        Returns:
            Dict with user info and session token on success
        """
        try:
            # Find user by email
            user = session.execute(
                text("""
                    SELECT id, hashed_password, full_name, role, is_active
                    FROM users WHERE email = :email
                """),
                {"email": email.lower().strip()}
            ).fetchone()

            if not user:
                logger.warning(f"Login failed - user not found: {email}")
                return {"success": False, "error": "Invalid email or password"}

            user_id, hashed, full_name, role, is_active = user

            # Check if account is active
            if not is_active:
                logger.warning(f"Login attempt on disabled account: {email}")
                return {"success": False, "error": "Account is disabled. Contact administrator."}

            # Verify password
            if not AuthManager.verify_password(password, hashed):
                logger.warning(f"Login failed - wrong password: {email}")
                return {"success": False, "error": "Invalid email or password"}

            # Create session token
            session_token = AuthManager.create_session_token()
            expires_at = datetime.utcnow() + timedelta(hours=AuthManager.SESSION_TIMEOUT_HOURS)

            # Save session to database
            session.execute(
                text("""
                    INSERT INTO user_sessions (user_id, session_token, ip_address, expires_at)
                    VALUES (:user_id, :token, :ip, :expires)
                """),
                {
                    "user_id": user_id,
                    "token": session_token,
                    "ip": ip_address,
                    "expires": expires_at
                }
            )

            # Update last login timestamp
            session.execute(
                text("UPDATE users SET last_login = NOW() WHERE id = :user_id"),
                {"user_id": user_id}
            )

            session.commit()

            logger.info(f"User logged in: {email} (ID: {user_id})")

            return {
                "success": True,
                "user_id": user_id,
                "email": email.lower().strip(),
                "full_name": full_name,
                "role": role,
                "session_token": session_token,
                "expires_at": expires_at.isoformat()
            }

        except Exception as e:
            session.rollback()
            logger.error(f"Login error for {email}: {str(e)}")
            return {"success": False, "error": "Login failed. Please try again."}

    @staticmethod
    def verify_session(session: Session, session_token: str) -> dict:
        """
        Verify if a session token is valid and not expired.

        Args:
            session: Database session
            session_token: Token to verify

        Returns:
            Dict with user info if valid, error otherwise
        """
        try:
            user = session.execute(
                text("""
                    SELECT u.id, u.email, u.full_name, u.role, u.is_active
                    FROM user_sessions us
                    JOIN users u ON u.id = us.user_id
                    WHERE us.session_token = :token
                    AND us.expires_at > NOW()
                """),
                {"token": session_token}
            ).fetchone()

            if not user:
                return {"success": False, "error": "Session expired or invalid"}

            user_id, email, full_name, role, is_active = user

            if not is_active:
                return {"success": False, "error": "Account has been disabled"}

            return {
                "success": True,
                "user_id": user_id,
                "email": email,
                "full_name": full_name,
                "role": role
            }

        except Exception as e:
            logger.error(f"Session verification failed: {str(e)}")
            return {"success": False, "error": "Session verification failed"}

    @staticmethod
    def logout_user(session: Session, session_token: str) -> bool:
        """
        Invalidate session token (logout).

        Args:
            session: Database session
            session_token: Token to invalidate

        Returns:
            True if successful
        """
        try:
            session.execute(
                text("DELETE FROM user_sessions WHERE session_token = :token"),
                {"token": session_token}
            )
            session.commit()
            logger.info("User session invalidated")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Logout failed: {str(e)}")
            return False

    @staticmethod
    def cleanup_expired_sessions(session: Session) -> int:
        """
        Remove expired sessions from database.

        Returns:
            Number of sessions removed
        """
        try:
            result = session.execute(
                text("DELETE FROM user_sessions WHERE expires_at < NOW()")
            )
            session.commit()
            count = result.rowcount
            if count > 0:
                logger.info(f"Cleaned up {count} expired sessions")
            return count
        except Exception as e:
            session.rollback()
            logger.error(f"Session cleanup failed: {str(e)}")
            return 0


class RoleBasedAccessControl:
    """Role-based permission checking for the application."""

    # Permission definitions by role
    PERMISSIONS = {
        "admin": [
            "read_all",
            "write_all",
            "delete_all",
            "manage_users",
            "view_audit",
            "read_invoices",
            "create_invoices",
            "export_reports",
            "view_dashboard"
        ],
        "accountant": [
            "read_invoices",
            "export_reports",
            "view_dashboard"
        ],
        "operator": [
            "read_invoices",
            "create_invoices",
            "view_dashboard"
        ]
    }

    @staticmethod
    def has_permission(role: str, permission: str) -> bool:
        """
        Check if a role has a specific permission.

        Args:
            role: User's role (admin, accountant, operator)
            permission: Permission to check

        Returns:
            True if role has permission
        """
        return permission in RoleBasedAccessControl.PERMISSIONS.get(role, [])

    @staticmethod
    def get_permissions(role: str) -> list:
        """Get all permissions for a role."""
        return RoleBasedAccessControl.PERMISSIONS.get(role, [])

    @staticmethod
    def require_permission(role: str, permission: str) -> bool:
        """
        Check permission and stop Streamlit if denied.

        Args:
            role: User's role
            permission: Required permission

        Returns:
            True if permitted (raises st.stop() if not)
        """
        if not RoleBasedAccessControl.has_permission(role, permission):
            st.error(f"Access denied. Your role ({role}) does not have '{permission}' permission.")
            st.stop()
        return True

    @staticmethod
    def require_role(current_role: str, allowed_roles: list) -> bool:
        """
        Check if user's role is in allowed list.

        Args:
            current_role: User's current role
            allowed_roles: List of allowed roles

        Returns:
            True if allowed (raises st.stop() if not)
        """
        if current_role not in allowed_roles:
            st.error(f"Access denied. This page requires one of these roles: {', '.join(allowed_roles)}")
            st.stop()
        return True


class AuditLog:
    """Audit trail for compliance and security tracking."""

    @staticmethod
    def log_action(
        session: Session,
        user_id: int,
        action: str,
        entity_type: str = None,
        entity_id: int = None,
        details: dict = None,
        ip_address: str = None
    ):
        """
        Log an action to the audit trail.

        Args:
            session: Database session
            user_id: Who performed the action
            action: What was done (insert, update, delete, login, logout, export, download)
            entity_type: Type of entity affected (invoice, user, settings)
            entity_id: ID of specific entity
            details: Additional details (old/new values, etc.)
            ip_address: Client IP address
        """
        try:
            session.execute(
                text("""
                    INSERT INTO audit_log (user_id, action, entity_type, entity_id, details, ip_address)
                    VALUES (:user_id, :action, :entity_type, :entity_id, :details, :ip)
                """),
                {
                    "user_id": user_id,
                    "action": action,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "details": json.dumps(details) if details else None,
                    "ip": ip_address
                }
            )
            session.commit()
            logger.debug(f"Audit log: {action} on {entity_type}:{entity_id} by user {user_id}")
        except Exception as e:
            session.rollback()
            logger.error(f"Audit logging failed: {str(e)}")

    @staticmethod
    def get_audit_trail(
        session: Session,
        days: int = 30,
        limit: int = 1000,
        user_id: int = None,
        action: str = None,
        entity_type: str = None
    ) -> list:
        """
        Retrieve audit log entries with optional filters.

        Args:
            session: Database session
            days: Number of days to look back
            limit: Maximum entries to return
            user_id: Filter by specific user
            action: Filter by action type
            entity_type: Filter by entity type

        Returns:
            List of audit log entries
        """
        try:
            # Build dynamic query with filters
            query = """
                SELECT
                    al.id,
                    al.created_at,
                    u.email,
                    u.full_name,
                    al.action,
                    al.entity_type,
                    al.entity_id,
                    al.details,
                    al.ip_address
                FROM audit_log al
                LEFT JOIN users u ON u.id = al.user_id
                WHERE al.created_at > NOW() - INTERVAL :days_interval
            """

            params = {"days_interval": f"{days} day", "limit": limit}

            if user_id:
                query += " AND al.user_id = :user_id"
                params["user_id"] = user_id

            if action:
                query += " AND al.action = :action"
                params["action"] = action

            if entity_type:
                query += " AND al.entity_type = :entity_type"
                params["entity_type"] = entity_type

            query += " ORDER BY al.created_at DESC LIMIT :limit"

            result = session.execute(text(query), params).fetchall()
            return result

        except Exception as e:
            logger.error(f"Failed to retrieve audit log: {str(e)}")
            return []

    @staticmethod
    def get_user_activity(session: Session, user_id: int, days: int = 7) -> list:
        """Get recent activity for a specific user."""
        return AuditLog.get_audit_trail(session, days=days, user_id=user_id)


def check_authentication() -> Optional[dict]:
    """
    Check if user is authenticated in current Streamlit session.

    Returns:
        Dict with user info if authenticated, None otherwise
    """
    if not st.session_state.get("authenticated"):
        return None

    return {
        "user_id": st.session_state.get("user_id"),
        "email": st.session_state.get("email"),
        "full_name": st.session_state.get("full_name"),
        "role": st.session_state.get("role"),
        "session_token": st.session_state.get("session_token")
    }


def require_authentication():
    """
    Require authentication for a page. Redirects to login if not authenticated.

    Usage:
        require_authentication()
        # Rest of your page code (only runs if authenticated)
    """
    if not st.session_state.get("authenticated"):
        st.warning("Please log in to access this page.")
        st.switch_page("pages/login.py")


def logout():
    """Clear session state and redirect to login."""
    st.session_state.clear()
    st.switch_page("pages/login.py")
