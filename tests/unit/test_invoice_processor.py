"""
Unit tests for invoice_processor Lambda handler - Phase 3.

Tests cover:
- Valid PDF/JPG/PNG event processing
- Invalid file format handling
- File size validation
- Malformed event handling
- Response format verification
- Textract integration (mocked)
"""

import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# Add src to path for imports
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "lambda_functions")
)

from invoice_processor import _process_record, _response, lambda_handler


def create_s3_event(
    bucket: str, key: str, size: int = 1024, event_name: str = "ObjectCreated:Put"
) -> dict:
    """Helper: create fake S3 event."""
    return {
        "Records": [
            {
                "eventName": event_name,
                "eventTime": "2026-01-12T02:00:00Z",
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key, "size": size},
                },
            }
        ]
    }


class TestValidEvents:
    """Test successful event processing."""

    def setup_method(self) -> None:
        """Set up test environment variables."""
        os.environ["INVOICE_BUCKET"] = "test-bucket"
        os.environ["ALLOWED_FORMATS"] = "pdf,jpg,jpeg,png"
        os.environ["TEXTRACT_ENABLED"] = "false"  # Disable for unit tests

    def test_valid_pdf_event(self) -> None:
        """Should accept valid PDF."""
        event = create_s3_event("test-bucket", "invoices/test.pdf")

        response = lambda_handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["results"][0]["success"] is True
        assert body["results"][0]["key"] == "invoices/test.pdf"
        assert body["results"][0]["format"] == "pdf"

    def test_valid_jpg_event(self) -> None:
        """Should accept valid JPG."""
        event = create_s3_event("test-bucket", "invoices/receipt.jpg")

        response = lambda_handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["results"][0]["success"] is True
        assert body["results"][0]["format"] == "jpg"

    def test_url_encoded_key(self) -> None:
        """Should handle URL-encoded file names."""
        event = create_s3_event("test-bucket", "invoices/my%20invoice%20file.pdf")

        response = lambda_handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["results"][0]["key"] == "invoices/my invoice file.pdf"

    def test_returns_idempotency_key(self) -> None:
        """Should include idempotency key in response."""
        event = create_s3_event("test-bucket", "invoices/test.pdf", size=2048)

        response = lambda_handler(event, None)

        body = json.loads(response["body"])
        assert "idempotencyKey" in body["results"][0]
        assert "test.pdf:2048:" in body["results"][0]["idempotencyKey"]


class TestInvalidFiles:
    """Test file validation."""

    def setup_method(self) -> None:
        """Set up test environment variables."""
        os.environ["INVOICE_BUCKET"] = "test-bucket"
        os.environ["ALLOWED_FORMATS"] = "pdf,jpg,jpeg,png"
        os.environ["TEXTRACT_ENABLED"] = "false"  # Disable for unit tests

    def test_invalid_format_txt(self) -> None:
        """Should reject .txt files."""
        event = create_s3_event("test-bucket", "invoices/document.txt")

        response = lambda_handler(event, None)

        assert response["statusCode"] == 200  # Overall request succeeds
        body = json.loads(response["body"])
        assert body["results"][0]["success"] is False
        assert "Invalid file format" in body["results"][0]["error"]

    def test_valid_format_png(self) -> None:
        """Should accept .png files (Phase 3 update)."""
        event = create_s3_event("test-bucket", "invoices/image.png")

        response = lambda_handler(event, None)

        body = json.loads(response["body"])
        assert body["results"][0]["success"] is True
        assert body["results"][0]["format"] == "png"

    def test_invalid_format_gif(self) -> None:
        """Should reject .gif files."""
        event = create_s3_event("test-bucket", "invoices/image.gif")

        response = lambda_handler(event, None)

        body = json.loads(response["body"])
        assert body["results"][0]["success"] is False

    def test_file_too_large(self) -> None:
        """Should reject files > 500MB."""
        large_size = 600 * 1024 * 1024  # 600 MB
        event = create_s3_event("test-bucket", "invoices/big.pdf", size=large_size)

        response = lambda_handler(event, None)

        body = json.loads(response["body"])
        assert body["results"][0]["success"] is False
        assert "too large" in body["results"][0]["error"].lower()

    def test_file_at_size_limit(self) -> None:
        """Should accept file at exactly 500MB."""
        limit_size = 500 * 1024 * 1024  # Exactly 500 MB
        event = create_s3_event("test-bucket", "invoices/limit.pdf", size=limit_size)

        response = lambda_handler(event, None)

        body = json.loads(response["body"])
        assert body["results"][0]["success"] is True

    def test_wrong_bucket(self) -> None:
        """Should reject events from wrong bucket."""
        os.environ["INVOICE_BUCKET"] = "correct-bucket"
        event = create_s3_event("wrong-bucket", "invoices/test.pdf")

        response = lambda_handler(event, None)

        body = json.loads(response["body"])
        assert body["results"][0]["success"] is False
        assert "Unexpected bucket" in body["results"][0]["error"]


