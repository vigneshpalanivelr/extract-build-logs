## 1. Overview

BFA MVP-2 extends the current error analyzer tool with autonomous action capabilities — enabling automatic code fixes for pipeline failures, intelligent retry mechanisms after fix application, and failure tracking with knowledge base accumulation.
The vision is to evolve from a passive analyzer into an active problem-solver that can detect failures, propose solutions, and help teams validate fixes seamlessly through GitLab CI pipelines.

## Existing Problem

If there is no approval, the analyzer is working fine. The moment we have approval with a big chunk of error message, the analyzer starts returning the
same fix for unrelated build failures. The root cause is four major bugs i.e errors and context, Similarity math, slack insert (no updates), 

**What we are proposing.** A *Hybrid* design with two layers:

- Issue must be fixed at Extractor/Analyzer:
  separate error from context on request
  Normalize before embedding, switch Chroma to cosine distance and update-not-insert on Slack approval.
- A single **LLM agent** (the *Deviation Analyzer*, "A3")
  Now we have error and error context using few agents like Error Summariser, Deviation Analyzer, Solution Synthesizer, Reporter
| # | Agent | Role | LLM? | Input | Output |
|---|---|---|---|---|---|
| A1 | **Error Summariser** | Analyze and Understand the error | Light Weight | Error lines and Context | Error summary |
| A2 | **Deviation Analyzer** | Decide `exact / applicable_with_adjustments / partial / no_match` per candidate | Yes | current error, stored error, stored fix | `{match_quality, adjusted_fix?, reasoning, confidence}` |
| A3 | **Solution Synthesizer** | Generate a fresh fix when no stored fix applies; cite any partial matches | Yes | error, context, domain snippet, partial matches | `{fix_text, confidence, cited_candidates[]}` |
| A4 | **Reporter** | Format final structured output to Slack blocks + developer DM | No | structured fix | Slack payload |


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

## 8. Why Hybrid (and not the alternatives)

### 8.1 Why not deterministic alone

The deterministic foundation (Layer 1) handles ~85% of requests
correctly: cache hits, exact vector matches, true LLM-fallback misses.
What it cannot do is reason about the **variant bucket** — same root
cause, different specifics. Without A3, those queries either return a
stored fix verbatim (developer has to mentally translate the version
number) or fall through to the LLM unnecessarily.

Foundation alone:
- ✅ Fixes the four root-cause bugs.
- ✅ Cheapest possible — ~$1.50 per 1 k requests.
- ❌ Variant accuracy: ~60–70%.

### 8.2 Why not full agentic (every request through 5–7 agents)

A full agentic redesign has the highest accuracy ceiling but pays the
agent tax on every request, including the 70% that are trivial cache
hits. At 1 k requests/day:

- **Cost**: ~$30–40/day vs ~$3/day for Hybrid.
- **Latency**: 12 s p50 vs 400 ms p50 for Hybrid.
- **Determinism**: full agentic is non-deterministic on every request;
  same error can yield different advice on different days. SMEs lose
  trust.
- **Code complexity**: ~2,500 LoC vs ~900 LoC for Hybrid.

The accuracy gain on the variant bucket is roughly the same as
Hybrid's; we'd be paying ~10× the cost for ~0% accuracy lift.

### 8.3 Hybrid splits the difference correctly

- Inherits the deterministic foundation (cheap and fast on the 85%).
- Pays for A3 only on the ~15% where it measurably helps.
- Falls back gracefully to the LLM Synthesizer if A3 misbehaves —
  worst case = foundation alone.
- ~$3/day, 400 ms p50, ~85–90% on variants.

---

## 9. What Changes — File-by-File

| # | File | Change | Est LoC |
|---|---|---|---|
| 1 | `src/log_error_extractor.py` | Split `extract_error_sections` to emit per-region `{error_lines, context_lines, error_fingerprint}` | 60 |
| 2 | `src/api_poster.py` | New `errors` payload shape; legacy `error_lines` kept for one release | 30 |
| 3 | `build-failure-analyzer/analyzer_service.py` | `FailedStep` schema → `errors: List[ErrorEntry]`; cache keys use fingerprint; delegate to orchestrator | 80 |
| 4 | `build-failure-analyzer/vector_db.py` | `normalize_error_text`; deterministic sha256 ID; cosine space; `context_sample` metadata; top-K disambiguation | 150 |
| 5 | `build-failure-analyzer/resolver_agent.py` | Pass `error_fingerprint` + `context_lines` through; enrich Synthesizer prompt with partial-match citations | 40 |
| 6 | `build-failure-analyzer/slack_reviewer.py` | `collection.update()` on fingerprint ID (replaces `add()`) | 20 |
| 7 | `build-failure-analyzer/agents/base.py` *(new)* | Bounded agent runner, tool-use loop, JSON schema validation, audit-trail entry | 120 |
| 8 | `build-failure-analyzer/agents/deviation.py` *(new)* | A3 Deviation Analyzer | 80 |
| 9 | `build-failure-analyzer/orchestrator.py` *(new)* | State machine from §4.1; feature flag; budget enforcement | 150 |
| 10 | `build-failure-analyzer/prompts/deviation.md` *(new)* | A3 system + user prompts | — |
| 11 | `scripts/migrate_vector_db.py` *(new)* | One-off migration | 80 |
| 12 | Tests (`tests/`, `build-failure-analyzer/tests/`) | Unit tests + golden-set integration | 300 |
| 13 | `build-failure-analyzer/eval/regression_set.jsonl` *(new)* | 50 seed pairs + augmented variants | data |
| 14 | `build-failure-analyzer/eval/run_eval.py` *(new)* | Replay harness + grading | 120 |

