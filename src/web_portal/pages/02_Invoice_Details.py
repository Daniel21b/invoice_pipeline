"""
Invoice Search & Details - Phase 8
Drill-down functionality for searching and filtering invoices.

Available at: localhost:8501/Invoice_Details (Streamlit auto-creates navigation)
Requires authentication to access (admin only via Streamlit secrets).
"""

import os
import sys
from datetime import datetime

import pandas as pd
import streamlit as st

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from database.database import get_db_manager
from database.auth import AuditLog

st.set_page_config(
    page_title="Invoice Search",
    page_icon="mag",
    layout="wide",
)

# Database connection
db = get_db_manager()
if db is None:
    st.error("Database connection failed")
    st.stop()

session = db.get_session()

# === AUTHENTICATION GATEKEEPER ===
if not st.session_state.get("authenticated"):
    st.warning("Access denied. Please log in to access invoice search.")
    st.switch_page("pages/login.py")
    st.stop()

# Get current user info from session state
user_id = st.session_state.get("user_id", 1)
user_email = st.session_state.get("email", "")
user_name = st.session_state.get("full_name", user_email)
user_role = st.session_state.get("role", "admin")

# === SIDEBAR WITH USER INFO ===
with st.sidebar:
    st.markdown(f"**{user_name}**")
    st.caption(f"{user_email}")
    st.caption(f"Role: Admin")
    st.divider()

    if st.button("Logout", use_container_width=True, key="search_logout"):
        AuditLog.log_action(
            session,
            user_id=user_id or 1,
            action="logout",
            entity_type="user",
            entity_id=user_id or 1
        )
        st.session_state.clear()
        st.switch_page("pages/login.py")

st.title("Invoice Search & Details")

# === ADMIN TOGGLE: Show deleted records ===
show_deleted = False
if user_role == "admin":
    with st.sidebar:
        st.divider()
        st.subheader("Admin Controls")
        show_deleted = st.checkbox(
            "Show Deleted Records",
            value=False,
            help="Toggle to view soft-deleted invoices"
        )

# Get all invoices (including deleted if admin toggle is on)
all_invoices = db.get_all_invoices(session, limit=10000, include_deleted=show_deleted)

if not all_invoices:
    st.info("No invoices found. Upload some data first.")
    session.close()
    st.stop()

# Create DataFrame with appropriate columns based on whether deleted records are included
if show_deleted:
    df_all = pd.DataFrame(
        all_invoices,
        columns=[
            "ID", "Invoice #", "Vendor", "Date", "Amount",
            "Category", "Source", "File", "Confidence", "Ingested", "Created By",
            "Type", "Is Deleted", "Deleted At", "Deletion Reason"
        ]
    )
else:
    df_all = pd.DataFrame(
        all_invoices,
        columns=[
            "ID", "Invoice #", "Vendor", "Date", "Amount",
            "Category", "Source", "File", "Confidence", "Ingested", "Created By", "Type"
        ]
    )

# === FILTERS ===
st.subheader("Filter Invoices")

col1, col2, col3, col4 = st.columns(4)

with col1:
    vendors = ["All"] + sorted(df_all["Vendor"].unique().tolist())
    selected_vendor = st.selectbox("Filter by Vendor", vendors)

with col2:
    categories = ["All"] + sorted([c for c in df_all["Category"].unique().tolist() if c])
    selected_category = st.selectbox("Filter by Category", categories)

with col3:
    sources = ["All"] + sorted(df_all["Source"].unique().tolist())
    selected_source = st.selectbox("Filter by Source", sources)

