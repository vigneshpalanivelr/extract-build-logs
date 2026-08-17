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

### 1.1 MVP1 Pain Points (priority order)

Reported by the team after MVP1 production use, plus issues found in
code review — **ordered by priority**: correctness bugs that produce
wrong answers today (P1–P5), safety/compliance (P6), enablers and
workflow (P7–P12), visibility (P13–P17), agent-era risks (P18–P19),
performance and hygiene (P20–P22), testing (P23). Every "proof"
reference points to §3.6. The duplicated-Slack-handler item was
removed from this list per review (implementation detail — tracked in
the LLD under B-14).

| # | Component | Pain point | What it hurts / proof | Addressed by |
|---|---|---|---|---|
| P1 | Extractor | Error and context glued into one blob before embedding | Error and context lines are sent as one single string (`log_error_extractor.py:138`). In many cases the exact error line differs but the context lines look similar — the embedding matches on context noise instead of the error. Proof: §3.6 Bug 1. | A-1, A-2 (runs as agent A1) |
| P2 | Analyzer | L2 distance treated as cosine | Collection created without `hnsw:space` (`vector_db.py:47`) → Chroma defaults to L2 (squared Euclidean); code computes `sim = 1 - dist` (`:212`), only valid for cosine. Opposite-direction vectors can score above the 0.78 threshold. Proof: §3.6 Bug 2. | A-3 |
| P3 | Analyzer | Non-deterministic row IDs (duplicates on every restart) | `save_fix_to_db` builds IDs from salted `hash()` (`vector_db.py:276`) — same error, different ID every process; approvals insert duplicates, bad rows become permanent. A deterministic sha1 helper exists at `:149` but is never called. Proof: §3.6 Bug 3. | A-3, A-6 |
| P4 | Analyzer | Whole-log cache key — near-zero cache hits | Cache key is sha256 of the full blob incl. timestamps (`analyzer_service.py:284`); a 1-second change → different key → no request ever hits cache; every failure pays full LLM cost. Proof: §3.6 Bug 4. | A-2, A-7 |
| P5 | Analyzer | Two processes open the same embedded Chroma directory | `analyzer_service.py` and `slack_reviewer.py:19` each construct a `PersistentClient` on the same directory. Embedded Chroma is single-process by design; concurrent writes risk index corruption. Proof: §3.6 item 5. | B-14 |
| P6 | Extractor | Secrets flow unredacted into Redis/Chroma/Slack | The extractor masks secrets only in its own log files (`logging_config.py:39`); the wire payload never passes that filter — tokens/passwords/credential URLs are POSTed as-is, stored in Chroma metadata, cached in Redis, posted to Slack. Proof: §3.6 item 8. | A-8 |
| P7 | Analyzer | Metadata too thin for search, trust, or team assignment | Stored fixes carry almost no context (no team, stage, pattern, hit counts). We cannot search by product, route to the right team, or judge whether a fix is trusted or stale. | A-4, C-2 |
| P8 | Slack | Slack message flood (track lost, history unreadable) | Every error in every failed stage posts a message. Across all products and pipelines the channel becomes unscannable and SMEs stop reading it. | B-4, B-5, B-7 |
| P9 | Analyzer | Same error in N stages → N analyses, N messages (common in GitLab) | Nested loop with no fingerprint dedup within a request (`analyzer_service.py:277`) — 3 stages → 3 analyses, 3 LLM calls, 3 messages for zero added information. Proof: §3.6 item 9. | B-7 |
| P10 | Slack | Multiple teams/products; no way to filter or assign | One global channel (`SLACK_CHANNEL` env); multiple SPOCs handling different products often miss messages; no "mine" filter, no ownership — triage stalls. | B-6, B-8 |
| P11 | Slack | Automated build failed → developer not found → fix silently lost | Service-account pipelines, or CI email ≠ Slack email, fail `users_lookupByEmail` — the fix is generated, then silently dropped. | B-8 |
| P12 | Analyzer | Retry-exhausted payloads lost; silent analyzer death unnoticed | After retry exhaustion the payload is only logged (`api_poster.py:1023`) — analysis lost. A silently-dead analyzer alerts no one; failures just stop being analyzed. | E-2, E-3 |
| P13 | Dashboard | Issue visualisation missing | No place to see open/analyzed failures; the only "view" is scrolling Slack history. | D-2 |
| P14 | Dashboard | Database (KB) visualisation missing | Chroma contents are invisible — nobody can list what fixes exist, which are stale, or find a poisoning row without ad-hoc scripts. | D-1, D-2 |
| P15 | Dashboard | No way to deprecate a bad fix | The poisoning row could only be removed by hand-editing the DB; no deprecate flag or delete API — any bad approval is effectively permanent. | D-1 |
| P16 | Dashboard | Resolution view/edit/update visibility missing | No UI or API to view, edit, or update a stored fix; corrections require developer intervention directly in the DB. | D-1, D-2, B-15 |
| P17 | Integration | No Jira ticket creation from an issue | Recurring/product-level failures need product-team attention or the proposed solution is wrong and needs tracking; no ticket creation exists and nothing links tickets to stored fixes. | B-12 |
| P18 | Agent | Infra errors (runner down, network) blamed on developers via DM | Runner disconnects and network timeouts DM the committing developer, implying their code broke the build. Repeated false blame destroys trust. | A-9, B-11 |
| P19 | Agent | Nothing stops a dangerous LLM fix reaching a developer | Destructive commands (`rm -rf`, `chmod 777`, force push) could reach a developer verbatim. Prompt instructions reduce but cannot guarantee safety (probabilistic output + attacker-controllable log text in the prompt) — hence prompt guidance + deterministic denylist + SME review for blocked output. | B-10 |
| P20 | Analyzer | One slow LLM call blocks the whole event loop | `async def analyze` (`analyzer_service.py:268`) makes blocking Redis/LLM/Slack calls (`requests.post`, `llm_openwebui_client.py:135`). One 8 s LLM call freezes the event loop for every in-flight request. Proof: §3.6 item 10. | A-10 |
| P21 | Analyzer | Redis keys never expire; error_map keyed by full error text | `store_fix` uses plain `set` — no TTL (`slack_helper.py:49,52,56`) while `resolver_agent.py:59` uses `setex` correctly, proving the omission; `error_map` uses the multi-KB blob as the key itself. Memory grows forever. Proof: §3.6 item 6. | A-7 |
| P22 | Analyzer | Embedding model upgrade would silently mix vector spaces | No record of which embedding model wrote each vector; a model upgrade mixes incompatible vector spaces and corrupts every similarity score with no error raised. | A-13 |
| P23 | Testing | Tests mock all vector math — bugs invisible to a green suite | `test_vector_db.py` patches `_get_embedding` → `[0.1, 0.2, 0.3]` and `collection.query` → canned distances. All four correctness bugs live in the mocked-out layer — the suite verified plumbing, not math, and stayed green through the incident. Explanation: §3.6 item 7. | F-2, F-5 |

