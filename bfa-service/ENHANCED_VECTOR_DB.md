# Enhanced Vector DB — Normalization & Fix Management

## Problem

After storing SME-approved fixes in ChromaDB for a week, a very large error log was approved. Its embedding became semantically "generic" — covering many topics shallowly — causing it to match above the 0.78 similarity threshold for nearly all incoming queries. Every new failure, regardless of type, returned the same fix from that oversized entry.

### Root Cause

1. **No text normalization**: The full `error_text` (potentially thousands of lines with `Line NNN:` prefixes, duplicate lines, and build output noise) was embedded as-is
2. **No length awareness**: The similarity scoring treated a 15,000-char stored entry the same as a 100-char entry
3. **Generic embeddings**: Large text inputs produce embeddings that sit near the "center" of the vector space, creating moderate similarity (~0.82) with almost any query

## Solution

Two complementary mechanisms in `vector_db.py`, plus management API endpoints:

### 1. Text Normalization (embedding quality fix)

A `_normalize_error_text()` method processes error text before embedding on **both save and lookup** sides:

| Step | What it does | Why |
|------|-------------|-----|
| Strip `Line NNN:` prefixes | Removes log-extraction line number markers | Not semantically useful for matching |
| Remove empty lines | Drops whitespace-only lines | Reduces noise |
| Deduplicate | Keeps first occurrence of duplicate lines | Build logs often repeat errors |
| Prioritize error signals | Lines with `ERROR`, `FAIL`, `FATAL`, `Exception`, `Traceback`, etc. come first | Ensures embedding is driven by actual errors |
| Cap length | `MAX_ERROR_LINES` (default 80) and `MAX_ERROR_CHARS` (default 4000) | Prevents generic embeddings from oversized text |

**Error-signal keywords detected:**
`ERROR`, `ERR!`, `FAIL`, `FATAL`, `Exception`, `Traceback`, `panic`, `denied`, `timeout`, `refused`, `killed`, `OOM`, `segfault`, `abort`, `CRITICAL`, `undefined reference`, `cannot find`, `no such file`, `permission`, `not found`, `exit code`, `compilation error`, `build failed`, `npm ERR`, `SyntaxError`, `ImportError`, `ModuleNotFoundError`, `KeyError`, `TypeError`, `ValueError`, `AttributeError`, `RuntimeError`, `NullPointer`, `OutOfMemory`, `stacktrace`, `coredump`, `signal`

### 2. Length-Penalized Similarity Scoring (immediate safety net)

During lookup, a logarithmic penalty is applied when the stored entry's `error_text` is much longer than the query:

```
length_ratio = max(stored_len, query_len) / min(stored_len, query_len)
penalty = 1 / (1 + ALPHA * ln(length_ratio))
adjusted_similarity = raw_similarity * penalty
```

Where `ALPHA = 0.15` (configurable via `LENGTH_PENALTY_ALPHA` env var).

#### Penalty Table

| Length Ratio | Penalty | Effect on 0.82 raw similarity |
|-------------|---------|-------------------------------|
| 1x (same length) | 1.00 | 0.82 — no change |
| 2x | 0.91 | 0.74 |
| 5x | 0.81 | 0.66 |
| 10x | 0.74 | 0.61 — below 0.78 threshold |
| 50x | 0.63 | 0.52 |
| 150x | 0.57 | 0.47 |

**Why logarithmic?** A linear penalty would be too aggressive for moderate length differences (2-3x is normal). The log curve only significantly penalizes extreme mismatches (10x+), which is exactly when embeddings become generic.

### How They Work Together

- **Normalization** fixes embedding quality for new entries and re-indexed old entries
- **Length penalty** provides immediate protection against old oversized entries (works without re-indexing)
- After running the re-index endpoint, both mechanisms reinforce each other

## Concrete Examples

### Example 1: Huge Log Dominating (the bug)

