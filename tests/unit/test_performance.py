"""
Performance tests for database operations - Phase 5

Measures rows per second for different insert methods:
- Traditional INSERT (slow, ~20 rows/sec)
- PostgreSQL COPY (fast, ~10,000 rows/sec)
- Hybrid method (auto-selects best approach)
"""

import os
import time
from datetime import date, timedelta

import pandas as pd
import pytest

# Add project root to path
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database.database import DatabaseManager

# Test database configuration (use environment variables for CI/CD)
TEST_HOST = os.getenv("TEST_DB_HOST", "localhost")
TEST_PORT = int(os.getenv("TEST_DB_PORT", "5432"))
TEST_USER = os.getenv("TEST_DB_USER", "postgres")
TEST_PASSWORD = os.getenv("TEST_DB_PASSWORD", "password")
TEST_DATABASE = os.getenv("TEST_DB_NAME", "test_invoices")


@pytest.fixture
def db_manager():
    """Create database manager for testing."""
    manager = DatabaseManager(
        host=TEST_HOST,
        port=TEST_PORT,
        user=TEST_USER,
        password=TEST_PASSWORD,
        database=TEST_DATABASE,
    )
    yield manager
    manager.close()


@pytest.fixture
def sample_data_small():
    """Create small sample invoice data (50 rows)."""
    rows = []
    for i in range(50):
        rows.append({
            "Date": date.today() - timedelta(days=i % 30),
            "Vendor": f"Vendor {i % 10}",
            "Amount": (i % 10) * 100 + 50.00,
            "Category": ["Inventory", "Utilities", "Rent", "Other"][i % 4],
        })
    return pd.DataFrame(rows)


@pytest.fixture
def sample_data_large():
    """Create large sample invoice data (1000 rows)."""
    rows = []
    for i in range(1000):
        rows.append({
            "Date": date.today() - timedelta(days=i % 30),
            "Vendor": f"Vendor {i % 50}",
            "Amount": (i % 10) * 100 + 50.00,
            "Category": ["Inventory", "Utilities", "Rent", "Other"][i % 4],
        })
    return pd.DataFrame(rows)


class TestInsertPerformance:
    """Performance benchmarks for INSERT method."""

    @pytest.mark.slow
    def test_insert_small_dataset(self, db_manager, sample_data_small):
        """Benchmark: Traditional INSERT with small dataset (50 rows)."""
        session = db_manager.get_session()

        start = time.time()
        inserted = db_manager.save_bulk_invoices(
            session, sample_data_small, "test_insert_small"
        )
        elapsed = time.time() - start

        rows_per_sec = len(sample_data_small) / elapsed if elapsed > 0 else 0

        print(f"\nINSERT Method (small): {inserted} rows in {elapsed:.2f}s ({rows_per_sec:.0f} rows/sec)")
        assert inserted == len(sample_data_small)

        session.close()

    @pytest.mark.slow
    def test_insert_large_dataset(self, db_manager, sample_data_large):
        """Benchmark: Traditional INSERT with large dataset (1000 rows)."""
        session = db_manager.get_session()

        start = time.time()
        inserted = db_manager.save_bulk_invoices(
            session, sample_data_large, "test_insert_large"
        )
        elapsed = time.time() - start

        rows_per_sec = len(sample_data_large) / elapsed if elapsed > 0 else 0

        print(f"\nINSERT Method (large): {inserted} rows in {elapsed:.2f}s ({rows_per_sec:.0f} rows/sec)")
        assert inserted == len(sample_data_large)

        session.close()


