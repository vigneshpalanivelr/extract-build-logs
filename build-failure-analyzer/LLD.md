# Build Failure Analyzer MVP2 — Low-Level Design (LLD)

Companion to `HYBRID_PROPOSAL.md` (scope: §1.2 Six Pillars) and
`CURRENT_FLOW.md` (MVP1 behavior). Scope IDs (A-1 … F-6) are used
throughout. This document is implementation-ready: file paths,
signatures, schemas, and pseudocode are normative unless a better
option is found during implementation (deviations go in PR
descriptions).

Team-size note: the plan (§13) is organized as independent
**workstreams** with explicit dependencies — it works for 1 engineer
(sequential), 2, or 3 (parallel), without re-planning.

---

## 1. Component Architecture

```mermaid
flowchart TB
    WH(["GitLab / Jenkins webhook<br/>(pipeline finished)"]) --> WL

    subgraph EXT["LOG EXTRACTOR (src/)"]
        direction TB
        WL["webhook_listener.py<br/>receive + validate"] --> PE["pipeline_extractor.py<br/>pipeline / stage info"]
        PE --> LF["log_fetcher.py<br/>pull console log"]
        LF --> LEE["log_error_extractor.py<br/>per-region split A-1 · patterns config A-9"]
        LEE -- "List[ErrorRegion]" --> RED["redactor.py A-8<br/>strip secrets"]
        RED --> AP["api_poster.py<br/>v2 payload A-1 · retry + dead-letter E-2"]
        AP -.-> DL[("dead_letter/*.json<br/>replay_failed.py")]
    end

    AP == "POST /api/analyze → 202 Accepted (A-10)" ==> AS

    subgraph ANA["BUILD FAILURE ANALYZER (build-failure-analyzer/)"]
        direction TB
        AS["analyzer_service.py (FastAPI)<br/>background task per request"] --> ORC

        ORC["orchestrator.py — state machine<br/>A1 summarizer (no LLM) · A2 deviation (LLM)<br/>A3 synthesizer (LLM) · A4 reporter (no LLM)"]

        subgraph DATA["data path"]
            NORM["normalizer.py A-2"]
            VDB["vector_db.py A-3 / A-13<br/>cosine · sha256 · dim guard"]
            KBS["kb_store.py A-4<br/>SQLite fixes + fix_revisions"]
        end

        subgraph DELIV["delivery path (A4)"]
            ROUT["routing.py B-6"]
            GUARD["guardrail.py B-10"]
            JIRA["jira_client.py B-12"]
            SLK["slack handlers B-14<br/>+ feedback B-13"]
        end

        subgraph MGMT["management plane"]
            KB["kb_api.py D-1<br/>full CRUD /api/fixes (SQL)"]
            ST["stats.py SQLite C-1..C-4"]
            DASH["dashboard/ SPA D-2"]
            WDG["watchdog.py E-3"]
        end

        ORC --> DATA
        ORC --> DELIV
        DASH --> KB
        ST --> KB
    end

    DATA --> R[("Redis<br/>caches")] & CH[("Chroma<br/>vectors only<br/>single process")] & KDB[("bfa_kb.db<br/>SQLite<br/>system of record")] & OL["Ollama<br/>granite-embedding"]
    ORC --> BR["Bedrock Claude<br/>via OpenWebUI"]
    SLK --> SAPI["Slack API"]
    JIRA --> JAPI["Jira API"]
    WDG --> SMTP["SMTP alerts"]
```

Reading guide:

| Zone | What happens there |
|---|---|
| Extractor (top) | webhook → fetch log → split into `ErrorRegion`s → redact secrets → POST v2 payload; failures land in `dead_letter/` for replay |
| Orchestrator (middle) | one background task per request runs the A1→cache→vector→A2/A3→A4 state machine |
| Left column | data path: normalization + vector KB (the layer the poisoning bug lived in) |
| Right column | delivery path: routing, guardrail, Jira, Slack — everything A4 touches |
| Bottom row inside analyzer | management plane: KB CRUD APIs, dashboard, stats, watchdog |
| External (bottom) | Redis, Chroma, Ollama, Bedrock LLM, Slack, Jira, SMTP |

Deleted in MVP2: `slack_reviewer.py` (duplicate Flask service, B-14)
and `summarize_error_with_ai` in `slack_helper.py` (replaced by A1's
deterministic summary, B-1).

### 1.1 End-to-end request sequence

The life of one failed pipeline — happy path with an ambiguous
candidate (the most complete route). Cache hits and exact matches
exit earlier; every terminal path goes through A4.

```mermaid
sequenceDiagram
    autonumber
    participant GL as GitLab
    participant EX as Extractor
    participant AN as Analyzer
    participant A1 as A1 Summariser
    participant RD as Redis
    participant CH as Chroma
    participant A2 as A2 Deviation
    participant A4 as A4 Reporter
    participant SL as Slack

    GL->>EX: webhook (pipeline failed)
    EX->>GL: fetch console log
    EX->>EX: split regions + redact (A-1, A-8)
    EX->>AN: POST /api/analyze (v2 payload)
    AN-->>EX: 202 Accepted (A-10)
    Note over AN: background task starts
    AN->>A1: run(region)
    A1-->>AN: fingerprint + summary
    AN->>RD: GET sme:fix / ai:fix
    RD-->>AN: MISS
    AN->>CH: lookup_candidates(fp, threshold 0.90)
    CH-->>AN: 1 candidate, sim 0.92
    AN->>RD: GET agent:deviation cache
    RD-->>AN: MISS
    AN->>A2: judge(current error, stored error, stored fix)
    A2-->>AN: applicable_with_adjustments
    AN->>RD: SETEX agent:deviation (7 d)
    AN->>CH: upsert adjusted fix
    AN->>A4: deliver(result)
    Note over A4: guardrail → routing → stage grouping
    A4->>SL: channel post (stage-grouped)
    A4->>SL: developer DM (provenance + feedback buttons)
    AN->>AN: record_decision(a2_adjusted, sim, latency, cost)
```

---

## 2. Requirement-by-Requirement — Issue and Solution

