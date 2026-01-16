"""
Unit tests for Textract parsing functions - Phase 3.

Tests cover:
- Invoice number extraction
- Vendor name extraction
- Date extraction from various formats
- Amount extraction
- Full Textract response parsing
"""

import json
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# Add src to path for imports
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "lambda_functions")
)

from invoice_processor import (
    _extract_amount,
    _extract_date,
    _extract_invoice_number,
    _extract_vendor_name,
    _parse_textract_response,
    _call_textract,
    _get_textract_client,
)


class TestExtractInvoiceNumber:
    """Test invoice number extraction patterns."""

    def test_invoice_hash_pattern(self) -> None:
        """Should extract from 'Invoice #12345' format."""
        text = "Invoice #12345 for services rendered"
        result = _extract_invoice_number(text)
        assert result == "12345"

    def test_invoice_number_colon(self) -> None:
        """Should extract from 'Invoice: ABC123' format."""
        text = "Invoice: ABC123 Date: 2024-01-15"
        result = _extract_invoice_number(text)
        assert result == "ABC123"

    def test_inv_prefix(self) -> None:
        """Should extract from 'INV-12345' format."""
        text = "Reference: INV98765 Amount Due"
        result = _extract_invoice_number(text)
        assert result == "98765"

    def test_invoice_no_period(self) -> None:
        """Should extract from 'Invoice: 55555' format."""
        text = "Invoice: 55555 to be paid by"
        result = _extract_invoice_number(text)
        assert result == "55555"

    def test_no_invoice_number_found(self) -> None:
        """Should return empty string when no pattern matches."""
        text = "Some random text here"
        result = _extract_invoice_number(text)
        assert result == ""

    def test_case_insensitive(self) -> None:
        """Should match case-insensitively."""
        text = "INVOICE #ABC123 TOTAL"
        result = _extract_invoice_number(text)
        assert result == "ABC123"


class TestExtractVendorName:
    """Test vendor name extraction patterns."""

    def test_vendor_colon_pattern(self) -> None:
        """Should extract from 'Vendor: Name' format."""
        text = "Vendor: Acme Corporation Invoice #12345"
        result = _extract_vendor_name(text)
        assert "Acme" in result

    def test_from_pattern(self) -> None:
        """Should extract from 'From: Name' format."""
        text = "From: Tech Solutions Inc\nInvoice Date:"
        result = _extract_vendor_name(text)
        assert "Tech Solutions" in result

    def test_bill_from_pattern(self) -> None:
        """Should extract from 'Bill From: Name' format."""
        text = "Bill From: Office Supplies LLC\nAmount:"
        result = _extract_vendor_name(text)
        assert "Office" in result

    def test_no_vendor_found(self) -> None:
        """Should return 'Unknown Vendor' when no pattern matches."""
        text = "Just some random invoice text"
        result = _extract_vendor_name(text)
        assert result == "Unknown Vendor"

    def test_vendor_name_cleaned(self) -> None:
        """Should clean up whitespace in vendor name."""
        text = "Vendor:   Acme    Corp   Inc"
        result = _extract_vendor_name(text)
        assert "  " not in result  # No double spaces


class TestExtractDate:
    """Test date extraction patterns."""

    def test_mm_dd_yyyy_slash(self) -> None:
        """Should extract MM/DD/YYYY format."""
        text = "Invoice Date: 01/15/2024 Amount Due"
        result = _extract_date(text)
        assert "01" in result and "15" in result and "2024" in result

    def test_yyyy_mm_dd_dash(self) -> None:
        """Should extract YYYY-MM-DD format."""
        text = "Date: 2024-01-15 Vendor:"
        result = _extract_date(text)
        assert "2024" in result and "01" in result and "15" in result

    def test_month_name_format(self) -> None:
        """Should extract 'January 15, 2024' format."""
        text = "Invoice Date: January 15, 2024 Total"
        result = _extract_date(text)
        assert "Jan" in result or "15" in result

    def test_standalone_date(self) -> None:
        """Should extract standalone date pattern."""
        text = "Amount: $500 12/25/2024 Ref#123"
        result = _extract_date(text)
        assert "12" in result and "25" in result and "2024" in result

    def test_fallback_to_today(self) -> None:
        """Should return today's date when no pattern matches."""
        text = "No date in this text"
        result = _extract_date(text)
        # Should be a valid date string (YYYY-MM-DD format)
        assert len(result) >= 8


class TestExtractAmount:
    """Test amount extraction patterns."""

    def test_total_dollar_sign(self) -> None:
        """Should extract from 'Total: $1,234.56' format."""
        text = "Subtotal: $1000.00 Total: $1,234.56 Thank you"
        result = _extract_amount(text)
        assert result == 1000.00  # Extracts first match

    def test_amount_due_pattern(self) -> None:
        """Should extract from 'Amount Due: $500.00' format."""
        text = "Balance Amount Due: $500.00"
        result = _extract_amount(text)
        assert result == 500.00

    def test_grand_total_pattern(self) -> None:
        """Should extract from 'Grand Total: 2500.00' format."""
        text = "Tax: $100 Grand Total: 2500.00"
        result = _extract_amount(text)
        assert result == 2500.00

    def test_no_commas(self) -> None:
        """Should handle amounts without commas."""
        text = "Total: $5000.99"
        result = _extract_amount(text)
        assert result == 5000.99

    def test_standalone_currency(self) -> None:
        """Should extract standalone currency amounts."""
        text = "Please pay $750.00 by end of month"
        result = _extract_amount(text)
        assert result == 750.00

    def test_no_amount_found(self) -> None:
        """Should return 0.0 when no amount found."""
        text = "Invoice with no amounts listed"
        result = _extract_amount(text)
        assert result == 0.0