### 1.2 Final MVP2 Scope — Six Pillars

Agreed scope. IDs are referenced throughout this document.

**Pillar A — Foundation**

| # | Item |
|---|---|
| A-1 | Wire contract: split `error_lines` / `context_lines` per region (legacy shape kept one release) |
| A-2 | Normalization + fingerprint (strip Line-N/timestamps, lowercase, collapse whitespace) |
| A-3 | Chroma cosine space + `sha256(fingerprint)` IDs + L2-normalized vectors, threshold 0.90 |
| A-4 | Embed only the error. Metadata moves to a **SQLite system-of-record** (`fixes` + `fix_revisions` tables — full edit history); Chroma holds vectors + fix_text only (§5.4) |
| A-5 | Context-cosine disambiguation (0.7/0.3 weighted, tie → A2) |
| A-6 | Update-not-insert on approval, `revision` bump |
| A-7 | Redis TTLs (30 d) on `fix:*` / `error_map:*` / `thread_map:*`; `error_map` keyed by fingerprint hash |
| A-8 | **Secret redaction** in extractor before posting (tokens, passwords, credential URLs) |
| A-9 | ERROR_PATTERNS → config file; each pattern classified `code \| infra` (team decision — `flaky` can be added later) |
| A-10 | Async processing: `202 Accepted` + background task (unblocks the event loop) |
| A-11 | Analyzer adopts extractor's `logging_config.py` pattern; no more `print()` |
| A-12 | Startup validation of all config files (routing JSON, patterns) — fail fast |
| A-13 | `embedding_model` **and `embedding_dim`** stamped in collection metadata; model-name mismatch at startup → refuse to start (forces migration); every embedding asserted against `embedding_dim` (catches silent model/quantization drift) |

**Pillar B — Agentic layer (4 agents)**

| # | Item |
|---|---|
| B-1 | A1 Error Summariser (deterministic) — also replaces the `summarize_error_with_ai` LLM call |
| B-2 | A2 Deviation Analyzer — JSON verdict, 7-day cache, fallback to A3 (§6.2) |
| B-3 | A3 Solution Synthesizer — on failure → "unable to analyze" + DevOps email & Slack (§6.3) |
| B-4 | A4 Reporter: one message **per failed stage**; multiple errors of that stage threaded under it |
| B-5 | A4: recurring fingerprint → update canonical message with counter; DM developer directly |
| B-6 | A4: routing via JSON config (repo pattern → channel, product_team, SME group); restart to apply |
| B-7 | A4: dedup by fingerprint within one request ("seen in 3 stages" — one analysis, one DM) |
| B-8 | A4: developer not found on Slack → fallback post to team channel, author named |
| B-9 | A4: DM shows provenance ("SME-approved, served 12×"), last-seen, originating repo |
| B-10 | Dangerous-fix guardrail: denylist regex on `fix_text` before any post; hit → SME review with ⚠️ |
| B-11 | Infra/flaky errors (per A-9 classification) → DevOps channel / "retry" DM — never blame the developer |
| B-12 | Jira: "Create Jira" button + auto-create on `no_match` / low confidence; `jira` key prevents duplicates |
| B-13 | 👍/👎 feedback buttons on developer DM; 3× 👎 auto-flags fix to SME channel |
| B-14 | Consolidate Slack handlers: delete `slack_reviewer.py`; keep FastAPI versions only. **Data-integrity fix, not just hygiene** (P5: two processes on one embedded Chroma risks index corruption) — execute at the start of Phase 1 |
| B-15 | Slack edit-prompt: TTL (configurable, default 1 week — team decision) + O(1) key lookup (editing stored fixes anytime = Edit API / dashboard) |

