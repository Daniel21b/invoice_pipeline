"""
Streamlit Unified Ingestion Portal - Phase 8

Admin-only access to invoice data.
Uses Streamlit Secrets for authentication (no database user management).
Requires authentication for all access.
"""

import os
import sys
import uuid
from datetime import date
import time

import boto3
import pandas as pd
import streamlit as st
from botocore.exceptions import ClientError

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database.database import get_db_manager
from database.auth import AuditLog

# === CONFIGURATION ===
REQUIRED_COLUMNS = ["Date", "Vendor", "Amount", "Category"]
CATEGORIES = ["Inventory", "Utilities", "Rent", "Supplies", "Services", "Other"]

# AWS config from Streamlit secrets (with fallbacks)
try:
    S3_BUCKET = st.secrets.get("aws", {}).get("s3_bucket", "")
    S3_REGION = st.secrets.get("aws", {}).get("region", "us-east-1")
    S3_PREFIX = st.secrets.get("aws", {}).get("s3_prefix", "invoices/")
except Exception:
    S3_BUCKET = os.getenv("S3_BUCKET", "")
    S3_REGION = os.getenv("S3_REGION", "us-east-1")
    S3_PREFIX = os.getenv("S3_PREFIX", "invoices/")

# Initialize AWS clients (only if credentials available)
s3_client = None
try:
    s3_client = boto3.client("s3", region_name=S3_REGION)
except Exception:
    pass


# === PAGE CONFIG ===
st.set_page_config(
    page_title="Business Data Portal",
    page_icon="receipt",
    layout="wide",
)

# === DATABASE CONNECTION ===
db = get_db_manager()
if db is None:
    st.error("Database connection failed. Please check your .streamlit/secrets.toml configuration.")
    st.info("""
    **Setup Instructions:**
    1. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
    2. Fill in your RDS database credentials
    3. Restart the app
    """)
    st.stop()

# Get database session
session = db.get_session()

# === AUTHENTICATION GATEKEEPER ===
# This MUST be at the top - stops execution if not authenticated
if not st.session_state.get("authenticated"):
    st.warning("Access denied. Please log in to access the portal.")
    st.switch_page("pages/login.py")
    st.stop()  # Extra safety to ensure nothing below runs

# Get current user info from session state
user_id = st.session_state.get("user_id", 1)
user_email = st.session_state.get("email", "")
user_name = st.session_state.get("full_name", user_email)
user_role = st.session_state.get("role", "admin")  # Default to admin for secrets-based auth

# === SIDEBAR WITH USER INFO ===
with st.sidebar:
    st.markdown(f"**{user_name}**")
    st.caption(f"{user_email}")
    st.caption(f"Role: {user_role.title()}")
    st.divider()

    if st.button("Logout", use_container_width=True):
        # Log the logout action
        AuditLog.log_action(
            session,
            user_id=user_id or 1,
            action="logout",
            entity_type="user",
            entity_id=user_id or 1
        )
        # Clear session and redirect to login
        st.session_state.clear()
        st.switch_page("pages/login.py")

# === TITLE ===
st.title("Business Data Portal")
st.markdown("Upload invoices from PDF, Excel, or manual entry. All data saved automatically.")

# === CREATE TABS (Admin-Only Access) ===
tabs = st.tabs([
    "Upload PDF",
    "Excel Upload",
    "Manual Entry",
    "Statistics",
    "Audit Log",
])
tab_pdf, tab_excel, tab_manual, tab_stats, tab_audit = tabs

