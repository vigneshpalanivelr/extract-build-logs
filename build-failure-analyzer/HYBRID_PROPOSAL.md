# Build Failure Analyzer — Hybrid Redesign

A self-contained design document for the proposed redesign of the
`build-failure-analyzer` service. Audience: engineering team review.

This is the implementation track. Background and the alternatives we
considered live in `PROPOSAL.md`; current behavior is documented in
`CURRENT_FLOW.md`.

Branch: `claude/setup-log-analysis-bedrock-gmLHN`.

---

## 1. Executive Summary

After roughly a week in production, the analyzer started returning the
same fix for unrelated build failures. The root cause is four
compounding bugs in how errors are embedded, hashed, stored, and
matched in the Chroma vector database — not a tuning issue.

**What we are proposing.** A *Hybrid* design with two layers:

- A **deterministic foundation** that fixes the four bugs at the source:
  separate error from context on the wire, normalize before embedding,
  switch Chroma to cosine distance, use deterministic SHA IDs, and
  update-not-insert on Slack approval.
- A single **LLM agent** (the *Deviation Analyzer*, "A3") that fires
  only on ambiguous matches — i.e., the ~15% of requests where the
  vector DB returns a candidate that is meaningful but not clearly
  exact. A3 decides whether the stored fix applies as-is, applies with
  small adjustments (version numbers, paths), or does not apply.

**Headline numbers at 1,000 requests/day:**

| Metric | Today (broken) | Hybrid (proposed) |
|---|---|---|
| Cost per 1k requests | ~$15 | ~$3 |
| LLM API calls per 1k requests | 1,000 (every request) | ~300 |
| p50 latency | 5–8 s | 400 ms–8 s (depending on hit/miss) |
| Wrong-answer rate (variant errors) | ~80% | ~13–15% |
| Code change | — | ~900 LoC + 300 LoC tests |

**Implementation order is non-negotiable.** Ship the deterministic
foundation first. Add A3 behind a feature flag in a follow-up. Roll
out at 10% traffic, then 100%. Every phase is revertible in <60s via
env-var flip.

---

## 2. The Problem

### 2.1 What developers see today

A build fails. The Slack DM arrives with a fix. The fix is confidently
worded but describes a different problem — often the same "fix"
another developer got yesterday for a completely unrelated failure.

### 2.2 Why this matters

- Developers lose confidence in the fix suggestions, traffic to the
  channel drops, less SME feedback flows back.
- SMEs see increasingly irrelevant "please approve" messages and
  disengage. The human-in-the-loop curation that was meant to grow
  the approved-fix corpus stalls.
- The fallback LLM path is still in place but pays full Bedrock Claude
  Sonnet price on every request because the existing cache key is a
  SHA of the entire log blob — and any timestamp change misses the
  cache.

### 2.3 When it started

The analyzer was deployed roughly a week ago. For the first few days
it behaved well because the vector DB was nearly empty — the service
fell through to the LLM for most requests, and the LLM did a
reasonable job with fresh context each time.

Then a very large log (several kilobytes of `error_lines` blob
including 50 lines of surrounding context per error) was approved via
Slack and saved to the vector DB. From that point on, the embedding
of that large blob has been matching almost every new error —
regardless of whether the root cause has anything to do with it.

### 2.4 What the existing flow does (1-paragraph recap)

The extractor (`src/log_error_extractor.py`) finds matched error
lines, expands each match into a context window (50 lines before, 10
after by default), merges overlapping ranges, and posts a single blob
to `/api/analyze` as `failed_steps[*].error_lines = ["<big blob>"]`.
The analyzer (`build-failure-analyzer/analyzer_service.py:267`) SHAs
the full blob for cache lookup, queries Chroma with the blob's
embedding, falls through to the LLM on a miss, and relies on Slack
Approve/Edit (`slack_reviewer.py:139`) to persist fixes. See
`CURRENT_FLOW.md` for the full walkthrough.

---

## 3. Root Cause (code-level)

Four compounding bugs. Each alone would be a nuisance; together they
guarantee the symptom.

### 3.1 Error and context glued into one blob before embedding

`src/log_error_extractor.py:138`:
```python
# Join all lines into a single string with newlines and return as list with one element
return ['\n'.join(sections)]
```

The extractor concatenates matched error lines with their surrounding
context, prefixes every line with `"Line N: ..."`, and returns it as a
single-element list. The embedding is then dominated by generic
context noise — timestamps, paths, surrounding build output — not by
the specific failure.

### 3.2 Similarity math uses the wrong metric

`build-failure-analyzer/vector_db.py:47` creates the Chroma collection
with the default distance metric (L2 / Euclidean). Later at
`vector_db.py:212`:
```python
sim = 1 - dist   # ← only valid for cosine distance
```

`1 - distance` only yields a similarity score in `[0, 1]` when
distance is cosine. With L2 the value can go negative for very
different vectors, and for a long-text "centroid" embedding the L2
distance tends to stay small, so the computed `sim` artificially
rises above the 0.78 threshold even for unrelated queries.

### 3.3 Vector row IDs are non-deterministic across restarts

`vector_db.py:276`:
```python
unique_id = f"fix-{abs(hash(error_text)) & ((1 << 128) - 1):032x}"
```

Python's builtin `hash()` is salted per process, so the same error
text produces a different ID every time the service restarts. Slack
approvals that should update an existing row keep inserting new ones.
Once the poisoning row exists, it is effectively permanent.

### 3.4 Whole-blob SHA is used as the cache key

`analyzer_service.py:284`:
```python
error_hash = hashlib.sha256(error_text.encode()).hexdigest()
```

Any timestamp change in the blob produces a different SHA, so the
Redis `sme:fix:<hash>` and `ai:fix:<hash>` caches almost never hit.
Every request re-embeds and re-queries, giving the poisoning row
another opportunity to match.

### 3.5 Why these compound

| Bug | Alone it means… | Combined effect |
|---|---|---|
| 3.1 blob embedding | retrieval matches on context noise | wide similarity band to anything with similar surrounding output |
| 3.2 L2 vs cosine | thresholds miscalibrated | blob row scores above 0.78 for everything |
| 3.3 salted hash IDs | duplicates accumulate | bad row re-inserted forever, never updated |
| 3.4 SHA-of-blob cache | cache hit rate near zero | bad retrievals get re-evaluated every request |

The Hybrid design fixes all four at the source (§5), then layers a
single LLM agent on top (§6) for cases where pure vector math is not
enough.

---
