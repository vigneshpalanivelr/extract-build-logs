# Build Failure Analyzer (RAG-Powered, Human-in-the-Loop)

The **Build Failure Analyzer (BFA)** is an AI-assisted system that automatically analyzes CI/CD build or pipeline failures, retrieves known fixes using **Retrieval-Augmented Generation (RAG)**, and generates new remediation suggestions when needed.

What makes BFA different is its **self-curating memory**:

- SME-approved fixes are persisted
- Slack is used as a **human-in-the-loop approval layer**
- The system continuously improves without retraining models

---

## Table of Contents

- [High-Level Architecture](#high-level-architecture)
- [RAG Workflow (How It Thinks)](#rag-workflow-how-it-thinks)
- [Key Features](#key-features)
  - [RAG-Based Fix Recommendation](#rag-based-fix-recommendation)
  - [Human-in-the-Loop via Slack](#human-in-the-loop-via-slack)
  - [Continuous Learning](#continuous-learning)
  - [Pipeline Domain Context (RAG Extension)](#pipeline-domain-context-rag-extension)
  - [Securing API with Authentication](#securing-api-with-authentication)
  - [Management Utilities](#management-utilities)
  - [Centralized Logging](#centralized-logging)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
  - [Pipeline Log Analysis](#1-pipeline-log-analysis)
  - [Slack Review Workflow](#2-slack-review-workflow)
  - [Systemd Service](#3-created-systemd-service)
- [Authentication & Security](#authentication--security)
- [Slack Error & Fix Handling](#slack-error--fix-handling)
- [Vector Database (RAG Memory)](#vector-database-rag-memory)
- [Enhanced Vector DB — Normalization & Fix Management](#enhanced-vector-db--normalization--fix-management)
  - [Problem: Oversized Error Logs Dominating Matches](#problem-oversized-error-logs-dominating-matches)
  - [Root Cause Analysis](#root-cause-analysis)
  - [Solution 1: Text Normalization](#solution-1-text-normalization-embedding-quality-fix)
  - [Solution 2: Length-Penalized Similarity Scoring](#solution-2-length-penalized-similarity-scoring)
  - [How Normalization and Penalty Work Together](#how-normalization-and-penalty-work-together)
  - [Concrete Examples with Before/After Comparisons](#concrete-examples-with-beforeafter-comparisons)
  - [Vector DB Environment Variables](#vector-db-environment-variables)
  - [Fix Management API](#fix-management-api)
  - [Vector Helper CLI Tool](#vector-helper-cli-tool)
  - [Deployment Steps for Vector DB Enhancements](#deployment-steps-for-vector-db-enhancements)
  - [Architecture Decision: Why Logarithmic Penalty](#architecture-decision-why-logarithmic-penalty)
  - [Tuning Guide for Similarity and Normalization](#tuning-guide-for-similarity-and-normalization)
  - [Monitoring and Observability for Vector DB](#monitoring-and-observability-for-vector-db)
- [Unit Test Coverage](#unit-test-coverage)
  - [Test Categories & Coverage Details](#test-categories--coverage-details)
  - [Testing Philosophy](#testing-philosophy)
  - [Running Tests](#running-tests)
  - [CI/CD Safety](#cicd-safety)
- [Environment Setup](#environment-setup)
- [Running the System](#running-the-system)
- [Tech Stack](#tech-stack)
- [RAG Workflow Diagram](#rag-workflow-diagram)
- [Future Enhancements](#future-enhancements)

---

## High-Level Architecture

BFA combines:

- **Vector search (ChromaDB)** for known error -> fix pairs
- **LLM reasoning (CrewAI + Ollama)** when no good match exists
- **Slack workflows** for SME approval
- **JWT-secured APIs** for CI/CD agents
- **RAG domain context** for pipeline-specific heuristics
- **Centralized logging** with sensitive data masking and request correlation

This results in **fast, explainable, and consistent fixes** with controlled learning.

---

## RAG Workflow (How It Thinks)

### Retrieve

When a build error occurs:

- Error text is embedded
- Vector DB (Chroma) is queried
- If similarity >= threshold -> reuse approved fix

### Augment

If no match (or low confidence):

- Domain-specific context (pipeline patterns) is retrieved
- Context + error is passed to LLM prompt
- SME-safe prompt structure is enforced

### Generate

- LLM generates a suggested fix
- Suggestion is sent to Slack
- SME can **Approve**, **Edit**, or **Discard**

Approved fixes are **stored back into the vector DB**.
The system gets smarter every time.

---

## Key Features

### RAG-Based Fix Recommendation

- ChromaDB vector search with embeddings
- Threshold-based similarity filtering
- Deterministic retrieval before LLM calls

### Human-in-the-Loop via Slack

- Slack interactive buttons:
  - Approve
  - Edit
  - Discard
- Edit mode tracked using Redis
- Slack thread-safe workflows
- DM notifications to reviewers

### Continuous Learning

- Only SME-approved fixes are persisted
- Prevents hallucinations from polluting memory
- Supports future analytics on fix reuse

### Pipeline Domain Context (RAG Extension)

- Separate vector collection (pipeline_context)
- Stores failure -> solution heuristics
- Used to enrich LLM prompts before generation

### Securing API with Authentication

- JWT tokens signed using **DMZ-side RSA private key**
- No shared secrets in pipelines
- Analyzer APIs verify issuer

### Management Utilities

- CLI tools to:
  - List vector DB entries
  - Preview deletions
  - Delete by ID or error substring
- Safe preview mode supported

### Centralized Logging

BFA uses a centralized logging module (`src/logging_config.py`) adapted from the log-extractor service pattern:

- **Pipe-delimited format**: `timestamp | level | logger | request_id | message | context`
- **Request ID correlation**: Traces a single build analysis across analyzer, resolver, vector DB, and Slack
- **Sensitive data masking**: Automatically masks Slack tokens (`xoxb-*`, `xoxp-*`), API keys, JWT tokens, passwords, and Redis credentials
- **Log rotation**: 50MB max file size with 5 backup files
- **Dual output**: Console (stdout) and `bfa-service.log` file

---

## Project Structure

```
bfa-service/
│
├── src/                              # Application source code
│   ├── __init__.py
│   ├── analyzer_service.py           # FastAPI service (main entrypoint)
│   ├── error_notifier.py             # Slack + Email internal error alerts
│   ├── llm_openwebui_client.py       # Querying to chat-internal.com
│   ├── logging_config.py             # Centralized logging configuration
│   ├── pipeline_context_rag.py       # Domain context RAG logic
│   ├── resolver_agent.py             # Normalize error text, query Redis + Vector + LLM
│   ├── slack_helper.py               # Slack message formatting and Redis fix storage
│   ├── slack_reviewer.py             # Flask Slack webhook listener (approve/edit/discard)
│   └── vector_db.py                  # Vector DB + embeddings abstraction
│
├── scripts/                          # CLI tools and utilities
│   ├── jwt_dmz_issuer.py             # JWT token issuer for CI/CD agents
│   ├── jwt_sign_helper.py            # JWT signing utility for CI agents
│   └── vector_helper.py              # CLI for vector DB management
│
├── tests/                            # Full unit test suite
│   ├── conftest.py                   # Shared pytest fixtures
│   ├── test_analyze_api.py
│   ├── test_context_rag_handler.py
│   ├── test_error_notifier.py
│   ├── test_jwt_auth_handler.py
│   ├── test_llm_client.py
│   ├── test_logging_config.py
│   ├── test_rate_my_mr_api.py
│   ├── test_resolver_agent.py
│   ├── test_slack_actions.py
│   ├── test_slack_helper.py
│   ├── test_vector_db.py
│   └── test_vector_helper.py
│
├── context/                          # Domain context data files
│   └── domain_context_patterns.json
│
├── .env.example                      # Environment variable template
├── .flake8                           # Flake8 configuration
├── .gitlab-ci.yml                    # CI/CD pipeline
├── .python-version                   # Python version pin
├── build-failure-analyzer.service    # systemd unit file
├── pyproject.toml                    # Project configuration
└── uv.lock                          # Dependency lock file
```

---

## How It Works

### 1. Pipeline Log Analysis

When `analyzer_service.py` runs, it:
- Extracts unique error strings from build logs.
- For each error:
  1. Queries the **vector DB** for a similar fix.
  2. If a close match is found -> recommends it directly.
  3. Otherwise -> triggers an **LLM call** to generate a new fix.

### 2. Slack Review Workflow

AI-generated fixes are sent to a designated Slack channel via `slack_helper.py`.
Each fix comes with action buttons:

- **Approve** -> Saves fix to vector DB (via `save_fix_to_db`)
- **Edit** -> SME can modify fix text
- **Discard** -> Ignores suggestion

API handlers were added in `analyzer_service.py` (Unified version holding all API routes) to handle slack actions using the Slack SDK.

### 3. Created systemd service
```bash
User build-failure-analyzer may run the following commands on slack-server-1:
    (ALL) NOPASSWD: sudo /usr/bin/systemctl restart build-failure-analyzer,
                    sudo /usr/bin/systemctl stop build-failure-analyzer,
                    sudo /usr/bin/systemctl start build-failure-analyzer,
                    sudo /usr/bin/systemctl status build-failure-analyzer,
                    sudo /usr/bin/journalctl -u build-failure-analyzer -> to view the logs

build-failure-analyzer@slack-server-1:~/build-failure-analyzer$ systemctl status build-failure-analyzer
● build-failure-analyzer.service - Build Failure Analyzer (FastAPI)
     Loaded: loaded (/mount/systemd/system/build-failure-analyzer.service; enabled; preset: enabled)
     Active: active (running) since Fri 2026-01-16 09:10:03 EST; 5min ago
```

## Authentication & Security

### JWT Authentication

- Tokens are issued using **RSA private key** in DMZ
- Analyzer verifies:
  - iss (issuer)
  - aud (audience)
  - exp (expiry)

No shared secrets. CI/CD agents only receive signed tokens.

---

## Slack Error & Fix Handling

### Slack Actions

- Approve -> Save fix to vector DB
- Edit -> Enter edit mode (Redis-tracked)
- Discard -> Drop suggestion safely

### Error Notifications

- Any internal exception triggers:
  - Slack DM alert
  - Optional SMTP email
- Fail-safe design:
  - Slack/email failures never crash the app

## Vector Database (RAG Memory)

The app uses **ChromaDB** as its vector store to persist embeddings and SME-approved fixes.

- **Embedding Model:** `granite-embedding` (or configurable via `OLLAMA_EMBED_MODEL`)
- **Persistence Directory:** Configurable via `CHROMA_DB_PATH`
- **Delete/Query Utilities:**
  - `python3 scripts/vector_helper.py` -- Query existing entries
  - `python3 scripts/vector_helper.py --id <doc-id>` -- Delete unwanted entry

---

## Enhanced Vector DB — Normalization & Fix Management

### Problem: Oversized Error Logs Dominating Matches

After storing SME-approved fixes in ChromaDB for a week, a very large error log was approved. Its embedding became semantically "generic" — covering many topics shallowly — causing it to match above the 0.78 similarity threshold for nearly all incoming queries. Every new failure, regardless of type, returned the same fix from that oversized entry.

### Root Cause Analysis

1. **No text normalization**: The full `error_text` (potentially thousands of lines with `Line NNN:` prefixes, duplicate lines, and build output noise) was embedded as-is. This meant embedding models had to compress thousands of tokens of noise into a single vector, diluting the semantic signal.

2. **No length awareness in scoring**: The similarity scoring treated a 15,000-char stored entry the same as a 100-char entry. ChromaDB returns raw cosine similarity without considering the structural mismatch between entries of vastly different lengths.

3. **Generic embeddings from large inputs**: Large text inputs produce embeddings that sit near the "center" of the vector space. This happens because the embedding model averages across many diverse tokens, resulting in a vector that has moderate similarity (~0.82) with almost any query — a phenomenon known as the "hub effect" in high-dimensional spaces.

4. **Cascading false positives**: Once a generic embedding exceeds the similarity threshold, it monopolizes all lookups. New errors that should have triggered LLM-generated fixes instead received the same irrelevant fix, degrading trust in the system.

### Solution 1: Text Normalization (Embedding Quality Fix)

A `_normalize_error_text()` method processes error text before embedding on **both save and lookup** sides to ensure consistent, high-quality embeddings:

| Step | What it does | Why | Implementation Detail |
|------|-------------|-----|----------------------|
| Strip `Line NNN:` prefixes | Removes log-extraction line number markers via regex `r'^Line\s+\d+:\s*'` | Not semantically useful for matching; adds noise to embeddings | Applied per-line using `re.sub()` |
| Remove empty lines | Drops whitespace-only lines after stripping | Reduces noise and embedding token waste | `line.strip()` filter |
| Deduplicate | Keeps first occurrence of duplicate lines using `seen` set | Build logs often repeat errors hundreds of times (e.g., compilation warnings) | Order-preserving dedup via `set()` |
| Prioritize error signals | Lines containing error keywords sorted to top of text | Ensures embedding is driven by actual errors, not build context noise | Two-pass split: error lines first, then remaining lines |
| Cap length | `MAX_ERROR_LINES` (default 80) and `MAX_ERROR_CHARS` (default 4000) | Prevents generic embeddings from oversized text; keeps within embedding model's effective token window | Applied after dedup and prioritization |

**Error-signal keywords detected (case-insensitive matching):**

| Category | Keywords |
|----------|----------|
| Error levels | `ERROR`, `ERR!`, `FAIL`, `FATAL`, `CRITICAL` |
| Exceptions | `Exception`, `Traceback`, `SyntaxError`, `ImportError`, `ModuleNotFoundError`, `KeyError`, `TypeError`, `ValueError`, `AttributeError`, `RuntimeError` |
| System failures | `panic`, `killed`, `OOM`, `segfault`, `abort`, `coredump`, `signal`, `NullPointer`, `OutOfMemory`, `stacktrace` |
| Access errors | `denied`, `timeout`, `refused`, `permission`, `not found` |
| Build errors | `undefined reference`, `cannot find`, `no such file`, `exit code`, `compilation error`, `build failed`, `npm ERR` |

**Normalization flow (step by step):**

```
Input: 500-line build log with Line NNN: prefixes
  ↓
Step 1: Strip "Line 123: " prefix from each line
  → 500 lines without prefixes
  ↓
Step 2: Remove empty/whitespace-only lines
  → ~350 non-empty lines
  ↓
Step 3: Deduplicate (keep first occurrence)
  → ~120 unique lines
  ↓
Step 4: Split into error_lines + context_lines
  → 8 error lines (contain ERROR/FAIL/etc.)
  → 112 context lines
  ↓
Step 5: Concatenate error_lines + context_lines (errors first)
  → Error-signal-driven ordering
  ↓
Step 6: Cap to MAX_ERROR_LINES (80 lines)
  → 80 lines max
  ↓
Step 7: Cap to MAX_ERROR_CHARS (4000 chars)
  → Final normalized text ≤ 4000 chars
```

### Solution 2: Length-Penalized Similarity Scoring

During lookup, a logarithmic penalty is applied when the stored entry's `error_text` is much longer than the query:

```
length_ratio = max(stored_len, query_len) / min(stored_len, query_len)
penalty = 1 / (1 + ALPHA * ln(length_ratio))
adjusted_similarity = raw_similarity * penalty
```

Where `ALPHA = 0.15` (configurable via `LENGTH_PENALTY_ALPHA` env var).

#### Penalty Table (Reference)

| Length Ratio | ln(ratio) | Penalty (ALPHA=0.15) | Effect on 0.82 raw similarity |
|-------------|-----------|----------------------|-------------------------------|
| 1x (same length) | 0.00 | 1.000 | 0.820 — no change |
| 1.5x | 0.41 | 0.942 | 0.773 |
| 2x | 0.69 | 0.906 | 0.743 |
| 3x | 1.10 | 0.858 | 0.704 |
| 5x | 1.61 | 0.806 | 0.661 |
| 10x | 2.30 | 0.743 | 0.609 — below 0.78 threshold |
| 20x | 3.00 | 0.690 | 0.566 |
| 50x | 3.91 | 0.630 | 0.517 |
| 100x | 4.61 | 0.591 | 0.485 |
| 150x | 5.01 | 0.571 | 0.468 |

#### Penalty Behavior by ALPHA Value

| ALPHA | 2x ratio penalty | 10x ratio penalty | Use case |
|-------|-----------------|-------------------|----------|
| 0.05 | 0.97 | 0.90 | Very lenient — only extreme mismatches penalized |
| 0.10 | 0.94 | 0.81 | Moderate — good for well-normalized data |
| **0.15** | **0.91** | **0.74** | **Default — balanced for mixed-quality data** |
| 0.25 | 0.85 | 0.63 | Aggressive — strict length matching required |
| 0.50 | 0.74 | 0.47 | Very aggressive — rarely appropriate |

### How Normalization and Penalty Work Together

- **Normalization** fixes embedding quality for new entries and re-indexed old entries. After normalization, most entries are between 500-4000 chars, reducing length variance dramatically.
- **Length penalty** provides immediate protection against old oversized entries that haven't been re-indexed yet. It works without re-indexing because it operates on the stored `error_text` metadata, not the embedding itself.
- After running the re-index endpoint, both mechanisms reinforce each other: normalized text produces better embeddings AND reduced length variance means the penalty rarely activates (which is ideal).

```
Timeline:
  Day 0: Deploy code → length penalty protects immediately
  Day 0: Run /api/fixes/reindex → normalization improves embedding quality
  Day 1+: Both mechanisms active, penalty rarely triggers (entries are similar length)
```

### Concrete Examples with Before/After Comparisons

#### Example 1: Huge Log Dominating (the original bug)

**Stored entry** (15,000 chars — 500 lines of build output + one OOM error):
```
fix_text: "Increase Node memory: NODE_OPTIONS=--max-old-space-size=4096"
```

**Query** (100 chars):
```
"ERROR: gcc compilation failed\nundefined reference to 'sqrt'"
```

| Metric | Before Fix | After Fix |
|--------|-----------|-----------|
| Raw similarity | 0.82 | 0.82 |
| Length ratio | N/A | 150x |
| Length penalty | N/A (1.0) | 0.57 |
| Adjusted score | **0.82 (MATCH — wrong fix!)** | **0.47 (REJECTED — correct!)** |
| Outcome | Returns OOM fix for gcc error | Falls through to LLM for proper gcc fix |

#### Example 2: Correct Same-Length Match (unaffected by changes)

**Stored entry** (120 chars):
```
"ERROR: gcc compilation failed\nundefined reference to 'pthread_create'"
fix_text: "Add -lpthread to LDFLAGS"
```

**Query** (100 chars):
```
"ERROR: gcc compilation failed\nundefined reference to 'sqrt'"
```

| Metric | Before Fix | After Fix |
|--------|-----------|-----------|
| Raw similarity | 0.92 | 0.92 |
| Length ratio | N/A | 1.2x |
| Length penalty | N/A (1.0) | 0.99 |
| Adjusted score | **0.92 (MATCH)** | **0.91 (MATCH — still works!)** |
| Outcome | Correct fix returned | Correct fix still returned with negligible penalty |

#### Example 3: Error at End of Long Context (normalization handles this)

**Query** (2000 chars — 10 error lines + 50 context lines):
```
Line 1: Cloning repository...
Line 2: Building project...
... (context lines) ...
Line 55: FATAL: OOM killed
Line 56: Process exited with code 137
```

**Stored entry** (2000 chars — similar structure):
```
fix_text: "Increase container memory limit in CI config"
```

**After normalization**, both become ~200 chars:
```
"FATAL: OOM killed\nProcess exited with code 137\nCloning repository...\nBuilding project..."
```
(Error lines promoted to top, context fills remaining slots)

| Metric | Behavior |
|--------|---------|
| Length ratio | ~1x (both ~2000 chars original, both ~200 chars normalized) |
| Penalty | 1.0 (no impact) |
| Embedding quality | High (both normalized to error signal) |
| Result | **Correct match — normalization eliminated noise from both sides** |

#### Example 4: Multiple Small Errors vs Single Large Error

**Stored entry** (300 chars — clean, targeted):
```
"ImportError: No module named 'numpy'\nModuleNotFoundError: 'numpy'"
fix_text: "Add numpy to requirements.txt: pip install numpy"
```

**Query** (8000 chars — large test output with the same error buried in noise):
```
Running test suite...
Test 1: PASSED
Test 2: PASSED
... (200 lines of test output) ...
Test 195: FAILED - ImportError: No module named 'numpy'
... (more output) ...
```

| Metric | Without normalization | With normalization |
|--------|----------------------|-------------------|
| Query effective text | 8000 chars of noise | ~100 chars: `"ImportError: No module named 'numpy'"` |
| Raw similarity | 0.71 (diluted by test output) | 0.95 (error signal matched precisely) |
| Length penalty | 0.66 (26x ratio) | 0.97 (3x ratio after normalization) |
| Adjusted score | **0.47 (MISSED)** | **0.92 (MATCHED — correct!)** |

### Vector DB Environment Variables

| Variable | Default | Description | Tuning Notes |
|----------|---------|-------------|--------------|
| `MAX_ERROR_LINES` | `80` | Max lines to keep after normalization | Increase if your errors span many lines; decrease for faster embedding |
| `MAX_ERROR_CHARS` | `4000` | Hard character cap after normalization | Should not exceed embedding model's effective context (typically 512 tokens ≈ 2000-4000 chars) |
| `LENGTH_PENALTY_ALPHA` | `0.15` | Penalty aggressiveness (higher = stricter) | Start with 0.15; increase to 0.25 if you still see false positives from length mismatch |
| `SIMILARITY_THRESHOLD` | `0.78` | Minimum adjusted similarity for a match | Lower = more permissive (more false positives); Higher = stricter (more LLM calls) |
| `VECTOR_TOP_K` | `3` | Number of candidates to retrieve before scoring | Higher values find more candidates but increase latency |
| `CHROMA_DB_PATH` | `/home/build-failure-analyzer/data/chroma` | ChromaDB persistence directory | Must be on persistent storage; avoid tmpfs |
| `CHROMA_COLLECTION` | `build_fixes` | ChromaDB collection name | Change when testing; separate production/staging collections |
| `OLLAMA_EMBED_MODEL` | `granite-embedding` | Embedding model for vectorization | Must match model used during initial indexing |
| `OLLAMA_HTTP_URL` | `http://localhost:11434` | Ollama HTTP API endpoint | Point to your Ollama instance |
| `OLLAMA_TIMEOUT` | `30` | Timeout in seconds for Ollama API calls | Increase for slow networks or large models |

### Fix Management API

All endpoints require JWT authentication (same as `/api/analyze`).

#### List Fixes
```
GET /api/fixes?page=1&page_size=20&search=gcc&status=approved&approver=alice
```

Returns paginated, filterable list of all stored fixes. Sorted by `error_text_length` descending.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | int | 1 | Page number (1-indexed) |
| `page_size` | int | 20 | Results per page (max 100) |
| `search` | string | — | Filter by error_text substring (case-insensitive) |
| `status` | string | — | Filter by fix status (approved, edited, etc.) |
| `approver` | string | — | Filter by approver username |

**Response:**
```json
{
  "total": 42,
  "page": 1,
  "page_size": 20,
  "fixes": [
    {
      "id": "fix-abc123...",
      "error_text": "ERROR: gcc compilation failed...",
      "error_text_length": 150,
      "fix_text": "Add -lpthread to LDFLAGS",
      "status": "approved",
      "approved_by": "alice",
      "normalized": "true",
      "metadata": { ... }
    }
  ]
}
```

#### Get Single Fix
```
GET /api/fixes/{fix_id}
```

Returns full details of a specific fix entry including metadata, timestamps, and normalization status.

#### Update Fix
```
PUT /api/fixes/{fix_id}
Content-Type: application/json

{
  "fix_text": "Updated solution text",
  "metadata": {"status": "edited"}
}
```
Re-embeds with normalized error text automatically. The old embedding is replaced with a new one based on the normalized error text plus updated fix text.

#### Delete Fix
```
DELETE /api/fixes/{fix_id}
```

Permanently removes the fix entry and its embedding from ChromaDB. This action is irreversible.

#### Audit Oversized Entries
```
GET /api/fixes/audit?max_chars=4000
```

Returns entries where `error_text` exceeds the threshold. Use this to identify problematic entries before/after reindexing.

**Response:**
```json
{
  "threshold": 4000,
  "oversized_count": 3,
  "entries": [
    {
      "id": "fix-abc...",
      "error_text_length": 15000,
      "error_text_preview": "Line 1: Starting build...(first 200 chars)...",
      "fix_text_preview": "Increase Node memory...",
      "status": "approved",
      "normalized": "false"
    }
  ]
}
```

#### Reindex All Entries
```
POST /api/fixes/reindex
```

Re-embeds all entries using normalized error text. Run this once after deploying to fix existing oversized entries.

**Response:**
```json
{
  "status": "ok",
  "total": 42,
  "reindexed": 40,
  "failed": 1,
  "skipped": 1
}
```

**Reindex behavior:**
- Each entry's `error_text` is normalized using `_normalize_error_text()`
- A new embedding is generated from the normalized text
- The entry's metadata is updated with `normalized: "true"` and new `error_text_length`
- Entries that fail during re-embedding are counted as `failed` but don't stop the process
- Entries already marked as normalized are counted as `skipped`

### Vector Helper CLI Tool

The `scripts/vector_helper.py` CLI provides direct database management:

```bash
# List all fixes
python3 scripts/vector_helper.py

# Delete by ID
python3 scripts/vector_helper.py --id fix-abc123 --preview

# Delete by error text
python3 scripts/vector_helper.py --error "gcc" --preview

# Edit a fix
python3 scripts/vector_helper.py --edit fix-abc123 --fix "New solution"

# Delete all
python3 scripts/vector_helper.py --delete-all --preview
```

**Important flags:**
| Flag | Description |
|------|-------------|
| `--preview` | Show what would be deleted without actually deleting (dry run) |
| `--id` | Target specific fix IDs (space-separated) |
| `--error` | Match entries by error text substring |
| `--edit` | Enter edit mode for a specific fix ID |
| `--fix` | Provide new fix text inline (use with `--edit`) |
| `--delete-all` | Delete all entries (requires `--preview` first for safety) |

### Deployment Steps for Vector DB Enhancements

1. **Deploy the updated code** — length penalty takes effect immediately for all lookups
2. **Audit existing entries**: `GET /api/fixes/audit` — identify oversized entries
3. **Reindex**: `POST /api/fixes/reindex` — re-embed all entries with normalized text
4. **Verify**: `GET /api/fixes` — browse entries and check `normalized` field is `"true"`

No database migration or schema changes required. Backward compatible with existing data.

### Architecture Decision: Why Logarithmic Penalty

Several penalty functions were considered:

| Function | Formula | Problem |
|----------|---------|---------|
| **Linear** | `1 / ratio` | Too aggressive: a 2x length difference would halve the score, causing many false negatives |
| **Square root** | `1 / sqrt(ratio)` | Still too aggressive for moderate differences |
| **Logarithmic** | `1 / (1 + α * ln(ratio))` | Gentle curve: barely affects 1-3x differences, significantly penalizes 10x+ |
| **Step function** | `1 if ratio < T else 0` | Binary — no gradual degradation, hard to tune threshold |

The logarithmic function was chosen because:
- **2-3x length differences are normal** (different log verbosity between CI systems)
- **10x+ differences are almost always problematic** (oversized entry dominating)
- The curve provides smooth, predictable degradation
- ALPHA parameter allows fine-tuning without changing the function

### Tuning Guide for Similarity and Normalization

**Symptom → Adjustment mapping:**

| Symptom | Root cause | Adjustment |
|---------|-----------|------------|
| Too many false positives (wrong fixes returned) | Threshold too low or penalty too lenient | Increase `SIMILARITY_THRESHOLD` to 0.82+ or increase `LENGTH_PENALTY_ALPHA` to 0.20+ |
| Too many misses (LLM called when fix exists) | Threshold too high or penalty too aggressive | Decrease `SIMILARITY_THRESHOLD` to 0.75 or decrease `LENGTH_PENALTY_ALPHA` to 0.10 |
| Errors at end of logs not matching | Important error lines not reaching top during normalization | Add missing keywords to error-signal list in `_normalize_error_text()` |
| Very short queries matching everything | Short text produces overfit embeddings | Increase `SIMILARITY_THRESHOLD` or add minimum query length validation |
| Reindex takes too long | Too many entries or slow Ollama | Increase `OLLAMA_TIMEOUT`; consider batch reindexing during off-hours |

### Monitoring and Observability for Vector DB

Key metrics to track:

| Metric | How to observe | Healthy range |
|--------|---------------|---------------|
| Adjusted similarity scores | Analyzer service logs (`similarity_score` field) | 0.80-0.95 for matches; below 0.78 for non-matches |
| Length penalty activations | Look for penalty < 0.95 in logs | Rare after reindexing; frequent = old entries need reindex |
| Oversized entry count | `GET /api/fixes/audit` | 0 after reindex; > 0 means new oversized entries approved |
| Normalization coverage | `GET /api/fixes` and count `normalized: "true"` | 100% after reindex |
| Average error_text_length | `GET /api/fixes` statistics | 200-2000 chars post-normalization |
| Fix reuse rate | Count vector DB matches vs LLM calls in logs | Higher is better (system is learning) |

#### Files Modified for Vector DB Enhancements

| File | Changes |
|------|---------|
| `src/vector_db.py` | Added `_normalize_error_text()`, length penalty in `lookup_existing_fix()`, normalization in `save_fix_to_db()`, management methods |
| `src/analyzer_service.py` | Added 6 REST API endpoints under `/api/fixes/` |
| `tests/test_vector_db.py` | Added 20 tests for normalization, penalty, and management |

---

## Unit Test Coverage

All critical components are fully unit-tested:

| **Component** | **Test File** | **Coverage** |
|---------------|---------------|--------------|
| Analyzer Service | `test_analyze_api.py` | API routing, dependencies, safety |
| Slack Actions | `test_slack_actions.py` | Approve/Edit/Discard flows |
| Slack Helper | `test_slack_helper.py` | Message formatting, Redis ops |
| Error Notifier | `test_error_notifier.py` | Slack/email safety |
| JWT Issuer | `test_jwt_auth_handler.py` | Claims, expiry, CLI |
| Pipeline RAG | `test_context_rag_handler.py` | Indexing, querying, thresholds |
| Vector Helper | `test_vector_helper.py` | List / preview / delete logic |
| LLM Client | `test_llm_client.py` | API calls, retries, errors |
| Resolver Agent | `test_resolver_agent.py` | Error analysis, LLM reasoning |
| Rate My MR | `test_rate_my_mr_api.py` | MR review API |
| Vector DB | `test_vector_db.py` | Normalization, penalty, CRUD |
| Logging Config | `test_logging_config.py` | Formatter, filters, masking |

### Test Categories & Coverage Details

#### Analyzer Service (`src/analyzer_service.py`)
- API endpoints initialization
- Dependency wiring (Redis, Slack, VectorDB)
- Slack action/event routing logic
- Error handling paths
- **Approach**: Mock FastAPI deps, Redis, Slack client, VectorDB; validate side effects

#### Slack Actions & Events
- Slack signature validation
- Approve / Edit / Discard flows
- Thread validation logic
- Redis edit-mode tracking
- Developer DM notifications
- **Approach**: No real Slack API; full Slack SDK mocking; thread safety verified

#### Error Notifier (`src/error_notifier.py`)
- Slack DM alerts on internal errors
- Email alerts (SMTP)
- Graceful degradation when Slack or SMTP is down
- **Guarantee**: `notify_global_error()` is fail-safe — never crashes the app

#### JWT DMZ Issuer (`scripts/jwt_dmz_issuer.py`)
- JWT creation using RSA private key
- Claim validation (iss, aud, sub, iat, exp)
- Custom expiry handling
- CLI execution (`__main__` path)
- **Approach**: RSA signing mocked; no real cryptographic material

#### Pipeline Context RAG (`src/pipeline_context_rag.py`)
- `load_domain_context`, `init_context_collection`, `index_domain_patterns`, `lookup_domain_matches`
- Missing domain context file handling, embedding failures, threshold filtering
- **Approach**: No real Chroma DB or embeddings; pure logic validation

#### Vector Helper CLI (`scripts/vector_helper.py`)
- `list_docs`, `delete_docs_by_id`, `delete_docs_by_error`, `preview_docs_by_error`
- Business logic tested independently (argparse CLI parsing intentionally not tested)

#### Vector DB (`src/vector_db.py`)
- Text normalization (stripping, dedup, prioritization, capping)
- Length-penalized similarity scoring
- Save/lookup/update/delete operations
- Reindex and audit functionality

#### Logging Config (`src/logging_config.py`)
- PipeDelimitedFormatter output format and alignment
- SensitiveDataFilter masking (Slack tokens, API keys, JWT, Redis URLs)
- RequestIdFilter context propagation
- LoggingConfig setup, rotation, and singleton behavior
- Convenience functions (get_logger, set_request_id, mask_token)

### Testing Philosophy

**What we DON'T use:**
- No real Slack, Redis, SMTP, Chroma DB
- No network calls or filesystem writes
- No real cryptographic material

**What we DO instead:**
- Everything is mocked
- Side effects are asserted
- Failures are predictable
- Tests are CI-friendly

### Running Tests

```bash
# Run all tests
pytest -v

# Run a single test file
pytest tests/test_error_notifier.py -v

# Run with coverage report
pytest tests/ -v --tb=short --cov=src --cov=scripts --cov-report=term-missing

# Run with shorter output
pytest -q
```

### CI/CD Safety

All tests are:
- Deterministic
- Stateless
- Parallel-safe
- Suitable for GitHub Actions / GitLab CI / Jenkins

No secrets are required to run tests.

---

## Environment Setup

Copy the `.env.example` file to `.env` and fill in the required values:

```bash
cp .env.example .env
# Edit .env and set SLACK_BOT_TOKEN, OPENWEBUI_API_KEY, etc.
```

See `.env.example` for the full list of configurable variables.

## Running the System

1. **Start the Slack Reviewer App**

   This Flask service listens for Slack button interactions.

   ```bash
   python3 src/slack_reviewer.py
   ```

   Runs on port 5001 by default (configurable via `FLASK_PORT`).
   Make sure it's reachable via ngrok or your Kubernetes ingress.

2. **Run the Analyzer**

   Run the main analyzer that processes build logs and sends results to Slack.

   ```bash
   python3 src/analyzer_service.py
   ```

3. **Query or Clean the Vector Store**

   ```bash
   # List all documents
   python3 scripts/vector_helper.py

   # Preview and confirm before deleting by ID
   python3 scripts/vector_helper.py --id abc123 xyz789 --preview

   # Delete by error text
   python3 scripts/vector_helper.py --error "cmake" --preview

   # Delete all documents
   python3 scripts/vector_helper.py --delete-all

   # Edit fix interactively
   python3 scripts/vector_helper.py --edit abc123

   # Edit fix with inline text
   python3 scripts/vector_helper.py --edit abc123 --fix "Run: sudo apt-get install cmake"
   ```


## Tech Stack

| Component | Purpose |
|-----------|---------|
| Python 3.13+ | Core language |
| ChromaDB | Vector storage & retrieval |
| Ollama Embeddings | Semantic understanding |
| Flask | Slack webhook listener |
| Slack SDK | Message sending & interactive review |
| Redis | In-Memory store for caching and exchange data between flask and analyzer |

## RAG Workflow Diagram

```
Flowchart Top -> Down (vertical)
    A[Pipeline Logs] --> B[Error Extraction]
    B --> C{Vector DB Lookup}
    C -->|Found Match| D[Recommend Existing Fix]
    C -->|No Match| E[LLM Generates New Fix]
    D --> F[Send to Slack for Review]
    E --> F
    F --> G[SME Approves/Edits/Discards]
    G -->|Approve| H[Persist Fix to Vector DB]
```

## Example Output

```
Found 2 unique error(s):
1. Caused by: missing semicolon
2. make: *** [build] Error 2

Generated AI fix for error:
Caused by: missing semicolon
--
1. Locate the pipeline script...
...
Fix approved by @sme_user and saved to memory.
```

## Future Enhancements

1. Auto-linting and pre-save validation for SME edits.
2. Web dashboard to visualize frequently recurring errors.
3. Fine-tuned embeddings for better semantic similarity.
4. Integration with Jira for ticket linking.
5. SLA-based auto-approval.

## Summary

The Build Failure Analyzer is:

- A production-grade RAG system
- With human-verified memory
- Designed for CI/CD reliability
- Secure, test-driven, and extensible

It doesn't just generate fixes -- it learns responsibly.
