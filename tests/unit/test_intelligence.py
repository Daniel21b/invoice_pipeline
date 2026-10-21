import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/lambda_functions"))
from intelligence import extract, can_persist, merge_suggestions, persist


def record():
    return {
        "id": "abc",
        "key": "invoices/a.pdf",
        "values": {
            "invoice_number": "INV-1",
            "vendor_name": "Vendor",
            "invoice_date": "2026-01-02",
            "amount": "12.30",
        },
        "confidence": dict.fromkeys(
            ("invoice_number", "vendor_name", "invoice_date", "amount"), 99
        ),
        "llm_fields": [],
    }


def test_high_confidence_persists():
    connection = MagicMock()
    persist(connection, record())
    connection.cursor.return_value.__enter__.return_value.execute.assert_called_once()


def test_uncertain_never_writes_before_review():
    r = record()
    r["confidence"]["amount"] = 12
    connection = MagicMock()
    with pytest.raises(ValueError):
        persist(connection, r)
    connection.cursor.assert_not_called()
    persist(connection, r, reviewer="reviewer@example.com")


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "1.234", "100000000.00"])
def test_invalid_money(amount):
    r = record()
    r["values"]["amount"] = amount
    assert not can_persist(r)
    with pytest.raises(ValueError):
        persist(MagicMock(), r, reviewer="reviewer")


def test_model_cannot_overwrite_verified_fields():
    with pytest.raises(ValueError):
        merge_suggestions(record(), {"amount": "999"})


def test_model_suggestion_always_requires_review():
    r = record()
    r["confidence"]["amount"] = 40
    merge_suggestions(r, {"amount": "12.30"})
    assert not can_persist(r)


def test_missing_and_multiple_documents_rejected():
    for response in ({}, {"ExpenseDocuments": [{}, {}]}):
        with pytest.raises(ValueError):
            extract(response)


def test_invalid_date_requires_review():
    r = record()
    r["values"]["invoice_date"] = "01/02/2026"
    assert not can_persist(r)


def test_stack_gates_database_and_scopes_model():
    import aws_cdk as cdk
    from aws_cdk.assertions import Template
    from invoice_pipeline.intelligence_stack import IntelligenceStack

    template = Template.from_stack(IntelligenceStack(cdk.App(), "Test"))
    template.resource_count_is("AWS::StepFunctions::StateMachine", 1)
    template.resource_count_is(
        "AWS::Lambda::Function", 6
    )  # includes S3 notifications provider
    rendered = str(template.to_json())
    assert "HoldForHumanReview" in rendered and "VerifiedFieldsOnly" in rendered
    assert "bedrock:InvokeModel" in rendered
    assert "RDS_PASSWORD" not in rendered
