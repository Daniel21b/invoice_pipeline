"""
Invoice Processor Lambda Handler - Phase 3

Handles S3 ObjectCreated events for invoice processing.
Phase 2: Validates uploaded files and logs to CloudWatch.
Phase 3: Calls AWS Textract for OCR and parses invoice data.
"""

import json
import logging
import os
import re
import boto3
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import unquote_plus

# Database imports (psycopg2 from Lambda layer)
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

# Configure logging for CloudWatch
logger = logging.getLogger()
log_level = os.environ.get("LOG_LEVEL", "INFO")
logger.setLevel(getattr(logging, log_level))

# Environment variable defaults
DEFAULT_ALLOWED_FORMATS = "pdf,jpg,jpeg,png"

# Lazy initialization of AWS clients (for testing support)
_textract_client = None
_s3_client = None


def _get_textract_client():
    """Get Textract client (lazy initialization)."""
    global _textract_client
    if _textract_client is None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        _textract_client = boto3.client("textract", region_name=region)
    return _textract_client


def _get_s3_client():
    """Get S3 client (lazy initialization)."""
    global _s3_client
    if _s3_client is None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        _s3_client = boto3.client("s3", region_name=region)
    return _s3_client


def _get_invoice_bucket() -> Optional[str]:
    """Get invoice bucket from environment."""
    return os.environ.get("INVOICE_BUCKET")


def _get_allowed_formats() -> List[str]:
    """Get allowed formats from environment."""
    return os.environ.get("ALLOWED_FORMATS", DEFAULT_ALLOWED_FORMATS).split(",")


def _is_textract_enabled() -> bool:
    """Check if Textract processing is enabled."""
    return os.environ.get("TEXTRACT_ENABLED", "true").lower() == "true"


def _get_confidence_threshold() -> float:
    """Get minimum confidence threshold for Textract results."""
    return float(os.environ.get("TEXTRACT_CONFIDENCE_THRESHOLD", "70"))


def _get_s3_object_metadata(bucket: str, key: str) -> Dict[str, str]:
    """
    Get metadata from S3 object (for transaction-type classification).

    Args:
        bucket: S3 bucket name
        key: S3 object key

    Returns:
        Dictionary of metadata key-value pairs
    """
    try:
        s3_client = _get_s3_client()
        response = s3_client.head_object(Bucket=bucket, Key=key)
        metadata = response.get("Metadata", {})
        logger.info(f"S3 metadata for {key}: {metadata}")
        return metadata
    except Exception as e:
        logger.warning(f"Failed to get S3 metadata: {e}")
        return {}


def _get_db_connection():
    """Get database connection from environment variables."""
    if not DB_AVAILABLE:
        logger.warning("psycopg2 not available - database saving disabled")
        return None

    host = os.environ.get("RDS_HOST")
    if not host:
        logger.warning("RDS_HOST not configured - database saving disabled")
        return None

    try:
        conn = psycopg2.connect(
            host=host,
            port=os.environ.get("RDS_PORT", "5432"),
            user=os.environ.get("RDS_USER", "postgres"),
            password=os.environ.get("RDS_PASSWORD", ""),
            database=os.environ.get("RDS_DB", "invoices"),
            connect_timeout=10,
        )
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None


