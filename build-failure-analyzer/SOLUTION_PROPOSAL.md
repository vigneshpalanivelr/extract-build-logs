# Build-Failure-Analyzer — Vector DB Poisoning: Analysis & Proposal

Branch: `claude/setup-log-analysis-bedrock-gmLHN`
Status: **Proposal only. No code changes yet. Awaiting user approval.**

---

## 1. How the two services talk today

### 1.1 Extractor side (`src/`)
- `src/log_error_extractor.py:90` `extract_error_sections()`
  - Finds error indices using 17 substring `ERROR_PATTERNS` (`log_error_extractor.py:29`).
  - Expands each index into a window using adaptive buckets
    `(50,50,10), (100,10,5), (150,5,2)` — first 50 errors get 50 before / 10 after, etc.
  - Calls `_extract_sections_with_context` (`log_error_extractor.py:206`) which merges
    overlapping ranges and returns lines prefixed with `"Line N: ..."`, sections
    separated by `"--- Next Error Section ---"`.
  - **Returns a single-element list: `['\n'.join(sections)]`** — i.e., error + context
    are concatenated into one giant blob.
- `src/api_poster.py:104` builds JSON payload:
  ```json
  {
    "source": "gitlab", "repo": "...", "branch": "...", "commit": "...",
    "job_name": "...", "pipeline_id": "...", "triggered_by": "...",
    "failed_steps": [
      { "step_name": "...", "error_lines": ["<ONE BIG BLOB of error+context>"] }
    ]
  }
  ```
- Posts to `http://{BFA_HOST}:8000/api/analyze` with Bearer JWT.

### 1.2 Analyzer side (`build-failure-analyzer/`)
- `analyzer_service.py:192` `FailedStep { error_lines: List[str], embedding_vector: Optional[List[float]] }`.
- `analyzer_service.py:277` loop: `for error_line in step.error_lines` — one iteration,
  `error_text = error_line.strip()` is the entire blob.
- `analyzer_service.py:284` `error_hash = sha256(error_text)` — full-blob SHA is used
  as Redis cache key (`ai:fix:<hash>`, `sme:fix:<hash>`).
- Redis SME cache → Redis AI cache → Domain RAG (`pipeline_context` collection) →
  `resolver.resolve([error_text], embedding_vector, metadata)`.
- `resolver_agent.py:64` `resolve()`:
  - `error_text = "\n".join([l.strip() for l in error_lines if l.strip()])`
  - Calls `self.vector.lookup_existing_fix(error_text, top_k=5, embedding_vector=...)`.
  - If no vector hit → LLM call (`llm_openwebui_client.call_llm`) with full blob
    inside user prompt. LLM response cached in Redis `ai:fix:<hash>`.
  - Resolver **does not** write to vector DB.
- `vector_db.py:159` `lookup_existing_fix()`:
  - Embeds the blob via Ollama `/api/embed` (default model `granite-embedding`).
  - `collection.query(query_embeddings=[vec], n_results=5, include=[metadatas, documents, distances])`.
  - Converts `sim = 1 - distance` (line 212). Uses collection default distance (L2).
  - Picks best `sim`, returns if `sim > 0.78`.
- `vector_db.py:240` `save_fix_to_db()`:
  - Called only by Slack Approve / Edit path (`slack_reviewer.py:141`, `slack_reviewer.py:94`).
  - `embedding = self._get_embedding(error_text)` (full blob).
  - `ids = ["fix-" + hex(hash(error_text))]` (Python `hash()` — process-salted, non-deterministic across runs!).
  - Documents = `[fix_text]`, metadata has `error_text` (full blob) + approver + status.

---

## 2. Root cause of the "one huge log matches everything" bug

Four compounding causes:

1. **Error and context are glued together before embedding.** A 2000-line blob is
   dominated by generic context (timestamps, paths, surrounding build output).
   Different failures with similar build environments produce nearly identical
   embeddings because 90% of the text is shared noise. (`log_error_extractor.py:138`,
   `resolver_agent.py:87`, `vector_db.py:270`)

2. **Granite-embedding on very long text collapses toward the space centroid.**
   Embedding models trained on short passages produce a near-average vector for
   texts far longer than the context window. That vector sits in a dense region
   where many unrelated short queries fall within `1 − distance > 0.78`.

