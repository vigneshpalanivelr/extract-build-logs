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

## 5. Approach B — Split Error (Deterministic)

### 5.1 Overview

Fix the four bugs from §3 without introducing any LLM agents. Separate
the matched error lines from their surrounding context both on the wire
and in storage, normalize error text before embedding, switch Chroma to
cosine distance, use deterministic IDs, and disambiguate multiple
candidates using a secondary cosine pass over the context.

### 5.2 Architecture — what changes

**5.2.1 Wire contract change (extractor → analyzer)**

Today `FailedStep.error_lines = [<one big blob>]`. Change to a list of
per-region objects:

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

Keep `error_lines: List[str]` on the analyzer for one release overlap so
old clients don't break.

**5.2.2 Normalization**

New helper `normalize_error_text(error_lines) -> str`:

- strip `"Line N:"` prefixes
- strip ISO timestamps, `[HH:MM:SS]`, epoch millis
- replace absolute paths, SHAs, UUIDs, container IDs, ports with
  placeholders (`<PATH>`, `<SHA>`, …)
- collapse whitespace, lowercase
- truncate to 512 tokens (granite-embedding's input ceiling)

The normalized text is used for both:

- the deterministic row ID: `id = "fix-" + sha256(fingerprint)[:32]`
- the embedding input

**5.2.3 Cosine distance + deterministic IDs**

At first write, create the Chroma collection with explicit cosine space:

```python
client.get_or_create_collection(
    name="fix_embeddings_v2",
    metadata={"hnsw:space": "cosine"},
)
```

L2-normalize every embedding vector before `add()` and `query()`.
Replace the Python `hash()`-based ID with `sha256(fingerprint)` (stable
across process restarts). Tighten the similarity threshold for the
error-only embedding to **0.90** (meaningful on cosine, unlike today's
0.78 on miscalibrated L2).

**5.2.4 Store only the error in the vector DB**

Rewrite `save_fix_to_db`:

- embedding input = normalized fingerprint (short, specific)
- document = `fix_text`
- metadata includes: `error_fingerprint`, `raw_error_lines`,
  `context_sample` (first ~2 KB of joined context, **metadata only**,
  not embedded), `approver`, `status`, `fix_id`, `revision`,
  repo/branch/job

Context lines remain available for display and disambiguation but never
pollute the retrieval embedding.

**5.2.5 Context-based disambiguation**

`lookup_existing_fix` returns top-K=10 candidates with cosine similarity
≥ 0.90. When more than one passes:

- compute `ctx_sim = cosine(embed(query.context_lines), embed(candidate.context_sample))`
- score = `0.7 * error_sim + 0.3 * ctx_sim`
- return the top score if `score_1 − score_2 > 0.05`; otherwise fall
  through to the LLM

No LLM call is involved — this is pure deterministic vector math.

**5.2.6 Update-not-insert on Slack approval**

In `slack_reviewer.py`, replace `collection.add()` with a look-up-then-
`collection.update()` on the deterministic fingerprint ID. Same fix
approved twice updates the same row (with `revision` bumped in
metadata) instead of creating a duplicate.

### 5.3 Per-request flow

```
POST /api/analyze
  │
  ├─ Redis sme:fix:<fingerprint>       (now hits because fingerprint is stable)
  │     └─ HIT → DM dev, done
  │
  ├─ Redis ai:fix:<fingerprint>
  │     └─ HIT → DM dev, done
  │
  ├─ VectorDB.lookup_candidates(fingerprint, top_k=10, threshold=0.90)
  │     ├─ 0 candidates → LLM (today's Synthesizer, unchanged)
  │     ├─ 1 candidate  → return stored fix
  │     └─ ≥2 candidates → context-cosine disambiguation
  │             ├─ clear winner (margin > 0.05) → return
  │             └─ tie                          → LLM
  │
  └─ LLM path → cache in Redis, post to SME Slack with Approve/Edit/Discard
```

### 5.4 Pros

- **Dirt cheap**: 0 LLM calls on the 70% of requests that hit cache or
  vector DB. Only the novel 10% pay for an LLM call.
- **Deterministic and debuggable**: same input → same output. One
  similarity score logged per lookup; easy to regression test.
- **Fixes the bug at the root**. All four §3 issues are addressed.
- **No new dependencies** — still the existing Chroma + Ollama +
  OpenWebUI stack.
- **Small surface**: ~500 LoC change, most of it contained in
  `vector_db.py` and `log_error_extractor.py`.
- **No prompt-injection exposure** beyond what the LLM synthesizer
  already has today.

### 5.5 Cons

- **Misses the "variant" bucket** (~20% of traffic): stored fix says
  "downgrade to react@17", new error is on `react@18.2.0`. Approach B
  returns the stored fix verbatim; developer has to mentally translate
  the version number.
- **No reasoning about applicability** — purely geometric. A stored
  Jenkins-agent-timeout fix with cosine 0.92 to a new hard-auth failure
  with similar wording can still be returned incorrectly.
- **Tight-threshold cliff**: errors that sit at cosine 0.88–0.89 fall
  through to the LLM even when a stored fix would have been fine, so
  some LLM calls are avoidable-but-unavoided.
- **No citation of partial matches** in the LLM fallback prompt.

### 5.6 Per-request cost & latency

| Metric | Value |
|---|---|
| Cost per 1k requests | ~$1.50 |
| LLM calls per request | 0 (cache/vector hit) to 1 (miss) |
| p50 latency | 250 ms |
| p99 latency | 10 s |
| Code complexity (LoC delta) | ~500 |
| Operational complexity | Low |

---

## 6. Approach C — Hybrid (B + A3 Deviation Analyzer only)

### 6.1 Overview

Approach B as the deterministic fast path, plus **exactly one LLM agent**
— the Deviation Analyzer (A3) — invoked only when the vector DB returns
a match that is meaningful but not clearly exact. Every other agent from
Approach A is dropped or replaced by deterministic code.

Key idea: pay the LLM tax only on the ~15% of requests where it
actually helps.

### 6.2 Architecture — B foundation plus one agent

Everything from §5 (split error/context, normalization, cosine,
deterministic IDs, update-not-insert) is the foundation. On top of that:

| Component | Source | Role |
|---|---|---|
| Redis caches | existing | Pre-agent shortcut, now with stable fingerprint keys |
| VectorDB cosine lookup | §5 | Retrieval (deterministic; no "agent") |
| Context-cosine disambiguation | §5 | First-line tie-breaker (deterministic) |
| **A3 Deviation Analyzer** | new | Single LLM agent, fires only on ambiguous matches |
| LLM Synthesizer | existing `resolver_agent.py:167` | Unchanged fallback for true misses, enriched with partial-match citations |
| Slack Approve/Edit | existing + §5 fix | Unchanged except for update-not-insert semantics |

Why A3 is the one we keep (and not A1, A4, A5, A6):

- **A1 Classifier**: redundant — the deterministic `normalize_error_text`
  already produces a canonical fingerprint. A1 would do slightly better
  at the cost of an LLM call on every request.
- **A2 Retrieval**: not a real agent — just a vector DB tool call.
- **A4 Disambiguator**: the context-cosine rule in §5 already
  disambiguates. Only add A4 if §5's tie-breaker fails in >5% of cases.
- **A5 Synthesizer**: already exists as today's `call_llm`. No new agent
  needed; enrich its prompt with partial-match citations from A3.
- **A6 Validator**: defer until a real safety incident. Regex pre-checks
  catch `rm -rf /` and `curl | sh` today.

**A3 is the only agent where LLM reasoning measurably beats pure vector
math**: it judges whether a 0.92-similar stored fix actually applies to
this specific variant and, if so, proposes minimal adjustments.

### 6.3 Per-request flow (state machine)

```
POST /api/analyze
  │
  ├─ Redis sme:fix:<fp> / ai:fix:<fp>           (cache hits — ~70% of traffic)
  │     └─ HIT → DM dev, done
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

A3 effectively fires on roughly the 15% of requests that sit in the
"meaningful but uncertain" band. The 70% cache-hit fast path and the
~15% clear-hit / clear-miss paths remain LLM-free.

**A3 output caching** (Redis, 7-day TTL):

```
key  = agent:deviation:sha(query_fingerprint + candidate_id)
value = { match_quality, adjusted_fix?, reasoning, confidence, ts }
```

Two developers hitting the same error pattern within a week share the
A3 decision — the second request pays zero LLM cost.

### 6.4 Pros

- **Cheap at steady state**: ~300 LLM calls per 1k requests (0 on
  cache/clear hits, 1 on ambiguous, 1 on true miss). ~10% of Approach
  A's cost.
- **Gets A's accuracy ceiling on variants**: A3 handles the "same root
  cause, different version number" case that Approach B cannot.
- **Deterministic floor**: Approach B underneath means 80%+ of requests
  behave identically on repeat — SME trust preserved.
- **Graceful degradation**: if A3 fails (timeout, schema error), the
  request falls through to the LLM Synthesizer — no worse than Approach
  B.
- **Small enough to land incrementally**: A3 + orchestrator behind a
  feature flag (`AGENTIC_MODE=deviation_only`) ships after Approach B is
  in prod; zero risk to the deterministic path.
- **Bounded failure surface**: one agent's prompt to own, one JSON
  schema to validate, one audit-trail row per request.

### 6.5 Cons

- **Still adds ~900 LoC** over baseline (vs ~500 for B alone).
- **Non-deterministic on the 15% ambiguous band**: A3 can give
  slightly different advice on different days even for the same input.
  Caching mitigates but does not eliminate.
- **Requires a golden-set eval harness** to prove A3 actually helps —
  otherwise we're spending money for a vibe.
- **A3's `adjusted_fix`** needs an approval story: do developers see
  adjusted fixes directly, or do they go through a lighter SME review?
  (Open question #4 in §10.)
- **Prompt-injection exposure in A3**: moderate — stored error text and
  fix text both flow into its prompt. Mitigated by keeping A3's tools
  empty (no file access, no shell) and validating its JSON output
  strictly.

### 6.6 Per-request cost & latency

| Metric | Value |
|---|---|
| Cost per 1k requests | ~$3 |
| LLM calls per request | 0 (cache/clear hit) / 1 (ambiguous with A3) / 1 (true miss with Synthesizer) |
| p50 latency | 400 ms (cache hit) to 8 s (A3 or Synthesizer) |
| p99 latency | 15 s |
| Code complexity (LoC delta) | ~900 (≈ 500 for B + 400 for A3 + orchestrator + eval) |
| Operational complexity | Medium |

---