**Pillar C — Stats & telemetry**

| # | Item |
|---|---|
| C-1 | Pipeline stats: user (name, mail, commit, branch), per-stage E.Time + status, total time — success & failed |
| C-2 | Decision telemetry per request: source, similarity, latency, cost estimate, fingerprint, team |
| C-3 | Feedback counts (`helpful_count` / `unhelpful_count`) wired into stats |
| C-4 | Zero-match telemetry: failed pipeline, no pattern matched → stat + DevOps notice with log tail |

**Pillar D — KB management & dashboard**

| # | Item |
|---|---|
| D-1 | REST APIs — **full CRUD**: add, list/filter/search, get detail, edit, deprecate (soft delete, filtered from retrieval). **SQL-backed** (plain SQL filters, pagination, free-text; revision history from `fix_revisions`). One API surface serving both CLI/automation consumers and the KB dashboard (RD-15321) |
| D-2 | Dashboard: Resolved view, Pending/needs-attention view (editable, any age), Stats view — full filters (§16) |
| D-3 | Monthly pruning job: deprecated / zero-hit > 6 months → archive + delete; surfaced in dashboard first |
| D-4 | Daily backup via the **SQLite `.backup` API** (`bfa_kb.db`, `bfa_stats.db`, Chroma's internal store — never raw `tar` of live DB files) + retention + documented restore |

**Pillar E — Resilience & ops**

| # | Item |
|---|---|
| E-1 | Degradation ladder: Redis down → skip cache; Ollama/Chroma down → straight to A3; LLM down → notify + "unable to analyze" |
| E-2 | Dead-letter dir for retry-exhausted payloads + `replay_failed.py` |
| E-3 | systemd `Restart=on-failure` in service unit + silent-failure alert (webhooks > 0, analyses = 0 in 15 min) |
| E-4 | Slack `RateLimitErrorRetryHandler` enabled |
| E-5 | Region cap: already exists (`ERROR_ADAPTIVE_THRESHOLDS` / `MAX_LOG_LINES`) — document only |

**Pillar F — Testing & validation**

| # | Item |
|---|---|
| F-1 | Unit: normalizer golden tests, orchestrator state-machine branches, A2/A3 mocked-LLM, A4 formatting |
| F-2 | Component with **real Chroma + real embeddings**: poisoning regression (gate: 0% false match), threshold calibration, deterministic-ID test |
| F-3 | Wire-contract JSON schema shared by extractor & analyzer tests |
| F-4 | docker-compose E2E: mock GitLab/Jenkins + mock LLM (record/replay) + mock Slack; real Redis/Chroma; 6 scenarios incl. approval-updates-row and degradation-ladder chaos tests |
| F-5 | Eval harness + metrics: routing accuracy ≥ 95%, poisoning 0%, recall ≥ 90%, keyword pass ≥ baseline, cost/latency vs forecast; CI mode (mock, every PR) + nightly (real LLM, report to DevOps) |
| F-6 | Linter cleanup of the `build-failure-analyzer` repo (RD-15333) — prerequisite for enabling lint gates alongside the CI wiring |

**Dropped by decision:** in-flight dedup lock, Slack request signing /
SME allowlist (SME-only audience), API rate limiting,
concurrent-approval lock.

**Pre-rollout blockers:** A-8, A-10, A-12, B-10, B-11, E-1, F-2, F-5.

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

`vector_db.py:276` (inside `save_fix_to_db`, the function every
Slack approval calls):
```python
unique_id = f"fix-{abs(hash(error_text)) & ((1 << 128) - 1):032x}"
```

Python's builtin `hash()` is salted per process (PEP 456 — since
Python 3.3, `PYTHONHASHSEED` is random by default), so the same error
text produces a different ID every time the service restarts. Slack
approvals that should update an existing row keep inserting new ones.
Once the poisoning row exists, it is effectively permanent.

**Aggravating detail:** a correct deterministic helper already exists
in the same file — `_generate_id()` at `vector_db.py:149` uses
`hashlib.sha1(error_text)` — but `save_fix_to_db` never calls it. The
bug is not a missing capability; it is a missed wiring.

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

### 3.6 Reproduction transcript (evidence for architecture review)

Every claim above is reproducible from a shell. Outputs below were
captured from this repository's code on 2026-07-15.

**Bug 3.1 — context dominates the embedding (illustrative geometry).**
Two *unrelated* errors (npm peer-dep vs Maven missing-artifact), each
wrapped in the same 50 lines of build context — exactly what
`log_error_extractor.py:138` produces. Cosine on token-count vectors
(directionally identical to what any text embedding does with shared
tokens):

```
UNRELATED errors, blob embedding (error+context):  cosine = 1.000  → above any threshold, WRONG MATCH
UNRELATED errors, error-only embedding:            cosine = 0.000  → correctly no match
```

Labeled *illustrative* honestly: it uses bag-of-words cosine, not
granite-embedding — but the mechanism (shared boilerplate tokens
dominate the vector) is the same, and the production incident is the
real-embedding confirmation. The F-2 poisoning-regression test makes
this proof permanent with real embeddings.

