"""Review extracted candidates before any invoice row is inserted."""

import json
import sys
from pathlib import Path
import boto3
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lambda_functions"))
from database.database import get_db_manager
from src.web_portal.authentication import require_reviewer, logout
from intelligence import FIELDS, persist

st.set_page_config(page_title="Invoice extraction review", layout="wide")
require_reviewer(st)
with st.sidebar:
    st.caption(st.session_state['email'])
    if st.button('Sign out'):
        logout(st)
st.title("Review invoice extractions")
bucket = st.secrets["aws"]["s3_bucket"]
s3 = boto3.client("s3", region_name=st.secrets["aws"].get("region", "us-east-1"))
keys = [
    obj["Key"]
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix="pending-review/"
    )
    for obj in page.get("Contents", [])
    if obj["Key"].endswith(".json")
]
if not keys:
    st.info("No invoices awaiting review.")
    st.stop()
key = st.selectbox("Pending extraction", keys)
record = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
source = {"Bucket": bucket, "Key": record["key"]}
if record.get("version"):
    source["VersionId"] = record["version"]
st.link_button(
    "Open original invoice",
    s3.generate_presigned_url("get_object", Params=source, ExpiresIn=300),
)
st.write("OCR confidence", record["confidence"])
st.write("Model-suggested fields", record["llm_fields"])
with st.form(key):
    values = {
        f: st.text_input(f.replace("_", " ").title(), str(record["values"].get(f, "")))
        for f in FIELDS
    }
    confirmed = st.checkbox("I checked every field against the original invoice.")
    submitted = st.form_submit_button("Approve and save")
if submitted:
    if not confirmed:
        st.error("Verify the fields before approval.")
    else:
        db = get_db_manager()
        connection = db.engine.raw_connection()
        try:
            persist(
                connection.driver_connection,
                {**record, "values": values},
                reviewer=st.session_state["email"],
            )
            s3.delete_object(Bucket=bucket, Key=key)
            st.success("Verified invoice saved.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
        finally:
            connection.close()