**Stored entry** (15,000 chars — 500 lines of build output + one OOM error):
```
fix_text: "Increase Node memory: NODE_OPTIONS=--max-old-space-size=4096"
```

**Query** (100 chars):
```
"ERROR: gcc compilation failed\nundefined reference to 'sqrt'"
```

| | Before Fix | After Fix |
|---|-----------|-----------|
| Raw similarity | 0.82 | 0.82 |
| Length penalty | N/A (1.0) | 0.57 (ratio 150x) |
| Adjusted score | **0.82 (MATCH)** | **0.47 (REJECTED)** |

### Example 2: Correct Same-Length Match (unaffected)

**Stored entry** (120 chars):
```
"ERROR: gcc compilation failed\nundefined reference to 'pthread_create'"
fix_text: "Add -lpthread to LDFLAGS"
```

**Query** (100 chars):
```
"ERROR: gcc compilation failed\nundefined reference to 'sqrt'"
```

| | Before Fix | After Fix |
|---|-----------|-----------|
| Raw similarity | 0.92 | 0.92 |
| Length penalty | N/A (1.0) | 0.99 (ratio 1.2x) |
| Adjusted score | **0.92 (MATCH)** | **0.91 (MATCH)** |

### Example 3: Error at End of Long Context (user concern)

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

| | Behavior |
|---|---------|
| Length ratio | ~1x (both ~2000 chars original) |
| Penalty | 1.0 (no impact) |
| Embedding quality | High (both normalized to error signal) |
| Result | **Correct match** |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_ERROR_LINES` | `80` | Max lines to keep after normalization |
| `MAX_ERROR_CHARS` | `4000` | Hard character cap after normalization |
| `LENGTH_PENALTY_ALPHA` | `0.15` | Penalty aggressiveness (higher = stricter) |
| `SIMILARITY_THRESHOLD` | `0.78` | Minimum adjusted similarity for a match |

## Fix Management API

All endpoints require JWT authentication (same as `/api/analyze`).

### List Fixes
```
GET /api/fixes?page=1&page_size=20&search=gcc&status=approved&approver=alice
```

Returns paginated, filterable list of all stored fixes. Sorted by `error_text_length` descending.

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

### Get Single Fix
```
GET /api/fixes/{fix_id}
```

### Update Fix
```
PUT /api/fixes/{fix_id}
Content-Type: application/json

{
  "fix_text": "Updated solution text",
  "metadata": {"status": "edited"}
}
```
Re-embeds with normalized error text automatically.

### Delete Fix
```
DELETE /api/fixes/{fix_id}
```

### Audit Oversized Entries
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

### Reindex All Entries
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

## CLI Tool

The existing `vector_helper.py` CLI continues to work for quick operations:

```bash
# List all fixes
python3 vector_helper.py

# Delete by ID
python3 vector_helper.py --id fix-abc123 --preview

# Delete by error text
python3 vector_helper.py --error "gcc" --preview

# Edit a fix
python3 vector_helper.py --edit fix-abc123 --fix "New solution"

# Delete all
python3 vector_helper.py --delete-all --preview
```

## Deployment Steps

1. **Deploy the updated code** — length penalty takes effect immediately for all lookups
2. **Audit existing entries**: `GET /api/fixes/audit` — identify oversized entries
3. **Reindex**: `POST /api/fixes/reindex` — re-embed all entries with normalized text
4. **Verify**: `GET /api/fixes` — browse entries and check `normalized` field is `"true"`

No database migration or schema changes required. Backward compatible with existing data.

## Files Modified

| File | Changes |
|------|---------|
| `vector_db.py` | Added `_normalize_error_text()`, length penalty in `lookup_existing_fix()`, normalization in `save_fix_to_db()`, management methods |
| `analyzer_service.py` | Added 6 REST API endpoints under `/api/fixes/` |
| `tests/test_vector_db.py` | Added 20 tests for normalization, penalty, and management |
