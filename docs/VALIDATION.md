# Validation — October 21, 2026

Focused unit tests cover invalid monetary/date values, missing documents,
review-before-save, protected high-confidence fields, model-generated fields,
invalid model output, S3 review queue, source version pinning and CDK synthesis.

An isolated PostgreSQL instance verified the additive migration, zero rows before
review, one row after approval, and no duplicate row on replay. Provider calls
are mocked in unit tests; no live Textract/Bedrock request or AWS deployment was
performed. The existing Linux x86_64 psycopg2 layer is used by the new stack.

Run `python -m pytest tests/unit/test_intelligence*.py -q` and
`cdk synth --app 'python intelligence_app.py'` to reproduce the focused checks.
