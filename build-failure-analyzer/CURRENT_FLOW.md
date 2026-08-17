# `build-failure-analyzer` — Current Flow Walkthrough

Companion to `SOLUTION_PROPOSAL.md`. This doc explains **what the code does today**,
with file:line anchors and quoted snippets. No design changes here — just the map.

---

## 1. Service overview

The analyzer is **two Python services** sharing one Redis and one Chroma DB:

| Service | File | Port | Framework | Role |
|---|---|---|---|---|
| Main API | `analyzer_service.py` | 8000 | FastAPI | Receives `/api/analyze` from extractor, runs resolver, DMs developer, posts to SME Slack |
| Slack reviewer | `slack_reviewer.py` | 5001 | Flask | Handles Slack interactive button callbacks (Approve/Edit/Discard), writes approved fixes to vector DB |

Shared state:
- **Redis** — caches fixes by `error_hash`, stores Slack thread mappings, edit-mode intents.
- **Chroma** (persistent on disk at `CHROMA_DB_PATH`) — two collections:
  - `fix_embeddings` — SME-approved/edited fixes (the problematic one).
  - `pipeline_context` — domain patterns from `context/domain_context_patterns.json` (not user-writable).

External dependencies:
- **Ollama** (`granite-embedding` model) — produces embedding vectors.
- **OpenWebUI** (`llm_openwebui_client.py`) — proxies to Bedrock Claude Sonnet for fix generation.
- **Slack** — DevOps SME channel (where humans approve) + developer DMs.

---

## 2. Data contract (what the extractor sends)

`analyzer_service.py:192`:
```python
class FailedStep(BaseModel):
    step_name: Optional[str]
    error_lines: List[str]
    embedding_vector: Optional[List[float]] = None


class AnalyzePayload(BaseModel):
    repo: str
    branch: Optional[str]
    commit: Optional[str]
    job_name: Optional[str]
    pipeline_id: Optional[str]
    triggered_by: Optional[str]
    failed_steps: List[FailedStep]
```

What actually arrives: `error_lines` is a **single-element list** containing one
giant string with error + context glued together, each line prefixed
`"Line N: ..."`, sections separated by `"--- Next Error Section ---"`.
(See `src/log_error_extractor.py:138`.)

There is **no separation between "the error" and "the context around it"** on
the wire or in the schema — this is the core design flaw.

---

## 3. `/api/analyze` request pipeline (the happy path)

`analyzer_service.py:267`:
```python
@app.post("/api/analyze")
async def analyze(payload: AnalyzePayload, claims=Depends(require_jwt)):
    if not payload.failed_steps:
        raise HTTPException(status_code=400, detail="No failed steps provided")

    init_domain_rag_if_needed()           # load domain patterns once
    results = []

    for step in payload.failed_steps:
        step_name = step.step_name or "Unknown Step"
        for error_line in step.error_lines:        # ONE iteration (blob)
            error_text = error_line.strip()
            ...
            error_hash = hashlib.sha256(error_text.encode()).hexdigest()
```

The resolution order for each step is:

### 3.1 SME cache check (Redis)
`analyzer_service.py:298`:
```python
sme_cached = r.get(SME_FIX_KEY.format(error_hash))   # "sme:fix:<sha256>"
if sme_cached:
    send_dev_dm_fix(..., source="sme_cache")
    results.append({..., "source": "sme_cache", "fix": cached_obj})
    continue
```
→ Fastest hit. Served from Redis only, never hits vector DB or LLM.

### 3.2 AI cache check (Redis)
`analyzer_service.py:333`:
```python
ai_cached = r.get(AI_FIX_KEY.format(error_hash))     # "ai:fix:<sha256>"
```
TTL is 24 h (`resolver_agent.py:38`). Cached LLM outputs keyed by SHA of the blob.

**Subtle point**: the SHA is over the **full blob**. Any timestamp change in the
blob makes this miss, so the AI cache hit rate is low in practice.

