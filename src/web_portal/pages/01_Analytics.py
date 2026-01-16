"""
Analytics Dashboard - Phase 8
KPIs, charts, and business insights for invoice data.

Available at: localhost:8501/Analytics (Streamlit auto-creates navigation)
Requires authentication to access (admin only via Streamlit secrets).
"""

import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from database.database import get_db_manager
from database.auth import AuditLog

st.set_page_config(
    page_title="Analytics Dashboard",
    page_icon="chart_with_upwards_trend",
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
    st.warning("Access denied. Please log in to access analytics.")
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

    if st.button("Logout", use_container_width=True, key="analytics_logout"):
        AuditLog.log_action(
            session,
            user_id=user_id or 1,
            action="logout",
            entity_type="user",
            entity_id=user_id or 1
        )
        st.session_state.clear()
        st.switch_page("pages/login.py")

st.title("Invoice Analytics Dashboard")

# === INCOME/EXPENSE KPIs ===
st.subheader("Financial Summary")

# Get income/expense stats
income_expense = db.get_income_expense_stats(session)

# Display Income, Expense, Net Profit, and Margin
kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)

with kpi_col1:
    st.metric(
        "Total Income",
        f"${income_expense['total_income']:,.2f}",
        f"{income_expense['income_count']} transactions",
        delta_color="normal"
    )

with kpi_col2:
    st.metric(
        "Total Expenses",
        f"${income_expense['total_expense']:,.2f}",
        f"{income_expense['expense_count']} transactions",
        delta_color="inverse"
    )

with kpi_col3:
    net_profit = income_expense['net_profit']
    profit_color = "normal" if net_profit >= 0 else "inverse"
    st.metric(
        "Net Profit",
        f"${net_profit:,.2f}",
        f"{'Profitable' if net_profit >= 0 else 'Loss'}",
        delta_color=profit_color
    )

with kpi_col4:
    margin = income_expense['profit_margin']
    margin_color = "normal" if margin >= 0 else "inverse"
    st.metric(
        "Profit Margin",
        f"{margin:.1f}%",
        f"{'Healthy' if margin >= 20 else 'Low' if margin >= 0 else 'Negative'}",
        delta_color=margin_color
    )

st.divider()

# === INCOME VS EXPENSE CHART ===
st.subheader("Income vs Expense Trend")

transaction_breakdown = db.get_transaction_type_breakdown(session, months=12)
if transaction_breakdown:
    df_txn = pd.DataFrame(
        transaction_breakdown,
        columns=["Year", "Month", "Type", "Amount", "Count"]
    )
    df_txn["Amount"] = df_txn["Amount"].astype(float)
    df_txn["Month-Year"] = df_txn.apply(
        lambda x: f"{int(x['Year'])}-{int(x['Month']):02d}", axis=1
    )

    # Color map: Green for Income, Pink/Red for Expense
    color_map = {
        'INCOME': '#2ECC71',      # Green
        'EXPENSE': '#E74C3C',     # Red/Pink
        'UNCLASSIFIED': '#95A5A6' # Gray for unclassified
    }

    fig_txn = px.bar(
        df_txn,
        x="Month-Year",
        y="Amount",
        color="Type",
        title="Monthly Income vs Expense",
        labels={"Amount": "Amount ($)", "Month-Year": "Month", "Type": "Transaction Type"},
        barmode="group",
        color_discrete_map=color_map
    )

    fig_txn.update_layout(
        xaxis_title="Month",
        yaxis_title="Amount ($)",
        hovermode="x unified",
        height=400,
        legend_title="Type"
    )

    st.plotly_chart(fig_txn, use_container_width=True)
else:
    st.info("No transaction data available for trend analysis. Upload invoices with transaction types to see this chart.")

st.divider()

# === TOP KPIs ===
st.subheader("Key Metrics")

col1, col2, col3, col4 = st.columns(4)

# Get total stats and quality metrics
total_stats = db.get_total_stats(session)
quality = db.get_quality_metrics(session)

# Get all invoices for additional calculations
all_invoices = db.get_all_invoices(session, limit=10000)

