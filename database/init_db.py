"""
Database Initialization Script - Phase 3

Initializes the PostgreSQL database with the invoice schema.
Can be run locally or as part of deployment.
"""

import os
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def get_connection_params():
    """Get database connection parameters from environment."""
    return {
        "host": os.getenv("RDS_HOST", "localhost"),
        "port": os.getenv("RDS_PORT", "5432"),
        "user": os.getenv("RDS_USER", "postgres"),
        "password": os.getenv("RDS_PASSWORD", ""),
        "database": os.getenv("RDS_DB", "invoices"),
    }


def create_database_if_not_exists():
    """Create the database if it doesn't exist."""
    params = get_connection_params()
    db_name = params.pop("database")

    # Connect to default postgres database
    params["database"] = "postgres"

    try:
        conn = psycopg2.connect(**params)
        conn.autocommit = True
        cursor = conn.cursor()

        # Check if database exists
        cursor.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (db_name,)
        )
        exists = cursor.fetchone()

        if not exists:
            print(f"Creating database '{db_name}'...")
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
            print(f"Database '{db_name}' created successfully.")
        else:
            print(f"Database '{db_name}' already exists.")

        cursor.close()
        conn.close()
        return True

    except psycopg2.Error as e:
        print(f"Error creating database: {e}")
        return False


def run_schema():
    """Execute the schema.sql file to create tables."""
    params = get_connection_params()

    # Get the schema file path
    schema_path = Path(__file__).parent / "schema.sql"

    if not schema_path.exists():
        print(f"Schema file not found: {schema_path}")
        return False

    try:
        conn = psycopg2.connect(**params)
        cursor = conn.cursor()

        # Read and execute schema
        with open(schema_path, "r") as f:
            schema_sql = f.read()

        print("Executing schema.sql...")
        cursor.execute(schema_sql)
        conn.commit()

        print("Schema applied successfully.")

        # Verify tables were created
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
        """)
        tables = cursor.fetchall()
        print(f"Tables created: {[t[0] for t in tables]}")

        cursor.close()
        conn.close()
        return True

    except psycopg2.Error as e:
        print(f"Error applying schema: {e}")
        return False


def verify_connection():
    """Verify database connection and print info."""
    params = get_connection_params()

    try:
        conn = psycopg2.connect(**params)
        cursor = conn.cursor()

        # Get PostgreSQL version
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        print(f"Connected to: {version}")

        # Get table count
        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        table_count = cursor.fetchone()[0]
        print(f"Tables in database: {table_count}")

        # Get invoice count if table exists
        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name = 'invoices'
        """)
        if cursor.fetchone()[0] > 0:
            cursor.execute("SELECT COUNT(*) FROM invoices;")
            invoice_count = cursor.fetchone()[0]
            print(f"Invoices in database: {invoice_count}")

        cursor.close()
        conn.close()
        return True

    except psycopg2.Error as e:
        print(f"Connection failed: {e}")
        return False


def main():
    """Main initialization function."""
    print("=" * 50)
    print("Invoice Pipeline - Database Initialization")
    print("=" * 50)

    # Check for required environment variables
    params = get_connection_params()
    print(f"\nConnection settings:")
    print(f"  Host: {params['host']}")
    print(f"  Port: {params['port']}")
    print(f"  User: {params['user']}")
    print(f"  Database: {params['database']}")
    print()

    # Step 1: Create database if needed
    print("Step 1: Checking database...")
    if not create_database_if_not_exists():
        print("Failed to create database. Exiting.")
        sys.exit(1)

    # Step 2: Apply schema
    print("\nStep 2: Applying schema...")
    if not run_schema():
        print("Failed to apply schema. Exiting.")
        sys.exit(1)

    # Step 3: Verify connection
    print("\nStep 3: Verifying setup...")
    if not verify_connection():
        print("Verification failed. Please check your configuration.")
        sys.exit(1)

    print("\n" + "=" * 50)
    print("Database initialization complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
