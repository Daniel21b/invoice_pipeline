# Historical delivery notes

This file described an earlier implementation plan and is not a current feature
or production-readiness statement. See [the current platform architecture](README.md)
and [validation record](docs/VALIDATION.md).

The implemented invoice intelligence workflow uses Step Functions, Textract,
Bedrock fallback, a Streamlit review gate and PostgreSQL. Uncertain candidates
stay in private S3 until review. No measured speedup, production readiness, cost
ceiling or deployment success is established by the old delivery checklist.