# ============================================================
# TAB 1: PDF UPLOAD (Async via Lambda)
# ============================================================
with tab_pdf:
        st.header("Upload Scanned Invoices (PDF)")
        st.markdown("""
        Upload PDF or scanned image files. They'll be processed automatically using AI.
        - **Processing**: Automated (2-5 seconds per page)
        - **Cost**: ~$0.015 per page
        - **Next**: Check the Statistics tab to see results
        """)

        # Transaction Type Classification (REQUIRED before upload)
        st.subheader("Step 1: Classify Transaction")
        pdf_transaction_type = st.radio(
            "Transaction Type",
            options=["INCOME", "EXPENSE"],
            horizontal=True,
            key="pdf_transaction_type",
            help="Classify this invoice as income (money received) or expense (money spent)"
        )

        st.subheader("Step 2: Upload File")

        # Check S3 configuration
        if not S3_BUCKET:
            st.warning("S3 bucket not configured. Set aws.s3_bucket in secrets.toml")
        elif not s3_client:
            st.warning("AWS credentials not configured. Unable to upload files.")
        else:
            uploaded_pdf = st.file_uploader(
                "Drop PDF, JPG, or PNG here",
                type=["pdf", "png", "jpg", "jpeg"],
                key="pdf_uploader",
            )

            if uploaded_pdf:
                st.info(f"Preparing to upload: {uploaded_pdf.name} as **{pdf_transaction_type}**")

                # File size check
                file_size_mb = uploaded_pdf.size / (1024 * 1024)
                if file_size_mb > 10:
                    st.warning(f"Large file detected ({file_size_mb:.1f} MB). Processing may take longer.")

                if st.button("Upload to Processing", key="upload_pdf_btn"):
                    try:
                        # Generate S3 key with prefix
                        s3_key = f"{S3_PREFIX}{uuid.uuid4().hex}_{uploaded_pdf.name}"

                        # Upload to S3 with transaction-type metadata
                        with st.spinner(f"Uploading {uploaded_pdf.name}..."):
                            s3_client.upload_fileobj(
                                uploaded_pdf,
                                S3_BUCKET,
                                s3_key,
                                ExtraArgs={
                                    "ContentType": uploaded_pdf.type,
                                    "Metadata": {"transaction-type": pdf_transaction_type}
                                },
                            )

                        # Log the upload action
                        AuditLog.log_action(
                            session,
                            user_id=user_id,
                            action="upload_pdf",
                            entity_type="invoice",
                            details={
                                "filename": uploaded_pdf.name,
                                "s3_key": s3_key,
                                "transaction_type": pdf_transaction_type
                            }
                        )

                        st.success(f"""
                        **Uploaded successfully!**

                        File: `{uploaded_pdf.name}`
                        Location: `{s3_key}`
                        Size: {uploaded_pdf.size / 1024:.1f} KB

                        **What happens next:**
                        1. AWS Lambda automatically processes your file
                        2. AI extracts invoice details (vendor, date, amount)
                        3. Data saved to our database
                        4. Processing takes 2-5 seconds per page

                        **Check the Statistics tab in 1-2 minutes to see results!**
                        """)

                    except ClientError as e:
                        st.error(f"Upload failed: {e}")

