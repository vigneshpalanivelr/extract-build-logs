# Build Failure Analyzer — Redesign Proposal

A team-review document for choosing how to fix the vector-DB poisoning
bug in `build-failure-analyzer` and improve accuracy going forward.

Replaces the now-deleted drafts `SOLUTION_PROPOSAL.md` and
`AGENTIC_APPROACH.md`. Reference material (what the service does today)
remains in `CURRENT_FLOW.md`.

Branch: `claude/setup-log-analysis-bedrock-gmLHN`.

---

## 1. Executive Summary

After roughly a week in production, the analyzer started returning the
same fix for unrelated build failures. Root cause: one large log gets
stored once, then its embedding dominates every future similarity query.
This is not a tuning issue — it is four compounding bugs in how errors
are embedded, hashed, stored, and matched.

Three remediation paths are on the table:

| Option | One-line description | Cost per 1k requests | Fits current volume? |
|---|---|---|---|
| **A — Full Agentic** | 7 coordinated LLM agents handle every request end-to-end | ~$30–40 | No — over-engineered |
| **B — Split Error (Deterministic)** | Separate error from context, normalize, cosine distance, deterministic IDs | ~$1.50 | Yes, but misses variant fixes |
| **C — Hybrid (B + one agent)** | Deterministic fast path + a single Deviation Analyzer agent on ambiguous matches | ~$3 | Yes — recommended |

**Recommendation: Approach C.** Land Approach B first as the foundation
(non-negotiable — agents reasoning over poisoned data are still wrong).
Then add exactly one agent (A3 Deviation Analyzer) and only where it
measurably helps.

---

## 2. The Problem

### 2.1 Symptom developers see

A build fails. The Slack DM arrives with a fix. The fix is confidently
worded but describes a different problem — often the same "fix" another
developer got yesterday for an unrelated failure. Developers start
ignoring the bot; SMEs stop approving because the answers look wrong;
the feedback loop that was supposed to improve the system goes quiet.

### 2.2 When and why it started

The analyzer was deployed roughly a week ago. For the first few days it
behaved well because the vector DB was nearly empty — the service fell
through to the LLM for most requests, and the LLM did a reasonable job
with fresh context each time.

Then a very large log (several kilobytes of `error_lines` blob including
50 lines of surrounding context per error) was approved via Slack and
saved to the vector DB. From that point on, the embedding of that large
blob has been matching almost every new error — regardless of whether
the root cause has anything to do with it.

### 2.3 Business impact

- Developers lose confidence in the fix suggestions → traffic to the
  channel drops → less SME feedback → the approved-fix corpus stops
  growing.
- SMEs see increasingly irrelevant "please approve" messages → they
  disengage → the human-in-the-loop review that was meant to curate
  the corpus stalls.
- The LLM-only fallback path is still available, but the cache keys are
  SHA of the full blob, so cache hit rates are near zero, meaning every
  request pays the full Bedrock Claude Sonnet cost.

### 2.4 What the existing flow is doing (1-paragraph recap)

The extractor (`src/log_error_extractor.py`) finds matched error lines in
a build log, expands each match into a context window (50 lines before,
10 after by default), merges overlapping ranges, and posts a single blob
to `/api/analyze` as `failed_steps[*].error_lines = ["<big blob>"]`. The
analyzer (`build-failure-analyzer/analyzer_service.py:267`) SHAs the full
blob for cache lookup, queries a Chroma collection with the blob's
embedding, falls through to the LLM on a miss, and relies on Slack
Approve/Edit (`slack_reviewer.py:139`) to persist fixes into the vector
DB. See `CURRENT_FLOW.md` for the full walkthrough.

---

## 3. Root Cause (code-level)

Four compounding bugs. Each alone would be a nuisance; together they
guarantee the symptom.

### 3.1 Error and context are glued into one blob before embedding

`src/log_error_extractor.py:138`:
```python
# Join all lines into a single string with newlines and return as list with one element
return ['\n'.join(sections)]
```

The extractor concatenates matched error lines with 50 lines of
surrounding context each, prefixes every line with `"Line N: ..."`, and
returns it as a single-element list. Downstream this becomes one
`error_text` string. Its embedding is dominated by generic context noise
(timestamps, file paths, surrounding build output), not by the specific
failure.

### 3.2 Similarity math uses the wrong metric

`build-failure-analyzer/vector_db.py:47` creates the collection with
Chroma's default distance metric (L2 / Euclidean). Later at
`vector_db.py:212`:
```python
sim = 1 - dist   # ← only valid for cosine distance
```

`1 - distance` only yields a similarity score in `[0, 1]` when the
distance is cosine. With L2 distance the value can go negative for very
different vectors, and for a long-text "centroid" embedding the L2
distance tends to stay small → the computed `sim` artificially rises
above the 0.78 threshold even for unrelated queries.

### 3.3 Vector row IDs are non-deterministic across restarts

`vector_db.py:276`:
```python
unique_id = f"fix-{abs(hash(error_text)) & ((1 << 128) - 1):032x}"
```

Python's builtin `hash()` is salted per process, so the same error text
produces a different ID every time the service restarts. Result: Slack
approvals that should update an existing row keep inserting new rows.
The duplicates accumulate; once the poisoning row exists, it is
effectively permanent.

### 3.4 Whole-blob SHA is used as the cache key

`analyzer_service.py:284`:
```python
error_hash = hashlib.sha256(error_text.encode()).hexdigest()
```