### 3.3 Domain RAG lookup (`pipeline_context` collection)
`analyzer_service.py:371`:
```python
if _domain_ctx_db is not None:
    domain_matches = lookup_domain_matches(
        error_text=error_text,
        ctx_db=_domain_ctx_db,
        threshold=0.55,
        top_k=5,
    )
    domain_snippet = build_domain_rag_snippet(domain_matches)
```
This **doesn't** resolve the fix — it just fetches snippets from
`context/domain_context_patterns.json` that look similar to the error, then
stuffs them into `metadata["domain_rag_snippet"]` so the LLM can read them
as hints later.

### 3.4 Resolver agent (vector DB + LLM)
`analyzer_service.py:395`:
```python
candidate = resolver.resolve(
    [error_text],
    embedding_vector=getattr(step, "embedding_vector", None),
    metadata=metadata,
) or {}
```

Inside `resolver_agent.py:64` `ResolverAgent.resolve()`:

1. **Normalize error text + hash**
   ```python
   error_text = "\n".join([l.strip() for l in error_lines if l.strip()])
   error_hash = self._hash(error_text)
   ```
2. **Re-check AI cache in Redis (`ai:fix:<sha256>`)** — second layer in case the outer analyzer missed it.
3. **Vector DB lookup** (`vector_db.py:159`):
   ```python
   vec_result = self.vector.lookup_existing_fix(
       error_text, top_k=top_k, embedding_vector=embedding_vector,
   )
   if vec_result:
       return vec_result            # {fix_text, confidence, source:"vector_db", metadata}
   ```
4. **LLM call** (when nothing above worked):
   ```python
   system_prompt = (
       "You are an expert CI/CD build failure resolver ...\n"
       + f"Domain knowledge snippet:\n{domain_snippet}\n"
       + f"Enterprise CI/CD infrastructure overview:\n{GLOBAL_CONTEXT_TEXT}"
   )
   user_prompt = f"Pipeline context:\n{context_header}\n\nError log:\n{error_text}"
   generated_text = call_llm(prompt=user_prompt, system_prompt=system_prompt, ...)
   ```
   The resolver **caches the LLM response in Redis (`ai:fix:<hash>`)** but does
   **NOT** write it to the vector DB. Vector DB writes happen only via Slack
   Approve/Edit, i.e., after a human SME says "this answer is good".

### 3.5 Post-resolution actions
- If source was `vector_db` / `sme_cache` / `ai_cache` → DM the developer directly.
- If source was `generated` (fresh LLM) → additionally post the error + fix to the
  SME Slack channel with Approve/Edit/Discard buttons (`analyzer_service.py:439`
  `send_error_message`).

---

## 4. `ResolverAgent` class — what it does and doesn't do

`resolver_agent.py:41`:
```python
class ResolverAgent:
    def __init__(self, redis_client: redis.Redis):
        self.redis  = redis_client
        self.vector = VectorDBClient()
```

Design intent: a **read-only** resolver. It reads Redis cache, reads the vector
DB, reads domain snippet metadata, and calls the LLM. It **never writes**:
- No Redis writes except the AI cache (`_ai_cache_set`).
- No vector DB writes anywhere — that's gated behind SME approval in
  `slack_reviewer.py`.

This means: **every LLM answer stays in Redis for 24 h max and is lost after
that unless a human approved it.** Only approved fixes enter the vector DB.

---

## 5. `VectorDBClient` — embedding + Chroma wrapper

`vector_db.py:38`:
```python
class VectorDBClient:
    def __init__(self, persist_path: Optional[str] = None):
        self.client     = chromadb.PersistentClient(path=...)
        self.collection = self.client.get_or_create_collection(name=CHROMA_COLLECTION)
```

### 5.1 Embedding
`vector_db.py:131`:
```python
def _get_embedding(self, text: str) -> Optional[List[float]]:
    emb = self._get_embedding_ollama_http(text)     # POST /api/embed
    if emb: return emb
    emb = self._get_embedding_ollama_cli(text)      # fallback CLI
    return emb
```
Model is `granite-embedding` (env `OLLAMA_EMBED_MODEL`). No text-length cap, no
normalization.

