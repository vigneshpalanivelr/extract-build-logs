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

## 4. The Hybrid Design — Overview

Two layers, deliberately stacked.

```
                    ┌──────────────────────────────────────┐
                    │   Layer 2 — Agentic                  │
                    │   A3 Deviation Analyzer              │
                    │   (fires on ~15% of requests)        │
                    └──────────────────────────────────────┘
                              ▲       ▲
                              │       │ ambiguous match
                              │       │ (multiple candidates,
                              │       │  or one in [0.90, 0.95))
                              │       │
                    ┌─────────┴───────┴────────────────────┐
                    │   Layer 1 — Deterministic Foundation │
                    │   Split error/context, normalize,    │
                    │   cosine, deterministic IDs,         │
                    │   update-not-insert                  │
                    │   (handles ~85% of requests alone)   │
                    └──────────────────────────────────────┘
```

The deterministic foundation handles the ~70% cache-hit traffic and
the ~15% clear-hit / clear-miss traffic on its own. A3 only fires on
the remaining ~15% — requests where the vector DB returns at least
one meaningful candidate but applicability is uncertain.

**Why two layers and not one.** A single-layer deterministic system
(split error, cosine, etc.) catches exact and near-exact repeats but
returns stored fixes verbatim — even when a small adjustment is
needed (e.g., stored fix says "downgrade to react@17", new error is
on `react@18.2.0`). A3 reads the new error, the stored error, and
the stored fix, and decides whether the fix applies as-is or needs
adjustments. That single judgment captures most of the "variant"
bucket without paying the agent tax on every request.

### 4.1 Combined per-request flow

```
POST /api/analyze
  │
  ├─ Redis sme:fix:<fp> / ai:fix:<fp>           cache hits, ~70% of traffic
  │     └─ HIT → DM developer, done
  │
  ├─ VectorDB.lookup_candidates(fp, top_k=10, threshold=0.90)
  │
  ├─ 0 candidates ≥ 0.90                        → LLM Synthesizer (existing path)
  │
  ├─ 1 candidate ≥ 0.95                         → return stored fix (high-confidence)
  │
  ├─ 1 candidate in [0.90, 0.95)                → A3 Deviation Analyzer
  │     ├─ exact_match                          → return stored fix
  │     ├─ applicable_with_adjustments          → return adjusted_fix
  │     ├─ partial / no_match                   → LLM Synthesizer
  │
  └─ ≥2 candidates ≥ 0.90                       → A3 on each (parallel, top-3)
        ├─ any exact_match                      → return
        ├─ 1 applicable                         → return adjusted
        ├─ ≥2 applicable                        → context-cosine tie-breaker (deterministic)
        └─ none applicable                      → LLM Synthesizer
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

## 6. Agentic Layer — A3 Deviation Analyzer

### 6.1 Why exactly one agent

A full agentic redesign was considered (seven coordinated agents:
Classifier, Retrieval, Deviation Analyzer, Disambiguator,
Synthesizer, Validator, Reporter — see `PROPOSAL.md` §4 for the full
analysis). The key finding: only the Deviation Analyzer has
leverage that justifies its cost.

| Candidate agent | Why we drop it |
|---|---|
| Classifier (A1) | Redundant — `normalize_error_text` already produces a canonical fingerprint |
| Retrieval (A2) | Not really an agent — just a vector DB tool call |
| Disambiguator (A4) | Context-cosine in §5.5 already disambiguates |
| Synthesizer (A5) | Already exists as today's LLM fallback (`call_llm`); no agent needed |
| Validator (A6) | YAGNI until a real safety incident; regex pre-checks catch obvious dangers |
| Reporter (A7) | Pure formatting — deterministic code |

A3 is the only one where natural-language reasoning measurably beats
geometry: it judges whether a 0.92-similar stored fix actually
applies to this specific variant and, if so, proposes minimal
adjustments.

### 6.2 What A3 does

Given:
- the *new* error (its fingerprint, raw lines, and context sample)
- one *stored* candidate (its stored error, its stored fix)

A3 returns a strict JSON verdict:

```json
{
  "match_quality":  "exact_match | applicable_with_adjustments | partial | no_match",
  "confidence":     0.92,
  "reasoning":      "<1-2 paragraphs>",
  "adjusted_fix":   "<modified fix text, only if applicable_with_adjustments>",
  "adjustments":    ["downgrade react: 17 -> 18.2", "path: /opt/old -> /opt/new"]
}
```

A3 must not invent new fixes. If the stored fix doesn't mostly
apply, A3 returns `partial` or `no_match` and the orchestrator
falls through to the LLM Synthesizer.

### 6.3 When A3 fires

A3 runs **only** in two situations:

1. The vector DB returns exactly one candidate with cosine similarity
   in the band `[0.90, 0.95)` — meaningful but not clearly exact.
2. The vector DB returns ≥2 candidates with cosine similarity ≥ 0.90.
   In this case A3 runs in parallel on the top-3 candidates.

A3 **never** runs when:
- The cache shortcuts hit (Redis sme:fix or ai:fix). ~70% of traffic.
- The single top candidate scores ≥0.95 (treated as high-confidence
  exact). ~10% of traffic.
- No candidate scores ≥0.90 (true miss; route to LLM Synthesizer).
  ~5% of traffic.

Net: A3 fires on roughly 15% of requests.

### 6.4 A3 result caching

Each A3 decision is cached in Redis for 7 days:

- key  = `agent:deviation:sha(query_fingerprint + candidate_id)`
- value = the full A3 verdict JSON

Two developers hitting the same error pattern within a week share
the A3 decision. The second request pays $0 for A3.

### 6.5 Failure handling

A3 is best-effort. If it:
- times out (>6 s)
- returns malformed JSON after one retry
- returns confidence <0.5

…the orchestrator skips A3 and routes to the LLM Synthesizer. Worst
case: same behavior as the foundation layer alone. No regression.

### 6.6 What A3 measurably adds

The "variant" bucket — same root cause, different specifics. Examples:

| Stored error | New error | Foundation alone | With A3 |
|---|---|---|---|
| `npm peer dep react@16 required, found react@17.0.1` | `npm peer dep react@16 required, found react@18.2.0` | returns "downgrade to 17" verbatim — wrong version | `applicable_with_adjustments`, fix updated to "downgrade to 17.0.x" |
| `Maven build failed: missing artifact com.acme:lib:1.2.3` | `…:lib:1.4.0` | returns 1.2.3 fix as-is | adjusts version in mvn command |
| `Jenkins agent timeout (node-12)` | `…(node-19)` | returns node-12 reset steps | adjusts node identifier in fix |

Foundation accuracy on this bucket: ~60–70%. With A3: ~85–90%.
Hybrid captures most of that lift without paying for A3 on the 70%
of requests that are clear cache hits.

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