class TestCopyPerformance:
    """Performance benchmarks for COPY method."""

    @pytest.mark.slow
    def test_copy_small_dataset(self, db_manager, sample_data_small):
        """Benchmark: COPY command with small dataset (50 rows)."""
        session = db_manager.get_session()

        start = time.time()
        inserted = db_manager.save_bulk_invoices_optimized(
            session, sample_data_small, "test_copy_small"
        )
        elapsed = time.time() - start

        rows_per_sec = len(sample_data_small) / elapsed if elapsed > 0 else 0

        print(f"\nCOPY Method (small): {inserted} rows in {elapsed:.2f}s ({rows_per_sec:.0f} rows/sec)")
        assert inserted == len(sample_data_small)

        session.close()

    @pytest.mark.slow
    def test_copy_large_dataset(self, db_manager, sample_data_large):
        """Benchmark: COPY command with large dataset (1000 rows)."""
        session = db_manager.get_session()

        start = time.time()
        inserted = db_manager.save_bulk_invoices_optimized(
            session, sample_data_large, "test_copy_large"
        )
        elapsed = time.time() - start

        rows_per_sec = len(sample_data_large) / elapsed if elapsed > 0 else 0

        print(f"\nCOPY Method (large): {inserted} rows in {elapsed:.2f}s ({rows_per_sec:.0f} rows/sec)")
        assert inserted == len(sample_data_large)

        session.close()


class TestMixedStrategy:
    """Tests for hybrid INSERT/COPY strategy."""

    def test_mixed_selects_insert_for_small(self, db_manager, sample_data_small):
        """Test that mixed strategy uses INSERT for small datasets (<100 rows)."""
        session = db_manager.get_session()

        # Small dataset should use INSERT
        inserted = db_manager.save_bulk_invoices_mixed(
            session, sample_data_small, "test_mixed_small"
        )
        assert inserted == len(sample_data_small)

        session.close()

    def test_mixed_selects_copy_for_large(self, db_manager, sample_data_large):
        """Test that mixed strategy uses COPY for large datasets (>=100 rows)."""
        session = db_manager.get_session()

        # Large dataset should use COPY
        inserted = db_manager.save_bulk_invoices_mixed(
            session, sample_data_large, "test_mixed_large"
        )
        assert inserted == len(sample_data_large)

        session.close()

    def test_threshold_boundary(self, db_manager):
        """Test behavior at the 100-row threshold."""
        session = db_manager.get_session()

        # Create dataset with exactly 99 rows (should use INSERT)
        data_99 = pd.DataFrame([{
            "Date": date.today(),
            "Vendor": f"Vendor {i}",
            "Amount": float(i * 10),
            "Category": "Test",
        } for i in range(99)])

        inserted_99 = db_manager.save_bulk_invoices_mixed(
            session, data_99, "test_threshold_99"
        )
        assert inserted_99 == 99

        # Create dataset with exactly 100 rows (should use COPY)
        data_100 = pd.DataFrame([{
            "Date": date.today(),
            "Vendor": f"Vendor {i}",
            "Amount": float(i * 10),
            "Category": "Test",
        } for i in range(100)])

        inserted_100 = db_manager.save_bulk_invoices_mixed(
            session, data_100, "test_threshold_100"
        )
        assert inserted_100 == 100

        session.close()


class TestPerformanceComparison:
    """Compare performance between INSERT and COPY methods."""

    @pytest.mark.slow
    def test_copy_faster_than_insert(self, db_manager, sample_data_large):
        """Verify COPY is significantly faster than INSERT for large datasets."""
        session = db_manager.get_session()

        # Benchmark INSERT
        start_insert = time.time()
        db_manager.save_bulk_invoices(session, sample_data_large, "perf_insert")
        insert_time = time.time() - start_insert

        # Benchmark COPY
        start_copy = time.time()
        db_manager.save_bulk_invoices_optimized(session, sample_data_large, "perf_copy")
        copy_time = time.time() - start_copy

        speedup = insert_time / copy_time if copy_time > 0 else float("inf")

        print(f"\nPerformance Comparison (1000 rows):")
        print(f"  INSERT: {insert_time:.2f}s")
        print(f"  COPY:   {copy_time:.2f}s")
        print(f"  Speedup: {speedup:.1f}x faster")

        # COPY should be at least 10x faster for 1000 rows
        assert speedup > 10, f"Expected >10x speedup, got {speedup:.1f}x"

        session.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "-m", "not slow"])