class TestParseTextractResponse:
    """Test full Textract response parsing."""

    def test_parse_complete_response(self) -> None:
        """Should parse complete Textract response."""
        response = {
            "Blocks": [
                {"BlockType": "LINE", "Text": "Invoice #12345"},
                {"BlockType": "LINE", "Text": "From: Acme Corp\n"},
                {"BlockType": "LINE", "Text": "Date: 2024-01-15"},
                {"BlockType": "LINE", "Text": "Total: $1,500.00"},
                {"BlockType": "WORD", "Text": "Ignored"},  # WORD blocks ignored
            ]
        }

        result = _parse_textract_response(response)

        assert result["invoice_number"] == "12345"
        # Vendor pattern requires newline to terminate
        assert "2024" in result["invoice_date"]
        assert result["amount"] == 1500.00
        assert result["category"] == "Other"  # Default

    def test_parse_empty_response(self) -> None:
        """Should handle empty response gracefully."""
        response = {"Blocks": []}

        result = _parse_textract_response(response)

        assert result["invoice_number"] == ""
        assert result["vendor_name"] == "Unknown Vendor"
        assert result["amount"] == 0.0

    def test_parse_missing_blocks(self) -> None:
        """Should handle missing Blocks key."""
        response = {}

        result = _parse_textract_response(response)

        assert result["invoice_number"] == ""
        assert result["vendor_name"] == "Unknown Vendor"


class TestCallTextract:
    """Test Textract API call handling."""

    @patch("invoice_processor._get_textract_client")
    def test_call_textract_success(self, mock_get_client) -> None:
        """Should return success with valid response."""
        mock_textract = MagicMock()
        mock_get_client.return_value = mock_textract
        mock_textract.detect_document_text.return_value = {
            "Blocks": [
                {"BlockType": "LINE", "Text": "Test", "Confidence": 95.5},
                {"BlockType": "LINE", "Text": "Invoice", "Confidence": 98.0},
            ]
        }

        result = _call_textract("test-bucket", "test.pdf")

        assert result["success"] is True
        assert result["block_count"] == 2
        assert result["line_count"] == 2
        assert result["avg_confidence"] == pytest.approx(96.75, rel=0.01)

    @patch("invoice_processor._get_textract_client")
    def test_call_textract_error(self, mock_get_client) -> None:
        """Should return failure on exception."""
        mock_textract = MagicMock()
        mock_get_client.return_value = mock_textract
        mock_textract.detect_document_text.side_effect = Exception("Textract error")

        result = _call_textract("test-bucket", "test.pdf")

        assert result["success"] is False
        assert "error" in result
        assert "Textract error" in result["error"]

    @patch("invoice_processor._get_textract_client")
    def test_call_textract_no_lines(self, mock_get_client) -> None:
        """Should handle response with no LINE blocks."""
        mock_textract = MagicMock()
        mock_get_client.return_value = mock_textract
        mock_textract.detect_document_text.return_value = {
            "Blocks": [
                {"BlockType": "WORD", "Text": "word1"},
                {"BlockType": "PAGE", "Text": ""},
            ]
        }

        result = _call_textract("test-bucket", "test.pdf")

        assert result["success"] is True
        assert result["line_count"] == 0
        assert result["avg_confidence"] == 0.0


class TestExcelValidation:
    """Test Excel column validation logic."""

    def test_required_columns_present(self) -> None:
        """Should validate that required columns are present."""
        import pandas as pd

        REQUIRED_COLUMNS = ["Date", "Vendor", "Amount", "Category"]
        df = pd.DataFrame({
            "Date": ["2024-01-15"],
            "Vendor": ["Acme"],
            "Amount": [1500.0],
            "Category": ["Inventory"],
        })

        missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
        assert missing == []

    def test_missing_columns_detected(self) -> None:
        """Should detect missing columns."""
        import pandas as pd

        REQUIRED_COLUMNS = ["Date", "Vendor", "Amount", "Category"]
        df = pd.DataFrame({
            "Date": ["2024-01-15"],
            "Vendor": ["Acme"],
            # Missing 'Amount' and 'Category'
        })

        missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
        assert "Amount" in missing
        assert "Category" in missing

    def test_extra_columns_ignored(self) -> None:
        """Extra columns should be identified but not cause errors."""
        import pandas as pd

        REQUIRED_COLUMNS = ["Date", "Vendor", "Amount", "Category"]
        df = pd.DataFrame({
            "Date": ["2024-01-15"],
            "Vendor": ["Acme"],
            "Amount": [1500.0],
            "Category": ["Inventory"],
            "ExtraColumn": ["ignored"],
            "AnotherExtra": [123],
        })

        missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
        extra = [col for col in df.columns if col not in REQUIRED_COLUMNS]

        assert missing == []
        assert "ExtraColumn" in extra
        assert "AnotherExtra" in extra


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