with col4:
    # Date range filter
    min_date = pd.to_datetime(df_all["Date"]).min().date()
    max_date = pd.to_datetime(df_all["Date"]).max().date()
    date_range = st.date_input(
        "Date Range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

# Additional filters
col5, col6 = st.columns(2)

with col5:
    amount_range = st.slider(
        "Amount Range ($)",
        min_value=float(df_all["Amount"].min()),
        max_value=float(df_all["Amount"].max()),
        value=(float(df_all["Amount"].min()), float(df_all["Amount"].max())),
        format="$%.2f"
    )

with col6:
    search_text = st.text_input("Search (Invoice # or Vendor)", placeholder="Type to search...")

# Apply filters
filtered = df_all.copy()

if selected_vendor != "All":
    filtered = filtered[filtered["Vendor"] == selected_vendor]

if selected_category != "All":
    filtered = filtered[filtered["Category"] == selected_category]

if selected_source != "All":
    filtered = filtered[filtered["Source"] == selected_source]

# Date filter
if len(date_range) == 2:
    filtered["Date"] = pd.to_datetime(filtered["Date"])
    filtered = filtered[
        (filtered["Date"].dt.date >= date_range[0]) &
        (filtered["Date"].dt.date <= date_range[1])
    ]

# Amount filter
filtered = filtered[
    (filtered["Amount"] >= amount_range[0]) &
    (filtered["Amount"] <= amount_range[1])
]

# Text search
if search_text:
    search_lower = search_text.lower()
    filtered = filtered[
        filtered["Invoice #"].astype(str).str.lower().str.contains(search_lower, na=False) |
        filtered["Vendor"].astype(str).str.lower().str.contains(search_lower, na=False)
    ]

st.divider()

# === RESULTS ===
st.subheader(f"Results: {len(filtered):,} invoices")

# Summary metrics for filtered data
if len(filtered) > 0:
    col_sum1, col_sum2, col_sum3, col_sum4 = st.columns(4)

    with col_sum1:
        st.metric("Total", f"${filtered['Amount'].sum():,.2f}")

    with col_sum2:
        st.metric("Count", f"{len(filtered):,}")

    with col_sum3:
        st.metric("Average", f"${filtered['Amount'].mean():,.2f}")

    with col_sum4:
        st.metric("Unique Vendors", f"{filtered['Vendor'].nunique():,}")

    st.divider()

    # Sortable table
    st.dataframe(
        filtered,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Amount": st.column_config.NumberColumn(
                "Amount",
                format="$%.2f"
            ),
            "Confidence": st.column_config.NumberColumn(
                "Confidence",
                format="%.1f%%"
            ),
        }
    )

    # Export button
    export_filename = f"filtered_invoices_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    if st.download_button(
        label="Export Filtered Results to CSV",
        data=filtered.to_csv(index=False),
        file_name=export_filename,
        mime="text/csv"
    ):
        # Log the export action
        AuditLog.log_action(
            session,
            user_id=user_id,
            action="export_invoices",
            entity_type="invoice",
            details={
                "filename": export_filename,
                "record_count": len(filtered),
                "total_amount": float(filtered["Amount"].sum()),
                "filters": {
                    "vendor": selected_vendor,
                    "category": selected_category,
                    "source": selected_source
                }
            }
        )
else:
    st.warning("No invoices match your filters. Try adjusting the criteria.")

st.divider()

# === QUICK STATS BY FILTER ===
if len(filtered) > 0:
    st.subheader("Breakdown by Category")

    category_summary = filtered.groupby("Category").agg({
        "Amount": ["sum", "count", "mean"]
    }).round(2)
    category_summary.columns = ["Total Amount", "Count", "Avg Amount"]
    category_summary = category_summary.sort_values("Total Amount", ascending=False)

    # Format display
    category_display = category_summary.copy()
    category_display["Total Amount"] = category_display["Total Amount"].apply(lambda x: f"${x:,.2f}")
    category_display["Avg Amount"] = category_display["Avg Amount"].apply(lambda x: f"${x:,.2f}")

    st.dataframe(category_display, use_container_width=True)

    st.subheader("Breakdown by Source")

    source_summary = filtered.groupby("Source").agg({
        "Amount": ["sum", "count", "mean"]
    }).round(2)
    source_summary.columns = ["Total Amount", "Count", "Avg Amount"]
    source_summary = source_summary.sort_values("Total Amount", ascending=False)

    # Format display
    source_display = source_summary.copy()
    source_display["Total Amount"] = source_display["Total Amount"].apply(lambda x: f"${x:,.2f}")
    source_display["Avg Amount"] = source_display["Avg Amount"].apply(lambda x: f"${x:,.2f}")

    st.dataframe(source_display, use_container_width=True)

st.divider()