# ============================================================
# TAB 2: EXCEL UPLOAD (Instant via SQLAlchemy)
# ============================================================
with tab_excel:
        st.header("Bulk Import from Excel")
        st.markdown("""
        Upload Excel spreadsheet with invoice data. Validate format, then save instantly.
        - **Processing**: Instant (< 1 second)
        - **Cost**: Free
        - **Requirements**: File must have columns: Date, Vendor, Amount, Category
        """)

        # Transaction Type Classification (REQUIRED before upload)
        st.subheader("Step 1: Classify All Transactions")
        excel_transaction_type = st.radio(
            "Transaction Type for All Rows",
            options=["INCOME", "EXPENSE"],
            horizontal=True,
            key="excel_transaction_type",
            help="All rows in this upload will be classified as this type"
        )

        st.subheader("Step 2: Upload File")

        # Show template
        with st.expander("Show Excel Template"):
            template_df = pd.DataFrame([
                {"Date": "2024-01-15", "Vendor": "Acme Corp", "Amount": 1500.00, "Category": "Inventory"},
                {"Date": "2024-01-16", "Vendor": "Office Supplies", "Amount": 250.00, "Category": "Utilities"},
            ])
            st.dataframe(template_df)
            st.download_button(
                "Download Template",
                template_df.to_csv(index=False),
                "invoice_template.csv",
                "text/csv",
            )

        uploaded_excel = st.file_uploader(
            "Drop Excel file here",
            type=["xlsx", "xls", "csv"],
            key="excel_uploader",
        )

        if uploaded_excel:
            try:
                # Read file
                if uploaded_excel.name.endswith(".csv"):
                    df = pd.read_csv(uploaded_excel)
                else:
                    df = pd.read_excel(uploaded_excel)

                # Validation: Check columns
                missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]

                if missing_cols:
                    st.error(f"""
                    **Error: Your file is missing these columns:**

                    Required: {', '.join(REQUIRED_COLUMNS)}
                    Missing: {', '.join(missing_cols)}

                    Please download the template above and use it as a guide.
                    """)
                else:
                    # Show preview
                    st.subheader("Preview of Data")
                    st.dataframe(df.head(10), use_container_width=True)

                    # Show statistics
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Rows to Import", len(df))
                    with col2:
                        st.metric("Total Amount", f"${df['Amount'].sum():,.2f}")
                    with col3:
                        st.metric("Categories", df["Category"].nunique())

                    # Check for extra columns
                    extra_cols = [col for col in df.columns if col not in REQUIRED_COLUMNS]
                    if extra_cols:
                        st.info(f"Note: Extra columns will be ignored: {', '.join(extra_cols)}")

                    # File info message for large uploads
                    if len(df) >= 100:
                        st.info(f"Large file ({len(df)} rows) - will use optimized bulk upload for faster processing.")

                    # Save button
                    if st.button("Confirm & Save to Database", key="save_excel_btn"):
                        # Show progress indicator
                        progress = st.progress(0)
                        status = st.empty()
                        status.write("Processing...")

                        start_time = time.time()

                        # Use optimized method (auto-selects COPY for large uploads)
                        rows_saved = db.save_bulk_invoices_mixed(
                            session,
                            df[REQUIRED_COLUMNS],
                            "excel_bulk",
                            uploaded_excel.name,
                            transaction_type=excel_transaction_type,
                        )

                        elapsed = time.time() - start_time
                        progress.progress(100)

                        if rows_saved > 0:
                            # Log the bulk upload
                            AuditLog.log_action(
                                session,
                                user_id=user_id,
                                action="upload_excel",
                                entity_type="invoice",
                                details={
                                    "filename": uploaded_excel.name,
                                    "rows_imported": rows_saved,
                                    "total_amount": float(df['Amount'].sum()),
                                    "transaction_type": excel_transaction_type
                                }
                            )

                            rows_per_sec = int(rows_saved / elapsed) if elapsed > 0 else rows_saved
                            st.success(f"""
                            **Success!**

                            Saved **{rows_saved} rows** to the database in {elapsed:.2f}s
                            Speed: ~{rows_per_sec:,} rows/sec
                            Total amount imported: ${df['Amount'].sum():,.2f}

                            Your data is now available in the Statistics tab.
                            """)
                        else:
                            st.error("Failed to save data. Please check database connection and try again.")

            except Exception as e:
                st.error(f"Error reading file: {e}")

# ============================================================
# TAB 3: MANUAL ENTRY (Instant via SQLAlchemy)
# ============================================================
with tab_manual:
        st.header("Add Single Transaction")
        st.markdown("""
        Manually add a single invoice entry. Perfect for quick, one-off entries.
        - **Processing**: Instant (< 1 second)
        - **Cost**: Free
        """)

        with st.form("manual_entry_form"):
            # Transaction Type Classification (REQUIRED)
            manual_transaction_type = st.radio(
                "Transaction Type",
                options=["INCOME", "EXPENSE"],
                horizontal=True,
                help="Classify this transaction as income (money received) or expense (money spent)"
            )

            col1, col2 = st.columns(2)

            with col1:
                txn_date = st.date_input("Date", value=date.today())
                vendor = st.text_input("Vendor Name", placeholder="Acme Corp")
                invoice_number = st.text_input("Invoice Number (Optional)", placeholder="INV-12345")

            with col2:
                amount = st.number_input("Amount ($)", min_value=0.0, step=0.01)
                category = st.selectbox("Category", CATEGORIES)

            notes = st.text_area("Notes (Optional)", placeholder="Any additional details...")

            submitted = st.form_submit_button("Add Transaction")

            if submitted:
                if not vendor:
                    st.error("Please enter a vendor name")
                elif amount <= 0:
                    st.error("Amount must be greater than 0")
                else:
                    # Build invoice data dict
                    invoice_data = {
                        "invoice_number": invoice_number if invoice_number else f"MANUAL-{uuid.uuid4().hex[:8]}",
                        "vendor_name": vendor,
                        "invoice_date": txn_date,
                        "amount": amount,
                        "category": category,
                        "source_type": "manual_entry",
                        "source_file": "manual",
                        "created_by": user_email,
                        "notes": notes if notes else None,
                        "transaction_type": manual_transaction_type,
                    }

                    with st.spinner("Saving transaction..."):
                        saved = db.save_invoice(session, invoice_data)

                    if saved:
                        # Log the manual entry
                        AuditLog.log_action(
                            session,
                            user_id=user_id,
                            action="create_invoice",
                            entity_type="invoice",
                            details={
                                "vendor": vendor,
                                "amount": amount,
                                "category": category,
                                "transaction_type": manual_transaction_type
                            }
                        )

                        st.success(f"""
                        **Transaction saved!**

                        Type: {manual_transaction_type}
                        Vendor: {vendor}
                        Date: {txn_date}
                        Amount: ${amount:.2f}
                        Category: {category}

                        Your transaction is now in the database.
                        """)
                    else:
                        st.error("Failed to save transaction. Please check database connection and try again.")