if all_invoices:
    df_all = pd.DataFrame(
        all_invoices,
        columns=[
            "ID", "Invoice #", "Vendor", "Date", "Amount",
            "Category", "Source", "File", "Confidence", "Ingested", "Created By"
        ]
    )

    # Convert Decimal columns to float for pandas calculations
    df_all["Amount"] = df_all["Amount"].astype(float)
    df_all["Confidence"] = df_all["Confidence"].astype(float)

    # Calculate week's invoices
    now = datetime.now()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    df_all["Ingested"] = pd.to_datetime(df_all["Ingested"])
    week_count = len(df_all[df_all["Ingested"] > week_ago])
    month_amount = df_all[df_all["Ingested"] > month_ago]["Amount"].sum()

    with col1:
        st.metric(
            "Total Invoices",
            f"{total_stats['total_count']:,}",
            f"+{week_count} this week"
        )

    with col2:
        st.metric(
            "Total Spend",
            f"${total_stats['total_amount']:,.2f}",
            f"${month_amount:,.2f} this month"
        )

    with col3:
        avg_amount = df_all["Amount"].mean() if len(df_all) > 0 else 0
        std_amount = df_all["Amount"].std() if len(df_all) > 1 else 0
        st.metric(
            "Avg Invoice",
            f"${avg_amount:,.2f}",
            f"+/-${std_amount:,.2f}"
        )

    with col4:
        st.metric(
            "Data Quality",
            quality.get("verification_rate", "N/A"),
            f"{quality.get('total_invoices', 0)} invoices (30d)"
        )
else:
    st.info("No data yet. Upload invoices to see analytics.")
    session.close()
    st.stop()

st.divider()

# === CHARTS ===

# 1. Monthly Trend (Line Chart)
st.subheader("Monthly Spending Trend")

monthly_data = db.get_monthly_summary(session, months=12)
if monthly_data:
    df_monthly = pd.DataFrame(
        monthly_data,
        columns=["Year", "Month", "Total Amount", "Count", "Source"]
    )
    # Convert Decimal to float for plotly
    df_monthly["Total Amount"] = df_monthly["Total Amount"].astype(float)

    # Create month-year label for better display
    df_monthly["Month-Year"] = df_monthly.apply(
        lambda x: f"{int(x['Year'])}-{int(x['Month']):02d}", axis=1
    )

    # Pivot by source type for stacked view
    fig = px.bar(
        df_monthly,
        x="Month-Year",
        y="Total Amount",
        color="Source",
        title="Monthly Spending by Source Type",
        labels={"Total Amount": "Amount ($)", "Month-Year": "Month"},
        barmode="stack"
    )

    fig.update_layout(
        xaxis_title="Month",
        yaxis_title="Amount ($)",
        hovermode="x unified",
        height=400
    )

    st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("Not enough data for trend analysis")

st.divider()

# 2. Category Breakdown (Pie Chart) and Table
st.subheader("Spending by Category (Current Month)")

col_left, col_right = st.columns(2)

category_data = db.get_category_breakdown(session)

with col_left:
    if category_data:
        df_category = pd.DataFrame(
            category_data,
            columns=["Category", "Total Amount", "Count", "Avg Amount"]
        )
        # Convert Decimal to float
        df_category["Total Amount"] = df_category["Total Amount"].astype(float)
        df_category["Avg Amount"] = df_category["Avg Amount"].astype(float)

        fig_pie = go.Figure(data=[go.Pie(
            labels=df_category["Category"],
            values=df_category["Total Amount"],
            hovertemplate="<b>%{label}</b><br>Amount: $%{value:,.2f}<extra></extra>",
            textinfo="percent+label"
        )])

        fig_pie.update_layout(
            title="Percentage of Total Spend",
            height=400
        )
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("No category data for current month")

with col_right:
    if category_data:
        df_category_display = df_category.copy()
        df_category_display["Total Amount"] = df_category_display["Total Amount"].apply(lambda x: f"${x:,.2f}")
        df_category_display["Avg Amount"] = df_category_display["Avg Amount"].apply(lambda x: f"${x:,.2f}")
        st.dataframe(df_category_display, use_container_width=True, hide_index=True)
    else:
        st.info("No category data for current month")

st.divider()

# 3. Top Vendors (Bar Chart)
st.subheader("Top 15 Vendors")

