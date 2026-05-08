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

**What we are proposing.** A *four-agent* agentic design layered on a
**deterministic foundation** that fixes the four bugs at the source:

- **Foundation Layer** (§5): Split error from context on the wire, normalize before
  embedding, switch Chroma to cosine distance, use deterministic SHA IDs, and
  update-not-insert on Slack approval.

- **Agentic Layer** (§6): Four specialized agents that cooperate on
  every request:
  - **A1 Error Summariser**: Parse and understand the error (lightweight,
    no LLM).
  - **A2 Deviation Analyzer**: Decide if a stored fix applies
    (`exact_match`, `applicable_with_adjustments`, `partial`,
    `no_match`).
  - **A3 Solution Synthesizer**: Generate fresh fixes when no stored
    fix applies.
  - **A4 Reporter**: Format and route the final answer to Slack.

**Headline numbers at 1,000 requests/day:**

| Metric | Today (broken) | 4-Agent (proposed) |
|---|---|---|
| Cost per 1k requests | ~$15 | ~$6–8 |
| LLM API calls per 1k requests | 1,000 (every request) | ~500–700 (A2 + A3 on candidate paths) |
| p50 latency | 5–8 s | 600 ms–12 s (depending on agent fan-out) |
| Wrong-answer rate (variant errors) | ~80% | ~8–10% |
| Code change | — | ~1,200 LoC + 350 LoC tests |

**Implementation order is non-negotiable.** Ship the deterministic
foundation first (Phase 1). Add agents A1–A4 behind feature flags in
Phase 2. Roll out at 10% traffic, then 100%. Every phase is revertible
in <60s via env-var flip.

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

## 4. The Four-Agent Design — Overview

A layered architecture where a deterministic foundation routes to
specialized agents only when needed.

```
                    ┌─────────────────────────────────────────┐
                    │   Agentic Layer                         │
                    │   A1: Error Summariser                  │
                    │   A2: Deviation Analyzer (on candidates) │
                    │   A3: Solution Synthesizer (on misses)  │
                    │   A4: Reporter (output routing)         │
                    └─────────────────────────────────────────┘
                              ▲       ▲       ▲
                              │       │       │
                    ┌─────────┴───────┴───────┴───────────────┐
                    │   Foundation Layer — Deterministic      │
                    │   Split error/context, normalize,       │
                    │   cosine, deterministic IDs,            │
                    │   context-cosine disambiguation,        │
                    │   update-not-insert                     │
                    │   (handles cache hits + clear cases)    │
                    └──────────────────────────────────────────┘
```

The foundation handles the ~70% cache-hit traffic and ~15% clear-hit
/ clear-miss traffic. Agents fire only when their judgment is needed:

- **A1** parses every request (lightweight, no LLM).
- **A2** fires on ambiguous candidates (15% of non-cache traffic).
- **A3** fires on vector-DB misses (5% of non-cache traffic).
- **A4** formats and routes the final answer (every request).

**Why four agents and not fewer.** Breaking the pipeline into four
distinct agents separates concerns: error understanding (A1),
deviation detection (A2), fix synthesis (A3), and output formatting
(A4). This makes each agent simpler to test, reason about, and
iterate on independently. A2 and A3 run in parallel where
applicable, reducing total latency on the critical path.

### 4.1 Combined per-request flow

```
POST /api/analyze
  │
  ├─ Redis sme:fix:<fp> / ai:fix:<fp>           cache hits, ~70% of traffic
  │     └─ HIT → A4 Reporter → DM developer, done
  │
  ├─ A1 Error Summariser: parse + normalize error fingerprint
  │
  ├─ VectorDB.lookup_candidates(fp, top_k=10, threshold=0.90)
  │
  ├─ 0 candidates ≥ 0.90                        → A3 Solution Synthesizer (generate fresh)
  │
  ├─ 1 candidate ≥ 0.95                         → return stored fix (high-confidence)
  │     └─ A4 Reporter → DM developer, done
  │
  ├─ 1 candidate in [0.90, 0.95)                → A2 Deviation Analyzer
  │     ├─ exact_match                          → store + A4 Reporter
  │     ├─ applicable_with_adjustments          → adjust + store + A4 Reporter
  │     ├─ partial / no_match                   → A3 Solution Synthesizer (generate fresh)
  │
  └─ ≥2 candidates ≥ 0.90                       → A2 on each (parallel, top-3)
        ├─ any exact_match                      → store + A4 Reporter
        ├─ 1 applicable (adjusted)              → store + A4 Reporter
        ├─ ≥2 applicable                        → context-cosine tie-breaker → store + A4 Reporter
        └─ none applicable                      → A3 Solution Synthesizer (generate fresh)
```

---

## 5. Foundation Layer — Deterministic Fixes

This is what we ship in Phase 1 and what every subsequent layer
depends on. Without this, an A3 agent reasoning over a poisoned DB
just produces wrong answers more expensively.

### 5.1 Wire contract change (extractor → analyzer)

Today the analyzer receives `FailedStep.error_lines = [<one big
blob>]`. Change it to a list of per-region objects:

```json
{
  "step_name": "...",
  "errors": [
    {
      "error_lines":       ["npm ERR! code ERESOLVE", "npm ERR! peer dep ..."],
      "context_lines":     ["Resolving dependencies...", "..."],
      "error_fingerprint": "npm err code eresolve peer dep <VERSION> <PATH>"
    }
  ]
}
```

Keep `error_lines: List[str]` on the analyzer for one release overlap
so old extractor clients continue working.

### 5.2 Normalization

New helper `normalize_error_text(error_lines) -> str`:

- strip `"Line N:"` prefixes
- strip ISO timestamps, `[HH:MM:SS]`, epoch millis
- replace absolute paths, SHAs, UUIDs, container IDs, ports with
  placeholders (`<PATH>`, `<SHA>`, …)
- collapse whitespace, lowercase
- truncate to 512 tokens (granite-embedding's input ceiling)

The normalized text is used for both the deterministic row ID and
the embedding input.

### 5.3 Cosine distance + deterministic IDs

At first write, create the Chroma collection with explicit cosine
space:

```python
client.get_or_create_collection(
    name="fix_embeddings_v2",
    metadata={"hnsw:space": "cosine"},
)
```

L2-normalize every embedding vector before `add()` and `query()`.
Replace the Python `hash()`-based ID with `sha256(fingerprint)`
(stable across process restarts). Tighten the similarity threshold
for the error-only embedding to **0.90** (meaningful on cosine,
unlike today's 0.78 on miscalibrated L2).

### 5.4 Store only the error in the vector DB

Rewrite `save_fix_to_db`:

- embedding input = normalized fingerprint (short, specific)
- document = `fix_text`
- metadata: `error_fingerprint`, `raw_error_lines`, `context_sample`
  (first ~2 KB of joined context, **metadata only**, never embedded),
  `approver`, `status`, `fix_id`, `revision`, repo/branch/job

Context lines stay available for display and disambiguation but
never pollute the retrieval embedding.

### 5.5 Context-based disambiguation

`lookup_existing_fix` returns top-K=10 candidates with cosine
similarity ≥ 0.90. When more than one passes:

- compute `ctx_sim = cosine(embed(query.context_lines),
  embed(candidate.context_sample))`
- score = `0.7 * error_sim + 0.3 * ctx_sim`
- return the top score if `score_1 − score_2 > 0.05`; otherwise
  let A3 (Layer 2) decide

No LLM call is involved in this disambiguation step — pure
deterministic vector math.

### 5.6 Update-not-insert on Slack approval

In `slack_reviewer.py`, replace `collection.add()` with a look-up-
then-`collection.update()` on the deterministic fingerprint ID. The
same fix approved twice updates the same row (with `revision`
bumped in metadata) instead of creating a duplicate.

### 5.7 What the foundation alone fixes

| Today's failure | After foundation alone |
|---|---|
| One huge blob matches every query | Embedding is short and specific; blob doesn't exist |
| Threshold 0.78 false-positives | 0.90 cosine on normalized text, properly calibrated |
| Approvals create duplicates | Fingerprint sha256 ID; same error → same row |
| Cache hit rate near zero | Fingerprint key is stable across timestamp changes |
| Variant errors return stored fix verbatim | Still returns verbatim — Layer 2 (A3) handles this |

---

## 6. Agentic Layer — Four Coordinated Agents

| # | Agent | Role | LLM? | Input | Output |
|---|---|---|---|---|---|
| **A1** | Error Summariser | Parse, normalize, and understand the error | No | Error lines + context sample | Canonical error fingerprint + summary |
| **A2** | Deviation Analyzer | Decide if stored fix applies (exact/adjusted/partial/no) | Yes | Current error + stored candidate (error + fix) | `match_quality`, `adjusted_fix`, confidence, reasoning |
| **A3** | Solution Synthesizer | Generate fresh fix when no stored fix applies | Yes | Error fingerprint + context | `fix_text`, confidence, reasoning |
| **A4** | Reporter | Format final answer and route to Slack | No | Structured result (stored or synthesized fix) | Slack DM payload + metadata |

### 6.1 A1 Error Summariser

**Role:** Parse and normalize the incoming error into a canonical
fingerprint, removing noise (timestamps, paths, SHAs) and identifying
the core failure pattern.

**Inputs:**
- `error_lines`: List of raw error message strings
- `context_lines`: Surrounding log context (for display, not embedding)

**Outputs:**
- `error_fingerprint`: Normalized, stable identifier for vector DB
  queries
- `summary`: Plain-text description of the error (for LLM context)

**Implementation:** This is deterministic code (no LLM). A1 calls
`normalize_error_text` from §5.2 and returns the result. It runs on
every request. Failure is not an option — on normalization failure,
use raw error lines as-is.

### 6.2 A2 Deviation Analyzer

**Role:** Given a stored fix candidate from the vector DB and the
current error, decide whether the stored fix applies as-is, requires
small adjustments, partially applies, or doesn't apply.

**Inputs:**
- Current error: normalized fingerprint, raw lines, context sample
- Stored candidate: stored error + stored fix text

**Outputs:** Strict JSON verdict:
```json
{
  "match_quality":  "exact_match | applicable_with_adjustments | partial | no_match",
  "confidence":     0.92,
  "reasoning":      "<1-2 paragraphs>",
  "adjusted_fix":   "<modified fix text, only if applicable_with_adjustments>",
  "adjustments":    ["downgrade react: 17 -> 18.2", "path: /opt/old -> /opt/new"]
}
```

**Trigger:** A2 runs in two scenarios:
1. Exactly 1 candidate with cosine similarity in `[0.90, 0.95)`.
2. ≥2 candidates ≥ 0.90 (A2 runs in parallel, top-3 candidates).

**Caching:** Results cached in Redis `agent:deviation:sha(fingerprint
+ candidate_id)` for 7 days. Two developers hitting the same error
within a week share the decision.

**Failure handling:** If A2 times out (>6 s), returns malformed JSON
after one retry, or returns confidence <0.5, the orchestrator routes
to A3 (Solution Synthesizer). No regression.

### 6.3 A3 Solution Synthesizer

**Role:** Generate a fresh fix from scratch when no stored fix
candidate exists or applies. This is the existing `/api/analyze` LLM
fallback, now formalized as an agent.

**Inputs:**
- Error fingerprint (from A1)
- Raw error lines + context
- Optional: partial-match citations from A2 (if A2 found a
  `partial` match)

**Outputs:** JSON result:
```json
{
  "fix_text":    "<generated fix steps>",
  "confidence":  0.85,
  "reasoning":   "<explanation>",
  "source":      "synthesized | partial_citation"
}
```

**Trigger:** A3 runs in two scenarios:
1. Vector DB returns 0 candidates ≥ 0.90 (true miss).
2. A2 returns `partial` or `no_match` on all candidates.

**Caching:** Results cached in Redis `agent:synthesizer:sha(fingerprint)`
for 7 days. Same error asked twice within a week returns the same fix.

**Failure handling:** If A3 times out or fails, respond with "unable
to analyze" rather than a wrong fix. Let the user escalate to Slack.

### 6.4 A4 Reporter

**Role:** Take the final decision (stored fix from vector DB, adjusted
fix from A2, or synthesized fix from A3) and format it into a Slack
DM payload with appropriate metadata and confidence level.

**Inputs:**
- The final fix (fix_text + source + confidence)
- Metadata: error_fingerprint, candidate similarity (if applicable),
  A2 reasoning (if applicable)

**Outputs:** Slack message payload with:
- Fix text (properly formatted)
- Confidence indicator
- Citation of stored vs synthesized
- SME "Approve/Edit" buttons (if applicable)
- Link to full error details

**Implementation:** Deterministic code (no LLM). A4 runs on every
request that reaches the output stage.

### 6.5 Caching and Coordination

Each agent decision is independently cached in Redis:

| Agent | Cache key | TTL | Saves |
|---|---|---|---|
| A2 | `agent:deviation:sha(fingerprint + candidate_id)` | 7 days | LLM cost |
| A3 | `agent:synthesizer:sha(fingerprint)` | 7 days | LLM cost |

On a cache hit (second request for the same error pattern within a
week), downstream agents are skipped. A4 uses the cached decision to
format the output.

**Coordination:** A2 and A3 can run in parallel when multiple
candidates are present:
- A2 evaluates the top-3 candidates in parallel.
- A3 starts immediately on `0 candidates ≥ 0.90`.
- A4 waits for the first decisive result (any `exact_match` or
  `applicable_with_adjustments`, or timeout).

### 6.6 What the four-agent design measurably adds

| Error pattern | Stored fix case | Foundation alone | With 4 agents | Gain |
|---|---|---|---|---|
| Version pinning mismatch | react@16→17 fix, error has react@18.2 | Returns 17 verbatim (wrong) | A2 adjusts to 17.0.x range | ~20% accuracy lift |
| Node/path renaming | Jenkins node-12 fix, error has node-19 | Returns node-12 fix (wrong) | A2 adjusts node ID | ~15% accuracy lift |
| Missing artifact (lib version) | Maven fix for lib:1.2.3, error shows lib:1.4.0 | Returns 1.2.3 fix (wrong) | A2 or A3 adapts version | ~20% accuracy lift |
| Novel error (no stored match) | No candidate ≥ 0.90 | Routes to A3 (old LLM) | A3 synthesizes with context + citations | Same cost, better reasoning |

Variant bucket accuracy with foundation alone: ~60–70%. With four agents:
~88–92%. Cost per synthesized answer: ~$0.015 (vs ~$1/request for
always-on LLM).

---

## 7. Past Errors and Migration

### 7.1 What "past errors" are

The fixes already approved by SMEs over the past week, sitting in
the current Chroma `fix_embeddings` collection. Each is a real
error + real SME-approved fix + metadata.

### 7.2 Why preserving them is high-value

These are the corpus that makes the vector DB economically useful.

| Effect | Empty DB (start fresh) | With cleaned past errors |
|---|---|---|
| Cost per 1k requests | ~$15 (every request hits LLM) | ~$3 (Hybrid hit rates) |
| p50 latency | ~5–8 s | 400 ms–8 s |
| SME workload | Re-approve errors already approved once | Approvals accumulate; one decision serves N future devs |
| Same error asked twice | Different LLM answers possible | SME-approved answer persists |
| Cold-start | System starts cold | System starts hot |

Concrete benefits:

1. **Flywheel.** One SME approval serves N future developers. Starting
   fresh resets the wheel.
2. **Cost leverage.** At a 50% hit rate on past errors, ~$13 saved
   per 1 k requests — roughly $400/month at 1 k/day.
3. **Consistency.** Developers learn "this error has a known fix";
   that breaks the moment the DB is emptied.
4. **Latency floor.** Cached / vector-DB answers return in
   hundreds of milliseconds; LLM calls take seconds.
5. **Encoded tribal knowledge.** Some approved fixes capture things
   a general-purpose LLM cannot reproduce — internal system names,
   custom Jenkins agents, repo-specific quirks.
6. **A3 leverage.** Every A3 candidate is a *past* fix. More past
   fixes = more opportunities for A3 to find an
   `applicable_with_adjustments` match = fewer expensive Synthesizer
   fallbacks.

### 7.3 Why we can't just import them as-is

- Poisoning rows (>5 KB blobs) carry over and continue contaminating
  retrieval.
- Duplicate rows from the salted-hash ID bug persist forever.
- Stored `error_text` has timestamps/paths baked in; without
  re-normalizing, those rows can't match new normalized queries —
  they sit in the DB unreachable.

### 7.4 The migration script

A one-off `scripts/migrate_vector_db.py` does the cleanup:

1. Open the existing `fix_embeddings` collection read-only.
2. For each row:
   - Re-derive `error_fingerprint` via `normalize_error_text`.
   - **Skip** if `len(metadata.error_text) > 5 KB` (poisoning
     outliers), `fix_text` empty, or `status` not in
     `("approved", "edited")`.
   - Re-embed normalized fingerprint with `granite-embedding`.
   - L2-normalize the vector.
   - Write to `fix_embeddings_v2` with deterministic ID
     `sha256(fingerprint)`. On duplicate fingerprint, keep the most
     recent approval and bump `revision`.
3. Run in staging first against a copy of prod. After verification,
   flip `CHROMA_COLLECTION=fix_embeddings_v2` on the analyzer and
   restart. Keep the old collection on disk for rollback.

### 7.5 Expected outcome

Rough estimate: ~70% of existing rows carry over cleanly into v2.
The remaining ~30% are the poisoning outliers and the salted-hash
duplicates we want gone. Numbers will firm up after the script runs
in Phase 1.

---

## 8. Why Four Agents (and not the alternatives)

### 8.1 Why not deterministic alone

The deterministic foundation handles ~85% of requests correctly: cache
hits, exact vector matches, clear misses. What it cannot do is reason
about the **variant bucket** — same root cause, different specifics.
Without A2 and A3, those queries either return a stored fix verbatim
(developer has to mentally translate the version number) or fall
through to the LLM unnecessarily.

Foundation alone:
- ✅ Fixes the four root-cause bugs.
- ✅ Cheapest possible — ~$1.50 per 1 k requests.
- ❌ Variant accuracy: ~60–70%.
- ❌ No fresh synthesis on novel errors.

### 8.2 Why not one agent per request (always-on agentic)

Always running agents on every request (cache hits included) pays the
LLM tax on the 70% of traffic that are trivial cache lookups. At 1 k
requests/day:

- **Cost**: ~$20–30/day vs ~$6–8/day for four-agent selective model.
- **Latency**: 8–12 s p50 vs 600 ms–8 s for selective agents.
- **Determinism**: always-on agents are non-deterministic; same error
  yields different advice on different days. SMEs lose trust.

The accuracy gain is marginal; we'd be paying ~4–5× the cost for
~2–3% accuracy lift on top of the four-agent design.

### 8.3 Four agents balanced correctly

- **A1 (every request):** Lightweight parsing, no LLM cost.
- **A2 (ambiguous candidates only):** ~15% of non-cache traffic.
  Judges whether stored fix applies.
- **A3 (misses only):** ~5% of non-cache traffic. Synthesizes fresh
  fixes with context.
- **A4 (every request):** Lightweight formatting, no LLM cost.

Collectively:
- ~$6–8/day at 1k requests/day (vs $15 today, $1.50 deterministic
  alone).
- 600 ms–8 s p50 latency depending on path.
- ~88–92% accuracy on variants (vs 60–70% deterministic alone).
- Caching compounds the win: repeated errors amortize A2/A3 cost
  across multiple developers.
- Each agent is simple enough to test, reason about, and iterate on
  independently.

---

## 9. What Changes — File-by-File

| # | File | Change | Est LoC |
|---|---|---|---|
| 1 | `src/log_error_extractor.py` | Split `extract_error_sections` to emit per-region `{error_lines, context_lines, error_fingerprint}` | 60 |
| 2 | `src/api_poster.py` | New `errors` payload shape; legacy `error_lines` kept for one release | 30 |
| 3 | `build-failure-analyzer/analyzer_service.py` | `FailedStep` schema → `errors: List[ErrorEntry]`; cache keys use fingerprint; delegate to orchestrator | 80 |
| 4 | `build-failure-analyzer/vector_db.py` | `normalize_error_text`; deterministic sha256 ID; cosine space; `context_sample` metadata; top-K disambiguation | 150 |
| 5 | `build-failure-analyzer/resolver_agent.py` | Pass `error_fingerprint` + `context_lines` through; enrich A3 prompt with partial-match citations | 40 |
| 6 | `build-failure-analyzer/slack_reviewer.py` | `collection.update()` on fingerprint ID (replaces `add()`) | 20 |
| 7 | `build-failure-analyzer/agents/base.py` *(new)* | Bounded agent runner, tool-use loop, JSON schema validation, audit-trail | 120 |
| 8 | `build-failure-analyzer/agents/summarizer.py` *(new)* | A1 Error Summariser (deterministic fingerprinting) | 40 |
| 9 | `build-failure-analyzer/agents/deviation.py` *(new)* | A2 Deviation Analyzer (LLM agent) | 100 |
| 10 | `build-failure-analyzer/agents/synthesizer.py` *(new)* | A3 Solution Synthesizer (LLM agent, refactored from `resolver_agent.py`) | 80 |
| 11 | `build-failure-analyzer/agents/reporter.py` *(new)* | A4 Reporter (deterministic formatting) | 60 |
| 12 | `build-failure-analyzer/orchestrator.py` *(new)* | State machine from §4.1; agent routing; caching; feature flags | 180 |
| 13 | `build-failure-analyzer/prompts/deviation.md` *(new)* | A2 system + user prompts | — |
| 14 | `build-failure-analyzer/prompts/synthesizer.md` *(new)* | A3 system + user prompts (refactored from existing) | — |
| 15 | `scripts/migrate_vector_db.py` *(new)* | One-off migration script | 80 |
| 16 | Tests (`tests/`, `build-failure-analyzer/tests/`) | Unit tests + golden-set integration | 350 |
| 17 | `build-failure-analyzer/eval/regression_set.jsonl` *(new)* | 50 seed pairs + augmented variants | data |
| 18 | `build-failure-analyzer/eval/run_eval.py` *(new)* | Replay harness + grading | 120 |

**Total:** ~1,380 LoC product code + 350 LoC tests + eval tooling
and seed data. Estimated 3–4 weeks for one engineer including
Phase 0.

---

## 10. Phased Rollout

| Phase | Scope | Duration | Gate to advance | Rollback |
|---|---|---|---|---|
| **0 — Eval harness** | Build regression suite from 50 seed pairs. Augment to ~200–400 via prod Chroma dump + synthetic variants + LLM stress tests (see §13). | ~1 week | Regression suite runs in CI; baseline grades published | n/a — pure tooling |
| **1 — Land foundation** | Implement §5 in extractor + analyzer. Run migration script (§7.4). Swap `CHROMA_COLLECTION=fix_embeddings_v2`. Implement A1 and A4 (no LLM). | ~1 week | No regressions on regression suite; SME spot-check of 20 live responses ≥ baseline; poisoning count = 0; A1 + A4 p99 < 100 ms | Revert env var to old collection |
| **2 — Add A2 in shadow** | Implement `agents/base.py`, `agents/deviation.py`, `orchestrator.py`, A2 prompt. Feature flag `AGENTS_MODE=off\|shadow\|on`. In shadow, A2 runs on ambiguous candidates but user response comes from foundation. A3 still routes to old LLM fallback. | ~1 week | A2 shadow decisions match SME verdicts ≥80% over 2 weeks; A2 p99 < 6 s; schema failure rate < 2%; cost tracking within ±10% forecast | Flag back to `off` |
| **3 — Add A3 in shadow** | Implement `agents/synthesizer.py`, A3 prompt. Run A3 in parallel with A2 shadow. Both log decisions but user response from foundation + old LLM fallback. | ~1 week | A3 shadow decisions on novel errors match prior LLM baseline ≥90%; A3 p99 < 8 s; combined (A2 + A3) cost within forecast ±15% | Flag back to off, keep A2 shadow |
| **4 — 10% traffic, A2+A3 active** | Flip `AGENTS_MODE=on` for 10% of `/api/analyze` traffic. A2 evaluates candidates; A3 synthesizes on misses. Monitor cost, latency, approval rate, developer feedback, SME satisfaction. | ~2 weeks | Cost within forecast; approval rate ≥ Phase 1 baseline; no safety incidents; A2 match_quality distribution stable | Flag back to off |
| **5 — 50% → 100% rollout** | Gradual ramp-up to 100% over 1 week (10% → 50% → 100%). Final stability gate: 1 week at 100%. | ~2 weeks | Stable metrics for 1 week at 100%; SME feedback positive; cost stable | Revert to Phase 1 foundation only |
| **6 (optional)** | Further agents or enhancements only if signal requires: extend A2 for new error categories, optimize A3 prompt for low-confidence cases. | n/a | per-change eval lift ≥ 3% | Per-change flag |

### 10.1 Non-negotiables

- **Phase 0 before Phase 1.** Regression suite is the single biggest
  risk item; without it we have no fallback on regression.
- **Phase 1 before Phase 2.** A2/A3 reasoning over un-migrated DB
  still poisons results.
- **Foundation (Phase 1) must be stable.** Phase 2–5 assume Phase 1
  is baseline. Any Phase 1 regression blocks Phase 2.
- **Feature flag everywhere.** Every phase must be revertible in
  <60s via env-var flip. No code rollbacks on weekends.

---

## 11. Open Questions for Team

The team needs to make calls on these before implementation begins.

1. **Orchestrator timeout vs upstream SLA.** Four-agent total budget
   is ~60 s per request (A1 <100 ms, A2 up to 6 s per candidate
   parallel, A3 up to 8 s, A4 <100 ms). Does Jenkins/GitLab
   post-build hook tolerate that? If timeout, risk duplicate analyses.

2. **Agent parallelization strategy.** Should A2 and A3 run in true
   parallel (both fire immediately when triggered), or sequentially
   (A2 first, A3 on A2 failure/miss)? Parallel is faster but doubles
   cost on some paths.

   Recommendation: Parallel, with early exit on first decisive
   result (A2 exact_match). Budget enforcer caps total cost per
   request.

3. **Eval-harness ownership.** Phase 0 is the biggest risk item.
   Who owns curating seed pairs, augmentation, and maintaining
   replay/grading over time?

4. **Per-team threshold tuning.** Should the 0.90 vector threshold,
   top-K fan-out (currently 3), context-cosine tie margin (0.05),
   and A2/A3 confidence floors be configurable per repo?
   Different teams have very different log styles.

   Recommendation: Centralize initially; expose as env-vars only if
   production tuning is needed.

5. **A2 `adjusted_fix` approval gating.** When A2 returns an
   adjusted version of a stored fix, should it:
   - (a) go to developer directly with "adjusted by AI" label;
   - (b) require lightweight SME thumbs-up in Slack; or
   - (c) require full Approve/Edit cycle?

   Recommendation: (a) — base fix is SME-approved, adjustments are
   mechanical (version numbers, paths). Lighter touch saves SME time.

6. **A3 confidence floor.** Should A3 synthesized answers below a
   confidence threshold (e.g., <0.70) be routed to human review
   instead of auto-posting? Balances automation vs accuracy.

   Recommendation: <0.60 → human escalation to Slack; 0.60–0.80 →
   post with warning label; ≥0.80 → post normally.

7. **Bedrock migration scope.** Branch is
   `claude/setup-log-analysis-bedrock-gmLHN`. Does the Bedrock LLM
   swap complete within this scope or as a separate PR? Four-agent
   design is LLM-backend-agnostic.

   Recommendation: Within scope — agents abstract the LLM backend.

8. **Salvage existing approved fixes.** Migration carries over ~70%
   of `fix_embeddings` (dropping poisoning and duplicates). Start
   with salvaged corpus or reset to empty?

   Recommendation: Salvage. ~70% hit rate on past errors justifies
   the migration effort; resetting loses accumulated tribal knowledge.

9. **`pipeline_context` collection.** Domain-RAG uses threshold 0.55
   on L2 space. Should it migrate to cosine with adjusted threshold,
   or leave as-is?

   Recommendation: Leave for now, non-critical path. Revisit only if
   precision drops in production.

---

## 12. Appendix A — A2 Deviation Analyzer Specification

### 12.1 Role

Given the current error (normalized fingerprint + raw lines + context
sample) and a candidate stored fix (its stored error + its stored fix
text), decide whether the stored fix applies. If it applies with
small adjustments (version numbers, paths, identifiers), emit an
`adjusted_fix`. Do not invent new fixes — return `partial` or
`no_match` to fall through to A3 Solution Synthesizer.

### 12.2 Output JSON schema

```json
{
  "type": "object",
  "required": ["match_quality", "confidence", "reasoning"],
  "properties": {
    "match_quality": {
      "enum": ["exact_match", "applicable_with_adjustments", "partial", "no_match"]
    },
    "confidence":   { "type": "number", "minimum": 0, "maximum": 1 },
    "reasoning":    { "type": "string", "maxLength": 2000 },
    "adjusted_fix": { "type": "string" },
    "adjustments":  { "type": "array", "items": { "type": "string" } }
  }
}
```

### 12.3 System prompt sketch

> You compare a CURRENT CI/CD build error with one STORED error and
> its SME-approved STORED fix, and decide whether the stored fix
> applies.
>
> Output STRICT JSON matching the provided schema. No prose outside
> the JSON object.
>
> Match-quality values:
> - `exact_match` — identical root cause; fix applies verbatim.
> - `applicable_with_adjustments` — same root cause; small edits
>   needed (version numbers, paths, identifiers). Provide `adjusted_fix`
>   and list changes in `adjustments`.
> - `partial` — some steps of stored fix apply; others don't.
> - `no_match` — different root cause entirely.
>
> Do NOT invent new remediation steps. If the stored fix mostly
> applies, mark as `applicable_with_adjustments`. Otherwise mark
> `partial` or `no_match` and let A3 synthesize fresh.

### 12.4 Trigger conditions

A2 fires only when the orchestrator state machine reaches one of:

- Exactly 1 candidate with cosine similarity in `[0.90, 0.95)`.
- ≥2 candidates with cosine similarity ≥ 0.90 (A2 runs in parallel,
  top-3 candidates).

Never fires when:
- 0 candidates ≥ 0.90 → A3 (synthesize fresh).
- 1 candidate ≥ 0.95 → high-confidence exact, skip to output.
- Cache shortcut hits → skip to A4 (report cached result).

### 12.5 Caching

- Redis key: `agent:deviation:sha(query_fingerprint + candidate_id)`
- TTL: 7 days
- Two developers hitting the same error within a week share the
  decision; second request pays $0 for A2.

### 12.6 Cost & latency

- Average input: ~3 K tokens (prompt + error + candidate fix).
- Average output: ~300 tokens.
- Bedrock Claude Sonnet pricing: ~$0.015 per A2 call.
- p99 latency: ~6 s (with one retry on JSON schema failure).
- Typical: 2–3 s (most decisions are clear).

---

## 12.7 Failure recovery

If A2:
- times out (>6 s) → skip to A3 (synthesize fresh).
- returns malformed JSON after one retry → skip to A3.
- returns confidence <0.5 → log as uncertain; skip to A3.

In all cases, worst-case is A3 synthesizes a fresh answer. No
regression.

---

## 13. Appendix B — A3 Solution Synthesizer Specification

### 13.1 Role

Generate a fresh fix from scratch when no stored fix candidate exists
or applies. This is the existing `/api/analyze` LLM fallback,
formalized as an agent with structured output and caching.

### 13.2 Output JSON schema

```json
{
  "type": "object",
  "required": ["fix_text", "confidence", "reasoning"],
  "properties": {
    "fix_text":    { "type": "string" },
    "confidence":  { "type": "number", "minimum": 0, "maximum": 1 },
    "reasoning":   { "type": "string", "maxLength": 2500 },
    "source":      { "enum": ["synthesized", "partial_citation"] },
    "citations":   {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "error_fingerprint": { "type": "string" },
          "step": { "type": "string" }
        }
      }
    }
  }
}
```

### 13.3 System prompt sketch

> You are a CI/CD troubleshooting expert. Given a build error, generate
> step-by-step remediation.
>
> Output STRICT JSON matching the schema. No prose outside the JSON.
>
> Guidelines:
> - Be specific: reference exact version numbers, paths, or
>   identifiers from the error.
> - Be concise: 3–7 actionable steps.
> - If given partial-match citations, prioritize steps from those
>   fixes that are likely to help.
> - If you are low-confidence (<0.60), say so in `confidence`.
> - Avoid generic advice ("update dependencies", "check permissions")
>   without specifics.

### 13.4 Trigger conditions

A3 fires in two scenarios:

1. Vector DB returns 0 candidates ≥ 0.90 (true miss).
2. A2 returns `partial` or `no_match` on all evaluated candidates.

A3 never fires when:
- Cache shortcut hits.
- Single candidate ≥ 0.95 (skip to output).
- A2 returns `exact_match` or `applicable_with_adjustments` (skip
  to output).

### 13.5 Caching

- Redis key: `agent:synthesizer:sha(query_fingerprint)`
- TTL: 7 days
- Same error asked twice within a week returns the same synthesized
  fix.

### 13.6 Cost & latency

- Average input: ~4 K tokens (error + context + optional citations).
- Average output: ~400 tokens (fix steps + reasoning).
- Bedrock Claude Sonnet pricing: ~$0.020 per A3 call.
- p99 latency: ~8 s (with one retry on schema failure).
- Typical: 3–4 s.

### 13.7 Failure recovery

If A3:
- times out (>8 s) → escalate to human review (post in Slack with
  "timeout, needs manual review").
- returns malformed JSON after one retry → same escalation.
- returns confidence <0.50 → post with "low confidence" flag,
  invite human review.

For Phase 1–3, low-confidence answers still post (so the system
accumulates real production signals). Phase 4+ may route <0.60 to
human review if metrics warrant.

---

### 14.1 Why 50 one-line pairs is not enough on its own

**Statistical power.** At n=50 the standard error on an accuracy
estimate near 80% is roughly ±5.7%. The 95% CI for the *difference*
between two approaches is ±16–18 percentage points. The 3–4% overall
lift Hybrid offers is invisible at this sample size — only
catastrophic regressions (~20%+) are reliably detectable.

**Coverage gaps.** Clean one-line pairs do not exercise:

| Pipeline feature | Exercised by one-line pairs? |
|---|---|
| Normalizer (strip timestamps, paths, SHAs, line prefixes) | No — nothing to strip |
| Context-cosine disambiguator (§5.5) | No — no context lines present |
| A3 `adjusted_fix` / `adjustments` output | Barely — no version numbers or paths to adjust |
| Multi-region merging in the extractor | No |
| Blob-poisoning regression | No — clean inputs do not reproduce the bug |
| Deterministic fingerprint ID | Yes |
| Cosine similarity threshold | Yes (only on clean short inputs) |
| LLM Synthesizer fallback | Yes |

### 14.2 Three-track mitigation

**Track 1 — Reframe the 50 as a regression suite, not a statistical
benchmark.** Each pair becomes a pass/fail assertion: *given this
error, the final response must contain these keywords and must not
contain these anti-keywords.* Runs in CI on every PR. Catches
catastrophic regressions; cannot prove "A is better than B".

**Track 2 — Augment the corpus to ~200–400 pairs in a week.**

- (a) **Prod Chroma dump.** Export all current `fix_embeddings` rows
  with `status in ("approved", "edited")`. Drop poisoning rows
  (>5 KB) and duplicates. Yield: 50–200 pairs with richer text than
  the seed 50.
- (b) **Synthetic variants of the 50 seeds.** Author 3–5 variants
  per seed that change version numbers, file paths, timestamps, or
  container IDs but should still map to the same fix. Tests
  normalizer + A2/A3 directly. Yield: 150–250 new pairs.
- (c) **LLM-generated stress tests.** Use Claude to paraphrase each
  seed into 2–3 realistic variants with surrounding log noise.
  Flags brittle normalizer regexes and A2/A3 prompt failure modes.
  Yield: 100–150 pairs labeled "synthetic, not gold".

Combined: 50 → ~400 pairs. Enough for Phase-1-grade offline checks.

**Track 3 — Make live shadow mode the primary accuracy signal.**
Offline eval at n=50–400 cannot distinguish small lift from noise.
Production telemetry can. Phase 2 runs A2 in shadow mode; Phase 3
adds A3 shadow. Over 2 weeks at 1,000 requests/day that is ~15,000
real-world samples per agent — far stronger than any offline eval.

### 14.3 Revised phase gates

| Phase | Sparse-data gate |
|---|---|
| 0 | Build regression suite from 50 seeds + augment to ~200–400 via tracks 2(a–c); ship pass/fail CI harness |
| 1 | No regressions on regression suite + SME spot-check of 20 live responses ≥ baseline; A1/A4 latency <100 ms p99 |
| 2 | A2 shadow-mode decisions match SME verdicts ≥80% over 2 weeks; A2 p99 <6 s; cost ±10% forecast |
| 3 | A3 shadow decisions on novel errors ≥90% prior LLM baseline; A3 p99 <8 s; combined cost ±15% forecast |
| 4 | 10% traffic: cost within forecast; approval rate ≥ Phase 1 baseline; no safety incidents |
| 5 | 100% traffic: stable metrics for 1 week; SME feedback positive |

### 14.4 Feature deferrals

- **Context-cosine disambiguator (§5.5).** Ship behind sub-flag
  `CONTEXT_COSINE_ENABLED=false`; enable only after Phase 1 has
  real multi-line context samples.
- **A2 `adjusted_fix`.** Cannot be offline-tested without
  version-number / path variations. Track 2(b) synthetic variants
  *must* include those, else `applicable_with_adjustments` branch
  untested on day one.
- **A3 low-confidence handling.** Phase 1–3: post all answers
  (accumulate signal). Phase 4+: route <0.60 confidence to human
  review if metrics warrant.

### 14.5 What we need from the team

1. Read/export access to the current prod `fix_embeddings`
   collection (track 2(a)).
2. One SME-hour to spot-check the first 20 synthetic variants
   (track 2(b)) so we confirm "same fix should still apply" before
   generating the rest.
3. Agreement that Phase 1 accuracy gate is qualitative (no
   regressions + SME spot-check), not a specific accuracy %. This is
   the honest position at n=400.
4. A budget for shadow-mode logging: ~2 KB extra log per shadowed
   request → ~60 MB per phase over 2 weeks at 1 k/day.

---

## 15. Appendix D — Future-reader Checklist

If picking this up cold (new engineer, future Claude session):

Read order:
1. `build-failure-analyzer/CURRENT_FLOW.md` — what the service does
   today.
2. `build-failure-analyzer/HYBRID_PROPOSAL.md` (this file) — what to
   change and why.
3. `build-failure-analyzer/PROPOSAL.md` — full alternatives analysis
   (Approach A vs B vs C) for context.

Source files to re-open when implementing:
- `src/log_error_extractor.py:90` — `extract_error_sections`
- `src/api_poster.py:104` — payload shape
- `build-failure-analyzer/analyzer_service.py:192` — `FailedStep`
- `build-failure-analyzer/analyzer_service.py:267` — `/api/analyze`
- `build-failure-analyzer/vector_db.py:159` — `lookup_existing_fix`
- `build-failure-analyzer/vector_db.py:240` — `save_fix_to_db`
- `build-failure-analyzer/resolver_agent.py:64` — `resolve`
- `build-failure-analyzer/slack_reviewer.py:139` — Approve handler

Implementation order: Phase 0 → 1 → 2 → 3 → 4. Never skip.
Feature flags everywhere; every phase must be revertible.

Do not begin implementation without the regression suite in place —
every "accuracy" number in this doc is an educated estimate until
it is measured.