### 5.2 Lookup
`vector_db.py:159`:
```python
def lookup_existing_fix(self, error_text, top_k=5,
                        similarity_threshold=SIMILARITY_THRESHOLD,
                        embedding_vector=None):
    vector = embedding_vector or self._get_embedding(error_text)
    res = self.collection.query(
        query_embeddings=[vector], n_results=top_k,
        include=["metadatas", "documents", "distances"],
    )
    ...
    for i, dist in enumerate(distances):
        ...
        sim = 1 - dist                 # ← WRONG for L2 (Chroma default)
        candidates.append((sim, i))

    candidates.sort(reverse=True, key=lambda x: x[0])
    best_sim, idx = candidates[0]
    if best_sim <= similarity_threshold:    # default 0.78
        return None
    return {"fix_text": docs[idx], "confidence": best_sim,
            "source": "vector_db", "metadata": metas[idx]}
```

Key defects exposed by this code:
- **L2 distance interpreted as cosine**: Chroma's default collection uses
  Euclidean distance; `1 − distance` is only meaningful for cosine.
  For a long-text "centroid" embedding, L2 distance is small → `sim` artificially high.
- Returns only the single best match; no tie-breaking.
- `similarity_threshold = 0.78` too low for the miscalibrated metric.

### 5.3 Save
`vector_db.py:240`:
```python
def save_fix_to_db(self, error_text, fix_text, approver=None, status=None, metadata=None):
    ...
    embedding = self._get_embedding(error_text)          # full blob
    unique_id = f"fix-{abs(hash(error_text)) & ((1<<128)-1):032x}"   # ← Python hash(): salted, non-deterministic

    self.collection.add(
        documents=[fix_text],
        metadatas=[{"error_text": error_text, **flat_metadata}],
        embeddings=[embedding],
        ids=[unique_id],
    )
```

Key defects:
- ID uses Python builtin `hash()` — **salted per-process**, so the same
  error across restarts creates new IDs; duplicates accumulate.
- Whole blob (error + context) is embedded, so the embedding is dominated by
  context noise.
- Uses `collection.add` — never `update` — so any Slack re-approval of the
  same error creates another row.

There's also a module-level wrapper at `vector_db.py:335`:
```python
def save_fix_to_db(db_client, error_text, fix_text, approver=None, status="generated", metadata=None):
    if status not in ("approved", "edited"):
        return False                                     # guard: no AI-only saves
    ...
    return db_client.save_fix_to_db(error_text=error_text, fix_text=fix_text, ...)
```
This is the enforcement point for "only human-approved fixes enter the DB".

---

## 6. Domain RAG (`pipeline_context_rag.py`) — separate read-only channel

A second, smaller Chroma collection stores curated patterns from
`context/domain_context_patterns.json`:

```json
{
  "IT":      [ { "failure": "...", "solution": "..." }, ... ],
  "Product": [ ... ],
  "Devops":  [ ... ]
}
```

Indexed once on startup (`init_domain_rag_if_needed`, `analyzer_service.py:92`),
never updated at runtime.

`lookup_domain_matches` (`pipeline_context_rag.py:118`) does a top-5 cosine-ish
query with `threshold=0.55` and returns pattern-snippets that are then **inlined
into the LLM's system prompt** via `build_domain_rag_snippet` — not returned
directly to the user.

This collection is **not** affected by the poisoning bug because:
1. It's never written to after startup.
2. Its documents are short and curated (not huge log blobs).

---

## 7. Human-in-the-loop (Slack) — `slack_reviewer.py`

### 7.1 SME sees a new error
`analyzer_service.py:439` calls `send_error_message(error_text, ai_fix_text, error_hash, metadata)`
(defined in `slack_helper.py:229`). Slack message has three buttons:

```python
# slack_helper.py:106
{"type": "actions", ...
 "elements": [
   {"type":"button", "text":"✅ Approve", "action_id": f"approve_{error_id}"},
   {"type":"button", "text":"✏️ Edit",    "action_id": f"edit_{error_id}"},
   {"type":"button", "text":"🗑️ Discard", "action_id": f"discard_{error_id}"},
 ]}
```

### 7.2 Approve button
`slack_reviewer.py:139`:
```python
if action_name == "approve":
    save_fix_to_db(db, error_text, fix_text, approver=approver, status="approved")
    store_fix(error_id, error_text, fix_text, source="approved", ...)   # sync Redis
```