**Bug 3.2 — `sim = 1 − dist` on the wrong metric.** Chroma's default
space is `l2` ([Chroma docs: `hnsw:space` defaults to `"l2"`]), which
returns **squared** Euclidean distance. `1 − dist` is only a
similarity for cosine distance. Three concrete vector pairs:

```
unit orthogonal:   cosine_sim = 0.00   code computes sim = 1−L2 = −1.00   ← negative "similarity"
non-normalized:    cosine_sim = 0.992  code computes sim = 1−L2 = +0.838
small magnitudes:  cosine_sim = −0.12  code computes sim = 1−L2 = +0.907  ← scores ABOVE the 0.78
                                                                            threshold while pointing in
                                                                            the OPPOSITE direction
```

The third row is the smoking gun: the code would serve this candidate
as a confident match (0.907 > 0.78) when the true directional
similarity is negative.

**Bug 3.3 — salted `hash()` IDs.** The exact expression from
`vector_db.py:276`, run in three separate Python processes:

```
$ python3 -c "err='npm ERR! code ERESOLVE'; print(f'fix-{abs(hash(err)) & ((1 << 128) - 1):032x}')"
fix-000000000000000045e68e8094890e32
$ python3 -c ...   (same command, new process)
fix-0000000000000000695d521233f48a53
$ python3 -c ...   (same command, new process)
fix-00000000000000001e64d9b87e9cdd39
```

Same error text, three different row IDs — every service restart makes
previously-saved rows un-updatable and every re-approval inserts a
duplicate. (Also visible: `abs(hash()) & (2^128−1)` zero-pads to 32
hex chars but Python's hash is only 64-bit — half the ID space is
always zeros, so even the intended uniqueness is half-broken.)

**Bug 3.4 — whole-blob SHA cache key.** Two blobs identical except a
timestamp one second apart (`analyzer_service.py:284` hashes the full
blob):

```
9:14:02 → sha256 = 910cb32919ead0bbf1e2b0d3…
9:14:03 → sha256 = 1f59997608960587c065dfed…
cache keys equal? False
```

Since every log line carries a timestamp, effectively **no two
requests ever share a cache key** — the observed near-zero hit rate
on `sme:fix:*` / `ai:fix:*` is structural, not tuning.

**Item 5 — two processes on one embedded Chroma (P5).**
`slack_reviewer.py:19` (`db = init_vector_db()`) and
`analyzer_service.py` startup both construct
`chromadb.PersistentClient(path=CHROMA_DB_PATH)` on the same
directory, as two separate OS processes. PersistentClient is an
embedded, in-process engine (SQLite + HNSW segment files) — safe
within one process, unsupported with concurrent writers from separate
processes. B-14 (consolidation) removes the hazard entirely.

**Item 6 — Redis keys never expire; blob used as key (P21).**
`slack_helper.py` `store_fix()`:

```python
redis_conn.set(f"fix:{error_id}", json.dumps(data))          # :49  no TTL
redis_conn.set(f"error_map:{error_title}", error_id)         # :52  no TTL — and the KEY
                                                             #      is the full error text
redis_conn.set(f"thread_map:{channel_id}:{message_ts}", …)   # :56  no TTL
```

The contrast proving it's an omission, not a choice:
`resolver_agent.py:59` in the same codebase uses
`setex(f"ai:fix:{…}", REDIS_TTL_AI, …)` with a 24 h TTL. Every
approval leaks three immortal keys, one of them multi-KB.

**Item 7 — why a green suite missed all four bugs (P23).**
`tests/test_vector_db.py` patches `_get_embedding` to a constant
`[0.1, 0.2, 0.3]` and `collection.query` to canned distances. So:
Bug 1 (no real embedding → context domination invisible), Bug 2
(hand-written distances → the L2/cosine mismatch never runs on real
geometry), Bug 3 (no process restart in a unit test → ID instability
invisible), Bug 4 (fixed test strings → timestamp sensitivity
invisible). The suite verified plumbing, not math — hence test level
F-2 with real Chroma + real embeddings.

**Item 8 — secrets in the wire payload (P6).** The extractor masks
secrets **only in its own log files** (`logging_config.py:39`,
`SensitiveDataFilter` on loggers). The payload built by
`api_poster.py` never passes through that filter — error/context
lines go to the analyzer verbatim, then into Redis (`store_fix`),
Chroma metadata (`save_fix_to_db` stores `error_text`), and the Slack
channel post. One leaked `password=…` becomes permanent in three
stores plus Slack history.

**Item 9 — same error, N stages, N× cost (P9).**
`analyzer_service.py:277` — `for step in payload.failed_steps: for
error_line in step.error_lines:` — no fingerprint dedup in the loop;
identical error text in build/test/package is embedded, matched,
LLM-analyzed, and posted three separate times.

**Item 10 — blocking calls inside the async event loop (P20).**
`analyzer_service.py:268` declares `async def analyze`; inside it,
`r.get()` (sync redis-py), the LLM call
(`llm_openwebui_client.py:135`, sync `requests.post`), and Slack SDK
calls all block. FastAPI runs an `async def` endpoint on the single
event loop — a blocking call stalls **every** in-flight request
(a plain `def` endpoint would at least run in a threadpool). One 8 s
LLM call = 8 s global freeze.

