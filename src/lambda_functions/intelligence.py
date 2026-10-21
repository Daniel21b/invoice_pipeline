"""Invoice domain contract: missing, uncertain and model-derived values require review."""

from datetime import date
from decimal import Decimal, InvalidOperation

FIELDS = ("invoice_number", "vendor_name", "invoice_date", "amount")
TYPES = {
    "INVOICE_RECEIPT_ID": "invoice_number",
    "VENDOR_NAME": "vendor_name",
    "INVOICE_RECEIPT_DATE": "invoice_date",
    "TOTAL": "amount",
}


def normalize(values):
    result = {}
    for field in FIELDS:
        value = values.get(field)
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ValueError(f"Missing or invalid {field}")
        value = str(value).strip()
        if not value or len(value) > (50 if field == "invoice_number" else 255):
            raise ValueError(f"Missing or invalid {field}")
        result[field] = value
    result["invoice_date"] = date.fromisoformat(result["invoice_date"]).isoformat()
    try:
        amount = Decimal(result["amount"])
        if not amount.is_finite() or amount < 0 or amount > Decimal("99999999.99"):
            raise ValueError("Invalid amount")
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueError("Amount must have at most two decimal places")
        result["amount"] = str(amount.quantize(Decimal("0.01")))
    except InvalidOperation as exc:
        raise ValueError("Invalid amount") from exc
    return result


def extract(response):
    docs = response.get("ExpenseDocuments", [])
    if len(docs) != 1:
        raise ValueError("Upload exactly one invoice per document")
    values, confidence = {}, {}
    for item in docs[0].get("SummaryFields", []):
        field = TYPES.get(item.get("Type", {}).get("Text"))
        detection = item.get("ValueDetection", {})
        if field and detection.get("Confidence", 0) > confidence.get(field, -1):
            values[field] = detection.get("Text", "")
            confidence[field] = detection.get("Confidence", 0)
    text = "\n".join(
        b.get("Text", "")
        for b in docs[0].get("Blocks", [])
        if b.get("BlockType") == "LINE"
    )
    return {
        "values": values,
        "confidence": confidence,
        "text": text[:40000],
        "llm_fields": [],
    }


def uncertain(record, threshold=90):
    return [
        f
        for f in FIELDS
        if not record["values"].get(f) or record["confidence"].get(f, 0) < threshold
    ]


def merge_suggestions(record, suggestions):
    allowed = uncertain(record)
    if not isinstance(suggestions, dict) or set(suggestions) - set(allowed):
        raise ValueError("Unexpected model fields")
    for field, value in suggestions.items():
        if value is not None:
            if not isinstance(value, str) or len(value) > 255:
                raise ValueError("Invalid model value")
            record["values"][field] = value
            record["llm_fields"].append(field)
    return record


def can_persist(record):
    if uncertain(record) or record["llm_fields"]:
        return False
    try:
        normalize(record["values"])
        return True
    except ValueError:
        return False


def persist(connection, record, reviewer=None):
    if not reviewer and not can_persist(record):
        raise ValueError("Review required before database persistence")
    values = normalize(record["values"])
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO invoices
                (invoice_number,vendor_name,invoice_date,amount,source_type,source_file,
                 extraction_confidence,created_by,extraction_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (extraction_id) DO NOTHING""",
                (
                    values["invoice_number"],
                    values["vendor_name"],
                    values["invoice_date"],
                    values["amount"],
                    "pdf_scan",
                    record["key"],
                    min(record["confidence"].values(), default=0),
                    reviewer or "workflow",
                    record["id"],
                ),
            )
