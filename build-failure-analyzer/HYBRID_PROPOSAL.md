## 1. Overview

BFA MVP-2 extends the current error analyzer tool with autonomous action capabilities — enabling automatic code fixes for pipeline failures, intelligent retry mechanisms after fix application, and failure tracking with knowledge base accumulation.
The vision is to evolve from a passive analyzer into an active problem-solver that can detect failures, propose solutions, and help teams validate fixes seamlessly through GitLab CI pipelines.

## Fix Existing Problem

If there is no approval, the analyzer is working fine. The moment we have approval with a big chunk of error message, the analyzer starts returning the
same fix for unrelated build failures. The root cause is four major bugs i.e errors and context, Similarity math, slack insert (no updates), 

**What we are proposing.** A *Hybrid* design with two layers:

- Issue must be fixed at Extractor/Analyzer:
  separate error from context on request. 
  Normalize the error before embedding, switch Chroma(l2) to Chroma(cosine) distance and update-not-insert on Slack approval.
- A single **LLM agent** (the *Deviation Analyzer*, "A3")
  Now we have error and error-context using few agents like Error Summariser, Deviation Analyzer, Solution Synthesizer, Reporter.

| # | Agent | Role | LLM? | Input | Output |
|---|---|---|---|---|---|
| A1 | **Error Summariser** | Analyze and Understand the error | Light Weight | Error lines and Context | Error summary |
| A2 | **Deviation Analyzer** | Decide `exact / applicable_with_adjustments / partial / no_match` | Yes | current error, stored error, stored fix | `match_quality, adjusted_fix?, reasoning, confidence` |
| A3 | **Solution Synthesizer** | Generate a fresh fix when no stored fix| Yes | error, context | `fix_text, confidence` |
| A4 | **Reporter** | Format final structured output to Slack blocks + developer DM | No | structured fix | Slack payload |


## 4. The Hybrid Design

### 4.1 Combined per-request flow

```
POST /api/analyze
  │
  ├─ Redis sme:fix:<fp> / ai:fix:<fp>           cache hits, ~X% of traffic
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

## 5. Foundation Layer — Deterministic Fixes

This is what we ship in Phase 1 and what every subsequent layer depends on.

### 5.1 Change needed in BFA request (extractor → analyzer)

Today the analyzer receives `FailedStep.error_lines = [<one big
blob>]`. Change it to a list of per-region objects:

```json
{
  "step_name": "...",
  "errors": [
    {
      "error_lines":       ["npm ERR! code ERESOLVE", "npm ERR! peer dep ..."],
      "context_lines":     ["Resolving dependencies...", "..."],
    }
  ]
}
```

### 5.2 Normalization

The normalized text is used for the embedding input. New helper `normalize_error_text(error_lines) -> str`:

- strip `"Line N:"` prefixes
- strip ISO timestamps, `[HH:MM:SS]`, epoch millis
- replace absolute paths, SHAs, UUIDs, container IDs, ports with
  placeholders (`<PATH>`, `<SHA>`, …)
- collapse whitespace, lowercase
- truncate to 512 tokens (granite-embedding's input ceiling)


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
for the error-only embedding to **0.70 to 0.90**

### 5.4 Store only the error in the vector DB

Rewrite `save_fix_to_db`:

- embedding input = normalized fingerprint (short, specific)
- document = `fix_text`
- metadata: `error_fingerprint`, `raw_error_lines`, `context_sample`
  (first ~2 KB of joined context, **metadata only**, never embedded),
  `approver`, `status`, `fix_id`, `revision`, repo/branch/job

Context lines stay available for display and disambiguation but never pollute the retrieval embedding.

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

## 6. Agentic Layer

### 6.1 Error Summariser
### 6.2 Deviation Analyzer
### 6.3 Solution Synthesizer
### 6.4 Reporter


### 6.2.1 What A3 Deviation Analyzer does

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

### 6.2.2 When A3 fires

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

### 6.2.3 A3 result caching

Each A3 decision is cached in Redis for 7 days:

- key  = `agent:deviation:sha(query_fingerprint + candidate_id)`
- value = the full A3 verdict JSON

Two developers hitting the same error pattern within a week share
the A3 decision. The second request pays $0 for A3.

### 6.2.4 Failure handling

A3 is best-effort. If it:
- times out (>6 s)
- returns malformed JSON after one retry
- returns confidence <0.5

…the orchestrator skips A3 and routes to the LLM Synthesizer. Worst
case: same behavior as the foundation layer alone. No regression.

### 6.2.5 What A3 measurably adds

The "variant" bucket — same root cause, different specifics. Examples:

| Stored error | New error | Foundation alone | With A3 |
|---|---|---|---|
| `npm peer dep react@16 required, found react@17.0.1` | `npm peer dep react@16 required, found react@18.2.0` | returns "downgrade to 17" verbatim — wrong version | `applicable_with_adjustments`, fix updated to "downgrade to 17.0.x" |
| `Maven build failed: missing artifact com.acme:lib:1.2.3` | `…:lib:1.4.0` | returns 1.2.3 fix as-is | adjusts version in mvn command |
| `Jenkins agent timeout (node-12)` | `…(node-19)` | returns node-12 reset steps | adjusts node identifier in fix |

Foundation accuracy on this bucket: ~60–70%. With A3: ~85–90%.
Hybrid captures most of that lift without paying for A3 on the 70%
of requests that are clear cache hits.

every "accuracy" number in this doc is an educated estimate until
it is measured.