vendor_data = db.get_vendor_breakdown(session, limit=15)
if vendor_data:
    df_vendor = pd.DataFrame(
        vendor_data,
        columns=["Vendor", "Total Amount", "Count", "Avg Amount", "Last Invoice"]
    )
    # Convert Decimal to float
    df_vendor["Total Amount"] = df_vendor["Total Amount"].astype(float)
    df_vendor["Avg Amount"] = df_vendor["Avg Amount"].astype(float)

    fig_bar = px.bar(
        df_vendor,
        x="Total Amount",
        y="Vendor",
        orientation="h",
        title="Top Vendors by Total Spend",
        color="Total Amount",
        color_continuous_scale="Viridis"
    )

    fig_bar.update_layout(
        height=500,
        yaxis={"categoryorder": "total ascending"}
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # Show table
    df_vendor_display = df_vendor.copy()
    df_vendor_display["Total Amount"] = df_vendor_display["Total Amount"].apply(lambda x: f"${x:,.2f}")
    df_vendor_display["Avg Amount"] = df_vendor_display["Avg Amount"].apply(lambda x: f"${x:,.2f}")
    st.dataframe(df_vendor_display, use_container_width=True, hide_index=True)
else:
    st.info("No vendor data yet")

st.divider()

# 4. Source Type Distribution (Donut Chart)
st.subheader("Invoice Source Distribution")

source_data = db.get_source_type_distribution(session)
if source_data:
    df_source = pd.DataFrame(
        source_data,
        columns=["Source Type", "Count", "Amount", "Percentage"]
    )
    # Convert Decimal to float
    df_source["Amount"] = df_source["Amount"].astype(float)

    col_a, col_b = st.columns(2)

    with col_a:
        fig_donut = go.Figure(data=[go.Pie(
            labels=df_source["Source Type"],
            values=df_source["Count"],
            hole=0.4,
            hovertemplate="<b>%{label}</b><br>Invoices: %{value}<br>Percentage: %{customdata}%<extra></extra>",
            customdata=df_source["Percentage"]
        )])

        fig_donut.update_layout(
            title="Invoice Count by Source",
            height=350
        )
        st.plotly_chart(fig_donut, use_container_width=True)

    with col_b:
        st.write("**Source Breakdown**")
        df_source_display = df_source.copy()
        df_source_display["Amount"] = df_source_display["Amount"].apply(lambda x: f"${x:,.2f}" if x else "$0.00")
        df_source_display["Percentage"] = df_source_display["Percentage"].apply(lambda x: f"{x}%" if x else "0%")
        st.dataframe(df_source_display, use_container_width=True, hide_index=True)
else:
    st.info("No source data yet")

st.divider()

# 5. Daily Trend (Area Chart)
st.subheader("Daily Spending Trend (Last 30 Days)")

daily_data = db.get_daily_trend(session, days=30)
if daily_data:
    df_daily = pd.DataFrame(
        daily_data,
        columns=["Date", "Daily Total", "Invoice Count"]
    )
    # Convert Decimal to float
    df_daily["Daily Total"] = df_daily["Daily Total"].astype(float)

    fig_area = go.Figure()
    fig_area.add_trace(go.Scatter(
        x=df_daily["Date"],
        y=df_daily["Daily Total"],
        fill="tozeroy",
        name="Daily Spend",
        mode="lines",
        line=dict(color="rgb(0, 100, 180)")
    ))

    fig_area.update_layout(
        title="Daily Spending Pattern",
        xaxis_title="Date",
        yaxis_title="Amount ($)",
        hovermode="x unified",
        height=350
    )

    st.plotly_chart(fig_area, use_container_width=True)
else:
    st.info("Not enough daily data")

st.divider()

# === DATA TABLE ===
st.subheader("Recent Invoices")

show_all = st.checkbox("Show all invoices", value=False)

if show_all:
    st.dataframe(df_all, use_container_width=True, hide_index=True)
else:
    st.dataframe(df_all.head(20), use_container_width=True, hide_index=True)

# Export option
st.download_button(
    label="Export to CSV",
    data=df_all.to_csv(index=False),
    file_name=f"invoices_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    mime="text/csv"
)

# Cleanup
session.close()

st.divider()
st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
