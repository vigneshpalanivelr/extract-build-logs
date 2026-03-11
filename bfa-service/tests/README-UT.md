# Build Failure Analyzer – Unit Test Guide

This repository contains a growing set of **robust, CI-safe unit tests** covering the core components of the **Build Failure Analyzer (BFA)** system.

The tests are designed to be:
- Deterministic (no network / DB access)
- Fast (pure unit tests, heavy mocking)
- Safe for CI/CD
- Aligned with current production code (no assumptions)

## Test Structure

All unit tests live under:
```
tests/
```

Current test coverage includes:
```
tests/
├── test_analyzer_api.py
├── test_slack_actions.py
├── test_slack_helper.py
├── test_error_notifier.py
├── test_jwt_auth_handler.py
├── test_pipeline_context_rag.py
├── test_vector_helper.py
├── test_llm_client.py
├── test_resolver_agent.py
├── test_rate_my_mr_api.py
└── test_vector_db.py
```

## Test Categories & Coverage

### Analyzer Service (`analyzer_service.py`)

**Covered behaviors:**
- API endpoints initialization
- Dependency wiring
- Slack action/event routing logic
- Error handling paths

**Testing approach:**
- Mock FastAPI dependencies
- Mock Redis, Slack client, VectorDB
- Validate side effects (calls, state changes)

### Slack Actions & Events

**Files tested:**
- `/bfa/slack/actions`
- `/bfa/slack/events`

**Covered behaviors:**
- Slack signature validation
- Approve / Edit / Discard flows
- Thread validation logic
- Redis edit-mode tracking
- Developer DM notifications

**Key principles:**
- No real Slack API calls
- Slack SDK fully mocked
- Thread safety and idempotency verified

### Error Notifier (`error_notifier.py`)

**Covered behaviors:**
- Slack DM alerts on internal errors
- Email alerts (SMTP)
- Graceful degradation when:
  - Slack is down
  - SMTP is not configured
- Ensures notifier never crashes the app

**Important guarantees:**
- `notify_global_error()` is **fail-safe**
- Slack/email failures never propagate exceptions
- Environment variable handling validated

### JWT DMZ Issuer (`jwt_dmz_issuer.py`)

**Covered behaviors:**
- JWT creation using RSA private key
- Claim validation:
  - `iss`, `aud`, `sub`
  - `iat`, `exp`
- Custom expiry handling
- Private key file read
- CLI execution (`__main__` path)

**Testing strategy:**
- RSA signing fully mocked
- No real cryptographic material required
- CLI tested using subprocess

### Pipeline Context RAG (`pipeline_context_rag.py`)

**Covered functions:**
- `load_domain_context`
- `init_context_collection`
- `index_domain_patterns`
- `lookup_domain_matches`

**Validated scenarios:**
- Missing domain context file
- Chroma collection initialization
- Embedding failures
- Threshold filtering
- Similarity score calculation
- Empty / error responses

**Key design goals:**
- No real Chroma DB
- No real embeddings
- Pure logic validation

### Vector Helper CLI (`vector_helper.py`)

**Covered functions:**
- `list_docs`
- `delete_docs_by_id`
- `delete_docs_by_error`
- `preview_docs_by_error`

**What is intentionally NOT tested:**
- argparse CLI wiring
- Real filesystem
- Real Chroma DB

**Why:**
- Business logic is tested independently
- CLI parsing adds no business value to unit tests

## Required Test Dependencies

Make sure the following are installed in your virtual environment:

```bash
pip install \
  pytest \
  pytest-asyncio \
  pytest-mock \
  slack-sdk \
  python-dotenv \
  PyJWT
```

> No additional test-only libraries are required.

## Running Tests

**Run all tests:**
```bash
pytest -v
```

**Run a single test file:**
```bash
pytest tests/test_error_notifier.py -v
```

**Run with shorter output:**
```bash
pytest -q
```

## Testing Philosophy

These tests follow strict principles:

**What we DON'T use:**
- No real Slack
- No real Redis
- No real SMTP
- No real Chroma DB
- No network calls
- No filesystem writes

**What we DO instead:**
- Everything is mocked
- Side effects are asserted
- Failures are predictable
- Tests are CI-friendly

## CI/CD Safety

All tests are:
- Deterministic
- Stateless
- Parallel-safe
- Suitable for GitHub Actions / GitLab CI / Jenkins

No secrets are required to run tests.

## Current Test Status

✅ All tests passing  
✅ Zero flaky tests  
✅ No environment dependencies  
✅ Production-aligned

## Maintainer Notes

If production behavior changes:
- Update tests **only after** code changes
- Never weaken assertions to "make tests pass"
