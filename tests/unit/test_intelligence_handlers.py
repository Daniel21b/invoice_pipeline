import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/lambda_functions"))
import intelligence_handlers as handlers


def candidate():
    return {
        "id": "a",
        "key": "invoices/a.pdf",
        "values": {"vendor_name": "Shop"},
        "confidence": {"vendor_name": 99},
        "llm_fields": [],
        "text": "Invoice 123",
    }


def test_bad_model_output_routes_to_review(monkeypatch):
    s3 = MagicMock()
    model = MagicMock()
    model.converse.return_value = {
        "stopReason": "end_turn",
        "output": {"message": {"content": [{"text": "not json"}]}},
    }
    monkeypatch.setenv("BEDROCK_MODEL_ID", "configured-model")
    monkeypatch.setattr(handlers, "load", lambda event: (s3, candidate()))
    monkeypatch.setattr(handlers, "client", lambda service: model)
    result = handlers.fallback(
        {"bucket": "bucket", "artifact": "extractions/a.json"}, None
    )
    assert result["ready"] is False
    assert model.converse.call_args.kwargs["inferenceConfig"]["maxTokens"] == 1024


def test_queue_never_calls_database(monkeypatch):
    s3 = MagicMock()
    monkeypatch.setattr(handlers, "load", lambda event: (s3, candidate()))
    result = handlers.queue_review({"bucket": "bucket", "id": "a"}, None)
    assert result["status"] == "pending_review"
    assert s3.put_object.call_args.kwargs["Key"] == "pending-review/a.json"
    assert "text" not in json.loads(s3.put_object.call_args.kwargs["Body"])


def test_starter_decodes_and_pins_object_version(monkeypatch):
    sfn = MagicMock()
    monkeypatch.setattr(handlers, "client", lambda name: sfn)
    monkeypatch.setenv("STATE_MACHINE_ARN", "arn:test")
    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "bucket"},
                    "object": {
                        "key": "invoices%2Fa+b.pdf",
                        "versionId": "v1",
                        "sequencer": "1",
                    },
                }
            }
        ]
    }
    handlers.starter(event, None)
    payload = json.loads(sfn.start_execution.call_args.kwargs["input"])
    assert payload["key"] == "invoices/a b.pdf"
    assert payload["version"] == "v1"