**How the four compound into the production incident:** 3.1 creates a
row whose vector matches broadly (context noise) → 3.2 lets that row
clear the 0.78 threshold for almost any query → 3.3 makes the row
impossible to update and duplicates it on re-approval → 3.4 guarantees
every request re-runs retrieval (no cache short-circuit), giving the
bad row a fresh chance to match every single time.

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

Ordering note: A1 runs **first** — the Redis cache keys
(`sme:fix:<fp>`) are keyed by the fingerprint A1 produces, so the
cache cannot be consulted before A1. Every terminal path goes through
A4, which applies guardrail, routing, and dedup rules before anything
reaches Slack.

```
POST /api/analyze  → 202 Accepted, processed in background task (A-10)
  │
  ├─ A1 Error Summariser: normalize → error_fingerprint + summary
  │       (deterministic, every request; in-request dedup by fingerprint, B-7)
  │
  ├─ Redis sme:fix:<fp> / ai:fix:<fp>           cache hits, ~70% of traffic
  │     └─ HIT → A4 Reporter → DM developer, done   (no LLM, no vector query)
  │
  ├─ VectorDB.lookup_candidates(fp, top_k=10, threshold=0.90)
  │
  ├─ 0 candidates ≥ 0.90                        → A3 Solution Synthesizer (generate fresh)
  │                                                → store as pending → A4 (SME channel + DM)
  │
  ├─ 1 candidate ≥ 0.95                         → stored fix (high-confidence, no LLM)
  │     └─ A4 Reporter → DM developer, done
  │
  ├─ 1 candidate in [0.90, 0.95)                → A2 Deviation Analyzer
  │     ├─ exact_match                          → stored fix → A4 Reporter
  │     ├─ applicable_with_adjustments          → adjusted fix → store → A4 Reporter
  │     ├─ partial / no_match                   → A3 (with partial-match citations) → A4
  │
  └─ ≥2 candidates ≥ 0.90                       → A2 on each (parallel, top-3)
        ├─ any exact_match                      → A4 Reporter
        ├─ exactly 1 applicable                 → adjusted → store → A4 Reporter
        ├─ ≥2 applicable                        → context-cosine tie-breaker (deterministic,
        │                                          0.7·error_sim + 0.3·ctx_sim) → A4 Reporter
        └─ none applicable                      → A3 Solution Synthesizer → A4

A4 Reporter, on every terminal path:
  guardrail check (B-10) → infra/flaky routing (B-11) → stage grouping (B-4)
  → recurring-error counter update (B-5) → provenance + feedback buttons (B-9, B-13)
```

Fallbacks: A2 timeout/malformed/low-confidence → A3. A3 failure →
"unable to analyze" + DevOps notification. Redis/Ollama/Chroma down →
degradation ladder (§17.1). Worst case is always the same behavior as
today's LLM fallback — never worse.

---

## 5. Foundation Layer — Deterministic Fixes

This is what we ship in Phase 1 and what every subsequent layer
depends on. Without this, an A3 agent reasoning over a poisoned DB
just produces wrong answers more expensively.

### 5.1 Wire contract change (extractor → analyzer)

**Today's structure (the problem).** The extractor finds error lines,
grabs ~50 lines before and ~10 lines after each error as "context",
merges overlapping ranges, and glues everything into **one giant
string** before posting:

```json
"failed_steps": [{
  "step_name": "Build",
  "error_lines": ["<5KB of error + context + timestamps + paths all mashed together>"]
}]
```

`error_lines` is a list with a single element — a huge blob. The
analyzer cannot tell where the actual error ends and the surrounding
noise begins, so it embeds and stores the whole thing.

**Proposed structure.** Send each error region as its own object,
with error and context **separated** on the wire:

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

**Why it matters.** The vector DB only embeds the *error* part.
Context is kept for display and disambiguation but never pollutes
the search.

### 5.2 Normalization

**Plain-terms goal.** Strip the parts of an error that change every
run but don't change the meaning, so the same logical error always
produces the same canonical fingerprint.

New helper `normalize_error_text(error_lines) -> str`:

- strip `"Line N:"` prefixes
- strip ISO timestamps, `[HH:MM:SS]`, epoch millis
- replace absolute paths, SHAs, UUIDs, container IDs, ports with
  placeholders (`<PATH>`, `<SHA>`, …)