3. **Distance metric is wrong.** Chroma's default metric for a collection created
   with `get_or_create_collection(name=...)` is **L2 (Euclidean)**. The code then
   computes `sim = 1 - distance` (`vector_db.py:212`). L2 distances are unbounded
   (can be >1 → negative "similarity") and are dominated by vector magnitude.
   For long-text "centroid" embeddings, magnitude shrinks → L2 distance shrinks →
   `sim` artificially climbs above 0.78 for everything.

4. **ID uses non-deterministic `hash()`** (`vector_db.py:276`). Python's builtin
   `hash()` is salted per-process, so the same error across restarts creates a
   new row instead of updating. The DB grows without dedup; one duplicated
   huge-blob row poisons all future queries.

Secondary contributors:
- No length cap on embedded text.
- No update-on-approval — Slack Approve always `collection.add()`, never updates.
- `lookup_existing_fix` returns only the single best match; it can't disambiguate
  between two equally-similar fixes.

---

## 3. Proposed solution (no code written yet)

### 3.1 Split `error_lines` from `context_lines` in the wire contract

**Extractor side (`src/log_error_extractor.py`):**
Change `extract_error_sections` return type from `List[str]` (1 blob)
to `List[dict]`:
```python
[
  {
    "error_lines":    ["npm ERR! code ERESOLVE", "npm ERR! ..."],  # pattern-matched only
    "context_lines":  ["Resolving dependencies...", "...", "..."], # 50 before / 10 after
    "error_fingerprint": "npm err code eresolve peer dep ..."       # normalized for hashing/embedding
  },
  ...
]
```
Each matched error index yields one dict. Merged ranges collapse to one dict per merged region (not per individual error) so we don't duplicate work.

**Extractor → API (`src/api_poster.py`):**
```json
"failed_steps": [{
  "step_name": "...",
  "errors": [
    { "error_lines": [...], "context_lines": [...], "error_fingerprint": "..." }
  ]
}]
```
Keep legacy `error_lines: List[str]` on the wire for back-compat until the analyzer is migrated (one release overlap).

### 3.2 Normalize before embedding/hashing