# ============================================================
# TAB 4: STATISTICS
# ============================================================
with tab_stats:
    st.header("Invoice Statistics")

    if st.button("Refresh Statistics"):
        st.rerun()

    # Get overall stats
    total_stats = db.get_total_stats(session)
    summary_stats = db.get_summary_stats(session)

    # Overall metrics
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Invoices", total_stats.get("total_count", 0))
    with col2:
        st.metric("Total Amount", f"${total_stats.get('total_amount', 0):,.2f}")

    # By source type
    st.subheader("Invoices by Source")

    if summary_stats:
        source_df = pd.DataFrame([
            {
                "Source Type": stat[0],
                "Count": stat[1],
                "Total Amount": f"${stat[2]:,.2f}" if stat[2] else "$0.00",
                "Avg Amount": f"${stat[3]:,.2f}" if stat[3] else "$0.00",
            }
            for stat in summary_stats
        ])
        st.dataframe(source_df, use_container_width=True)
    else:
        st.info("No invoices in database yet.")

    # Show recent invoices
    st.subheader("Recent Invoices")
    invoices = db.get_all_invoices(session, limit=20)

    if invoices:
        df_display = pd.DataFrame(
            invoices,
            columns=[
                "ID", "Invoice #", "Vendor", "Date", "Amount",
                "Category", "Source", "File", "Confidence", "Ingested", "Created By"
            ]
        )
        st.dataframe(df_display, use_container_width=True)
    else:
        st.info("No invoices found.")

# ============================================================
# TAB 5: AUDIT LOG
# ============================================================
with tab_audit:
        st.header("Audit Log")
        st.markdown("View all system activity and changes.")

        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            audit_days = st.selectbox("Time Range", [7, 14, 30, 90], index=2)
        with col2:
            audit_action = st.selectbox("Action Type", ["All", "login", "logout", "create_invoice", "upload_pdf", "upload_excel", "create_user"])
        with col3:
            audit_limit = st.selectbox("Show", [50, 100, 500, 1000], index=1)

        # Get audit log
        action_filter = None if audit_action == "All" else audit_action
        audit_entries = AuditLog.get_audit_trail(
            session,
            days=audit_days,
            limit=audit_limit,
            action=action_filter
        )

        if audit_entries:
            audit_df = pd.DataFrame(
                audit_entries,
                columns=["ID", "Timestamp", "Email", "User Name", "Action", "Entity Type", "Entity ID", "Details", "IP Address"]
            )
            # Format timestamp
            audit_df["Timestamp"] = pd.to_datetime(audit_df["Timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
            st.dataframe(audit_df, use_container_width=True)

            # Export option
            csv = audit_df.to_csv(index=False)
            st.download_button(
                "Download Audit Log (CSV)",
                csv,
                f"audit_log_{audit_days}days.csv",
                "text/csv"
            )
        else:
            st.info("No audit entries found for the selected filters.")

# ============================================================
# FOOTER
# ============================================================
st.divider()
st.markdown(f"""
---
**About This Portal:**
- PDFs are processed by AI (2-5 sec)
- Excel uploads are instant
- Manual entries are instant
- All data tracked by source (PDF, Excel, Manual)
- Admin-only access enabled
- All actions are logged for audit compliance

Logged in as: {user_email} (Admin)
""")