- collapse whitespace, lowercase
- truncate to 512 tokens (granite-embedding's input ceiling)

The normalized text is used for both the deterministic row ID and
the embedding input.

**Why it matters.** Today, the same error at 9 AM vs 10 AM produces
different embeddings (because of timestamps), so the cache never
hits and semantically identical errors don't cluster in the vector
DB. After normalization, both produce the same canonical
fingerprint — the cache hits, the vector DB clusters correctly, and
SME-approved fixes get reused.

### 5.3 Cosine distance + deterministic IDs

**Two different things share the name "L2" — clarify up front.**

- **L2 *distance* (Euclidean):** Today's bug. Chroma defaults to L2
  distance, but the code computes `sim = 1 - dist`, which only makes
  sense for cosine. We are switching the distance metric **away** from
  L2.
- **L2 *normalize* the vector:** A math preprocessing step. Divide
  each vector by its length so it has magnitude 1. After
  L2-normalizing, cosine similarity equals a simple dot product
  (faster, numerically stable). This is a preprocessing trick, not
  the distance metric.

So we are: dropping L2 *distance*, switching to *cosine* distance,
and L2-*normalizing* the vectors before storing them.

**Concrete changes.**

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

**Why it matters.** Without this, (a) the same approved fix gets
stored as multiple separate rows over a week because Python's
`hash()` is salted per process, and (b) the threshold of 0.78 on a
mismatched metric was matching unrelated errors. After these
changes, the same fingerprint always maps to the same row, and the
threshold is properly calibrated.

### 5.4 Store only the error in the vector DB

**Plain-terms goal.** Embed only the normalized error fingerprint
(short and specific). Keep context lines available as metadata for
display and disambiguation, but never let them influence the vector
search.

Rewrite `save_fix_to_db`. Only **one** thing is embedded, and the
stores split cleanly (A-4): **Chroma holds vectors, SQLite holds
facts.** Metadata lives in a SQLite system-of-record (`fixes` table,
with `fix_revisions` capturing full edit history — who, when,
old/new text), because the KB APIs and dashboard need SQL-grade
filtering, pagination, and free-text search that Chroma metadata
cannot provide.

| Field | Where it goes | Embedded? |
|---|---|---|
| Normalized fingerprint | Chroma embedding input | ✅ yes |
| `fix_text` | Chroma document (debug copy) **+ SQLite `fixes.fix_text` (source of truth)** | ❌ no |
| everything below | **SQLite `fixes` table** (joined to Chroma by the shared `fix-sha256(fp)` id) | ❌ no |

**Full metadata key list (A-4):**

*From GitLab / Jenkins (via extractor):*

| Key | Example / note |
|---|---|
| `ci_system` | `gitlab` / `jenkins` |
| `repo` | `payments-service` |
| `branch` | `feature/JIRA-123` |
| `commit_sha` / `commit_message` | `a1b2c3d` / `"fix: bump react"` |
| `author_name` / `author_email` | the developer to DM |
| `pipeline_id` / `pipeline_url` | link to the run |
| `job_name` / `job_url` | `build-frontend` |
| `stage` | `Build` / `Test` / `Deploy` |
| `build_number` | Jenkins `#482` |
| `runner_or_agent` | `linux-node-12` — useful for infra errors |
| `stage_durations` / `total_duration` | per-stage E.Time + total (feeds stats, C-1) |
| `failed_at` | timestamp |

*From analysis (analyzer-side):*

| Key | Example / note |
|---|---|
| `error_fingerprint` | normalized error (§5.2) |
| `error_pattern` | which pattern matched: `npm_error`, `maven_failure`, `timeout`, … |
| `error_class` | `code \| infra \| flaky` (A-9; drives B-11 routing) |
| `raw_error_lines` | original lines, untouched, for display |
| `context_sample` | first ~2 KB of surrounding log |
| `product_team` | auto-derived from repo name via routing JSON (B-6) |
| `embedding_model` | e.g. `granite-embedding:latest` (A-13 upgrade guard) |

*Fix lifecycle:*

| Key | Example / note |
|---|---|
| `fix_text` | the solution (also the Chroma document) |
| `source` | `manual` / `llm` / `sme_approved` / `sme_edited` / `llm_adjusted` (A2) |
| `status` | `pending` / `approved` / `edited` / `deprecated` |
| `approver` | Slack display name |
| `revision` | bumped on each edit — edit history |
| `created_at` / `updated_at` | timestamps |
| `hits` | how many times this fix has been served — trust + pruning signal |
| `last_served_at` | freshness signal; drives "needs attention" ordering |
| `helpful_count` / `unhelpful_count` | 👍/👎 from developer DMs (B-13); 3× 👎 auto-flags |
| `jira` | linked ticket key, e.g. `RD-15420` — prevents duplicate tickets (B-12) |

Context lines stay available for display and disambiguation but
never pollute the retrieval embedding.

**Why it matters.** Today the embedding contains the error plus ~50
lines of surrounding build output. That noise dominates the
similarity math, so unrelated errors with similar surrounding output
match against each other (this is the "poisoning" symptom we saw in
production). Embedding only the normalized error fingerprint makes
the search laser-focused on the failure itself.

### 5.5 Context-based disambiguation

**Plain-terms goal.** When the vector DB returns multiple candidates
above 0.90 — same error pattern, but the right fix depends on
*where* the error happened (frontend vs backend repo, Node 12 vs
Node 19 agent, etc.) — break the tie cheaply using context
similarity, without spending an LLM call.

`lookup_existing_fix` returns top-K=10 candidates with cosine
similarity ≥ 0.90. When more than one passes:

- compute `ctx_sim = cosine(embed(query.context_lines),
  embed(candidate.context_sample))`
- score = `0.7 * error_sim + 0.3 * ctx_sim`
- return the top score if `score_1 − score_2 > 0.05`; otherwise
  let A2 (Deviation Analyzer) decide

No LLM call is involved in this disambiguation step — pure
deterministic vector math.

**Why it matters.** Two repos can have identical error text but the
correct fix depends on surrounding context (which build tool, which
CI agent, which language version). Pure error-text similarity cannot
tell them apart. A small weighted boost from context similarity
resolves most ties cheaply; only the genuinely ambiguous cases
escalate to A2.

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

**Replaces `summarize_error_with_ai` (B-1).** MVP1 makes an extra
uncached LLM call per Slack message just to shorten long error text
(`slack_helper.py:124`). A1's fingerprint + first N error lines become
the display summary instead — that LLM call is deleted, saving cost
and latency on every message.

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
fix from A2, or synthesized fix from A3), apply routing and safety
rules, and format it into Slack payloads. A4 owns everything about
*how results reach people* (scope items B-4 … B-13).

