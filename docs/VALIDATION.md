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

## Google OAuth/OIDC update — October 29, 2026

39 local tests pass across invoice intelligence, authorization and real Streamlit AppTest execution. Checks cover verified email/Google issuer/subject/expiry, unapproved accounts, explicit distinct user-ID mappings, stale session flags, allowlist removal, logout cleanup, all data-page guards, and the Google button's native login call. Missing auth configuration displays access guidance without opening AWS/database connections.

The external Google redirect is mocked in the button test. No live Google callback or deployed OAuth session is claimed. Owner client registration, secrets, callback URL and live allow/deny/logout testing remain required; see GOOGLE_OAUTH_SETUP.md.