def _save_invoice_to_db(invoice_data: Dict[str, Any]) -> bool:
    """
    Save extracted invoice data to PostgreSQL database.

    Args:
        invoice_data: Dictionary with invoice fields
                     Now includes optional 'transaction_type' (INCOME/EXPENSE)

    Returns:
        True if saved successfully, False otherwise
    """
    conn = _get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()

        # Parse the date string to a proper date
        invoice_date = invoice_data.get("invoice_date", datetime.now().strftime("%Y-%m-%d"))

        # Get transaction_type (may be None if not provided)
        transaction_type = invoice_data.get("transaction_type")

        # Insert invoice record
        cursor.execute("""
            INSERT INTO invoices (
                invoice_number, vendor_name, invoice_date, amount,
                category, source_type, source_file, extraction_confidence,
                created_by, notes, transaction_type
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING id
        """, (
            invoice_data.get("invoice_number", ""),
            invoice_data.get("vendor_name", "Unknown"),
            invoice_date,
            invoice_data.get("amount", 0.0),
            invoice_data.get("category", "Other"),
            invoice_data.get("source_type", "pdf_scan"),
            invoice_data.get("source_file", ""),
            invoice_data.get("extraction_confidence", 0.0),
            "lambda_processor",
            "Auto-extracted via Textract",
            transaction_type
        ))

        invoice_id = cursor.fetchone()[0]
        conn.commit()

        logger.info(f"Saved invoice to database with ID: {invoice_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to save invoice to database: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Process S3 ObjectCreated event notification.

    Args:
        event: S3 notification event containing Records array
        context: Lambda context object with runtime information

    Returns:
        dict with statusCode, body (JSON string), and headers

    CloudWatch Logs:
        All events logged to /aws/lambda/InvoiceProcessor

    Raises:
        Nothing - all exceptions caught and returned as JSON response
    """
    try:
        # Log incoming event
        logger.info(f"Received event: {json.dumps(event)}")

        # Validate event structure
        if "Records" not in event or not event["Records"]:
            msg = "No records found in event"
            logger.error(msg)
            return _response(400, {"error": msg})

        # Process each record (typically one per event)
        results = []
        for record in event["Records"]:
            result = _process_record(record)
            results.append(result)

        # Return aggregated results
        success_count = sum(1 for r in results if r.get("success", False))
        logger.info(f"Processed {len(results)} records, {success_count} successful")

        return _response(
            200,
            {
                "message": f"Processed {len(results)} records",
                "results": results,
                "processedAt": datetime.now(timezone.utc).isoformat(),
            },
        )

    except KeyError as e:
        msg = f"Malformed event: missing {e!s}"
        logger.error(msg, exc_info=True)
        return _response(400, {"error": msg})

    except Exception as e:
        msg = f"Unhandled exception: {e!s}"
        logger.error(msg, exc_info=True)
        return _response(500, {"error": msg})


def _process_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a single S3 event record.

    Args:
        record: Single record from S3 event Records array

    Returns:
        dict with processing result for this record
    """
    try:
        # Parse S3 event data
        s3_data = record.get("s3", {})
        bucket = s3_data.get("bucket", {}).get("name", "")
        key = unquote_plus(s3_data.get("object", {}).get("key", ""))
        size = s3_data.get("object", {}).get("size", 0)
        event_name = record.get("eventName", "")
        event_time = record.get("eventTime", "")

        logger.info(f"Processing {event_name} for s3://{bucket}/{key} ({size} bytes)")

        # Get environment configuration
        invoice_bucket = _get_invoice_bucket()
        allowed_formats = _get_allowed_formats()

        # Validate bucket match
        if invoice_bucket and bucket != invoice_bucket:
            msg = f"Unexpected bucket: {bucket} (expected {invoice_bucket})"
            logger.warning(msg)
            return {"success": False, "error": msg, "key": key}

        # Extract and validate file extension
        file_ext = key.split(".")[-1].lower() if "." in key else ""

        if file_ext not in allowed_formats:
            msg = f"Invalid file format: {file_ext}. Allowed: {allowed_formats}"
            logger.warning(msg)
            return {"success": False, "error": msg, "key": key}

        # Validate file size (Textract max is 500MB)
        max_size = 500 * 1024 * 1024  # 500 MB
        if size > max_size:
            msg = f"File too large: {size} bytes > {max_size} bytes"
            logger.warning(msg)
            return {"success": False, "error": msg, "size": size, "key": key}

        # Build idempotency key from object key + size + event time
        idempotency_key = f"{key}:{size}:{event_time}"

        # Log successful validation
        logger.info(f"Successfully validated: {key} (idempotency: {idempotency_key})")

        # Get transaction_type from S3 object metadata (if provided during upload)
        s3_metadata = _get_s3_object_metadata(bucket, key)
        transaction_type = s3_metadata.get("transaction-type") or s3_metadata.get("transaction_type")
        if transaction_type:
            transaction_type = transaction_type.upper()
            if transaction_type not in ("INCOME", "EXPENSE"):
                logger.warning(f"Invalid transaction_type in metadata: {transaction_type}")
                transaction_type = None
            else:
                logger.info(f"Transaction type from S3 metadata: {transaction_type}")

        # Phase 3: Call Textract if enabled
        invoice_data = None
        textract_result = None

        if _is_textract_enabled():
            logger.info(f"Calling Textract for s3://{bucket}/{key}")
            textract_result = _call_textract(bucket, key)

            if textract_result.get("success"):
                # Parse the Textract response into structured invoice data
                invoice_data = _parse_textract_response(textract_result.get("response", {}))
                invoice_data["source_file"] = key
                invoice_data["source_type"] = "pdf_scan"
                invoice_data["extraction_confidence"] = textract_result.get("avg_confidence", 0)
                invoice_data["transaction_type"] = transaction_type  # Add classification from metadata

                logger.info(f"Extracted invoice data: {json.dumps(invoice_data, default=str)}")

                # Save to database
                db_saved = _save_invoice_to_db(invoice_data)
                if db_saved:
                    logger.info("Invoice saved to database successfully")
                else:
                    logger.warning("Failed to save invoice to database")
            else:
                logger.warning(f"Textract failed: {textract_result.get('error')}")

        # Return success result
        result = {
            "success": True,
            "bucket": bucket,
            "key": key,
            "size": size,
            "format": file_ext,
            "eventName": event_name,
            "eventTime": event_time,
            "idempotencyKey": idempotency_key,
            "status": "processed" if invoice_data else "queued_for_textract",
        }

        if invoice_data:
            result["invoiceData"] = invoice_data
            result["textractConfidence"] = textract_result.get("avg_confidence", 0)

        return result

    except Exception as e:
        msg = f"Error processing record: {e!s}"
        logger.error(msg, exc_info=True)
        return {"success": False, "error": msg}


def _call_textract(bucket: str, key: str) -> Dict[str, Any]:
    """
    Call AWS Textract to extract text from document.

    Args:
        bucket: S3 bucket name
        key: S3 object key

    Returns:
        dict with success status, response data, and average confidence
    """
    try:
        logger.info(f"Calling Textract DetectDocumentText for s3://{bucket}/{key}")

        textract_client = _get_textract_client()
        response = textract_client.detect_document_text(
            Document={
                "S3Object": {
                    "Bucket": bucket,
                    "Name": key
                }
            }
        )

        # Calculate average confidence from LINE blocks
        blocks = response.get("Blocks", [])
        line_blocks = [b for b in blocks if b.get("BlockType") == "LINE"]

        avg_confidence = 0.0
        if line_blocks:
            confidences = [b.get("Confidence", 0) for b in line_blocks]
            avg_confidence = sum(confidences) / len(confidences)

        logger.info(f"Textract returned {len(blocks)} blocks, {len(line_blocks)} lines, avg confidence: {avg_confidence:.2f}%")

        return {
            "success": True,
            "response": response,
            "block_count": len(blocks),
            "line_count": len(line_blocks),
            "avg_confidence": avg_confidence,
        }

    except Exception as e:
        logger.error(f"Textract error: {e!s}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
        }


def _parse_textract_response(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse Textract JSON response into structured invoice data.

    Textract returns:
    {
        'Blocks': [
            {'BlockType': 'LINE', 'Text': '...', 'Confidence': 99.5},
            {'BlockType': 'WORD', 'Text': '...'},
            ...
        ]
    }

    Args:
        response: Textract API response

    Returns:
        dict with extracted invoice fields
    """
    blocks = response.get("Blocks", [])

    # Extract all LINE text blocks
    text_blocks = [b.get("Text", "") for b in blocks if b.get("BlockType") == "LINE"]
    full_text = " ".join(text_blocks)

    logger.debug(f"Full extracted text: {full_text[:500]}...")

    # Extract fields using regex patterns
    invoice_data = {
        "invoice_number": _extract_invoice_number(full_text),
        "vendor_name": _extract_vendor_name(full_text),
        "invoice_date": _extract_date(full_text),
        "amount": _extract_amount(full_text),
        "category": "Other",  # Default category
    }

    return invoice_data


def _extract_invoice_number(text: str) -> str:
    """
    Extract invoice number from text.

    Looks for patterns like:
    - Invoice #12345
    - Invoice Number: 12345
    - INV-12345
    - Invoice: ABC123
    """
    patterns = [
        r"Invoice\s*#?\s*:?\s*([A-Z0-9][\w-]*)",
        r"INV[-#]?\s*([A-Z0-9][\w-]*)",
        r"Invoice\s+Number\s*:?\s*([A-Z0-9][\w-]*)",
        r"Invoice\s+No\.?\s*:?\s*([A-Z0-9][\w-]*)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return ""


def _extract_vendor_name(text: str) -> str:
    """
    Extract vendor name from text.

    Looks for patterns like:
    - Vendor: Acme Corp
    - From: Acme Corp
    - Bill From: Acme Corp
    - Company Name
    """
    patterns = [
        r"(?:Vendor|From|Bill\s+From|Supplier)\s*:?\s*([A-Za-z][A-Za-z0-9\s&.,'-]+?)(?:\n|$|Invoice)",
        r"(?:Company|Business)\s*:?\s*([A-Za-z][A-Za-z0-9\s&.,'-]+?)(?:\n|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            vendor = match.group(1).strip()
            # Clean up the vendor name
            vendor = re.sub(r"\s+", " ", vendor)
            if len(vendor) > 3:  # Minimum reasonable vendor name
                return vendor[:255]  # Limit to DB column size

    return "Unknown Vendor"


def _extract_date(text: str) -> str:
    """
    Extract invoice date from text.

    Looks for common date formats:
    - MM/DD/YYYY, DD/MM/YYYY
    - YYYY-MM-DD
    - Month DD, YYYY
    """
    date_patterns = [
        # MM/DD/YYYY or DD/MM/YYYY
        r"(?:Date|Invoice\s+Date|Dated?)\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
        # YYYY-MM-DD (ISO format)
        r"(?:Date|Invoice\s+Date|Dated?)\s*:?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
        # Month DD, YYYY
        r"(?:Date|Invoice\s+Date|Dated?)\s*:?\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})",
        # Standalone date patterns (fallback)
        r"(\d{1,2}[-/]\d{1,2}[-/]\d{4})",
        r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
    ]

    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # Fallback to today's date
    return datetime.now().strftime("%Y-%m-%d")


def _extract_amount(text: str) -> float:
    """
    Extract total amount from text.

    Looks for patterns like:
    - Total: $1,234.56
    - Amount Due: $1234.56
    - Grand Total: 1,234.56
    """
    amount_patterns = [
        r"(?:Total|Amount\s+Due|Grand\s+Total|Balance\s+Due|Total\s+Amount)\s*:?\s*\$?\s*([\d,]+\.?\d*)",
        r"(?:Total|Due)\s*:?\s*\$\s*([\d,]+\.?\d*)",
        # Standalone currency amounts (last resort)
        r"\$\s*([\d,]+\.\d{2})",
    ]

    for pattern in amount_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(1).replace(",", "")
            try:
                return float(amount_str)
            except ValueError:
                continue

    return 0.0


def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate Lambda response in standard format.

    Args:
        status_code: HTTP status code (200, 400, 500, etc)
        body: Response body as dictionary

    Returns:
        Properly formatted Lambda response with headers
    """
    return {
        "statusCode": status_code,
        "body": json.dumps(body, default=str),
        "headers": {"Content-Type": "application/json"},
    }