### 7.3 Edit flow
- Click **Edit** → server writes `last_edit:<channel>:<error_id> → user_id` in Redis
  and posts a prompt in the message thread.
- User replies in that thread.
- `slack_reviewer.py:39` `/bfa/slack/events` scans Redis for any `last_edit:*`
  key that maps to this user, validates the thread matches, then:
  ```python
  # slack_reviewer.py:94
  save_fix_to_db(db, error_text, new_fix_text, approver=display_name, status="edited")
  store_fix(error_id, error_text, new_fix_text, source="edited", ...)
  ```

### 7.4 Discard
Deletes `fix:<error_id>` from Redis. Nothing touches vector DB.

---

## 8. Full life-cycle in one picture

```
  Jenkins/GitLab build fails
            │
            ▼
  src/log_error_extractor.extract_error_sections()   ← finds error patterns
            │ (blob: error+context glued, "Line N: ..." prefixed)
            ▼
  src/api_poster POST /api/analyze                   ← JWT-signed
            │
            ▼
  analyzer_service.analyze(payload)
    ├── Redis sme:fix:<hash>     ─HIT→ DM dev, done
    ├── Redis ai:fix:<hash>      ─HIT→ DM dev, done
    ├── Domain RAG (pipeline_context, read-only)  → snippet for LLM prompt
    ├── resolver.resolve(...)
    │     ├── Redis ai:fix:<hash>         ─HIT→ return cached
    │     ├── VectorDB.lookup_existing_fix ─HIT→ return approved fix
    │     └── call_llm(prompt) → Redis ai:fix:<hash> (24h TTL)
    ├── source == "vector_db" / "*_cache" → DM dev only
    └── source == "generated"
          ├── DM dev
          └── Slack SME channel message with Approve/Edit/Discard
                                              │
  ───────────────────────────────────────────┘
  slack_reviewer.py  /bfa/slack/actions
    ├── Approve   → VectorDB.save_fix_to_db(..., status="approved")   ← THE write
    ├── Edit      → stashes intent, expects thread reply
    │   └── /bfa/slack/events (thread reply)
    │         → VectorDB.save_fix_to_db(..., status="edited")         ← THE write
    └── Discard   → Redis del fix:<id>
```

---

## 9. Why the DB gets poisoned (code-level mapping)

| Symptom                                    | Root cause in code                                                                 |
|--------------------------------------------|-------------------------------------------------------------------------------------|
| One huge log matches everything            | `log_error_extractor.py:138` returns `['\n'.join(sections)]` — error+context blob   |
| Short errors score ~0.8 against the blob   | `vector_db.py:212` `sim = 1 - distance` with L2 metric (Chroma default)            |
| Same error re-saved instead of updated     | `vector_db.py:276` `f"fix-{abs(hash(error_text)):...}"` — Python `hash()` is salted |
| Context noise dominates the embedding      | `vector_db.py:270` `embedding = self._get_embedding(error_text)` on full blob       |
| Threshold 0.78 too loose for miscalibrated scoring | `vector_db.py:30`                                                           |

---

## 10. Where to look first when debugging

- `vector_db.py:226` prints `"Best Similarity Score: {best_sim}"` on every lookup
  — grep your analyzer log for this line to see scores vs. threshold.
- `vector_db.py:278` logs `"Saving fix: id=... approver=... fields=..."` — trace
  which rows have been inserted.
- `chromadb.PersistentClient(path=CHROMA_DB_PATH).get_collection("fix_embeddings").count()`
  gives the current row count.
- Redis: `KEYS "fix:*"`, `KEYS "ai:fix:*"`, `KEYS "sme:fix:*"`, `KEYS "error_map:*"`.

---

## 11. Session-restart checklist

If restarting in a fresh Claude session, read in this order:
1. `build-failure-analyzer/CURRENT_FLOW.md` (this file) — what exists.
2. `build-failure-analyzer/SOLUTION_PROPOSAL.md` — what to change.
3. Entry points to re-open: `analyzer_service.py:267` (/api/analyze),
   `resolver_agent.py:64` (resolve), `vector_db.py:159` & `:240`
   (lookup + save), `slack_reviewer.py:139` (approve flow).