**How to read this document.** This section is the map: every
requirement from the Scope document appears here with the issue it
fixes (current behavior → why it's a problem → impact), the solution
step by step, the files touched, and where the detailed reference
design lives. Read this section first; use the later sections as
reference detail.

**Solution approach in one paragraph.** A deterministic foundation
(normalize → fingerprint → cosine vector search with exact and
candidate thresholds) answers the easy 85%: cache hits, exact
repeats, and clear misses. Four agents cover the rest: A1 produces
the fingerprint on every request, A2 judges ambiguous stored-fix
candidates, A3 synthesizes fresh fixes on misses, and A4 applies
safety/routing rules and delivers. The full flow diagram is in §6.3;
every fallback lands on "same behavior as today's LLM fallback —
never worse."

### A — Foundation

#### A-1 — Split error/context on the wire

**Issue — today:** The extractor merges matched error lines with their context windows (50 lines before, 10 after), prefixes every line with `Line N:`, and joins everything into ONE string — `return ['\n'.join(sections)]` (log_error_extractor.py:138). api_poster sends it as a single-element `error_lines`, and the analyzer embeds that whole blob as one vector.

**Why it's a problem:** 95%+ of the blob is boilerplate (timestamps, paths, generic build output) shared by almost every pipeline. A text embedding is dominated by the majority of its tokens, so vectors of completely unrelated failures come out nearly identical — the 2 lines of actual error contribute almost nothing.

**Impact:** This is the direct mechanism of the production poisoning incident: the first approved blob matched nearly every subsequent failure. Reproduction: two unrelated errors wrapped in the same 50 context lines score cosine 1.000 as blobs vs 0.000 error-only (Evidence Pack, Bug 1). Pain: P1.

**Solution:**

1. Change `extract_error_sections` to return `List[ErrorRegion]` (error_lines, context_lines, pattern, class) — stop joining regions, stop `Line N:` prefixes.
2. `api_poster` builds the v2 payload with an `errors[]` array per step; legacy blob field kept while `API_LEGACY_COMPAT=true` (one release).
3. Analyzer accepts both shapes; legacy blobs converted to an ErrorRegion at the boundary.
4. Freeze the shape in `schemas/analyze_payload.schema.json` — both test suites validate against it (F-3).

**Files:** log_error_extractor.py · api_poster.py · analyzer_service.py · schemas/ · **Reference design:** §5

#### A-2 — Normalization + stable fingerprint

**Issue — today:** Raw error text — timestamps, `Line N:` prefixes, epoch values included — is used directly as the cache-key input and the embedding input. There is no canonical identity for an error anywhere in the system.

**Why it's a problem:** The same logical error at 9:14:02 and 9:14:03 is a different string → a different sha256 cache key (captured proof: Evidence Pack, Bug 4) and a slightly different vector. Identity changes every minute by construction.

**Impact:** The cache essentially never hits — every recurrence of a known error pays the full LLM cost — and identical errors fail to cluster in the vector DB. Pains: P1, P5.

**Solution:**

1. New `normalizer.py`: ordered rule table — strip `Line N:` prefixes, ISO/`[HH:MM:SS]`/epoch timestamps, SHA/UUID → placeholders; lowercase; collapse whitespace; cap 2000 chars.
2. `fingerprint_hash = sha256(fingerprint)`.
3. Use the fingerprint everywhere: Redis cache keys, Chroma row IDs, embedding input.
4. Golden tests: table of input → exact expected fingerprint (F-1).

**Files:** normalizer.py · **Reference design:** §6

#### A-3 — Cosine space, deterministic IDs, threshold 0.90

**Issue — today:** The collection is created without `hnsw:space` (vector_db.py:47), so Chroma defaults to L2 — squared Euclidean — while vector_db.py:212 computes `sim = 1 - dist`, a formula valid only for cosine distance. Separately, row IDs come from Python's salted `hash()` (vector_db.py:276), which changes on every process restart; a correct sha1 helper exists at :149 but is never called.

**Why it's a problem:** The computed 'similarity' is unbounded and directionless: a captured vector pair scores +0.907 — above the 0.78 serve threshold — while its true cosine is −0.12, i.e. pointing the opposite way (Evidence Pack, Bug 2). And because IDs are unreproducible across restarts, previously saved rows can never be updated — every re-approval inserts a duplicate (Bug 3: same error, three different IDs in three runs).

**Impact:** The single gate deciding whether a stored fix is served is mathematically meaningless, and bad rows are both permanent and multiplying. Pains: P3, P4.

**Solution:**

1. Create `fix_embeddings_v2` with `{"hnsw:space": "cosine"}`.
2. L2-normalize every vector before `add()`/`query()`; now `sim = 1 - dist` is valid.
3. Thresholds: candidate ≥ 0.90, high-confidence exact ≥ 0.95.
4. Row ID = `fix-` + sha256(fingerprint) — stable across restarts and processes.

**Files:** vector_db.py · **Reference design:** §6

#### A-4 — SQLite system-of-record for metadata

**Issue — today:** Fixes are stored with only ad-hoc metadata (error_text, approver, status) flattened into Chroma metadata. 'Revision' is at best a counter — no record of who changed what, when.

**Why it's a problem:** Chroma metadata supports only exact-match filters: no free-text search, no ranges, no sorting, no pagination. And the data itself is missing — no team, no pattern, no usage counts, no history. The planned KB APIs and dashboard are unimplementable on this storage.

**Impact:** Cannot search the KB by product, cannot route to owning teams, cannot distinguish a battle-tested fix (served 40×) from a stale one-off, cannot audit edits. Pain: P7.

**Solution:**

1. Create `bfa_kb.db`: `fixes` table (wire + analysis + lifecycle keys, indexed) and `fix_revisions` (who/when/old/new per edit) via `kb_store.py`.
2. Chroma keeps only id + embedding + fix_text (debug copy).
3. Write order: SQLite first, then Chroma — partial failure leaves a repairable, consistent record.
4. Retrieval: ANN in Chroma → join metadata from SQLite by shared id.

**Files:** kb_store.py · vector_db.py · **Reference design:** §4

#### A-5 — Context-cosine disambiguation

**Issue — today:** When several stored fixes clear the similarity threshold, the code simply takes the top score.

**Why it's a problem:** Identical error text can come from different contexts requiring different fixes — the same `npm ERESOLVE` in a frontend repo vs a backend service, different build tools, different agents. Error-text similarity alone cannot separate them; near-ties get resolved arbitrarily. Asking an LLM for every tie would be slow and costly.

**Impact:** Wrong-but-similar fixes get served with high confidence in multi-candidate situations.

**Solution:**

1. Compute `ctx_sim = cosine(embed(query context), embed(candidate context_sample))`.
2. Score = 0.7·error_sim + 0.3·ctx_sim; return winner if margin > 0.05.
3. No clear winner → escalate to A2. Ship behind `CONTEXT_COSINE_ENABLED=false` until real context data accumulates.

**Files:** vector_db.py · **Reference design:** §6

#### A-6 — Update-not-insert on approval

**Issue — today:** Every Slack approval calls `collection.add()` — insert, never update — compounded by the non-deterministic IDs from A-3.

**Why it's a problem:** Re-approving or correcting a fix creates a second row for the same error; retrieval then surfaces whichever version wins the similarity race that day.

**Impact:** Duplicates accumulate forever; a corrected fix competes against its own outdated version; during the incident, the poisoning row could not be replaced — only joined by more copies. Pain: P4.

**Solution:**

1. `save_fix` checks the deterministic id: exists → update + revision++ + `fix_revisions` history row; else insert with revision=1.
2. Test: same fix approved twice across two client instances → exactly one row (F-2).

**Files:** vector_db.py · kb_store.py · **Reference design:** §6

#### A-7 — Redis TTLs + fingerprint keys

**Issue — today:** `store_fix` writes `fix:`, `error_map:`, `thread_map:` keys with plain SET — no TTL (slack_helper.py:49, :52, :56). The same codebase uses SETEX correctly elsewhere (resolver_agent.py:59, 24 h TTL on ai:fix), proving this is an omission, not a policy. Worse, `error_map`'s Redis key is the full multi-KB error text itself.

**Why it's a problem:** Every approval leaks three immortal keys, one of them multi-kilobyte. And keys built from raw blobs can never match again once a timestamp changes.

**Impact:** Redis memory grows monotonically forever; the keyspace bloats, which also slows the edit flow's keys() scan (B-15). Pains: P5, P11.

**Solution:**

1. All fix/error_map/thread_map keys switch to `SETEX` with 30-day TTL.
2. `error_map` keyed by fingerprint hash, never raw text.
3. Cache keys become `sme:fix:<fph>` / `ai:fix:<fph>` — same error at any timestamp hits the same key.

**Files:** slack_helper.py · analyzer_service.py · **Reference design:** §4

#### A-8 — Secret redaction in the extractor

**Issue — today:** The extractor masks secrets ONLY in its own log files — logging_config.py:39 is a logging filter attached to loggers. The analysis payload built by api_poster never passes through it: whatever the console log contains is POSTed verbatim.

**Why it's a problem:** Build logs routinely contain Bearer tokens, `password=...` arguments, `https://user:token@...` URLs, and cloud keys printed by misconfigured steps.

**Impact:** One leaked credential becomes PERMANENT in three stores — Redis (cached fix record), Chroma metadata (stored error_text), Slack history (channel post) — outliving any log rotation. Compliance incident waiting to happen. Pain: P2. Pre-rollout blocker.

**Solution:**

1. New `redactor.py`: pattern table (password/token/secret assignments, Bearer, JWT, AWS keys, GitLab/GitHub tokens, user:pass@ URLs) → placeholders.
2. Apply in `api_poster` to every field carrying log content (error_lines, context_lines, tail_lines, commit_message).
3. Golden-file tests with true/false positives; patterns extendable via config.

**Files:** redactor.py · api_poster.py · **Reference design:** §5

#### A-9 — Patterns to config with code|infra class

**Issue — today:** ERROR_PATTERNS is a hardcoded Python list (log_error_extractor.py:29). Adding or fixing a pattern requires a code change and deployment. Patterns carry no classification — a runner disconnect and a compile error are processed identically.

**Why it's a problem:** Pattern coverage lags reality (new failure types go undetected until the next release), and the system cannot tell infrastructure failures from code failures.

**Impact:** Slow evolution of detection, plus the P21 blame problem: developers are DM'd fixes for runner outages that have nothing to do with their commit.

**Solution:**

1. Move ERROR_PATTERNS to `config/error_patterns.json`: {name, regex, class: code|infra, enabled}.
2. Validate at startup (unique names, valid regex) — fail fast naming the bad pattern.
3. The matched pattern's name/class travel in the payload as `error_pattern`/`error_class` and drive B-11 routing.

**Files:** config/error_patterns.json · config_loader.py · log_error_extractor.py · **Reference design:** §3

#### A-10 — 202 + background processing

**Issue — today:** `/api/analyze` is declared `async def` (analyzer_service.py:268), but everything inside blocks: synchronous redis-py, synchronous `requests.post` to the LLM (llm_openwebui_client.py:135), synchronous Slack SDK calls.

**Why it's a problem:** FastAPI runs an `async def` endpoint on the single event-loop thread. A blocking call inside it freezes EVERY in-flight request and stops new ones being accepted — strictly worse than a plain `def`, which would at least run in a threadpool.

**Impact:** One 8-second LLM call = an 8-second global freeze. A burst of 10 failures serializes into ~80 s of frozen service; upstream webhooks time out; extractor retries amplify the load. Pain: P10. Pre-rollout blocker.

**Solution:**

1. `/api/analyze` validates, returns `202 {request_id}` immediately.
2. Orchestrator runs in a FastAPI background task.
3. Blocking clients wrapped: LLM via thread executor, redis/Slack likewise (or async clients).

**Files:** analyzer_service.py · orchestrator.py · **Reference design:** §6

#### A-11 — Structured logging in the analyzer

**Issue — today:** The analyzer logs via bare `print()` — no levels, no structure, no rotation, no request correlation — while the extractor already has a full logging framework (logging_config.py) with rotation and masking.

**Why it's a problem:** Production incidents cannot be traced: which request, which fingerprint, which agent produced a given line? Output capture depends on how the process happens to be launched.

**Impact:** Every diagnosis is grep-and-guess; the existing backlog item RD-15339 tracks exactly this pain.

**Solution:**

1. `logging_setup.py` mirroring the extractor's `logging_config.py` (rotating files, structured extras: request_id, fingerprint, agent).
2. Mechanical PR replacing all print(); then flake8-print (T201) gate keeps it clean (with F-6).

**Files:** logging_setup.py + all analyzer modules · **Reference design:** §9

#### A-12 — Config validation at startup

**Issue — today:** Configuration files are read without validation. A malformed routing file or an invalid regex surfaces later — as a runtime exception on some request, or as silently wrong behavior (e.g., everything falling to a default).

**Why it's a problem:** Config errors are discovered at use-time in production instead of at deploy-time.

**Impact:** A typo deployed Friday evening mis-routes every message all weekend with nobody aware. Fail-fast validation converts that into a refused restart with a clear error message. Pre-rollout blocker.

**Solution:**

1. JSON-Schema for each config file; validate at startup; refuse to start with a clear error message.
2. Unit tests feed malformed configs and assert the exact failure (F-1).

**Files:** routing.py · config_loader.py · **Reference design:** §3

#### A-13 — Embedding model + dimension guard

**Issue — today:** Vectors carry no record of which embedding model produced them; the model is just an env var (OLLAMA_EMBED_MODEL). Nothing pins the collection to a model or a dimension.

**Why it's a problem:** Embeddings from different models — or different quantizations of the same model — live in incompatible vector spaces. Mixed in one collection, every similarity computation is numerically valid but semantically meaningless, and no error is ever raised.

**Impact:** A routine Ollama model upgrade or re-pull would silently reintroduce poisoning-like behavior with no obvious cause. Pain: P12.

**Solution:**

1. Stamp `embedding_model` + `embedding_dim` into collection metadata at creation.
2. Startup: env model ≠ recorded model → StartupError (forces migration to a fresh collection).
3. Every embedding asserted against `embedding_dim` — catches quantization/response-shape drift the name check misses.

**Files:** vector_db.py · **Reference design:** §6

### B — Agents & Delivery

#### B-1 — A1 Error Summariser (deterministic)

**Issue — today:** There is no canonical 'understand the error' step — raw text flows into caches and vectors directly. Meanwhile, Slack display text is produced by an EXTRA uncached LLM call per message (`summarize_error_with_ai`, slack_helper.py:124).

**Why it's a problem:** Error identity work is scattered across the codebase, and a paid, slow, non-deterministic model call is spent on a job a deterministic function does better.

**Impact:** Cost and latency on every single Slack message; inconsistent identity between cache, vector store, and display. Pain: P1 (identity side).

**Solution:**

1. `Summarizer.run(region)` → fingerprint (via normalizer) + display summary (first 3 error lines, ≤300 chars) + pattern/class passthrough.
2. Never fails: normalization error → raw lines as fingerprint.
3. Delete `summarize_error_with_ai` — display text becomes free and deterministic.

**Files:** agents/summarizer.py · **Reference design:** §7

#### B-2 — A2 Deviation Analyzer

**Issue — today:** Retrieval is binary: above the threshold the stored fix is served verbatim; below it, a fresh fix is synthesized. Nothing in between.

**Why it's a problem:** The common 'variant' case — same root cause, different specifics — has no judge. A 0.92-similar stored fix that says 'downgrade to react@17' is served verbatim to a react@18.2 failure (wrong version), or discarded entirely and re-synthesized at full cost.

**Impact:** Wrong specifics served confidently, or paid regeneration of knowledge that is 95% already stored.

**Solution:**

1. `LLMAgent` base: render prompt → LLM in executor → JSON parse → schema validate → ONE retry echoing the validation error.
2. Verdict schema: match_quality (exact/applicable_with_adjustments/partial/no_match), confidence, reasoning, adjusted_fix, adjustments.
3. Redis cache `agent:deviation:sha(fph+candidate_id)` 7 d.
4. Timeout 6 s / malformed / confidence < 0.5 → fall back to A3. No regression possible.

**Files:** agents/base.py · agents/deviation.py · prompts/deviation.md · **Reference design:** §7

#### B-3 — A3 Solution Synthesizer

**Issue — today:** The LLM fallback (`resolver_agent.call_llm`) returns free text: no schema, no confidence value, no structured failure mode, no citations.

**Why it's a problem:** Output cannot be validated, safely post-processed, or measured; failures surface as exceptions or garbage messages; there is no way to distinguish 'the model answered badly' from 'the pipeline broke'.

**Impact:** Unsafe/unusable output paths and no quality signal on the most expensive component in the system.

**Solution:**

1. Formalize as `LLMAgent`: strict JSON {fix_text, confidence, reasoning, source, citations}, timeout 8 s.
2. Accepts partial-match citations from A2 to seed the prompt.
3. Cache `agent:synthesizer:<fph>` 7 d.
4. On failure: respond "unable to analyze" + DevOps email & Slack via error_notifier — never a wrong fix.

**Files:** agents/synthesizer.py · prompts/synthesizer.md · **Reference design:** §7

#### B-4 — Stage-grouped Slack messages

**Issue — today:** Every analyzed error posts its own top-level channel message (send_error_message) — no threading, no grouping by pipeline or stage.

**Why it's a problem:** One pipeline failing 3 stages posts 3+ disconnected messages; a busy day across products produces a wall of them.

**Impact:** The channel becomes an unreadable firehose; SMEs stop scanning; approvals stall; the human-in-the-loop flywheel that grows the KB dies of fatigue. This was reported as the team's #1 daily friction. Pain: P17.

**Solution:**

1. A4 groups results by `stage` per request.
2. First result of a stage posts the parent message (stage, repo, branch, pipeline link, author).
3. Further errors of that stage post as thread replies under the parent's `thread_ts`.

**Files:** agents/reporter.py · **Reference design:** §7

#### B-5 — Recurring-error counter instead of re-post

**Issue — today:** A recurring known error posts a brand-new message on every recurrence.

**Why it's a problem:** Recurrence is exactly when LESS attention is needed — the fix is already known and approved. Yet repeats dominate the channel volume.

**Impact:** Genuinely new failures drown among repeats. Pain: P17.

**Solution:**

1. `msg:canonical:<fph>` in Redis stores {channel, ts, count, last_seen} (30 d TTL).
2. Recurrence → `chat_update` the canonical message ("seen N× this week") + DM the developer directly. No new channel post.

**Files:** agents/reporter.py · **Reference design:** §7

#### B-6 — Team routing via config

**Issue — today:** The destination channel is one global env var (`SLACK_CHANNEL`, slack_helper.py:16). No repo→team mapping exists anywhere in the system.

**Why it's a problem:** Every product's failures land in one shared channel. With multiple SPOCs each owning different products, everyone must read everything to find their own items; nothing can be assigned or mentioned to the right group.

**Impact:** Messages are routinely missed; ownership is ambiguous; cross-team noise trains people to ignore the channel. Pain: P18.

**Solution:**

1. `config/routing.json`: repo_pattern → channel, product_team, sme_group, jira_project; first match wins; default route for unmapped repos.
2. `routing.resolve(repo, job)` called by A4 for every delivery; SME group mentioned on post.
3. Change file + restart = new routing live; schema-validated at startup (A-12).

**Files:** routing.py · config/routing.json · **Reference design:** §3

#### B-7 — In-request fingerprint dedup

**Issue — today:** The analyzer loops `for step in failed_steps: for error_line in step.error_lines:` (analyzer_service.py:277) with no de-duplication inside a request.

**Why it's a problem:** One root cause failing build, test, and package stages is treated as three unrelated problems — common in GitLab, where one broken dependency fails every stage that touches it.

**Impact:** 3× embedding cost, 3× LLM calls, 3× messages and DMs — for zero added information. Pain: P8.

**Solution:**

1. `dedupe_by_fingerprint(all_regions(payload))` at orchestrator entry.
2. One analysis; the DM and channel message note "seen in N stages: build, test, package".

**Files:** orchestrator.py · **Reference design:** §6

#### B-8 — Delivery fallback when developer not found

**Issue — today:** The developer DM resolves its recipient via `users_lookupByEmail` on the CI-provided email; on failure the code logs the miss and DROPS the generated fix.

**Why it's a problem:** Failures are routine, not exotic: scheduled/automated pipelines run as service accounts, and some developers' CI email differs from their Slack email.

**Impact:** Precisely the unattended pipelines (nightly builds, release automation) — where a surfaced fix is most valuable — are the ones whose fixes silently evaporate after the full analysis cost was paid. Pain: P19.

**Solution:**

1. `users_lookupByEmail` failure → post the fix to `route.channel` (B-6) naming the commit author.
2. A generated fix always lands somewhere visible; the miss is counted in stats.

**Files:** agents/reporter.py · **Reference design:** §7

#### B-9 — Provenance in the developer DM

**Issue — today:** The DM shows the fix text and nothing else — no indication of where the fix came from or its track record.

**Why it's a problem:** An SME-approved fix that has resolved 40 failures and a fresh unverified AI guess are visually identical to the recipient.

**Impact:** Developers cannot calibrate trust: they either over-trust guesses (dangerous) or under-trust proven fixes (wasteful).

**Solution:**

1. DM includes: source (SME-approved / AI-generated), `hits` ("served 12×"), `last_served_at`, originating repo — all read from kb_store.

**Files:** agents/reporter.py · **Reference design:** §7

#### B-10 — Dangerous-fix guardrail

**Issue — today:** A3-synthesized fixes go straight to the developer DM with no safety check of any kind.

**Why it's a problem:** Two reasons a prompt alone cannot fix this: (1) LLM output is probabilistic — instructions reduce frequency, never to zero; (2) the build log itself is part of the prompt, and log content is attacker-controllable — a malicious dependency can print text designed to steer the model (prompt injection). A guard living inside the prompt can be defeated by the prompt.

**Impact:** One `rm -rf` suggestion followed by a tired developer is a disaster plus permanent trust loss. Pain: P22. Pre-rollout blocker.

**Solution:**

1. `guardrail.py`: table-driven denylist regex (rm -rf, chmod -R 777, force-push to protected, kubectl delete ns/deploy, DROP TABLE/DATABASE, mkfs, dd if=, fork bomb, curl|sh).
2. Runs on final fix_text before ANY post, on every terminal path.
3. Hit → SME review with ⚠ warning; the developer never receives it directly.
4. Plus prompt guidance in A3 (reduces frequency; the denylist is the enforcement).

**Files:** guardrail.py · agents/reporter.py · **Reference design:** §7

#### B-11 — Infra errors to DevOps, never the developer

**Issue — today:** Every failure follows the same path: extract → analyze → DM the person who triggered the pipeline — regardless of cause.

**Why it's a problem:** A runner disconnect, registry outage, or network timeout is not the developer's fault, but the DM implies 'your build failed, here is a fix'.

**Impact:** Repeated false blame is the fastest way to get the bot muted; once muted, even correct fixes go unseen. Pain: P21.

**Solution:**

1. A4 switches on `error_class` (from A-9): infra → DevOps channel post, no developer DM; code → normal flow.

**Files:** agents/reporter.py · **Reference design:** §7

#### B-12 — Jira creation from an issue

**Issue — today:** Escalating a failure to the product team means manually creating a Jira ticket and retyping the error, context, and history by hand. Nothing links tickets to stored fixes.

**Why it's a problem:** Friction means tickets often are not created at all; when they are, the next occurrence of the same failure creates a duplicate because nothing connects them.

**Impact:** Recurring issues stay untracked; ticket history fragments. Pain: P20.

**Solution:**

1. `jira_client.create_or_link(error_id)`: fix already has `jira` key → return it (link, never duplicate).
2. Else POST issue: project from routing config; summary `[BFA] <pattern>: <summary>`; description = error + context + probable fix + pipeline metadata + Slack permalink.
3. Store key in `fixes.jira`; update the Slack message with the link.
4. Triggers: 🎫 button on SME messages; optional auto-create on no-match/low-confidence.

**Files:** jira_client.py · **Reference design:** §7

#### B-13 — Feedback buttons + auto-flag

**Issue — today:** After a fix is DM'd, the loop simply ends — there is no signal whether the fix actually helped.

**Why it's a problem:** Fix quality is unmeasurable, so bad fixes keep being served indefinitely and good ones earn no visible track record (see B-9).

**Impact:** KB quality can only degrade silently; SMEs never learn which of their approvals work in practice.

**Solution:**

1. 👍/👎 on every developer DM (`fb_up_<fph>` / `fb_down_<fph>` actions).
2. Handler → `stats.record_feedback` + `fixes.helpful_count/unhelpful_count`.
3. `unhelpful_count ≥ 3` → auto-flag post to the owning SME channel + appears in the dashboard needs-attention view.

**Files:** slack handlers · stats.py · kb_store.py · **Reference design:** §7

#### B-14 — Consolidate Slack handlers (delete slack_reviewer.py)

**Issue — today:** Two OS processes run against the same data: the analyzer (FastAPI) and slack_reviewer.py (a separate Flask app) — each opens its own `chromadb.PersistentClient` on the SAME directory (slack_reviewer.py:19), and each carries a near-identical copy of the Approve/Edit/Discard handler code.

**Why it's a problem:** Embedded Chroma is single-process by design (SQLite + memory-mapped HNSW segments); concurrent writers from separate processes are unsupported and can corrupt the index. The duplicated handlers also mean a bug fixed in one copy silently survives in the other.

**Impact:** Every Slack approval (a write from the Flask process) races analyzer writes over the knowledge base. Pain: P6 — this is a data-integrity fix, scheduled FIRST in Phase 1.

**Solution:**

1. Delete `slack_reviewer.py`; the FastAPI handlers in analyzer_service are the single implementation.
2. Point the Slack app's event/action URLs at the analyzer.
3. Execute FIRST in Phase 1 — it is a data-integrity fix, and trivial (a deletion).

**Files:** delete slack_reviewer.py · **Reference design:** §7

#### B-15 — Sane edit-session TTL + O(1) lookup

**Issue — today:** Clicking ✏ Edit stores the edit intent in Redis with NO TTL, and the message handler runs `redis.keys(pattern)` — a full keyspace scan — on EVERY channel message to check whether the sender is in edit mode.

**Why it's a problem:** An SME who clicks Edit and walks away is stuck in edit mode forever: their next unrelated thread reply gets silently saved as a 'fix'. And the O(N) scan runs on every message in the channel, against a keyspace that (per A-7) only ever grows.

**Impact:** Accidentally corrupted fixes + growing Redis load; and outside this fragile window there is NO way to edit a stored fix at all. Pain: P16.

**Solution:**

1. Edit click → `SETEX last_edit:<channel>:<user> <TTL> <error_id>` (configurable; default 1 week per team decision).
2. Message handler does one O(1) GET (replaces the keys() scan).
3. Expired → friendly "edit session expired" prompt. Any-age editing lives in the Edit API/dashboard (D-1/D-2).

**Files:** slack handlers · **Reference design:** §7

### C — Stats & Telemetry

#### C-1 — Pipeline statistics

**Issue — today:** No pipeline outcome is recorded anywhere: success/failure counts, per-stage durations, and affected users flow through the system and are discarded.

**Why it's a problem:** Basic operational questions are unanswerable: which products fail most? how long do stages take? is CI health improving or degrading?

**Impact:** No baseline exists for measuring anything — including whether BFA itself helps.

**Solution:**

1. `stats.py` (SQLite `bfa_stats.db`, WAL): `pipeline_events` row per webhook — user (name, mail, commit, branch, product), per-stage E.time + status, total time, success/failed.
2. Fire-and-forget writes: never block or fail an analysis.

**Files:** stats.py · **Reference design:** §4

#### C-2 — Decision telemetry

**Issue — today:** The analyzer does not record what it decided: which path answered each request (cache / vector / LLM), at what similarity, latency, or cost.

**Why it's a problem:** Cost and accuracy claims are anecdotes. A regression in cache hit-rate or a drift in similarity scores would be invisible until users complain.

**Impact:** No basis for tuning thresholds, forecasting spend, or proving value. Pain: P7 (measurement side).

**Solution:**

1. `analyze_decisions` row per analyzed error: source, similarity, latency_ms, llm_calls, est_cost, fingerprint, product_team.
2. Emitted at every orchestrator terminal path; feeds the dashboard Stats view.

**Files:** stats.py · orchestrator.py · **Reference design:** §4

#### C-3 — Feedback counts in stats

**Issue — today:** Even once feedback buttons exist (B-13), individual clicks are useless without aggregation.

**Why it's a problem:** Per-fix helpfulness must be queryable for the dashboard, the auto-flag rule, and pruning (D-3) to act on it.

**Impact:** Without aggregation, the feedback signal collected from developers changes nothing.

**Solution:**

1. `feedback_events` rows + rollups exposed via `GET /api/stats/*` for the dashboard.

**Files:** stats.py · **Reference design:** §4

#### C-4 — Zero-match telemetry

**Issue — today:** A failed pipeline that matches no ERROR_PATTERN produces nothing at all: no analysis, no message, no record that the miss happened.

**Why it's a problem:** When a new failure class appears, the tool goes blind to it — and nobody can even know, because the miss leaves no trace.

**Impact:** Silent coverage decay; the pattern config never learns; developers assume the tool 'went quiet'.

**Solution:**

1. Extractor still posts with `errors: []` + `tail_lines` (last 50).
2. Analyzer records `zero_match=1` and notifies DevOps with the tail so the missing pattern gets added.

**Files:** log_error_extractor.py · stats.py · **Reference design:** §4

### D — KB Management & Dashboard

#### D-1 — Full-CRUD KB APIs (SQL-backed)

**Issue — today:** The KB is writable only through Slack approval and readable only through ad-hoc Python scripts. There is no endpoint to list, search, edit, or retire a fix.

**Why it's a problem:** During the incident, removing the poisoning row required hand-editing a live, single-process embedded database — the riskiest possible intervention (see B-14).

**Impact:** Bad approvals are effectively permanent (P15); routine KB maintenance — corrections, updates, curation — is impossible (P14, P16).

**Solution:**

1. `kb_api.py` router: POST add · GET list (team/pattern/repo/stage/source/status/approver/date/free-text filters, pagination) · GET detail (+revision history) · PUT edit (revision++) · DELETE deprecate (soft; retrieval filters it out).
2. All reads are plain SQL on `bfa_kb.db`; Chroma touched only on add / fix_text change.
3. JWT-protected like /api/analyze; serves CLI/automation and the dashboard alike.

**Files:** kb_api.py · kb_store.py · **Reference design:** §8

#### D-2 — Dashboard

**Issue — today:** The only 'view' of failures, pending reviews, or KB contents is scrolling Slack history.

**Why it's a problem:** SMEs triage from memory; managers have no failure overview; low-confidence answers and flagged fixes have no home where anyone would notice them.

**Impact:** Work that needs attention is invisible until someone stumbles on it. Pains: P13, P14, P16.

**Solution:**

1. Static SPA (plain HTML+JS, no build toolchain) served at `/dashboard` by FastAPI StaticFiles.
2. Tabs mapping 1:1 to APIs: Resolved · Needs-attention (pending review, low-confidence, 👎-flagged; edit/deprecate inline, any age) · Stats.
3. Filters are query-param passthroughs to D-1.

**Files:** dashboard/ · **Reference design:** §8

#### D-3 — Monthly KB pruning

**Issue — today:** Nothing ever leaves the knowledge base — deprecated rows and fixes for repos deleted a year ago stay forever.

**Why it's a problem:** Dead rows add retrieval noise (more candidates to score, more near-threshold accidents) and storage grows without bound.

**Impact:** KB quality decays passively over time even if every individual approval was good.

**Solution:**

1. `prune_kb.py --dry-run|--apply`: status=deprecated OR (hits=0 ∧ age>6 mo) → JSON archive → delete.
2. Monthly cron posts the dry-run to DevOps; --apply run manually after review; candidates visible in the dashboard first.

**Files:** scripts/prune_kb.py · **Reference design:** §9

#### D-4 — Safe daily backups

**Issue — today:** No backups exist for the KB or stats. The naive approach — tar of the live directory — can capture a mid-write state and restore corruption.

**Why it's a problem:** The KB is the system's main asset: accumulated, SME-curated tribal knowledge that cannot be regenerated.

**Impact:** One disk failure erases everything the flywheel has built.

**Solution:**

1. `backup_bfa.sh` daily cron: SQLite `.backup` API for bfa_kb.db, bfa_stats.db, and Chroma's internal chroma.sqlite3 (+ index dir copy).
2. Keep 14; documented restore procedure in README-OPS.

**Files:** scripts/backup_bfa.sh · **Reference design:** §9

### E — Resilience & Operations

#### E-1 — Degradation ladder

**Issue — today:** An outage of Redis, Ollama, Chroma, or the LLM endpoint surfaces as unhandled exceptions → 500s → extractor retries → eventually dead letters.

**Why it's a problem:** Each dependency has an obvious weaker-but-working fallback (skip cache; skip vector, synthesize fresh; report 'unable to analyze') — but none is implemented, so any single outage becomes total failure.

**Impact:** Availability is the minimum of five dependencies, and retry storms amplify every incident. Pre-rollout blocker.

**Solution:**

1. Thin wrappers everywhere: Redis error → skip cache, continue; Ollama/Chroma error → `VectorUnavailable` → treat as 0 candidates → A3; LLM error → "unable to analyze" + notify.
2. Every recovery increments a stats counter (dashboard-visible) and is watchdog/health-check notified.
3. One chaos test per ladder row in the E2E suite (F-4).

**Files:** orchestrator.py · vector_db.py · **Reference design:** §9

#### E-2 — Dead-letter + replay

**Issue — today:** When POST retries are exhausted, api_poster only LOGS the failed payload (api_poster.py:1023) and gives up.

**Why it's a problem:** The analysis is lost; recovery means grepping log files and reconstructing payloads by hand.

**Impact:** A two-hour analyzer outage silently swallows two hours of failures — none of them ever analyzed. Pain: P9.

**Solution:**

1. On RetryExhaustedError, write the exact payload + failure metadata to `dead_letter/<pipeline>_<epoch>.json`.
2. `replay_failed.py` re-POSTs oldest-first; success → `replayed/`; `--dry-run` supported.

**Files:** api_poster.py · scripts/replay_failed.py · **Reference design:** §9

#### E-3 — Auto-restart + silent-failure alert

**Issue — today:** A crashed analyzer stays down until someone notices and restarts it. Worse, the 'process alive but nothing works' mode (bad env var, dead LLM endpoint, misconfigured after restart) alerts no one at all.

**Why it's a problem:** systemd can restart a dead process, but cannot see a living process that fails every request — that needs an output-based signal.

**Impact:** Outages are discovered by developers noticing the silence, hours later. Pain: P9.

**Solution:**

1. systemd unit: `Restart=on-failure`, `RestartSec=5`.
2. `watchdog.py` cron (15 min): failed webhooks > 0 AND analyses = 0 in window → error_notifier (Slack DM + email); also curls `/health`.

**Files:** build-failure-analyzer.service · watchdog.py · **Reference design:** §9

#### E-4 — Slack rate-limit handling

**Issue — today:** Slack 429 (rate-limit) responses are dropped with a print.

**Why it's a problem:** Rate limits hit exactly during failure bursts — when the most messages are being sent and visibility matters most.

**Impact:** Messages vanish without trace at the worst possible time.

**Solution:**

1. Construct WebClient with `RateLimitErrorRetryHandler(max_retry_count=3)` — combined with B-4/B-5/B-7 volume cuts, bursts survive.

**Files:** slack client setup · **Reference design:** §9

### F — Testing & Validation

#### F-1 — Unit tests for all new logic

**Issue — today:** The new MVP2 modules (normalizer, orchestrator, agents, reporter, KB APIs) do not exist yet, hence have no tests; the existing suite covers only MVP1 shapes.

**Why it's a problem:** Without the fast unit layer, every regression in the new logic is discovered at integration time or in production.

**Impact:** Slow feedback loops during the build phase; fragile refactors after it.

**Solution:**

1. Normalizer golden table; orchestrator branch coverage with fake agents (every flow branch incl. fallbacks); A2/A3 contract tests with mocked LLM (schema, retry, floors); reporter grouping/routing/guardrail; kb_api CRUD.

**Files:** tests/… · **Reference design:** §11

#### F-2 — Component tests with real vector math

**Issue — today:** The existing suite patches `_get_embedding` to a constant `[0.1, 0.2, 0.3]` and `collection.query` to hand-written distances (test_vector_db.py).

**Why it's a problem:** All four correctness bugs live exactly in the mocked-out layer: real embeddings (blob domination), real metric (L2/cosine), real IDs across restarts (salted hash), realistic inputs (cache keys). The mocks made them untestable by construction.

**Impact:** The suite stayed green through the entire production incident — and nothing today prevents a recurrence. Pain: P23. Pre-rollout blocker.

**Solution:**

1. Real Chroma (temp dir) + real Ollama embeddings, no mocked distances.
2. Permanent poisoning-regression test: old-style 5 KB blob inserted → unrelated error must NOT match ≥ 0.90 (gate: 0%).
3. Threshold calibration on ~20 labeled pairs; deterministic-ID test across two client instances.
4. Runs on the Ollama test instance (RD-15346); skipped elsewhere via marker.

**Files:** tests/component/ · **Reference design:** §11

#### F-3 — Shared wire-contract schema

**Issue — today:** The /api/analyze payload shape exists only implicitly, duplicated in two codebases (what api_poster builds vs what FailedStep parses).

**Why it's a problem:** During the v1→v2 payload migration, either side can drift — add, rename, or drop a field — without any test failing on either side.

**Impact:** Silent contract breakage between the services, discovered in production.

**Solution:**

1. One `analyze_payload.schema.json`; extractor asserts real output validates; analyzer asserts schema examples POST OK; both v1+v2 shapes during overlap.

**Files:** schemas/ · both test suites · **Reference design:** §11

#### F-4 — docker-compose end-to-end

**Issue — today:** No test exercises the two services wired together: extractor tests stop at a mocked POST; analyzer tests start at the endpoint.

**Why it's a problem:** Everything between them — payload compatibility, Slack formatting, threading behavior, the degradation ladder — is untested as a system.

**Impact:** Integration bugs reach production as the first real test.

**Solution:**

1. Compose stack: real extractor+analyzer+Redis+Chroma; mock GitLab/Jenkins (canned logs), mock LLM (record/replay), mock Slack (captures posts).
2. 6 scenarios (cold→A3, cache-hit with changed timestamps = zero LLM calls, approve-updates-row, variant→A2-adjusted, unrelated→no false match, stage threading) + one chaos test per E-1 ladder row.

**Files:** e2e/ · **Reference design:** §11

#### F-5 — Eval harness with metric gates

**Issue — today:** There is no measurement of answer quality anywhere — no labeled cases, no replay, no metrics.

**Why it's a problem:** 'Accuracy' claims are anecdotes; the effect of a threshold change, prompt change, or embedding-model change cannot be evaluated before shipping it.

**Impact:** Quality regressions ship invisibly; tuning is guesswork. Pain: P23. Pre-rollout blocker.

**Solution:**

1. `regression_set.jsonl` cases: error, context, expected_route, must_contain, must_not_contain.
2. `run_eval.py` replays through the orchestrator; computes routing accuracy (≥95%), poisoning (0%), recall (≥90%), keyword pass (≥baseline), cost/latency vs forecast; emits report.{json,md}.
3. CI mode (mock LLM) every PR; nightly real-LLM mode (~$1/night) with report to DevOps.

**Files:** eval/ · **Reference design:** §11

#### F-6 — Linter cleanup

**Issue — today:** The analyzer repo has standing linter violations (tracked as RD-15333).

**Why it's a problem:** A lint gate enabled on a dirty repo fails instantly on every PR, so no gate can be turned on — including the flake8-print rule that keeps A-11 honest.

**Impact:** Style and print() regressions cannot be enforced in CI until the slate is clean.

**Solution:**

1. Fix existing linter issues in build-failure-analyzer; then enable the lint gate (incl. flake8-print for A-11) in CI.

**Files:** build-failure-analyzer/* · **Reference design:** §11

---

## 3. Configuration

### 3.1 `src/config/error_patterns.json` (A-9) — extractor

Replaces the hardcoded `ERROR_PATTERNS` list in
`log_error_extractor.py:29`. Loaded by `config_loader.py` at startup;
schema-validated (A-12).

```json
{
  "version": 1,
  "patterns": [
    {
      "name": "npm_error",
      "regex": "npm ERR!",
      "class": "code",
      "enabled": true
    },
    {
      "name": "runner_disconnect",
      "regex": "(?i)runner.*(lost connection|system failure)",
      "class": "infra",
      "enabled": true
    },
    {
      "name": "docker_pull_ratelimit",
      "regex": "toomanyrequests: You have reached your pull rate limit",
      "class": "flaky",
      "enabled": true
    }
  ]
}
```

Rules: `name` unique; `class ∈ {code, infra}` (team decision — a third `flaky` class can be added later without schema change); invalid regex →
startup failure with the pattern name in the error. The matched
pattern's `name` and `class` travel in the payload as `error_pattern`
/ `error_class`.

### 3.2 `build-failure-analyzer/config/routing.json` (B-6) — analyzer

```json
{
  "version": 1,
  "routing": [
    {
      "repo_pattern": "frontend-.*",
      "channel": "#ci-frontend",
      "product_team": "web",
      "sme_group": "@web-smes",
      "jira_project": "WEB"
    }
  ],
  "default": {
    "channel": "#ci-failures",
    "product_team": "unassigned",
    "sme_group": "@devops",
    "jira_project": "RD"
  }
}
```

`routing.py::resolve(repo, job_name) -> Route` — first regex match on
`repo_pattern` wins (list order), else `default`. Loaded once at
startup (restart to apply); schema + regex validation at load (A-12).

### 3.3 Environment variables (new / changed)

| Var | Default | Used by |
|---|---|---|
| `CHROMA_COLLECTION` | `fix_embeddings_v2` | vector_db (rollback lever) |
| `EMBEDDING_MODEL` | `granite-embedding` | vector_db, A-13 guard |
| `AGENTS_MODE` | `off` | orchestrator: `off\|shadow\|on` |
| `A2_TIMEOUT_S` / `A3_TIMEOUT_S` | `6` / `8` | agents |
| `A2_CONF_FLOOR` | `0.5` | orchestrator |
| `VECTOR_THRESHOLD` / `VECTOR_EXACT` | `0.90` / `0.95` | orchestrator |
| `CONTEXT_COSINE_ENABLED` | `false` | disambiguation sub-flag |
| `ROUTING_CONFIG` | `config/routing.json` | routing.py |
| `ERROR_PATTERNS_CONFIG` | `config/error_patterns.json` | extractor |
| `DEAD_LETTER_DIR` | `dead_letter/` | api_poster |
| `STATS_DB_PATH` | `bfa_stats.db` | stats.py |
| `KB_DB_PATH` | `bfa_kb.db` | kb_store.py (fix metadata system-of-record) |
| `JIRA_BASE_URL` / `JIRA_TOKEN` | — | jira_client |
| `DASHBOARD_ENABLED` | `true` | analyzer_service |

Legacy env vars (`SLACK_CHANNEL`, thresholds baked in code) removed
after one release of deprecation warning.

---

## 4. Data Design

How the stores relate — the fingerprint hash (`fph`) is the join key
across all of them:

```mermaid
flowchart TB
    FP["fingerprint = normalize(error_lines)<br/>fph = sha256(fingerprint) — the join key"]

    subgraph REDIS["Redis — caches, all TTLed"]
        R1["sme:fix:fph · ai:fix:fph<br/>agent:deviation:* · agent:synthesizer:fph<br/>fix:error_id · error_map:fph · last_edit:*"]
    end
    subgraph CHROMA["Chroma — knowledge base"]
        C1["id = fix-sha256(fp)<br/>embedding(fp) ONLY<br/>document = fix_text<br/>metadata: wire + analysis + lifecycle keys"]
    end
    subgraph SQLITE["SQLite — stats"]
        S1["analyze_decisions"]
        S2["pipeline_events"]
        S3["feedback_events"]
    end
    subgraph SLACK["Slack"]
        SL1["msg:canonical:fph → channel, ts, count<br/>thread_map:channel:ts → error_id"]
    end

    FP --> REDIS
    FP --> CHROMA
    FP --> SQLITE
    FP --> SLACK
    C1 -- "metadata.jira" --> J["Jira ticket (RD-xxxxx)"]
    S1 -. "fingerprint" .-> SL1
    S3 -. "fix_id" .-> C1
```

### 4.1 Wire contract v2 (A-1) — `POST /api/analyze`

Shared JSON Schema lives at `schemas/analyze_payload.schema.json`
(repo root; single source for extractor and analyzer tests, F-3).

```json
{
  "repo": "payments-service",
  "branch": "feature/JIRA-123",
  "commit": "a1b2c3d",
  "commit_message": "fix: bump react",
  "job_name": "build-frontend",
  "job_url": "https://…",
  "pipeline_id": "12345",
  "pipeline_url": "https://…",
  "ci_system": "gitlab",
  "build_number": null,
  "runner_or_agent": "linux-node-12",
  "triggered_by": "dev@corp.com",
  "author_name": "Nila",
  "failed_at": "2026-07-15T09:14:02Z",
  "stage_durations": {"Build": 312, "Test": 0},
  "total_duration": 312,
  "failed_steps": [
    {
      "step_name": "Build",
      "stage": "Build",
      "errors": [
        {
          "error_lines": ["npm ERR! code ERESOLVE", "npm ERR! peer dep …"],
          "context_lines": ["Resolving dependencies…", "…"],
          "error_pattern": "npm_error",
          "error_class": "code"
        }
      ],
      "error_lines": ["<legacy blob — optional, one release overlap>"]
    }
  ]
}
```

Analyzer accepts **either** `errors` (v2) or legacy `error_lines`
(v1). v1 input is converted at the boundary:
`ErrorEntry(error_lines=[blob], context_lines=[], error_pattern="legacy", error_class="code")`.
Response is `202 {"status": "accepted", "request_id": "<uuid>"}` (A-10).

### 4.2 Redis key design (A-7)

All keys carry TTLs. `<fph> = sha256(fingerprint)[:32]`.

| Key | Value | TTL | Writer |
|---|---|---|---|
| `sme:fix:<fph>` | fix JSON (SME approved/edited) | 30 d | approval handler |
| `ai:fix:<fph>` | fix JSON (AI generated) | 24 h | orchestrator |
| `agent:deviation:<sha256(fph+candidate_id)>` | A2 verdict JSON | 7 d | A2 wrapper |
| `agent:synthesizer:<fph>` | A3 result JSON | 7 d | A3 wrapper |
| `fix:<error_id>` | Slack-flow fix record | 30 d | store_fix |
| `error_map:<fph>` | error_id | 30 d | store_fix (key was full error text in MVP1 — changed) |
| `thread_map:<channel>:<ts>` | error_id | 30 d | store_fix |
| `msg:canonical:<fph>` | `{channel, ts, count, last_seen}` | 30 d | A4 (B-5 counter) |
| `last_edit:<channel>:<user_id>` | error_id | **15 min** | edit handler (B-15; O(1) GET replaces `keys()` scan) |

### 4.3 Chroma collection `fix_embeddings_v2` (A-3/A-4) — vectors only

- Space: `{"hnsw:space": "cosine"}`; vectors L2-normalized pre-add/query.
- `id = "fix-" + sha256(fingerprint).hexdigest()` — the join key to SQLite.
- `document = fix_text` (debug copy; SQLite is the source of truth).
- `embedding = embed(fingerprint)` — the **only** embedded text.
- Collection metadata: `embedding_model` + `embedding_dim` (A-13/#5
  guard). **No per-row business metadata in Chroma** — that lives in
  SQLite (§4.4), because the KB APIs need SQL-grade filtering,
  pagination, and free-text search that Chroma metadata cannot do.
- **Multi-process rule (P5):** exactly ONE process may open the
  embedded `PersistentClient`. MVP1 violates this today
  (`slack_reviewer.py:19` + `analyzer_service.py` share the dir) —
  B-14 deletes the second process at the start of Phase 1.

### 4.4 KB store — SQLite `bfa_kb.db` (A-4, D-1)

System of record for all fix facts. Retrieval = ANN in Chroma →
join by id here. `kb_store.py` wraps it (WAL mode, like
`monitoring.py`).

```sql
CREATE TABLE fixes (
  id TEXT PRIMARY KEY,               -- fix-sha256(fingerprint), same as Chroma id
  fingerprint TEXT NOT NULL, fix_text TEXT NOT NULL,
  -- wire keys
  ci_system TEXT, repo TEXT, branch TEXT, commit_sha TEXT, commit_message TEXT,
  author_name TEXT, author_email TEXT, pipeline_id TEXT, pipeline_url TEXT,
  job_name TEXT, job_url TEXT, stage TEXT, build_number TEXT, runner_or_agent TEXT,
  -- analysis keys
  error_pattern TEXT, error_class TEXT,
  raw_error_lines TEXT,              -- JSON array
  context_sample TEXT,               -- first ~2 KB
  product_team TEXT,
  -- lifecycle
  source TEXT, status TEXT, approver TEXT, revision INTEGER DEFAULT 1,
  created_at TEXT, updated_at TEXT,
  hits INTEGER DEFAULT 0, last_served_at TEXT,
  helpful_count INTEGER DEFAULT 0, unhelpful_count INTEGER DEFAULT 0,
  jira TEXT
);
CREATE INDEX idx_fixes_team_status ON fixes(product_team, status);
CREATE INDEX idx_fixes_pattern    ON fixes(error_pattern);
CREATE INDEX idx_fixes_updated    ON fixes(updated_at);

CREATE TABLE fix_revisions (         -- full edit history (D-1)
  id INTEGER PRIMARY KEY, fix_id TEXT REFERENCES fixes(id),
  revision INTEGER, editor TEXT, edited_at TEXT,
  old_fix_text TEXT, new_fix_text TEXT,
  change_source TEXT                 -- approve | edit | api | migration
);
```

Write order: SQLite first, then Chroma upsert. A Chroma row with no
SQLite row is ignored at join time (repairable by re-embedding from
`fixes`), so partial failures degrade safely.

### 4.5 Stats store (C-1..C-4) — SQLite `bfa_stats.db`

Same approach as the extractor's `monitoring.py` (SQLite, WAL mode).

```sql
CREATE TABLE pipeline_events (        -- C-1, one row per webhook
  id INTEGER PRIMARY KEY, ts TEXT, ci_system TEXT, repo TEXT,
  branch TEXT, pipeline_id TEXT, status TEXT,          -- success|failed
  author_name TEXT, author_email TEXT, commit_sha TEXT,
  stage_durations TEXT,                                -- JSON
  total_duration REAL, failed_stage TEXT
);
CREATE TABLE analyze_decisions (      -- C-2, one row per analyzed error
  id INTEGER PRIMARY KEY, ts TEXT, request_id TEXT, fingerprint TEXT,
  repo TEXT, product_team TEXT, error_pattern TEXT, error_class TEXT,
  source TEXT,        -- sme_cache|ai_cache|vector|a2_exact|a2_adjusted|a3|unable
  similarity REAL, latency_ms INTEGER, llm_calls INTEGER,
  est_cost_usd REAL, zero_match INTEGER DEFAULT 0      -- C-4
);
CREATE TABLE feedback_events (        -- C-3
  id INTEGER PRIMARY KEY, ts TEXT, fingerprint TEXT, fix_id TEXT,
  user_id TEXT, verdict TEXT          -- helpful|unhelpful
);
```

`stats.py` exposes `record_pipeline()`, `record_decision()`,
`record_feedback()`, and read APIs for the dashboard
(`GET /api/stats/*`). Writes are fire-and-forget (never block or fail
an analysis). Kept as a **separate file** from `bfa_kb.db`: stats is
append-heavy, the KB is read-heavy — separate files avoid lock
contention. Indexes on `ts`, `fingerprint`, `repo`, `product_team`;
retention job reuses the extractor's `cleanup_old_records` pattern.

### 4.6 Dead-letter format (E-2)

`{DEAD_LETTER_DIR}/{pipeline_id}_{epoch}.json` — the exact payload
that failed, plus `{"_dead_letter": {"first_failed_at": …,
"attempts": N, "last_error": "…"}}`. `scripts/replay_failed.py`
re-POSTs each file (oldest first), moves success → `replayed/`,
keeps failures in place; `--dry-run` supported.

---

## 5. Extractor Changes (`src/`)

### 5.1 `log_error_extractor.py` — per-region output (A-1)

Today `extract_error_sections` merges everything and returns
`['\n'.join(sections)]` (line 138). Change the return type:

```python
@dataclass
class ErrorRegion:
    error_lines: List[str]      # the matched lines only, no "Line N:" prefix
    context_lines: List[str]    # window around them (existing before/after config)
    error_pattern: str          # pattern name from config
    error_class: str            # code | infra | flaky

def extract_error_sections(self, log_text: str) -> List[ErrorRegion]: ...
```

- Region building reuses the existing match→window→merge logic; the
  change is *not* re-joining regions and *not* prefixing `"Line N:"`.
- When merged regions contain multiple pattern matches, the region's
  `error_pattern`/`error_class` come from the **first** match
  (severity refinement is out of scope).
- Existing caps stay: `ERROR_ADAPTIVE_THRESHOLDS`, `MAX_LOG_LINES`,
  `max_line_length` (E-5).
- Zero regions on a failed pipeline → `api_poster` still posts with
  `errors: []` and the analyzer records `zero_match=1` and notifies
  DevOps with the log tail (C-4). Extractor attaches
  `tail_lines: last 50 lines` in that case.

### 5.2 `src/redactor.py` (new, A-8)

```python
SECRET_PATTERNS: List[Tuple[str, str]] = [
    (r"(?i)(password|passwd|pwd)\s*[=:]\s*\S+",        r"\1=<REDACTED>"),
    (r"(?i)(token|api[_-]?key|secret)\s*[=:]\s*\S+",   r"\1=<REDACTED>"),
    (r"(?i)bearer\s+[a-z0-9._\-]+",                     "Bearer <REDACTED>"),
    (r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9._\-]+",       "<JWT_REDACTED>"),   # JWT
    (r"AKIA[0-9A-Z]{16}",                               "<AWS_KEY_REDACTED>"),
    (r"glpat-[A-Za-z0-9\-_]{20,}",                      "<GITLAB_TOKEN_REDACTED>"),
    (r"://[^/\s:]+:[^@\s]+@",                           "://<REDACTED>@"),   # user:pass@ URLs
    (r"ghp_[A-Za-z0-9]{36}",                            "<GITHUB_TOKEN_REDACTED>"),
]

def redact(lines: List[str]) -> List[str]: ...
def redact_text(text: str) -> str: ...
```

Applied in `api_poster` to **every** outgoing field that carries log
content (`error_lines`, `context_lines`, `tail_lines`,
`commit_message`). Unit-tested with a golden file of true/false
positives (F-1). Patterns extendable via optional
`config/redaction_patterns.json` (same loader style as A-9).

### 5.3 `api_poster.py` — v2 payload + dead-letter (A-1, E-2)

- Build the §4.1 payload; keep legacy `error_lines` field populated
  for one release (`API_LEGACY_COMPAT=true` env, default true → flip
  false after analyzer v2 ships).
- On `RetryExhaustedError` (`api_poster.py:1008`): write dead-letter
  file (§4.5) **instead of** only logging.
- New: `scripts/replay_failed.py` (see §4.6).

---

## 6. Analyzer Core

### 6.1 `normalizer.py` (new, A-2) — the fingerprint function

```python
_RULES: List[Tuple[Pattern, str]] = [
    (re.compile(r"^Line \d+:\s*", re.M), ""),                       # 1 line prefixes
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?"), "<TS>"),
    (re.compile(r"\[\d{2}:\d{2}:\d{2}\]"), "<TS>"),                 # 3 [HH:MM:SS]
    (re.compile(r"\b\d{13}\b|\b\d{10}\b"), "<EPOCH>"),              # 4 epoch s/ms
    (re.compile(r"\b[0-9a-f]{40}\b|\b[0-9a-f]{7,12}\b(?=[\s:/])"), "<SHA>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "<UUID>"),
]

def normalize_error_text(error_lines: List[str]) -> str:
    text = "\n".join(error_lines)
    for pat, repl in _RULES: text = pat.sub(repl, text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text[:MAX_FINGERPRINT_CHARS]      # 2000 chars ≈ 512 tokens

def fingerprint_hash(fp: str) -> str:
    return hashlib.sha256(fp.encode()).hexdigest()
```

Scope decision honored: **no** path replacement in MVP2 normalization
(per team review, only Line-N/timestamps/whitespace/lowercase +
SHA/UUID/epoch which are timestamp-like). Rules are ordered and
table-driven → golden tests assert exact outputs (F-1).

### 6.2 `vector_db.py` — v2 behavior (A-3, A-4, A-13)

Changed/new methods on `VectorDBClient`:

```python
def __init__(..., collection=os.getenv("CHROMA_COLLECTION", "fix_embeddings_v2")):
    # create with {"hnsw:space": "cosine"}
    # A-13: read collection.metadata["embedding_model" / "embedding_dim"];
    # model name != EMBEDDING_MODEL env → raise StartupError (forces migration)
    # dim guard (#5): every _embed_normalized() asserts
    # len(vector) == embedding_dim — catches silent model/quantization
    # drift and Ollama response-shape surprises that the name check misses

def _generate_id(self, fingerprint: str) -> str:
    return "fix-" + hashlib.sha256(fingerprint.encode()).hexdigest()

def _embed_normalized(self, fingerprint: str) -> List[float]:
    v = self._get_embedding(fingerprint)
    n = math.sqrt(sum(x*x for x in v))
    return [x/n for x in v] if n else v          # L2-normalize

def lookup_candidates(self, fingerprint: str, top_k=10, threshold=0.90)
        -> List[Candidate]:
    # query with normalized vector; sim = 1 - cosine_distance (valid now)
    # join Chroma ids -> kb_store.fixes rows (SQLite, A-4);
    # filter: sim >= threshold AND fixes.status != "deprecated";
    # Chroma rows with no fixes row are ignored (safe partial-failure)
    # returns Candidate(id, fix_text, stored_error, metadata, similarity)

def save_fix(self, fingerprint, fix_text, metadata, status) -> str:
    # upsert semantics (A-6), SQLite FIRST then Chroma:
    # 1 kb_store.upsert_fix(...) — writes fixes row, appends
    #   fix_revisions entry (who/when/old/new), revision += 1
    # 2 Chroma add/update: id + embedding + fix_text only
    # (a Chroma failure leaves a consistent SQLite record that a
    #  repair pass can re-embed)

# metadata operations live on kb_store (SQLite), not Chroma:
kb_store.touch_served(fix_id)          # hits += 1, last_served_at = now
kb_store.set_status(fix_id, status)    # deprecate API (soft delete)
kb_store.get_by_id / list_filtered(...)# plain SQL — used by kb_api.py
```

Context disambiguation (A-5) in `disambiguate(candidates, context_lines)`:
`score = 0.7*error_sim + 0.3*cosine(embed(ctx_query), embed(candidate.context_sample))`,
return top if margin > 0.05 else `None` (→ A2). Behind
`CONTEXT_COSINE_ENABLED` (default false until shadow data exists).

### 6.3 `orchestrator.py` (new) — state machine

```mermaid
flowchart TB
    START(["POST /api/analyze → 202"]) --> A1["A1 normalize<br/>(never fails — raw-lines fallback)"]
    A1 --> CACHE{"Redis cache?"}
    CACHE -- "HIT (no LLM)" --> A4
    CACHE -- MISS --> VEC["vector lookup<br/>(Chroma / Ollama down → 0 candidates)"]
    VEC --> N{"candidates ≥ 0.90"}
    N -- "0" --> A3["A3 synthesize fresh fix"]
    N -- "1, sim ≥ 0.95" --> STORED["stored fix · touch_served"]
    N -- "1 in [0.90, 0.95)" --> A2["A2 judge candidate"]
    N -- "≥ 2" --> TIE{"deterministic tie-break<br/>(A-5, context-cosine)?"}
    TIE -- winner --> STORED
    TIE -- "no margin" --> A2P["A2 × top-3 parallel<br/>→ best verdict"]
    A2 -- exact_match --> STORED
    A2 -- applicable_with_adjustments --> ADJ["upsert adjusted fix"]
    A2 -- "partial / no_match / A2 failure" --> A3
    A2P -- "exact / adjusted" --> ADJ
    A2P -- "none applicable" --> A3
    A3 -- "A3 failure" --> UN["unable to analyze<br/>+ DevOps notify"]
    STORED --> A4
    ADJ --> A4
    A3 --> A4
    UN --> A4
    A4["A4 Reporter<br/>guardrail → routing → stage grouping<br/>→ counters → DM + stats"] --> DONE([done])
```

```python
async def analyze_request(payload: AnalyzePayload) -> None:   # runs in background task
    stats_ctx = stats.start(payload)
    regions = dedupe_by_fingerprint(all_regions(payload))      # B-7
    for region in regions:
        result = await analyze_region(region, payload)
        await reporter.deliver(result, payload)                # A4, groups by stage

async def analyze_region(region, payload) -> Result:
    fp   = summarizer.run(region)                              # A1, never fails
    if hit := cache.get_sme(fp) or cache.get_ai(fp):
        return Result(source=hit.source, fix=hit, fp=fp)
    try:
        cands = vector_db.lookup_candidates(fp.fingerprint)
    except VectorUnavailable:                                  # E-1 ladder
        cands = []
    if not cands:
        return await run_a3(fp, region, citations=None)
    if cands[0].similarity >= VECTOR_EXACT and len(cands) == 1:
        vector_db.touch_served(cands[0].id)
        return Result(source="vector", fix=cands[0], fp=fp)
    if len(cands) == 1:
        verdict = await run_a2(fp, region, cands[0])
        return route_a2_verdict(verdict, cands[0], fp, region)
    # ≥2 candidates: deterministic tie-break first, then A2 top-3 parallel
    if best := vector_db.disambiguate(cands, region.context_lines):
        return Result(source="vector", fix=best, fp=fp)
    verdicts = await asyncio.gather(*[run_a2(fp, region, c) for c in cands[:3]])
    return pick_best(verdicts, cands, fp, region)   # exact > adjusted > A3
```

- `run_a2` / `run_a3` wrap the agents with: Redis result cache (§4.2),
  timeout, one retry on schema failure, confidence floor; every
  failure path degrades exactly as HYBRID_PROPOSAL §4.1 fallbacks.
- `AGENTS_MODE=off` → skip A2 entirely (candidates in [0.90,0.95)
  behave like misses → A3 path = today's fallback). `shadow` → run A2,
  log verdict to stats, but respond as if `off`. `on` → full flow.
- Every terminal emits `stats.record_decision(...)` (C-2).

---

## 7. Agents (`agents/`)

### 7.1 `agents/base.py`

```python
class AgentResult(TypedDict): ...          # parsed JSON + _meta (latency, retries)

class LLMAgent:
    name: str; schema: dict; timeout_s: float; prompt_file: str
    async def run(self, **prompt_vars) -> AgentResult:
        # 1 render prompt (prompts/<name>.md, {placeholders})
        # 2 call LLM via llm_openwebui_client in a thread executor (non-blocking)
        # 3 json.loads → jsonschema.validate; on failure: ONE retry with
        #   "Your previous output failed validation: <err>. Output ONLY JSON."
        # 4 raise AgentFailure(reason) on timeout/2nd failure
        # 5 audit log entry (request_id, agent, latency, tokens if available)
```

A1/A4 are plain classes (no LLM, no base inheritance) — they must
never fail; internal exceptions are caught and degrade (A1 → raw
lines; A4 → minimal fallback message).

### 7.2 `agents/summarizer.py` — A1

```python
class Summarizer:
    def run(self, region: ErrorRegion) -> Fingerprint:
        fp = normalize_error_text(region.error_lines)
        return Fingerprint(
            fingerprint=fp, fp_hash=fingerprint_hash(fp),
            summary=self._summary(region),      # first 3 error lines, ≤300 chars
            error_pattern=region.error_pattern, error_class=region.error_class)
```

`_summary` replaces `summarize_error_with_ai` (B-1) — display text is
now free and deterministic.

### 7.3 `agents/deviation.py` — A2

`LLMAgent(name="deviation", timeout=A2_TIMEOUT_S)` with the verdict
schema from HYBRID_PROPOSAL §12.2 and prompt `prompts/deviation.md`
(system prompt from §12.3). Wrapper adds the Redis cache
(`agent:deviation:*`) and returns `AgentFailure → caller routes to A3`.

### 7.4 `agents/synthesizer.py` — A3

`LLMAgent(name="synthesizer", timeout=A3_TIMEOUT_S)`; schema from
HYBRID_PROPOSAL §13.2; prompt `prompts/synthesizer.md` — refactor of
the current `resolver_agent.py` prompt, plus optional
`{partial_citations}` block (stored fixes A2 judged `partial`).
On `AgentFailure`: orchestrator produces
`Result(source="unable", fix=None)` → A4 posts "unable to analyze" to
the SME channel and `error_notifier` alerts DevOps (email + Slack).
`resolver_agent.py` is reduced to a thin deprecated shim for one
release, then deleted.

### 7.5 `agents/reporter.py` — A4

Delivery decision flow:

```mermaid
flowchart TB
    R(["Result: stored / a2_adjusted / a3 / unable"]) --> RT["routing.resolve(repo, job) — B-6<br/>channel · product_team · SME group"]
    RT --> G{"guardrail.check(fix_text) — B-10"}
    G -- blocked --> SME["SME review only, warning flag — NO DM"]
    G -- pass --> EC{"error_class — B-11"}
    EC -- infra --> DEVOPS["DevOps channel<br/>(no developer DM)"]
    EC -- flaky --> RETRY["DM: suggest pipeline retry"]
    EC -- code --> CAN{"msg:canonical:fph exists? — B-5"}
    CAN -- yes --> BUMP["edit canonical message:<br/>bump seen-N× counter"]
    CAN -- "first time" --> GRP["stage grouping — B-4<br/>parent msg per stage,<br/>extra errors as thread replies"]
    BUMP --> DM
    GRP --> DM
    DM["DM developer — B-8 / B-9<br/>provenance line + 👍/👎 (B-13) + Create Jira (B-12)<br/>lookup fails → team channel, author named"]
```

```python
class Reporter:
    async def deliver(self, result: Result, payload: AnalyzePayload):
        route = routing.resolve(payload.repo, payload.job_name)        # B-6
        verdict = guardrail.check(result.fix_text)                     # B-10
        if verdict.blocked:
            return await self._sme_review_only(result, route, verdict) # ⚠️ hold
        if result.error_class == "infra":                              # B-11
            return await self._post_infra(result, route)               # DevOps ch.
        if result.error_class == "flaky":
            return await self._dm_retry_suggestion(result, payload)
        canonical = redis.get(f"msg:canonical:{result.fp_hash}")       # B-5
        if canonical:
            await self._bump_counter(canonical)                        # edit msg
        else:
            await self._post_stage_grouped(result, payload, route)     # B-4
        await self._dm_developer(result, payload, route)               # B-8/B-9/B-13
```

- **Stage grouping (B-4):** per request, results are grouped by
  `stage`; first result of a stage posts the parent message
  (stage, repo, branch, pipeline link, author); further errors of the
  same stage post as thread replies (`thread_ts` of parent). Parent
  `ts` kept in-memory per request only.
- **DM (B-8/B-9/B-13):** resolve `triggered_by` →
  `users_lookupByEmail`; on failure post to `route.channel`
  mentioning `author_name`. DM blocks: fix text, provenance line
  ("SME-approved · served 12× · last seen 2d ago · from repo X" —
  from metadata `hits/last_served_at/repo`), 👍/👎 buttons
  (`action_id: fb_up_<fp_hash>` / `fb_down_<fp_hash>`), "🎫 Create
  Jira" button (`jira_<error_id>`) where applicable.
- **`guardrail.py` (B-10):** `check(text) -> Verdict(blocked, matches)`
  against a denylist: `rm -rf /`, `rm -rf` on non-tmp paths,
  `chmod -R 777`, `git push --force` to protected branches,
  `kubectl delete (ns|namespace|deploy)`, `DROP TABLE|DATABASE`,
  `mkfs`, `dd if=`, `:(){ :|:& };:`, `curl … | sh`. Table-driven +
  unit golden tests; extendable via config.

### 7.6 Slack handlers (B-13, B-14, B-15)

```mermaid
sequenceDiagram
    participant U as SME / Developer
    participant S as Slack
    participant H as Analyzer handlers
    participant C as Chroma
    participant R as Redis
    participant Q as SQLite
    participant J as Jira

    rect rgb(232, 242, 255)
    Note over U,C: Approve
    U->>S: click Approve
    S->>H: action payload
    H->>C: save_fix (upsert, revision++)
    H->>R: SETEX sme:fix:fph 30d
    H->>S: update message + DM developer
    end

    rect rgb(232, 255, 240)
    Note over U,R: Edit (15-minute session)
    U->>S: click Edit
    S->>H: action payload
    H->>R: SETEX last_edit:ch:user 900 error_id
    H->>S: thread prompt
    U->>S: thread reply (new fix text)
    S->>H: message event
    H->>R: GET last_edit (O(1))
    H->>C: save edited fix (upsert, revision++)
    H->>S: confirmation
    end

    rect rgb(255, 248, 232)
    Note over U,J: Feedback and Jira
    U->>S: click thumbs up / down
    S->>H: action payload
    H->>Q: record_feedback
    H->>C: helpful / unhelpful counter++
    alt unhelpful count >= 3
        H->>S: auto-flag to SME channel
    end
    U->>S: click Create Jira
    S->>H: action payload
    H->>J: create_or_link (never duplicates)
    H->>S: ticket link added to message
    end
```

- Delete `slack_reviewer.py`; `analyzer_service.py` keeps
  `/bfa/slack/events` + `/bfa/slack/actions` (already implemented
  there) — Slack app config points at the analyzer.
- Edit mode: on ✏️ Edit → `SETEX last_edit:<channel>:<user_id> 900
  <error_id>`; message handler does one `GET` (replaces `keys()`
  scan). Expired key → friendly "edit session expired, click Edit
  again".
- New action handlers: `fb_up_*` / `fb_down_*` →
  `stats.record_feedback` + metadata counters
  (`helpful_count/unhelpful_count`); on `unhelpful_count >= 3` → post
  alert to `route.channel` SME group (auto-flag). `jira_*` →
  `jira_client.create_or_link`.
- Approval handler: `save_fix` (upsert §6.2) + `SETEX sme:fix:<fph>`.

### 7.7 `jira_client.py` (B-12)

```python
def create_or_link(error_id: str) -> str:   # returns jira key
    # 1 fix metadata already has `jira` → return it (link, don't duplicate)
    # 2 POST {JIRA_BASE_URL}/rest/api/2/issue
    #   project = route.jira_project, type = Bug
    #   summary = "[BFA] <error_pattern>: <summary ≤120 chars>"
    #   description = error + context sample + probable fix +
    #                 pipeline metadata + Slack permalink
    # 3 vector_db metadata update: jira=<key>; Slack message updated with link
```

Auto-create trigger (configurable, default on): `source == "a3"` and
`confidence < 0.6`, or `source == "unable"`.

---

## 8. KB API & Dashboard (Pillar D)

### 8.1 `kb_api.py` — FastAPI router, JWT-protected like `/api/analyze`

All reads/filters/search run as plain SQL on `bfa_kb.db` (§4.4) —
fast, paginated, free-text-capable. Revision history comes from
`fix_revisions`. Chroma is touched only by `POST` (embed) and
`PUT` when `fix_text` changes (re-store document).

| Endpoint | Request | Response / behavior |
|---|---|---|
| `POST /api/fixes` | `{error_text OR error_lines[], fix_text, metadata?}` | normalize → fingerprint → upsert; absorbs `add_manual_fix` / `bulk_manual_fix` (kept as deprecated aliases one release) |
| `GET /api/fixes` | query: `team, error_pattern, repo, branch, stage, source, status, approver, from, to, q, limit=50, offset` | `{total, items:[FixSummary]}` — Chroma `get` + metadata filter; `q` = substring on fingerprint/fix_text |
| `GET /api/fixes/{id}` | — | `FixDetail` (all metadata + revision history from `revisions` field) |
| `PUT /api/fixes/{id}` | `{fix_text?, status?, metadata_patch?}` | `collection.update`, revision += 1, `updated_at`; `sme:fix` cache refreshed |
| `DELETE /api/fixes/{id}` | — | `status=deprecated` (soft); excluded from retrieval + caches purged |
| `GET /api/stats/summary` | `from,to,team?` | hit-rate split by source, cost, latency percentiles (reads §4.4) |
| `GET /api/stats/pipelines` | filters | success/failure counts, per-stage durations |
| `GET /api/issues` | `status=pending\|flagged` | pending SME reviews + 👎-flagged fixes (needs-attention feed) |

### 8.2 `dashboard/` (D-2)

Static single-page app (plain HTML + JS + fetch, no build toolchain)
served by FastAPI `StaticFiles` at `/dashboard`. Three tabs mapping
1:1 to the APIs: **Resolved** (`GET /api/fixes?status=approved,edited`),
**Needs attention** (`GET /api/issues`, row → edit form → `PUT`,
deprecate button → `DELETE`), **Stats** (`GET /api/stats/*`, rendered
with a small inline chart lib or plain tables in v1). Filters are
query-param passthroughs. No separate backend, no separate deploy.

---

## 9. Resilience & Ops implementation (Pillar E)

### 9.1 Degradation ladder (E-1)

Thin wrappers, used everywhere instead of raw clients:

```python
def safe_cache_get(key) -> Optional[str]:
    try: return r.get(key)
    except redis.RedisError:
        stats.incr("redis_down"); return None      # → proceed to vector

class VectorUnavailable(Exception): ...
# vector_db raises it on Chroma/Ollama errors; orchestrator catches → cands=[]
# LLM failure inside agents → AgentFailure → A3 "unable" path (§7.4)
```

Rules: dependency errors are **never** propagated to the webhook
response; each recovery increments a stats counter (visible on the
dashboard); each ladder row has a chaos test (F-4).

### 9.2 Alerts & recovery (E-2, E-3)

- `build-failure-analyzer.service`: add `Restart=on-failure`,
  `RestartSec=5`.
- Silent-failure alert: a lightweight `watchdog.py` cron (every 15
  min) reads §4.4: `pipeline_events(status=failed)` in window > 0 AND
  `analyze_decisions` in window == 0 → `error_notifier` (Slack DM +
  email). Also curls `/health`.
- Slack: `WebClient(retry_handlers=[RateLimitErrorRetryHandler(max_retry_count=3)])` (E-4).

### 9.3 Logging (A-11)

Analyzer gets `logging_setup.py` mirroring `src/logging_config.py`
(rotating file + console, structured extras: `request_id`,
`fingerprint`, `agent`). All `print()` in analyzer files replaced —
mechanical PR, enforced afterwards by lint rule (`T201` flake8-print)
as part of F-6.

### 9.4 Backup (D-4) & pruning (D-3)

- `scripts/backup_bfa.sh` — daily cron using the **SQLite `.backup`
  API** for every store: `bfa_kb.db`, `bfa_stats.db`, and Chroma's
  internal `chroma.sqlite3` (+ copy of index segment dirs). Never a
  raw `tar` of live DB files — a live tar can capture a mid-write
  state (#3). Keep 14; restore procedure in README-OPS.
- `scripts/prune_kb.py --dry-run|--apply`: select
  `status=deprecated OR (hits=0 AND created_at < now-6mo)` → export
  JSON archive → delete rows. Monthly cron with `--dry-run` output
  posted to DevOps channel; `--apply` run manually after review.

---

## 10. Migration (`scripts/migrate_vector_db.py`)

```mermaid
flowchart LR
    OLD[("fix_embeddings<br/>old · L2 · blobs")] --> F{"filter row"}
    F -- "error_text > 5 KB (poison)<br/>or empty fix<br/>or status not approved/edited" --> SKIP["skip<br/>+ count reason"]
    F -- pass --> NRM["normalize<br/>→ fingerprint"] --> EMB["re-embed<br/>+ L2-normalize"] --> UP{"duplicate<br/>fingerprint?"}
    UP -- yes --> KEEP["keep newest<br/>revision++"]
    UP -- no --> NEW["insert"]
    KEEP --> V2[("fix_embeddings_v2<br/>cosine · model stamped<br/>source = migrated")]
    NEW --> V2
    V2 --> REP["report: total / migrated /<br/>skipped(reason) / deduped"]
```

1. Open old `fix_embeddings` read-only; create `fix_embeddings_v2`
   (cosine) if absent; stamp `embedding_model`.
2. Per row: skip if `len(error_text) > 5KB` (poisoning), empty fix,
   or status not in (approved, edited). Else: `normalize_error_text`
   → fingerprint → re-embed → L2-normalize → upsert **into both
   stores** (SQLite `fixes` row with metadata mapped to the §4.4
   schema, `source="migrated"`, missing keys defaulted; then Chroma
   id+embedding+fix_text). Dup fingerprint: keep newest, bump
   revision (history row in `fix_revisions`).
3. Report: total/migrated/skipped(reason)/deduped → JSON + stdout.
4. Run on staging copy first; verify with F-2 suite; then prod run +
   flip `CHROMA_COLLECTION`. Rollback = flip env var back (old
   collection untouched).

---

## 11. Testing implementation (Pillar F)

Test pyramid — many fast tests at the bottom, few expensive ones at
the top; F-2 exists because MVP1 mocked all vector math and shipped
the poisoning bug under a green build:

```mermaid
flowchart BT
    F1["F-1 Unit — many, fast<br/>normalizer goldens · orchestrator branches · agents · reporter · kb_api"]
    F3["F-3 Wire-contract schema — one schema, both services"]
    F2["F-2 Component — REAL Chroma + REAL embeddings<br/>poisoning regression 0% · threshold calibration · deterministic IDs"]
    F4["F-4 E2E docker-compose — 6 scenarios + 4 chaos tests"]
    F5["F-5 Eval harness — metric gates · CI mode every PR · nightly real LLM"]
    F1 --> F3 --> F2 --> F4 --> F5
```

```
tests-shared/schemas/analyze_payload.schema.json      (F-3, single source)
src → tests/ (existing)  + test_redactor.py, test_error_patterns_config.py,
                           test_extract_regions.py, test_payload_schema.py
build-failure-analyzer/tests/ (existing) +
  test_normalizer_golden.py        # table: input → exact fingerprint (F-1)
  test_orchestrator_paths.py       # fake agents; every HYBRID-§4.1 branch (F-1)
  test_agents_contract.py          # mocked LLM: schema, retry, floors (F-1)
  test_reporter.py                 # grouping, routing, guardrail, provenance (F-1)
  test_kb_api.py                   # CRUD + filters (F-1)
  component/test_vector_real.py    # REAL Chroma+Ollama: poisoning regression,
                                   # calibration pairs, deterministic ID (F-2)
                                   # @pytest.mark.component, skipped w/o Ollama
e2e/                               # F-4
  docker-compose.test.yml          # extractor, analyzer, redis, chroma-dir,
                                   # mock-gitlab, mock-llm, mock-slack
  mock_llm/app.py                  # keyed canned responses (record/replay dir)
  mock_slack/app.py                # captures chat.postMessage → /messages
  scenarios/test_scenarios.py      # 6 happy paths + 4 chaos (ladder rows)
eval/
  regression_set.jsonl             # {id, error_lines, context_lines,
                                   #  expected_route, must_contain[], must_not_contain[]}
  run_eval.py                      # replays via orchestrator, computes §18.2
                                   # metrics of HYBRID_PROPOSAL, writes
                                   # report.{json,md}; --mode=ci|nightly
```

CI wiring (per HYBRID_PROPOSAL §18.3): PR → unit + schema + eval(ci);
main → e2e + component; nightly → eval(nightly) with report to DevOps
channel. Root `pyproject.toml` gains
`testpaths = ["tests", "build-failure-analyzer/tests"]`; lint gate
enabled after F-6 cleanup.

---

## 12. Rollout & Feature Flags

| Lever | Values | Reverts |
|---|---|---|
| `CHROMA_COLLECTION` | v2 ↔ old | foundation swap, <60 s |
| `API_LEGACY_COMPAT` (extractor) | true → false | wire format |
| `AGENTS_MODE` | off → shadow → on | A2 (A3 path always exists) |
| `CONTEXT_COSINE_ENABLED` | false → true | disambiguation |
| `DASHBOARD_ENABLED` | true/false | dashboard exposure |
| Jira auto-create | config | manual-button-only mode |

Order: migrate DB → foundation live (agents off) → A2 shadow → on at
10% → 100% (gates in HYBRID_PROPOSAL §10 / §14.3).

---

## 13. Implementation Plan — 3 Phases, Team-Size-Agnostic

Workstreams (WS) are independently mergeable; the dependency graph is
what matters. 1 engineer executes them top-to-bottom; 2–3 engineers
take one column each. Estimates are effort (person-weeks), not
calendar.

### Workstream dependency graph

```mermaid
flowchart LR
    subgraph P1["Phase 1 — Foundation & Safety (~4 pw)"]
        WS1A["1A Extractor<br/>A-1 A-8 A-9 E-2 F-3"]
        WS1B["1B Analyzer core<br/>A-2..A-7 A-10..A-13<br/>+ migration"]
        WS1C["1C Test base<br/>F-1 F-2 F-6 · RD-15346"]
    end
    subgraph P2["Phase 2 — Agents & Delivery (~4 pw)"]
        WS2A["2A Orchestrator + agents<br/>B-1 B-2 B-3 + shadow mode"]
        WS2B["2B Reporter + Slack<br/>B-4..B-11 B-13..B-15"]
        WS2C["2C E2E + Eval<br/>F-4 F-5 (starts on mocks)"]
    end
    subgraph P3["Phase 3 — Visibility & Ops (~3 pw)"]
        WS3A["3A KB API + Dashboard<br/>D-1 D-2"]
        WS3B["3B Stats + Jira<br/>C-1..C-4 B-12"]
        WS3C["3C Ops hardening<br/>E-1 E-3 E-4 D-3 D-4"]
    end
    WS1A --> WS2B
    WS1B --> WS2A
    WS1B --> WS2B
    WS1B --> WS3A
    WS1C --> WS2C
    WS2A --> WS2C
    WS2A --> WS3C
    WS2B --> WS3B
```

### Phase 1 — Foundation & Safety (blockers first)   [~4 pw]

| WS | Content (scope IDs) | Files | Depends on |
|---|---|---|---|
| **1A Extractor** | region split A-1, redaction A-8, patterns config A-9, dead-letter E-2, schema F-3 | `log_error_extractor.py`, `redactor.py`, `api_poster.py`, `config/error_patterns.json` | — |
| **1B Analyzer core** | normalizer A-2, vector_db v2 A-3/A-13 (+dim guard), **kb_store SQLite A-4**, Redis TTLs A-7, async A-10, logging A-11, config validation A-12, migration §10, **delete `slack_reviewer.py` first (P5 corruption hazard, B-14)** | `normalizer.py`, `vector_db.py`, `kb_store.py`, `analyzer_service.py`, `scripts/migrate_vector_db.py` | — |
| **1C Test base** | normalizer goldens, redactor tests, F-2 component suite, F-3 schema tests, F-6 linter cleanup, test instance setup (RD-15346) | `tests/…`, `component/…` | 1B for F-2 |

**Phase gate:** migration verified on staging copy; poisoning
regression test green; regression suite in CI; foundation live with
`AGENTS_MODE=off`.

### Phase 2 — Agents & Delivery   [~4 pw]

| WS | Content | Files | Depends on |
|---|---|---|---|
| **2A Orchestrator+agents** | base/A1/A2/A3 B-1..B-3, orchestrator flow, shadow mode | `agents/*`, `orchestrator.py`, `prompts/*` | 1B |
| **2B Reporter+Slack** | A4 B-4..B-11, B-13..B-15, guardrail, routing.json, feedback handlers, consolidation | `agents/reporter.py`, `routing.py`, `guardrail.py`, slack handlers | 1B (fingerprints) |
| **2C E2E+eval** | F-4 compose stack, mock LLM/Slack, F-5 eval harness + regression set | `e2e/*`, `eval/*` | 2A/2B interfaces (can start on mocks immediately) |

**Phase gate:** A2 shadow ≥80% agreement over 2 weeks; e2e scenarios
green; eval report in CI.

### Phase 3 — Visibility & Ops   [~3 pw]

| WS | Content | Files | Depends on |
|---|---|---|---|
| **3A KB API+dashboard** | D-1 CRUD, D-2 SPA, needs-attention feed | `kb_api.py`, `dashboard/` | 1B |
| **3B Stats+Jira** | C-1..C-4 stats.py + wiring, B-12 jira_client, stats APIs | `stats.py`, `jira_client.py` | 2B for wiring points |
| **3C Ops hardening** | E-1 ladder + chaos tests, E-3 watchdog+systemd, E-4, D-3 prune, D-4 backup | `watchdog.py`, `scripts/*`, service unit | 2A (ladder touches orchestrator) |

**Phase gate:** 10% → 100% rollout per HYBRID_PROPOSAL §10 gates;
dashboard usable by SMEs; nightly eval green 1 week.

### Staffing patterns

| Team | Mapping | Duration (rough) |
|---|---|---|
| 1 engineer | 1A→1B→1C → 2A→2B→2C → 3A→3B→3C | ~11 weeks |
| 2 engineers | E1: 1B→2A→2C→3B/3C · E2: 1A→1C→2B→3A | ~6–7 weeks |
| 3 engineers | E1: 1B→2A→3B · E2: 1A→1C→2C→3C · E3: 2B(start on routing/guardrail/Slack after 1B fingerprint lands)→3A | ~5 weeks |

### Known blockers & resolutions

| # | Blocker | Blocks | Resolution / owner action |
|---|---|---|---|
| K1 | Prod Chroma export access | migration §10, eval seed data | request read access before Phase 1 starts |
| K2 | Test instance w/ Ollama (RD-15346) | F-2, F-4 | provision during Phase 1 (WS 1C first task) |
| K3 | Slack app scopes (`users:read.email`, `chat:write`, actions) | B-8, B-13 DMs/buttons | verify/extend app config before Phase 2 |
| K4 | Jira API token + project keys | B-12 | request during Phase 2; auto-create ships config-off if late |
| K5 | Bedrock/OpenWebUI quota for nightly eval | F-5 nightly | confirm budget (~$30/mo); nightly can start weekly if constrained |
| K6 | SME hour to bless synthetic eval variants | F-5 quality | book during Phase 1 (per HYBRID_PROPOSAL §14.5) |
| K7 | routing.json contents (repo→team→channel map) | B-6 | team provides mapping; default route works meanwhile |
| K8 | Wire-contract freeze | 1A/1B parallelism | §4.1 schema in this doc is the freeze; changes require both-WS sign-off |

Cross-cutting rules: every WS lands behind its flag (§12); a WS is
"done" only with its tests (F-1 additions ship inside the same PR);
`main` stays releasable throughout.