**Total:** ~1,130 LoC product code + 300 LoC tests + eval tooling
and seed data. Estimated 2–3 weeks for one engineer including
Phase 0.

---

## 10. Phased Rollout

| Phase | Scope | Duration | Gate to advance | Rollback |
|---|---|---|---|---|
| **0 — Eval harness** | Build regression suite from the 50 seed pairs (pass/fail assertions). Augment to ~200–400 via prod Chroma dump + synthetic variants + LLM-generated stress tests (see §13). | ~1 week | Regression suite runs in CI; baseline grades published | n/a — pure tooling |
| **1 — Land foundation** | Implement §5 in extractor + analyzer. Run migration script (§7.4) against staging copy of prod Chroma. Swap `CHROMA_COLLECTION` env var. | ~1 week | No regressions on regression suite; SME spot-check of 20 live responses rates ≥ baseline; poisoning row count in v2 = 0 | Revert env var to old collection |
| **2 — Add A3 in shadow mode** | Implement `agents/base.py`, `agents/deviation.py`, `orchestrator.py`, prompt template. Feature flag `AGENTIC_MODE=off\|shadow\|on`. In shadow, A3 runs and logs decisions but the user-visible response comes from foundation alone. | ~1 week | A3 shadow decisions match SME verdicts on ≥80% of shadowed requests over 2 weeks; A3 p99 < 6 s; A3 JSON-schema failure rate < 2% | Flag back to `off` |
| **3 — 10% traffic with A3 active** | Flip flag to `on` for 10% of `/api/analyze` traffic. Monitor cost, latency, SME approval rate, developer feedback. | ~2 weeks | Cost within forecast; SME approval rate ≥ Phase 1 baseline; no customer complaints attributable to A3 | Flag back to 0% |
| **4 — 100% rollout** | All traffic. Close out. | ~1 week | Stable for 2 weeks | Flag back to 10% |
| **5 (optional)** | Add further agents only if signals require: A6 Validator on a safety incident, A1 Classifier if retrieval precision is still low, A4 Disambiguator if §5.5 ties exceed 5%. | n/a | per-agent eval lift ≥ 5% | Per-agent flag |

### 10.1 Non-negotiables

- **Phase 0 before Phase 1.** Without the regression suite we have
  nothing to fall back on if Phase 1 introduces a regression. This
  is the single biggest risk item.
- **Phase 1 before Phase 2.** A3 reasoning over an un-migrated DB is
  still reasoning over poisoned data.
- **Feature flag everywhere.** Every phase must be revertible in
  under 60 seconds via env-var flip. No code-revert rollbacks on a
  weekend.

---

## 11. Open Questions for Team

The team needs to make calls on these before implementation begins.

1. **Orchestrator timeout vs upstream SLA.** Hybrid's total budget is
   45 s per request. Does Jenkins/GitLab post-build hook tolerate
   that? If the extractor retries on timeout we risk duplicate
   analyses.

2. **Eval-harness ownership.** Phase 0 is the biggest risk item.
   Who owns curating the seed pairs, running augmentation, and
   maintaining the replay/grading script over time?

3. **Per-team threshold tuning.** Should the 0.90 vector threshold,
   the top-K fan-out (currently 3 for A3), and the context-cosine
   tie margin (0.05) be configurable per repo? Different teams have
   very different log styles.

4. **A3 `adjusted_fix` approval gating.** When A3 returns an
   adjusted version of a stored fix, should it:
   - (a) go to the developer directly with a note that it's derived;
   - (b) go through a fresh SME Approve/Edit cycle; or
   - (c) go through a lighter thumbs-up review in Slack?

   Recommendation: (c) — base fix is already SME-approved, so a
   lighter touch is appropriate.

5. **Bedrock migration scope.** Branch is
   `claude/setup-log-analysis-bedrock-gmLHN`. Does the Bedrock LLM
   swap (from OpenWebUI to native Bedrock SDK) complete within this
   scope or as a separate PR? Hybrid is LLM-backend-agnostic.

6. **Salvage existing approved fixes.** Migration carries over
   ~70% of `fix_embeddings` (dropping poisoning outliers and
   duplicates) — the default per §7. Does the team prefer this, or
   start with empty `fix_embeddings_v2` and have SMEs re-approve?
   Recommendation: salvage.