**Inputs:**
- The final fix (fix_text + source + confidence)
- Metadata: error_fingerprint, candidate similarity (if applicable),
  A2 reasoning (if applicable), error_class, product_team

**Responsibilities:**

| Scope | Behavior |
|---|---|
| B-4 | One Slack message **per failed stage**; multiple errors within that stage go as thread replies under it. Different stages → separate messages. |
| B-5 | Recurring fingerprint → update the canonical message with a counter ("⚠️ seen 6× this week"), DM the developer directly instead of re-posting. |
| B-6 | Resolve repo/job → channel + product_team + SME group from the routing JSON (restart to apply). Default route for unmapped repos. |
| B-7 | Dedup by fingerprint within one request: same error in 3 stages → one analysis, one DM noting "seen in 3 stages". |
| B-8 | `users_lookupByEmail` fails (service account, bot, email mismatch) → post to the team channel from routing config, naming the commit author. |
| B-9 | DM shows provenance: source ("SME-approved fix, served 12× this month" vs "AI-generated, unverified"), last-seen date, originating repo. |
| B-10 | Dangerous-fix guardrail: denylist regex (`rm -rf`, `chmod 777`, `git push --force`, `kubectl delete`, …) on fix_text before any post. Hit → hold for SME review with ⚠️, never DM'd raw. |
| B-11 | `error_class = infra` → route to DevOps channel, not the developer. `flaky` → DM suggests pipeline retry. Only `code` errors DM the developer as actionable. |
| B-12 | "🎫 Create Jira" button on SME messages; auto-create on `no_match`/low-confidence (configurable). Ticket pre-filled with error, context, probable fix, metadata, Slack permalink; `jira` key stored to link recurrences instead of duplicating. |
| B-13 | 👍/👎 buttons on the developer DM; counts stored on the fix; 3× 👎 auto-flags to the SME channel. |

**Outputs:** Slack channel message (stage-grouped, with SME
Approve/Edit buttons where applicable) + developer DM (fix,
provenance, feedback buttons) + optional Jira ticket.

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

---

## 16. KB Management & Dashboard (Pillar D)

### 16.1 REST APIs (D-1)

Full CRUD, **SQL-backed**: list/filter/search/pagination run as
plain SQL against the `fixes` table (A-4), and revision history comes
from `fix_revisions` — no Chroma metadata queries involved. One API
surface serves **both** consumers: CLI/automation (scripts, future
Claude CLI integration) and the KB dashboard (§16.2) — the dashboard
is just a UI over these endpoints, no separate write path.

| Endpoint | Purpose |
|---|---|
| `POST /api/fixes` | Add a new fix manually (absorbs today's `add_manual_fix` / `bulk_manual_fix` endpoints into the same CRUD surface) |
| `GET /api/fixes` | List/filter/search the KB: by product team, error_pattern, repo, branch, stage, source, status, approver, date range, free text |
| `GET /api/fixes/{id}` | Full detail incl. revision history, hits, feedback, Jira link |
| `PUT /api/fixes/{id}` | Edit a stored fix — any fix, any age (RD-15321). Bumps `revision`. |
| `DELETE /api/fixes/{id}` | **Deprecate, not hard-delete**: sets `status=deprecated`; retrieval filters it out. A poisoning row becomes a 10-second API call instead of manual DB surgery. |

### 16.2 Dashboard views (D-2)

- **Resolved view** — every resolved error: error, solution, source
  (manual/LLM/SME), approver, hits, product team, error_pattern,
  Jira link, last served, feedback counts.
- **Pending / needs-attention view** — errors awaiting SME review,
  low-confidence LLM answers, 👎-flagged fixes. Same columns,
  **editable from here regardless of age**.
- **Stats view** — hit rates, per-product failure counts, per-pattern
  trends, cost (powered by C-2/C-3/C-4 telemetry).
- **Filters everywhere:** product team, error_pattern, repo, branch,
  stage, source, status, approver, date range, free-text search.

### 16.3 Lifecycle (D-3, D-4)

- Monthly pruning job: `status=deprecated` or (hits=0 ∧ age > 6
  months) → export to archive file, delete from collection. Candidates
  surfaced in the dashboard before deletion.
- Backups: daily, via the SQLite `.backup` API for `bfa_kb.db`,
  `bfa_stats.db`, and Chroma's internal store — never a raw `tar` of
  live database files (a live tar can capture a mid-write state).
  Retention 14 days; restore procedure documented. Interim answer
  until RD-15338 (scalable vector DB — direction: pgvector, which
  would unify vectors + metadata + stats in one Postgres).

---

## 17. Resilience & Ops (Pillar E)

### 17.1 Degradation ladder (E-1)

Each dependency degrades; none of them 500s the request:

| Dependency down | Behavior |
|---|---|
| Redis | skip cache, continue to vector DB |
| Ollama (embeddings) | skip vector lookup, go straight to A3 |
| Chroma | same — straight to A3 |
| LLM endpoint | "unable to analyze" + DevOps email & Slack (B-3) |

Every row is a chaos test in the E2E suite (§18, F-4).

### 17.2 Recovery & alerting (E-2, E-3)

- **Dead-letter queue:** payloads that exhaust `api_poster` retries are
  written as JSON files to a dead-letter directory (today they are
  only logged — `api_poster.py:1023` — and lost). `replay_failed.py`
  re-posts them once the analyzer is back.
- **Crash recovery:** `Restart=on-failure` in
  `build-failure-analyzer.service` (covers RD-15248).
- **Silent-failure alert:** systemd can't see "process alive but
  nothing works" — one alert rule via `error_notifier.py`: webhooks
  received > 0 while analyses completed = 0 over 15 min → notify
  DevOps. Plus a cron hitting `/health`.

### 17.3 Slack & config hygiene (E-4, A-12, B-14, B-15)

- Enable slack_sdk's `RateLimitErrorRetryHandler` (burst of failures
  → 429s are retried, not dropped).