New helper `normalize_error_text(error_lines: List[str]) -> str`:
- Strip `Line N:` prefix.
- Strip ISO timestamps, `[HH:MM:SS]`, epoch millis.
- Replace absolute paths (`/home/...`, `C:\...`, `/tmp/build-xxx/`) with `<PATH>`.
- Replace SHAs (`[a-f0-9]{7,40}`), UUIDs, container IDs, port numbers with placeholders.
- Collapse whitespace; lowercase.
- Truncate to 512 tokens (granite's input ceiling).

Use the normalized text as:
- `error_fingerprint` for dedup.
- `id = "fix-" + sha256(fingerprint)[:32]` (deterministic, replaces `hash()`).
- Embedding input.

### 3.3 Store **only** error_lines embeddings in vector DB

Rewrite `vector_db.save_fix_to_db` signature:
```python
save_fix_to_db(
    error_fingerprint: str,    # normalized, used for ID + embedding
    error_lines: List[str],    # raw matched lines, stored in metadata for display
    context_sample: str,       # first ~2KB of joined context_lines; metadata-only
    fix_text: str,
    approver, status, metadata
)
```

Chroma write:
- `embeddings=[embed(error_fingerprint)]`
- `documents=[fix_text]`
- `metadatas=[{ error_fingerprint, raw_error_lines, context_sample, repo, job_name, approver, status, fix_id, revision }]`

### 3.4 Fix the similarity math

- On first call create collection with explicit cosine space:
  ```python
  client.get_or_create_collection(
      name=CHROMA_COLLECTION,
      metadata={"hnsw:space": "cosine"},
  )
  ```
  (new collection name, e.g., `fix_embeddings_v2`, so existing DB is untouched).
- Normalize embedding vectors to unit length before `add`/`query`.
- Tighten `SIMILARITY_THRESHOLD` for the error-only embedding to **0.90**.
- Cap embedding input length; reject embeddings of text <8 chars.

### 3.5 Context-based disambiguation (no extra LLM call)

Rewrite `lookup_existing_fix`:
1. Embed normalized error_fingerprint → top-K=10 with cosine.
2. Keep candidates with `sim >= 0.90`.
3. If 0 → return None (fall through to LLM).
4. If 1 → return it.
5. If >1 → compute a secondary context similarity:
   - `ctx_sim = cosine(embed(query.context_lines[:2KB]), embed(candidate.context_sample))`
   - score = `0.7 * error_sim + 0.3 * ctx_sim`
   - Return top if `score_1 − score_2 > 0.05`; otherwise fall through to LLM.

This preserves the user-requested property: "if more solutions are present, pick
the exact one based on context_lines without going to the LLM."

### 3.6 Approval linking (update, don't duplicate)

In `slack_reviewer.py` Approve/Edit handler:
- Look up existing row by `id = sha256(fingerprint)`.
- If exists → `collection.update(ids=[id], documents=[new_fix], metadatas=[{..., revision: n+1, edited_by: ...}])`.
- If absent → `collection.add(...)`.
- Keep a `fix_id` UUID in metadata so the same canonical fix can be aliased to
  multiple fingerprints via a Redis set `alias:<fix_id> → {fingerprint1, ...}`.

### 3.7 Defensive guards

- Hard cap the extractor: drop a matched region if `len(joined_error_lines) > 2 KB`;
  log + alert instead of sending.
- Skip vector save if `len(error_fingerprint) < 8`.
- Log every best-match similarity score; add a Prometheus metric
  `bfa_vector_best_sim` for re-detecting poisoning.

### 3.8 One-off migration

`scripts/migrate_vector_db.py` (new):
- Read all rows from `fix_embeddings`.
- Re-derive `error_fingerprint` from `metadata.error_text` via the new normalizer.
- Skip rows where `len(error_text) > 5 KB` or `fix_text` in `("", "(empty fix)")` — these are the poisoning rows.
- Write to `fix_embeddings_v2` with cosine space and normalized embeddings.
- Run manually after deploy; swap `CHROMA_COLLECTION` env var once verified.

---

## 4. Files that change

| # | File | Change | ~LoC |
|---|---|---|---|
| 1 | `src/log_error_extractor.py` | Split return, emit `error_lines`/`context_lines`/`error_fingerprint` dicts | 60 |
| 2 | `src/api_poster.py` | New `errors` payload shape, keep legacy field for one release | 30 |
| 3 | `build-failure-analyzer/analyzer_service.py` | New `FailedStep` → `errors: List[ErrorEntry]`, loop adapt, cache key by fingerprint | 80 |
| 4 | `build-failure-analyzer/vector_db.py` | Normalizer, deterministic ID, cosine space, `context_sample` metadata, disambiguation lookup | 150 |
| 5 | `build-failure-analyzer/resolver_agent.py` | Pass `error_fingerprint` + `context_lines` through to vector lookup | 30 |
| 6 | `build-failure-analyzer/slack_reviewer.py` | Update-not-insert on Approve/Edit | 20 |
| 7 | `scripts/migrate_vector_db.py` (new) | One-off migration | 80 |
| 8 | Tests (`tests/`, `build-failure-analyzer/tests/`) | Unit tests for normalizer, disambiguation, migration | 200 |

---

## 5. Rollout order (so nothing breaks mid-deploy)

1. Land analyzer changes accepting **both** `error_lines` (legacy) and `errors` (new) — deploy first.
2. Run migration script into `fix_embeddings_v2`; verify counts and a few queries by hand.
3. Flip `CHROMA_COLLECTION=fix_embeddings_v2` on analyzer; restart.
4. Land extractor changes emitting `errors` field; deploy.
5. Remove legacy `error_lines` handling from analyzer after one stable week.

---

## 6. Open questions for the user

- Are the Slack Approve flow's existing approved fixes worth salvaging via
  migration, or is it acceptable to start fresh and have SMEs re-approve the
  common ones? (migration is fine either way — flag for decision)
- Should `pipeline_context` collection (domain patterns, `pipeline_context_rag.py`)
  also be migrated to cosine? (It uses threshold 0.55 — probably fine as-is.)
- Should the 0.90 threshold be configurable per-job? (Currently one env var.)
- Do you want the AWS Bedrock LLM swap-in done in this PR or separately?
  (branch name says `setup-log-analysis-bedrock` — currently code uses OpenWebUI
  via `llm_openwebui_client.py`.)

---

## 7. Session-restart checklist (for future Claude sessions)

If context is lost, re-read this file first, then:
- `build-failure-analyzer/analyzer_service.py:192` (FailedStep schema)
- `build-failure-analyzer/analyzer_service.py:267` (analyze endpoint)
- `build-failure-analyzer/vector_db.py:159` (lookup) + `:240` (save)
- `build-failure-analyzer/resolver_agent.py:64` (resolve)
- `src/log_error_extractor.py:90` (extraction)
- `src/api_poster.py:104` (payload shape)

Branch: `claude/setup-log-analysis-bedrock-gmLHN`.
Do **not** implement until the user approves the plan above.
