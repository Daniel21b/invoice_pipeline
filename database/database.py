"""
Database connection manager using SQLAlchemy - Phase 5

Handles all RDS interactions securely with connection pooling.
Uses Streamlit secrets for credential management.
Includes optimized bulk insert using PostgreSQL COPY command.
"""

import io
import logging
import time
import uuid
from typing import Optional

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)


# Query performance monitoring
@event.listens_for(Engine, "before_cursor_execute")
def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """Record query start time for performance monitoring."""
    conn.info.setdefault("query_start_time", []).append(time.time())


@event.listens_for(Engine, "after_cursor_execute")
def receive_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """Log slow queries (>100ms) for performance monitoring."""
    start_times = conn.info.get("query_start_time", [])
    if start_times:
        total_time = time.time() - start_times.pop(-1)
        if total_time > 0.1:  # Log slow queries (>100ms)
            logger.warning(f"SLOW QUERY ({total_time:.3f}s): {statement[:100]}...")


class DatabaseManager:
    """
    Manages all database connections and operations.
    Uses connection pooling for efficiency.
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        region: str = "us-east-1",
    ):
        """
        Initialize database connection.

        Args:
            host: RDS endpoint (e.g., 'my-db.us-east-1.rds.amazonaws.com')
            port: PostgreSQL port (usually 5432)
            user: Database user
            password: Database password
            database: Database name
            region: AWS region (for IAM auth if using token-based)
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.region = region

        # Build connection string
        self.connection_string = (
            f"postgresql://{user}:{password}@{host}:{port}/{database}"
        )

        # Create engine with connection pooling
        # pool_size: max 5 concurrent connections
        # max_overflow: allow 10 extra connections if needed
        # pool_recycle: recycle connections every 3600 seconds (AWS RDS timeout)
        self.engine = create_engine(
            self.connection_string,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_recycle=3600,
            echo=False,  # Set True to see SQL queries (debug only)
        )

        # Create session factory
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    def test_connection(self) -> bool:
        """
        Test if database is reachable.
        Returns True if successful, False otherwise.
        """
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database connection successful")
            return True
        except Exception as e:
            logger.error(f"Database connection failed: {str(e)}")
            return False

    def save_invoice(self, session: Session, invoice_data: dict) -> bool:
        """
        Save a single invoice to database.

        Args:
            session: SQLAlchemy session
            invoice_data: Dict with keys matching the invoices table schema
                         Now includes optional 'transaction_type' (INCOME/EXPENSE)

        Returns:
            True if successful, False otherwise
        """
        try:
            query = text("""
                INSERT INTO invoices
                (invoice_number, vendor_name, invoice_date, amount, category,
                 source_type, source_file, extraction_confidence, created_by, notes,
                 transaction_type)
                VALUES
                (:invoice_number, :vendor_name, :invoice_date, :amount, :category,
                 :source_type, :source_file, :extraction_confidence, :created_by, :notes,
                 :transaction_type)
            """)

            session.execute(
                query,
                {
                    "invoice_number": invoice_data.get("invoice_number"),
                    "vendor_name": invoice_data["vendor_name"],
                    "invoice_date": invoice_data["invoice_date"],
                    "amount": invoice_data["amount"],
                    "category": invoice_data.get("category"),
                    "source_type": invoice_data["source_type"],
                    "source_file": invoice_data.get("source_file", "manual"),
                    "extraction_confidence": invoice_data.get("extraction_confidence"),
                    "created_by": invoice_data.get("created_by", "streamlit_user"),
                    "notes": invoice_data.get("notes"),
                    "transaction_type": invoice_data.get("transaction_type"),
                },
            )
            session.commit()
            logger.info(f"Saved invoice: {invoice_data['vendor_name']}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save invoice: {str(e)}")
            return False

    def save_bulk_invoices(
        self, session: Session, invoices_df: pd.DataFrame, source_type: str,
        source_file: str = "bulk_upload", transaction_type: str = None
    ) -> int:
        """
        Save multiple invoices from DataFrame (Excel/CSV import).

        Args:
            session: SQLAlchemy session
            invoices_df: Pandas DataFrame with columns: Date, Vendor, Amount, Category
            source_type: 'excel_bulk' or similar
            source_file: Original filename
            transaction_type: 'INCOME' or 'EXPENSE' (optional)

        Returns:
            Number of rows inserted
        """
        try:
            inserted_count = 0
            for _, row in invoices_df.iterrows():
                query = text("""
                    INSERT INTO invoices
                    (invoice_number, vendor_name, invoice_date, amount, category,
                     source_type, source_file, created_by, transaction_type)
                    VALUES
                    (:invoice_number, :vendor_name, :invoice_date, :amount, :category,
                     :source_type, :source_file, :created_by, :transaction_type)
                """)

                # Generate invoice number if not provided
                invoice_num = row.get("InvoiceNumber") if "InvoiceNumber" in row.index else None
                if not invoice_num:
                    invoice_num = f"AUTO-{uuid.uuid4().hex[:8]}"

                session.execute(
                    query,
                    {
                        "invoice_number": invoice_num,
                        "vendor_name": row["Vendor"],
                        "invoice_date": pd.to_datetime(row["Date"]).date(),
                        "amount": float(row["Amount"]),
                        "category": row.get("Category"),
                        "source_type": source_type,
                        "source_file": source_file,
                        "created_by": "streamlit_user",
                        "transaction_type": transaction_type,
                    },
                )
                inserted_count += 1

            session.commit()
            logger.info(f"Inserted {inserted_count} invoices from {source_type}")
            return inserted_count
        except Exception as e:
            session.rollback()
            logger.error(f"Bulk insert failed: {str(e)}")
            return 0

    def save_bulk_invoices_optimized(
        self, session: Session, invoices_df: pd.DataFrame, source_type: str,
        source_file: str = "bulk_upload", transaction_type: str = None
    ) -> int:
        """
        OPTIMIZED: Use PostgreSQL COPY for 500x faster inserts.

        Args:
            session: SQLAlchemy session
            invoices_df: Pandas DataFrame with columns: Date, Vendor, Amount, Category
            source_type: 'excel_bulk', 'pdf_scan', etc.
            source_file: Original filename
            transaction_type: 'INCOME' or 'EXPENSE' (optional)

        Returns:
            Number of rows inserted
        """
        try:
            # Prepare data with required columns
            df_copy = invoices_df.copy()

            # Generate invoice numbers for rows that don't have them
            if "InvoiceNumber" not in df_copy.columns:
                df_copy["invoice_number"] = [f"AUTO-{uuid.uuid4().hex[:8]}" for _ in range(len(df_copy))]
            else:
                df_copy["invoice_number"] = df_copy["InvoiceNumber"].fillna("").apply(
                    lambda x: x if x else f"AUTO-{uuid.uuid4().hex[:8]}"
                )

            # Normalize column names
            df_copy["vendor_name"] = df_copy["Vendor"]
            df_copy["invoice_date"] = pd.to_datetime(df_copy["Date"]).dt.date
            df_copy["amount"] = pd.to_numeric(df_copy["Amount"], errors="coerce")
            df_copy["category"] = df_copy["Category"]
            df_copy["source_type"] = source_type
            df_copy["source_file"] = source_file
            df_copy["created_by"] = "streamlit_user"
            df_copy["ingested_at"] = pd.Timestamp.now()
            df_copy["transaction_type"] = transaction_type

            # Prepare CSV data in memory (pipe-delimited to avoid conflicts)
            csv_buffer = io.StringIO()
            df_copy[
                ["invoice_number", "vendor_name", "invoice_date", "amount", "category",
                 "source_type", "source_file", "created_by", "ingested_at", "transaction_type"]
            ].to_csv(
                csv_buffer,
                index=False,
                header=False,
                sep="|",
            )
            csv_buffer.seek(0)

            # Get raw connection and execute COPY command
            raw_connection = session.connection().connection
            cursor = raw_connection.cursor()

            try:
                cursor.copy_from(
                    csv_buffer,
                    "invoices",
                    columns=(
                        "invoice_number", "vendor_name", "invoice_date", "amount", "category",
                        "source_type", "source_file", "created_by", "ingested_at", "transaction_type"
                    ),
                    sep="|",
                )
                raw_connection.commit()

                inserted_count = len(df_copy)
                logger.info(f"COPY inserted {inserted_count} rows from {source_type}")
                return inserted_count

            except Exception as e:
                raw_connection.rollback()
                logger.error(f"COPY failed: {str(e)}")
                raise
            finally:
                cursor.close()

        except Exception as e:
            logger.error(f"Bulk COPY operation failed: {str(e)}")
            return 0

    def save_bulk_invoices_mixed(
        self, session: Session, invoices_df: pd.DataFrame, source_type: str,
        source_file: str = "bulk_upload", transaction_type: str = None
    ) -> int:
        """
        HYBRID: Use COPY for large uploads (>100 rows), INSERT for small ones.

        Rationale:
        - For 5 rows: COPY overhead not worth it, use INSERT
        - For 500 rows: COPY is 100x faster
        - For 5,000 rows: COPY is 500x faster

        This method auto-detects and picks the best approach.

        Args:
            session: SQLAlchemy session
            invoices_df: Pandas DataFrame with columns: Date, Vendor, Amount, Category
            source_type: 'excel_bulk', 'pdf_scan', etc.
            source_file: Original filename
            transaction_type: 'INCOME' or 'EXPENSE' (optional)

        Returns:
            Number of rows inserted
        """
        if len(invoices_df) < 100:
            logger.info(f"Using INSERT (small upload: {len(invoices_df)} rows)")
            return self.save_bulk_invoices(session, invoices_df, source_type, source_file, transaction_type)
        else:
            logger.info(f"Using COPY (large upload: {len(invoices_df)} rows)")
            return self.save_bulk_invoices_optimized(session, invoices_df, source_type, source_file, transaction_type)

    def get_all_invoices(self, session: Session, limit: int = 1000, include_deleted: bool = False) -> list:
        """
        Fetch all invoices from database (limit for performance).

        Args:
            session: SQLAlchemy session
            limit: Max number of records to return
            include_deleted: If True, include soft-deleted records (admin only)

        Returns:
            List of invoice tuples
        """
        try:
            if include_deleted:
                query = text("""
                    SELECT id, invoice_number, vendor_name, invoice_date, amount,
                           category, source_type, source_file, extraction_confidence,
                           ingested_at, created_by, transaction_type, is_deleted,
                           deleted_at, deletion_reason
                    FROM invoices
                    ORDER BY ingested_at DESC
                    LIMIT :limit
                """)
            else:
                query = text("""
                    SELECT id, invoice_number, vendor_name, invoice_date, amount,
                           category, source_type, source_file, extraction_confidence,
                           ingested_at, created_by, transaction_type
                    FROM invoices
                    WHERE is_deleted = FALSE
                    ORDER BY ingested_at DESC
                    LIMIT :limit
                """)
            result = session.execute(query, {"limit": limit}).fetchall()
            logger.info(f"Retrieved {len(result)} invoices")
            return result
        except Exception as e:
            logger.error(f"Failed to retrieve invoices: {str(e)}")
            return []

    def get_invoices_by_source(self, session: Session, source_type: str) -> list:
        """Fetch invoices by source type (pdf_scan, excel_bulk, manual_entry)."""
        try:
            query = text("""
                SELECT id, invoice_number, vendor_name, invoice_date, amount,
                       category, source_type, source_file, extraction_confidence,
                       ingested_at, created_by
                FROM invoices
                WHERE source_type = :source_type
                  AND is_deleted = FALSE
                ORDER BY ingested_at DESC
            """)
            result = session.execute(query, {"source_type": source_type}).fetchall()
            return result
        except Exception as e:
            logger.error(f"Failed to filter by source: {str(e)}")
            return []

    def get_summary_stats(self, session: Session) -> list:
        """Get summary statistics for dashboard."""
        try:
            query = text("""
                SELECT
                    source_type,
                    COUNT(*) as total_invoices,
                    SUM(amount) as total_amount,
                    AVG(amount) as avg_amount
                FROM invoices
                WHERE is_deleted = FALSE
                GROUP BY source_type
            """)
            result = session.execute(query).fetchall()
            return result
        except Exception as e:
            logger.error(f"Failed to get stats: {str(e)}")
            return []

    def get_total_stats(self, session: Session) -> dict:
        """Get overall statistics."""
        try:
            query = text("""
                SELECT COUNT(*), SUM(amount)
                FROM invoices
                WHERE is_deleted = FALSE
            """)
            result = session.execute(query).fetchone()
            return {
                "total_count": result[0] or 0,
                "total_amount": float(result[1] or 0),
            }
        except Exception as e:
            logger.error(f"Failed to get total stats: {str(e)}")
            return {"total_count": 0, "total_amount": 0}

    # ============================================================
    # Soft Delete & Restore Methods
    # ============================================================

    def soft_delete_invoice(self, session: Session, invoice_id: int, reason: str, deleted_by: str = None) -> bool:
        """
        Soft delete an invoice (sets is_deleted=TRUE).

        Args:
            session: SQLAlchemy session
            invoice_id: ID of the invoice to delete
            reason: Reason for deletion (required for audit)
            deleted_by: User who performed the deletion

        Returns:
            True if successful, False otherwise
        """
        try:
            query = text("""
                UPDATE invoices
                SET is_deleted = TRUE,
                    deleted_at = NOW(),
                    deletion_reason = :reason,
                    updated_by = :deleted_by,
                    updated_at = NOW()
                WHERE id = :invoice_id AND is_deleted = FALSE
            """)
            result = session.execute(query, {
                "invoice_id": invoice_id,
                "reason": reason,
                "deleted_by": deleted_by
            })
            session.commit()

            if result.rowcount > 0:
                logger.info(f"Soft deleted invoice ID {invoice_id}: {reason}")
                return True
            else:
                logger.warning(f"Invoice ID {invoice_id} not found or already deleted")
                return False
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to soft delete invoice: {str(e)}")
            return False

    def restore_invoice(self, session: Session, invoice_id: int, restored_by: str = None) -> bool:
        """
        Restore a soft-deleted invoice.

        Args:
            session: SQLAlchemy session
            invoice_id: ID of the invoice to restore
            restored_by: User who performed the restoration

        Returns:
            True if successful, False otherwise
        """
        try:
            query = text("""
                UPDATE invoices
                SET is_deleted = FALSE,
                    deleted_at = NULL,
                    deletion_reason = NULL,
                    updated_by = :restored_by,
                    updated_at = NOW()
                WHERE id = :invoice_id AND is_deleted = TRUE
            """)
            result = session.execute(query, {
                "invoice_id": invoice_id,
                "restored_by": restored_by
            })
            session.commit()

            if result.rowcount > 0:
                logger.info(f"Restored invoice ID {invoice_id}")
                return True
            else:
                logger.warning(f"Invoice ID {invoice_id} not found or not deleted")
                return False
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to restore invoice: {str(e)}")
            return False

    # ============================================================
    # Income/Expense Statistics Methods
    # ============================================================

    def get_income_expense_stats(self, session: Session) -> dict:
        """
        Get income vs expense statistics.

        Returns:
            Dict with total_income, total_expense, and profit_margin
        """
        try:
            query = text("""
                SELECT
                    COALESCE(SUM(CASE WHEN transaction_type = 'INCOME' THEN amount ELSE 0 END), 0) as total_income,
                    COALESCE(SUM(CASE WHEN transaction_type = 'EXPENSE' THEN amount ELSE 0 END), 0) as total_expense,
                    COUNT(CASE WHEN transaction_type = 'INCOME' THEN 1 END) as income_count,
                    COUNT(CASE WHEN transaction_type = 'EXPENSE' THEN 1 END) as expense_count
                FROM invoices
                WHERE is_deleted = FALSE
            """)
            result = session.execute(query).fetchone()

            total_income = float(result[0] or 0)
            total_expense = float(result[1] or 0)
            income_count = result[2] or 0
            expense_count = result[3] or 0

            # Calculate profit margin (handle division by zero)
            if total_income > 0:
                profit_margin = ((total_income - total_expense) / total_income) * 100
            else:
                profit_margin = 0.0

            return {
                "total_income": total_income,
                "total_expense": total_expense,
                "income_count": income_count,
                "expense_count": expense_count,
                "net_profit": total_income - total_expense,
                "profit_margin": round(profit_margin, 2),
            }
        except Exception as e:
            logger.error(f"Failed to get income/expense stats: {str(e)}")
            return {
                "total_income": 0,
                "total_expense": 0,
                "income_count": 0,
                "expense_count": 0,
                "net_profit": 0,
                "profit_margin": 0,
            }

    def get_transaction_type_breakdown(self, session: Session, months: int = 12) -> list:
        """
        Get monthly breakdown by transaction type for charts.

        Args:
            session: SQLAlchemy session
            months: Number of months to look back

        Returns:
            List of (year, month, transaction_type, total_amount, count)
        """
        try:
            query = text("""
                SELECT
                    EXTRACT(YEAR FROM ingested_at)::int as year,
                    EXTRACT(MONTH FROM ingested_at)::int as month,
                    COALESCE(transaction_type, 'UNCLASSIFIED') as transaction_type,
                    SUM(amount) as total_amount,
                    COUNT(*) as count
                FROM invoices
                WHERE ingested_at > NOW() - INTERVAL :months_interval
                  AND is_deleted = FALSE
                GROUP BY year, month, transaction_type
                ORDER BY year DESC, month DESC, transaction_type
            """)
            result = session.execute(query, {"months_interval": f"{months} month"}).fetchall()
            return result
        except Exception as e:
            logger.error(f"Failed to get transaction type breakdown: {str(e)}")
            return []

    # ============================================================
    # Phase 6: Analytics Query Methods
    # ============================================================

    def get_monthly_summary(self, session: Session, months: int = 12) -> list:
        """
        Get last N months of spending.

        Args:
            session: SQLAlchemy session
            months: Number of months to look back

        Returns:
            List of (year, month, total_amount, total_count, source_type)
        """
        query = text("""
            SELECT
                EXTRACT(YEAR FROM ingested_at)::int as year,
                EXTRACT(MONTH FROM ingested_at)::int as month,
                SUM(amount) as total_amount,
                COUNT(*) as total_count,
                source_type
            FROM invoices
            WHERE ingested_at > NOW() - INTERVAL :months_interval
              AND is_deleted = FALSE
            GROUP BY year, month, source_type
            ORDER BY year DESC, month DESC
        """)

        try:
            result = session.execute(
                query, {"months_interval": f"{months} month"}
            ).fetchall()
            return result
        except Exception as e:
            logger.error(f"Failed to get monthly summary: {str(e)}")
            return []

    def get_category_breakdown(self, session: Session) -> list:
        """
        Spending by category (current month).

        Returns:
            List of (category, total_amount, total_count, avg_amount)
        """
        query = text("""
            SELECT
                COALESCE(category, 'Uncategorized') as category,
                SUM(amount) as total_amount,
                COUNT(*) as total_count,
                AVG(amount) as avg_amount
            FROM invoices
            WHERE ingested_at > DATE_TRUNC('month', NOW())
              AND is_deleted = FALSE
            GROUP BY category
            ORDER BY total_amount DESC
        """)

        try:
            result = session.execute(query).fetchall()
            return result
        except Exception as e:
            logger.error(f"Failed to get category breakdown: {str(e)}")
            return []

    def get_vendor_breakdown(self, session: Session, limit: int = 20) -> list:
        """
        Top vendors by spending.

        Args:
            session: SQLAlchemy session
            limit: Maximum number of vendors to return

        Returns:
            List of (vendor, total_amount, total_count, avg_amount, last_invoice_date)
        """
        query = text("""
            SELECT
                vendor_name as vendor,
                SUM(amount) as total_amount,
                COUNT(*) as total_count,
                AVG(amount) as avg_amount,
                MAX(invoice_date) as last_invoice_date
            FROM invoices
            WHERE is_deleted = FALSE
            GROUP BY vendor_name
            ORDER BY total_amount DESC
            LIMIT :limit
        """)

        try:
            result = session.execute(query, {"limit": limit}).fetchall()
            return result
        except Exception as e:
            logger.error(f"Failed to get vendor breakdown: {str(e)}")
            return []

    def get_source_type_distribution(self, session: Session) -> list:
        """
        How many invoices from each source?

        Returns:
            List of (source_type, total_count, total_amount, pct_of_total)
        """
        query = text("""
            WITH source_stats AS (
                SELECT
                    source_type,
                    COUNT(*) as total_count,
                    SUM(amount) as total_amount
                FROM invoices
                WHERE is_deleted = FALSE
                GROUP BY source_type
            ),
            totals AS (
                SELECT SUM(total_amount) as grand_total FROM source_stats
            )
            SELECT
                s.source_type,
                s.total_count,
                s.total_amount,
                ROUND((s.total_amount / NULLIF(t.grand_total, 0) * 100)::numeric, 1) as pct_of_total
            FROM source_stats s, totals t
            ORDER BY s.total_amount DESC
        """)

        try:
            result = session.execute(query).fetchall()
            return result
        except Exception as e:
            logger.error(f"Failed to get source distribution: {str(e)}")
            return []

    def get_daily_trend(self, session: Session, days: int = 30) -> list:
        """
        Daily spending trend for line chart.

        Args:
            session: SQLAlchemy session
            days: Number of days to look back

        Returns:
            List of (date, daily_total, invoice_count)
        """
        query = text("""
            SELECT
                DATE(ingested_at) as date,
                SUM(amount) as daily_total,
                COUNT(*) as invoice_count
            FROM invoices
            WHERE ingested_at > NOW() - INTERVAL :days_interval
              AND is_deleted = FALSE
            GROUP BY DATE(ingested_at)
            ORDER BY date ASC
        """)

        try:
            result = session.execute(
                query, {"days_interval": f"{days} day"}
            ).fetchall()
            return result
        except Exception as e:
            logger.error(f"Failed to get daily trend: {str(e)}")
            return []

    def get_quality_metrics(self, session: Session) -> dict:
        """
        Data quality scorecard.

        Returns:
            Dict with verification rates, source breakdown, etc.
        """
        query = text("""
            SELECT
                COUNT(*) as total_invoices,
                COUNT(CASE WHEN source_type = 'pdf_scan' AND extraction_confidence >= 70 THEN 1 END) as verified_count,
                COUNT(CASE WHEN source_type IN ('excel_bulk', 'manual_entry') OR extraction_confidence < 70 THEN 1 END) as unverified_count
            FROM invoices
            WHERE ingested_at > NOW() - INTERVAL '30 day'
              AND is_deleted = FALSE
        """)

        try:
            result = session.execute(query).fetchone()
            total = result[0] or 0
            verified = result[1] or 0
            return {
                "total_invoices": total,
                "verified_count": verified,
                "unverified_count": result[2] or 0,
                "verification_rate": f"{(verified / total * 100):.1f}%" if total > 0 else "0%",
            }
        except Exception as e:
            logger.error(f"Failed to get quality metrics: {str(e)}")
            return {
                "total_invoices": 0,
                "verified_count": 0,
                "unverified_count": 0,
                "verification_rate": "0%",
            }

    def close(self):
        """Close all database connections."""
        self.engine.dispose()
        logger.info("Database connections closed")


@st.cache_resource
def get_db_manager() -> Optional[DatabaseManager]:
    """
    Get or create database manager instance.
    Uses Streamlit's cache to ensure single instance per session.
    """
    try:
        # Load secrets from Streamlit's secret management
        db_config = st.secrets["database"]

        manager = DatabaseManager(
            host=db_config["host"],
            port=db_config["port"],
            user=db_config["user"],
            password=db_config["password"],
            database=db_config["database"],
            region=st.secrets.get("aws", {}).get("region", "us-east-1"),
        )

        # Test connection on initialization
        if not manager.test_connection():
            st.error("Cannot connect to database. Check your secrets configuration.")
            return None

        return manager
    except KeyError as e:
        st.error(f"Missing secret: {str(e)}. Add to .streamlit/secrets.toml")
        return None
    except Exception as e:
        st.error(f"Failed to initialize database: {str(e)}")
        return None