- Validate routing JSON + patterns config against a schema at startup;
  refuse to start on error. Fail fast beats mis-route quietly.
- Delete `slack_reviewer.py` (duplicate Flask copy of the FastAPI
  handlers); one source of truth for Slack actions.
- Slack edit-prompt keys get a 15-min TTL and O(1) per-user lookup
  (replaces the `redis.keys()` scan per message event).

### 17.4 Already covered by existing config (E-5)

Extraction volume caps already exist — `ERROR_ADAPTIVE_THRESHOLDS`
and `MAX_LOG_LINES` (`config_loader.py:339`,
`log_error_extractor.py:527`). No new work; document the knobs in the
ops runbook.

---

## 18. Testing & Validation Strategy (Pillar F)

**Why this pillar exists (P23):** the MVP1 suite mocks all vector
math — `_get_embedding` returns `[0.1, 0.2, 0.3]`, `collection.query`
returns canned results. The production poisoning bug lived exactly in
the mocked-out layer, which is why the suite stayed green while
production was wrong. MVP2 adds layers where the real math and the
real wiring are exercised.

### 18.1 Five levels

| Level | What | Runs |
|---|---|---|
| **1 — Unit** (extend existing pattern) | Normalizer golden tests (30–50 input→fingerprint pairs); orchestrator state machine — every branch of §4.1 with fake agents; A2/A3 with mocked LLM (schema, retry, confidence floor); A4 formatting/routing/guardrail | every PR |
| **2 — Component, real vector math** | Real Chroma (temp dir) + real Ollama embeddings, no mocked distances. **Poisoning regression test** (insert old-style 5 KB blob → unrelated error must NOT match ≥ 0.90 — this test recreates the production incident and stays forever). Threshold calibration on ~20 known pairs. Deterministic-ID test (same fix saved twice across restarts → one row, revision bumped). | merge to main, on the Ollama test instance (RD-15346) |
| **3 — Wire contract** | One shared JSON Schema for `/api/analyze`; extractor asserts its real output validates; analyzer asserts schema examples POST successfully. Both old + new payload shapes during the migration overlap. | every PR |
| **4 — End-to-end, mocked externals** | docker-compose stack: real extractor + analyzer + Redis + Chroma; mock GitLab/Jenkins (canned logs), mock LLM (record real responses once, replay deterministically), mock Slack (captures payloads). Scenarios: cold → A3 → messages; repeat with changed timestamps → cache hit, zero LLM calls; Approve click → row **updated** not inserted; variant → A2 adjusted; unrelated error → no false match; 2 stages/3 errors → exactly 2 messages, 1 threaded; plus one chaos test per §17.1 row. | merge to main |
| **5 — Eval harness** | `eval/regression_set.jsonl` cases (`error`, `context`, `expected_route`, `must_contain`, `must_not_contain`) replayed through the full pipeline by `eval/run_eval.py`, which computes the metrics below and emits a JSON + markdown report as a CI artifact. | CI mode (mock LLM) every PR; nightly mode (real Bedrock, ~50 gold cases, ~$1/night) with report to DevOps channel |

### 18.2 Metrics & gates (F-5)

| Metric | Calculation | Gate |
|---|---|---|
| Routing accuracy | % of cases taking `expected_route` (+ confusion matrix) | ≥ 95% |
| False-positive match rate | % of known-unrelated pairs scoring ≥ 0.90 — *the poisoning metric* | **0%** |
| Retrieval recall | % of known-variant pairs with the right stored fix in top-3 | ≥ 90% |
| Answer keyword pass | `must_contain` present ∧ `must_not_contain` absent | ≥ baseline, never drops on a PR |
| Cost per 1k | mock-LLM call count × per-call price | within forecast (~$6–8) |
| Latency p50/p99 | measured per route | within §1 targets |

### 18.3 CI wiring

| When | What runs |
|---|---|
| Every PR | Level 1 + Level 3 + Level 5 (mock mode) |
| Merge to main | Level 4 compose stack + Level 2 (Ollama test instance) |
| Nightly | Level 5 real-LLM mode; report posted to DevOps channel |

Housekeeping: wire the analyzer's test suite into the root
`pyproject.toml` testpaths so one command runs both services' tests,
and clear the analyzer repo's linter issues (F-6, RD-15333) before
enabling lint gates in CI.