Any timestamp change in the blob produces a different SHA, so the Redis
`sme:fix:<hash>` and `ai:fix:<hash>` caches almost never hit. Every
request re-embeds and re-queries — giving the poisoning row another
opportunity to match.

### 3.5 Why these compound

| Bug | Alone it means… | Combined effect |
|---|---|---|
| 3.1 blob embedding | retrieval matches on context noise rather than root cause | wide similarity band to anything with similar surrounding build output |
| 3.2 L2 vs cosine | thresholds are miscalibrated | blob row scores above 0.78 for everything |
| 3.3 salted hash IDs | duplicate rows accumulate | any bad row is re-inserted forever, never updated |
| 3.4 SHA-of-blob cache | cache hit rate near zero | bad retrievals get re-evaluated every request |

Conclusion: **whichever approach we pick (A, B, or C), the deterministic
fixes in §3 must land.** Agents reasoning over a poisoned DB still
produce wrong answers — just more expensively.

---

## 4. Approach A — Full Agentic

### 4.1 Overview

Redesign the analyzer as a multi-agent system. Each agent is a focused
LLM call with a narrow role, structured JSON output, and (optionally) a
small set of tools. An orchestrator decides which agent runs next based
on the previous agent's output. Every request goes through the full
agent chain.

### 4.2 Architecture — the 7 agents

| # | Agent | Role | LLM? | Input | Output |
|---|---|---|---|---|---|
| A1 | **Classifier** | Parse raw error → canonical fingerprint + category + severity | Light (Haiku) | raw error + context | `{category, fingerprint, severity, key_tokens[]}` |
| A2 | **Retrieval** | Query vector DB + domain RAG, return ranked candidates | Tool-only | fingerprint, category, top_k | `[{candidate_id, stored_error, stored_fix, sim, meta}]` |
| A3 | **Deviation Analyzer** | Decide `exact / applicable_with_adjustments / partial / no_match` per candidate | Yes | current error, stored error, stored fix | `{match_quality, adjusted_fix?, reasoning, confidence}` |
| A4 | **Context Disambiguator** | Pick best among multiple applicable candidates using pipeline metadata | Maybe | applicable candidates, metadata | `{chosen_id, reasoning}` |
| A5 | **Solution Synthesizer** | Generate a fresh fix when no stored fix applies; cite any partial matches | Yes | error, context, domain snippet, partial matches | `{fix_text, confidence, cited_candidates[]}` |
| A6 | **Validator** | Safety sanity check (dangerous commands, unrelated repo, hallucinated file paths) | Light | final fix, current error | `{pass, warnings[], block_reasons[]}` |
| A7 | **Reporter** | Format final structured output to Slack blocks + developer DM | No | structured fix | Slack payload |

### 4.3 Per-request flow

```
POST /api/analyze
  │
  ├─ Redis sme:fix:<fp> / ai:fix:<fp>  (pre-agent shortcut; ~70% hit rate in theory)
  │     └─ HIT → A7 format, done
  │
  ├─ A1 Classifier                       produces fingerprint + category
  ├─ A2 Retrieval                        top-K candidates
  │     └─ 0 candidates → A5
  │
  ├─ A3 Deviation Analyzer (parallel, top-3 candidates)
  │     ├─ any exact_match → pick, skip to A6
  │     ├─ ≥2 applicable  → A4
  │     ├─ 1 applicable   → pick, skip to A6
  │     └─ all no_match   → A5
  │
  ├─ A4 Disambiguator  (only on multi-applicable)
  ├─ A5 Synthesizer    (only when no reusable fix)
  ├─ A6 Validator      (final gate)
  └─ A7 Reporter
```

Each agent appends an `audit_trail` entry with `agent`, `ms`, `tokens_in`,
`tokens_out`, `result_summary` — essential for debugging.

### 4.4 Pros

- **Highest accuracy ceiling** on ambiguous cases. Estimated 85–90% on
  the "variant" bucket (same root cause, different specifics) versus
  ~60–70% for Approach B.
- **Natural-language reasoning** about whether a stored fix actually
  applies, not just cosine similarity.
- **Explainability** — each agent's reasoning is captured; SMEs can see
  *why* a fix was chosen.
- **Combinable partial fixes** — A5 can cite multiple near-misses when
  synthesizing a fresh answer.
- **Future flywheel**: if we grow the approved-fix corpus, per-agent
  prompts can be iterated independently without touching the pipeline.

### 4.5 Cons

- **Cost**: 4–6 LLM calls per request, regardless of difficulty. At
  1,000 requests/day that is ~6,000 LLM calls/day.
- **Latency**: 12 s p50, 40 s p99 (sequential agent chain with parallel
  A3 fan-out). Today's p50 is ~250 ms on cache hits.
- **Determinism loss**: same error can yield different advice on
  different days (temperature > 0, agent variance). SMEs may lose trust.
- **Code complexity**: ~2,500 LoC added (agents, orchestrator, prompts,
  schemas, tool loop, audit trail).
- **New failure modes**: malformed JSON output, agent loops, prompt
  injection from log content flowing into A3/A5 prompts.
- **Prompt-injection risk** is real — build logs can contain anything,
  including text that looks like an instruction.
- **Observability overhead**: without a full Grafana dashboard for
  per-agent metrics, debugging becomes nearly impossible.

### 4.6 Per-request cost & latency

| Metric | Value |
|---|---|
| Cost per 1k requests | ~$30–$40 |
| LLM calls per request | 5–6 |
| p50 latency | 12 s |
| p99 latency | 40 s |
| Code complexity (LoC delta) | ~2,500 |
| Operational complexity | High |

---