# === DELETE / RESTORE SECTION ===
st.subheader("Invoice Actions")

# Only show delete functionality if user has permission (admin or operator)
if user_role in ["admin", "operator"]:
    # Select invoice to delete
    invoice_ids = filtered["ID"].tolist() if len(filtered) > 0 else []

    if invoice_ids:
        col_action1, col_action2 = st.columns(2)

        with col_action1:
            st.markdown("**Delete Invoice**")

            # Show only non-deleted invoices for deletion
            if show_deleted:
                active_ids = filtered[filtered["Is Deleted"] == False]["ID"].tolist()
            else:
                active_ids = invoice_ids

            if active_ids:
                selected_delete_id = st.selectbox(
                    "Select Invoice ID to Delete",
                    options=active_ids,
                    key="delete_invoice_select"
                )

                # Show invoice details
                if selected_delete_id:
                    selected_invoice = filtered[filtered["ID"] == selected_delete_id].iloc[0]
                    st.caption(f"Vendor: {selected_invoice['Vendor']} | Amount: ${selected_invoice['Amount']:.2f}")

                # Delete form with reason
                with st.form("delete_form"):
                    delete_reason = st.text_area(
                        "Reason for Deletion (required)",
                        placeholder="e.g., Duplicate entry, Data entry error, etc."
                    )

                    delete_submitted = st.form_submit_button("Delete Invoice", type="primary")

                    if delete_submitted:
                        if not delete_reason or len(delete_reason.strip()) < 5:
                            st.error("Please provide a reason for deletion (at least 5 characters)")
                        else:
                            success = db.soft_delete_invoice(
                                session,
                                invoice_id=selected_delete_id,
                                reason=delete_reason.strip(),
                                deleted_by=user_email
                            )

                            if success:
                                # Log the deletion
                                AuditLog.log_action(
                                    session,
                                    user_id=user_id,
                                    action="soft_delete",
                                    entity_type="invoice",
                                    entity_id=selected_delete_id,
                                    details={
                                        "reason": delete_reason.strip(),
                                        "vendor": selected_invoice['Vendor'],
                                        "amount": float(selected_invoice['Amount'])
                                    }
                                )
                                st.success(f"Invoice ID {selected_delete_id} has been deleted.")
                                st.rerun()
                            else:
                                st.error("Failed to delete invoice. Please try again.")
            else:
                st.info("No active invoices available to delete.")

        # Admin-only: Restore functionality
        if user_role == "admin" and show_deleted:
            with col_action2:
                st.markdown("**Restore Deleted Invoice**")

                # Show only deleted invoices for restoration
                deleted_ids = filtered[filtered["Is Deleted"] == True]["ID"].tolist()

                if deleted_ids:
                    selected_restore_id = st.selectbox(
                        "Select Invoice ID to Restore",
                        options=deleted_ids,
                        key="restore_invoice_select"
                    )

                    # Show invoice details
                    if selected_restore_id:
                        selected_deleted = filtered[filtered["ID"] == selected_restore_id].iloc[0]
                        st.caption(f"Vendor: {selected_deleted['Vendor']} | Amount: ${selected_deleted['Amount']:.2f}")
                        st.caption(f"Deleted: {selected_deleted['Deleted At']} | Reason: {selected_deleted['Deletion Reason']}")

                    if st.button("Restore Invoice", key="restore_btn"):
                        success = db.restore_invoice(
                            session,
                            invoice_id=selected_restore_id,
                            restored_by=user_email
                        )

                        if success:
                            # Log the restoration
                            AuditLog.log_action(
                                session,
                                user_id=user_id,
                                action="restore",
                                entity_type="invoice",
                                entity_id=selected_restore_id,
                                details={
                                    "vendor": selected_deleted['Vendor'],
                                    "amount": float(selected_deleted['Amount'])
                                }
                            )
                            st.success(f"Invoice ID {selected_restore_id} has been restored.")
                            st.rerun()
                        else:
                            st.error("Failed to restore invoice. Please try again.")
                else:
                    st.info("No deleted invoices to restore.")
else:
    st.info("You don't have permission to delete invoices. Contact an administrator.")

# Cleanup
session.close()

st.divider()
st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
