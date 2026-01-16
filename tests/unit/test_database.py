"""
Test database connection and operations - Phase 4

Tests for the SQLAlchemy DatabaseManager.
Uses test database configuration from environment variables.
"""

import os
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Test configuration - override for testing
TEST_HOST = os.getenv("TEST_DB_HOST", "localhost")
TEST_PORT = int(os.getenv("TEST_DB_PORT", "5432"))
TEST_USER = os.getenv("TEST_DB_USER", "postgres")
TEST_PASSWORD = os.getenv("TEST_DB_PASSWORD", "password")
TEST_DATABASE = os.getenv("TEST_DB_NAME", "test_invoices")


class TestDatabaseManagerUnit:
    """Unit tests that don't require a real database."""

    def test_connection_string_format(self):
        """Test that connection string is formatted correctly."""
        # Import here to avoid streamlit import issues in tests
        with patch("streamlit.cache_resource", lambda f: f):
            from database.database import DatabaseManager

            manager = DatabaseManager(
                host="test-host.rds.amazonaws.com",
                port=5432,
                user="testuser",
                password="testpass",
                database="testdb",
            )

            expected = "postgresql://testuser:testpass@test-host.rds.amazonaws.com:5432/testdb"
            assert manager.connection_string == expected

    def test_database_manager_initialization(self):
        """Test DatabaseManager initializes with correct attributes."""
        with patch("streamlit.cache_resource", lambda f: f):
            from database.database import DatabaseManager

            manager = DatabaseManager(
                host="localhost",
                port=5432,
                user="postgres",
                password="password",
                database="invoices",
                region="us-west-2",
            )

            assert manager.host == "localhost"
            assert manager.port == 5432
            assert manager.user == "postgres"
            assert manager.database == "invoices"
            assert manager.region == "us-west-2"


class TestDatabaseManagerIntegration:
    """
    Integration tests that require a real database.
    These tests are skipped if no database is available.
    """

    @pytest.fixture
    def db_manager(self):
        """Create test database manager if database is available."""
        with patch("streamlit.cache_resource", lambda f: f):
            from database.database import DatabaseManager

            manager = DatabaseManager(
                host=TEST_HOST,
                port=TEST_PORT,
                user=TEST_USER,
                password=TEST_PASSWORD,
                database=TEST_DATABASE,
            )

            # Check if database is available
            if not manager.test_connection():
                pytest.skip("Test database not available")

            yield manager
            manager.close()

    def test_connection(self, db_manager):
        """Test database connection succeeds."""
        assert db_manager.test_connection() is True

    def test_save_single_invoice(self, db_manager):
        """Test saving a single invoice."""
        session = db_manager.get_session()

        invoice = {
            "invoice_number": "TEST-001",
            "vendor_name": "Test Vendor",
            "invoice_date": date.today(),
            "amount": 100.50,
            "category": "Test",
            "source_type": "test",
            "source_file": "test.py",
            "created_by": "pytest",
        }

        result = db_manager.save_invoice(session, invoice)
        assert result is True

        session.close()

    def test_save_bulk_invoices(self, db_manager):
        """Test saving multiple invoices from DataFrame."""
        session = db_manager.get_session()

        test_df = pd.DataFrame([
            {"Date": "2024-01-15", "Vendor": "Bulk Test 1", "Amount": 100.00, "Category": "Test"},
            {"Date": "2024-01-16", "Vendor": "Bulk Test 2", "Amount": 200.00, "Category": "Test"},
        ])

        result = db_manager.save_bulk_invoices(session, test_df, "test_bulk", "test_file.csv")
        assert result == 2

        session.close()

    def test_get_all_invoices(self, db_manager):
        """Test retrieving invoices."""
        session = db_manager.get_session()

        invoices = db_manager.get_all_invoices(session, limit=10)
        assert isinstance(invoices, list)

        session.close()

    def test_get_invoices_by_source(self, db_manager):
        """Test filtering invoices by source type."""
        session = db_manager.get_session()

        invoices = db_manager.get_invoices_by_source(session, "test")
        assert isinstance(invoices, list)

        session.close()

    def test_get_summary_stats(self, db_manager):
        """Test getting summary statistics."""
        session = db_manager.get_session()

        stats = db_manager.get_summary_stats(session)
        assert isinstance(stats, list)

        session.close()

    def test_get_total_stats(self, db_manager):
        """Test getting total statistics."""
        session = db_manager.get_session()

        stats = db_manager.get_total_stats(session)
        assert isinstance(stats, dict)
        assert "total_count" in stats
        assert "total_amount" in stats

        session.close()


class TestGetDbManager:
    """Test the get_db_manager singleton function."""

    def test_get_db_manager_missing_secrets(self):
        """Test that get_db_manager handles missing secrets gracefully."""
        with patch("streamlit.secrets", {}):
            with patch("streamlit.error") as mock_error:
                with patch("streamlit.cache_resource", lambda f: f):
                    from database.database import get_db_manager

                    result = get_db_manager()
                    # Should return None and call st.error
                    assert result is None or mock_error.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