7. **`pipeline_context` collection.** The domain-RAG collection
   (`pipeline_context_rag.py`) uses threshold 0.55. Should it also
   migrate to explicit cosine space, or leave as-is? It is read-only
   and not affected by the poisoning bug. Recommendation: leave for
   now, revisit only if precision drops.

---

## 12. Appendix A — A3 Deviation Analyzer Specification

### 12.1 Role

Given the current error (normalized fingerprint + raw lines + context
sample) and a candidate stored fix (its stored error + its stored fix
text), decide whether the stored fix applies. If it applies with
small adjustments (version numbers, paths, identifiers), emit an
`adjusted_fix`. Do not invent new fixes — fall through to the
Synthesizer for that.

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
> its approved STORED fix, and decide whether the stored fix applies.
>
> Output STRICT JSON matching the provided schema. No prose outside
> the JSON object.
>
> Match-quality values:
> - `exact_match` — identical root cause; fix applies verbatim
> - `applicable_with_adjustments` — same root cause; small edits
>   needed (version numbers, paths). Provide `adjusted_fix` and list
>   changes in `adjustments`.
> - `partial` — some steps of the stored fix apply; list which.
> - `no_match` — different root cause.
>
> Do not invent new remediation steps. If the stored fix does not
> mostly apply, return `partial` or `no_match` and let downstream
> synthesis handle it.

### 12.4 Trigger conditions

A3 fires only when the orchestrator state machine reaches one of:

- Exactly 1 candidate with cosine similarity in `[0.90, 0.95)`.
- ≥2 candidates with cosine similarity ≥ 0.90 (A3 runs in parallel,
  top-3 candidates).

Never fires when:
- 0 candidates above 0.90 → Synthesizer.
- 1 candidate at ≥ 0.95 → high-confidence exact, no A3.
- Cache shortcut hits → no A3.

### 12.5 Caching

- Redis key: `agent:deviation:sha(query_fingerprint + candidate_id)`
- TTL: 7 days
- Two developers hitting the same error pattern within a week share
  the decision; second request pays $0 for A3.

### 12.6 Cost & latency

- Average input: ~3 K tokens (prompt + error + candidate fix).
- Average output: ~300 tokens.
- Bedrock Claude Sonnet pricing: ~$0.015 per A3 call.
- p99 latency: ~6 s (with one retry on schema validation failure).

---

## 13. Appendix B — Eval Strategy Under Sparse Data

Phase 0 starts with only ~50 labeled pairs, each a single error line
and a single solution line (no multi-line context, no surrounding log
noise). This appendix adapts the plan for that reality.

### 13.1 Why 50 one-line pairs is not enough on its own

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

### 13.2 Three-track mitigation

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
  normalizer + A3 directly. Yield: 150–250 new pairs.
- (c) **LLM-generated stress tests.** Use Claude to paraphrase each
  seed into 2–3 realistic variants with surrounding log noise.
  Flags brittle normalizer regexes and A3 prompt failure modes.
  Yield: 100–150 pairs labeled "synthetic, not gold".

Combined: 50 → ~400 pairs. Enough for Phase-1-grade offline checks.

**Track 3 — Make live shadow mode the primary accuracy signal.**
Offline eval at n=50–400 cannot distinguish small lift from noise.
Production telemetry can. Phase 2 runs A3 in shadow mode on every
qualifying request and logs its decisions. Over 2 weeks at
1,000 requests/day that is ~15,000 real-world samples — far stronger
than any offline eval.

### 13.3 Revised phase gates

| Phase | Sparse-data gate |
|---|---|
| 0 | Build regression suite from 50 seeds + augment to ~200–400 via tracks 2(a–c); ship pass/fail CI harness |
| 1 | No regressions on regression suite + SME spot-check of 20 live responses rates ≥ baseline |
| 2 | A3 shadow-mode decisions match SME verdicts on ≥80% of shadowed requests over 2 weeks |
| 3 | Cost within forecast; SME approval rate ≥ Phase 1 baseline |
| 4 | Stable for 2 weeks |

### 13.4 Feature deferrals

- **Context-cosine disambiguator (§5.5).** Ship behind its own
  sub-flag `CONTEXT_COSINE_ENABLED=false`; enable only after shadow
  mode accumulates real multi-line context samples.
- **A3 `adjusted_fix`.** Cannot be offline-tested without
  version-number / path variations. Track 2(b) synthetic variants
  *must* include those, otherwise the
  `applicable_with_adjustments` branch is untested on day one.

### 13.5 What we need from the team

1. Read/export access to the current prod `fix_embeddings`
   collection (track 2(a)).
2. One SME-hour to spot-check the first 20 synthetic variants
   (track 2(b)) so we confirm the "same fix should still apply"
   assumption holds before generating the rest.
3. Agreement that the Phase 1 accuracy gate is qualitative (no
   regressions + SME spot-check), not a specific accuracy
   percentage. This is the honest position at n=400.
4. A budget for shadow-mode logging in Phase 2: ~2 KB extra log per
   shadowed request → ~60 MB over 2 weeks at 1 k/day.

---

## 14. Appendix C — Future-reader Checklist

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