class TestErrorHandling:
    """Test error cases."""

    def setup_method(self) -> None:
        """Set up test environment variables."""
        os.environ["INVOICE_BUCKET"] = "test-bucket"
        os.environ["ALLOWED_FORMATS"] = "pdf,jpg,jpeg,png"
        os.environ["TEXTRACT_ENABLED"] = "false"

    def test_empty_records(self) -> None:
        """Should handle empty Records array."""
        event = {"Records": []}

        response = lambda_handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "No records found" in body["error"]

    def test_missing_records_key(self) -> None:
        """Should handle missing Records key."""
        event = {}

        response = lambda_handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "No records found" in body["error"]

    def test_malformed_s3_data(self) -> None:
        """Should handle malformed S3 data gracefully."""
        event = {"Records": [{"eventName": "ObjectCreated:Put"}]}  # Missing s3 key

        response = lambda_handler(event, None)

        # Should not crash, but record should fail
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["results"][0]["success"] is False

    def test_no_extension_in_key(self) -> None:
        """Should handle files without extension."""
        event = create_s3_event("test-bucket", "invoices/noextension")

        response = lambda_handler(event, None)

        body = json.loads(response["body"])
        assert body["results"][0]["success"] is False
        assert "Invalid file format" in body["results"][0]["error"]


class TestMultipleRecords:
    """Test handling of multiple records in single event."""

    def setup_method(self) -> None:
        """Set up test environment variables."""
        os.environ["INVOICE_BUCKET"] = "test-bucket"
        os.environ["ALLOWED_FORMATS"] = "pdf,jpg,jpeg,png"
        os.environ["TEXTRACT_ENABLED"] = "false"

    def test_multiple_valid_records(self) -> None:
        """Should process multiple records."""
        event = {
            "Records": [
                {
                    "eventName": "ObjectCreated:Put",
                    "eventTime": "2026-01-12T02:00:00Z",
                    "s3": {
                        "bucket": {"name": "test-bucket"},
                        "object": {"key": "invoices/file1.pdf", "size": 1024},
                    },
                },
                {
                    "eventName": "ObjectCreated:Put",
                    "eventTime": "2026-01-12T02:01:00Z",
                    "s3": {
                        "bucket": {"name": "test-bucket"},
                        "object": {"key": "invoices/file2.jpg", "size": 2048},
                    },
                },
            ]
        }

        response = lambda_handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert len(body["results"]) == 2
        assert body["results"][0]["success"] is True
        assert body["results"][1]["success"] is True

    def test_mixed_valid_invalid_records(self) -> None:
        """Should process mix of valid and invalid records."""
        event = {
            "Records": [
                {
                    "eventName": "ObjectCreated:Put",
                    "eventTime": "2026-01-12T02:00:00Z",
                    "s3": {
                        "bucket": {"name": "test-bucket"},
                        "object": {"key": "invoices/valid.pdf", "size": 1024},
                    },
                },
                {
                    "eventName": "ObjectCreated:Put",
                    "eventTime": "2026-01-12T02:01:00Z",
                    "s3": {
                        "bucket": {"name": "test-bucket"},
                        "object": {"key": "invoices/invalid.txt", "size": 512},
                    },
                },
            ]
        }

        response = lambda_handler(event, None)

        body = json.loads(response["body"])
        assert body["results"][0]["success"] is True
        assert body["results"][1]["success"] is False


class TestResponseFormat:
    """Test response helper function."""

    def test_response_200(self) -> None:
        """Should format 200 response."""
        resp = _response(200, {"key": "test.pdf"})

        assert resp["statusCode"] == 200
        assert resp["headers"]["Content-Type"] == "application/json"
        body = json.loads(resp["body"])
        assert body["key"] == "test.pdf"

    def test_response_400(self) -> None:
        """Should format error response."""
        resp = _response(400, {"error": "Invalid"})

        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "Invalid"

    def test_response_500(self) -> None:
        """Should format server error response."""
        resp = _response(500, {"error": "Internal error"})

        assert resp["statusCode"] == 500


class TestProcessRecord:
    """Test _process_record helper function."""

    def setup_method(self) -> None:
        """Set up test environment variables."""
        os.environ["INVOICE_BUCKET"] = "test-bucket"
        os.environ["ALLOWED_FORMATS"] = "pdf,jpg,jpeg,png"
        os.environ["TEXTRACT_ENABLED"] = "false"

    def test_process_valid_record(self) -> None:
        """Should process valid record."""
        record = {
            "eventName": "ObjectCreated:Put",
            "eventTime": "2026-01-12T02:00:00Z",
            "s3": {
                "bucket": {"name": "test-bucket"},
                "object": {"key": "invoices/test.pdf", "size": 1024},
            },
        }

        result = _process_record(record)

        assert result["success"] is True
        assert result["bucket"] == "test-bucket"
        assert result["key"] == "invoices/test.pdf"
        assert result["size"] == 1024
        assert result["format"] == "pdf"
        assert result["status"] == "queued_for_textract"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
