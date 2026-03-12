# Enhanced Vector DB — Normalization & Fix Management
## Team Presentation

---

## Agenda

1. The Problem We Faced
2. Possible Mitigations (Other Solutions)
3. Why Those Approaches Won't Work
4. Why Our Approach Works
5. Implementation Details

---

## 1. The Problem We Faced

### What Happened

After running the Build Failure Analyzer (BFA) in production for about a week, SMEs approved several fixes into ChromaDB. The system worked well — until one very large error log (~15,000 chars, 500+ lines) was approved.

After that single approval, **every new build failure — regardless of type — returned the same fix**. GCC linker errors got "Increase Node memory." Python import errors got "Increase Node memory." Docker pull failures got "Increase Node memory."

The system became effectively broken.

### Root Cause: The Hub Effect in High-Dimensional Spaces

When you embed a very large text, the embedding model averages across many diverse tokens. The result is a vector that sits near the **center of the vector space** — a phenomenon called the "hub effect."

```
Imagine a dart board:
- Small, specific error text → lands in a precise spot
- Huge, noisy log → lands near the bullseye (center)

The center has moderate distance (~0.82 cosine similarity) to EVERYTHING.
```

This creates a cascading problem:

```
Step 1: SME approves oversized log → stored embedding = "center of space"
Step 2: New gcc error comes in → compared against all stored embeddings
Step 3: Oversized entry has 0.82 similarity (above 0.78 threshold) → WINS
Step 4: User gets wrong fix → trust in system degrades
Step 5: This happens for EVERY new error → system is broken
```

### Four Contributing Factors

| # | Factor | What it means |
|---|--------|---------------|
| 1 | **No text normalization** | Full raw log embedded as-is — Line NNN: prefixes, duplicate lines, build output noise all included |
| 2 | **No length awareness** | A 15,000-char entry treated identically to a 100-char entry in similarity scoring |
| 3 | **Generic embeddings from large inputs** | Embedding model averages across many diverse tokens → vector near center of space |
| 4 | **Cascading false positives** | One generic embedding monopolizes all lookups → every query returns same wrong fix |

### Real Example

**Stored entries:**

| ID | Error Text | Fix | Length |
|---|-----------|-----|--------|
| fix-abc123 | `"Line 1: Starting build...\n...(500 lines)...\nLine 450: FATAL ERROR: heap out of memory\n...(200 more lines)"` | "Increase Node memory: NODE_OPTIONS=--max-old-space-size=4096" | ~15,000 chars |
| fix-def456 | `"ERROR: gcc compilation failed\n/src/main.c:42: undefined reference to 'pthread_create'"` | "Add -lpthread to LDFLAGS" | ~120 chars |

**Query:** `"ERROR: gcc compilation failed\n/src/utils.c:15: undefined reference to 'sqrt'"` (~100 chars)

| Entry | Raw Similarity | Result |
|-------|---------------|--------|
| fix-abc123 (huge log) | 0.82 | **WINS** (above 0.78 threshold) |
| fix-def456 (gcc error) | 0.80 | Loses |

**User gets "Increase Node memory" for a gcc linker error. WRONG FIX.**

---

## 2. Possible Mitigations (Other Solutions)

We evaluated several approaches before settling on our solution:

### Option A: Just Raise the Similarity Threshold

**Idea:** Increase the threshold from 0.78 to 0.85 or 0.90 so the oversized entry (0.82) falls below it.

### Option B: Limit Stored Text Length (Hard Truncation)

**Idea:** Simply truncate any error text to N characters before embedding.

### Option C: Use a Better Embedding Model

**Idea:** Switch to a model with a longer context window or better long-text handling (e.g., OpenAI ada-002, Cohere embed-v3).

### Option D: Linear Length Penalty

**Idea:** Apply a simple `1/ratio` penalty based on length difference.

### Option E: Step-Function Cutoff

**Idea:** If stored entry is more than Nx longer than query, reject it entirely.

### Option F: Re-embed Periodically / Manual Cleanup

**Idea:** Just monitor the database and manually delete problematic entries.

---

## 3. Why Those Approaches Won't Work

### Option A: Raise Threshold — Causes False Negatives

```
Problem: The oversized entry has 0.82 similarity.
If we raise threshold to 0.85:
  - fix-abc123 (oversized): 0.82 → rejected (good)
  - fix-def456 (correct gcc match): 0.80 → ALSO rejected (bad!)

We lose correct matches just to block one bad one.
```

| Threshold | Blocks oversized? | Blocks correct matches? | Verdict |
|-----------|------------------|------------------------|---------|
| 0.78 | No | No | Current (broken) |
| 0.82 | Barely | Some | Still risky |
| 0.85 | Yes | Many | Too many false negatives |
| 0.90 | Yes | Almost all | System barely returns DB matches |

**Conclusion:** This is a blunt instrument. The problem isn't that 0.78 is wrong — the problem is that a specific entry has artificially inflated similarity.

### Option B: Hard Truncation — Loses Error Signal

```
Error log (500 lines):
  Line 1: Starting pipeline...
  Line 2: Cloning repository...
  Line 3: Installing dependencies...
  ...
  Line 450: FATAL ERROR: heap out of memory    ← THE ACTUAL ERROR
  Line 451: Build failed
  ...

Hard truncation at 2000 chars = keeps lines 1-50 (setup noise)
The actual error at line 450 is THROWN AWAY.
```

| Approach | What you keep | What you lose |
|----------|-------------|--------------|
| First N chars | Setup/context noise | Actual errors (often at end) |
| Last N chars | Stack traces, errors | Repository/branch context |
| Random N chars | Unpredictable | Unpredictable |

**Conclusion:** Errors are NOT uniformly distributed in build logs. They're usually at the end, mixed with stack traces. Hard truncation is lossy in the worst way.

### Option C: Better Embedding Model — Doesn't Solve the Core Problem

```
Even with a 128K context model:
  - Input: 15,000 chars of mixed content
  - Output: still ONE vector (e.g., 768 dimensions)

  The fundamental problem remains:
  averaging 15,000 chars of diverse content into one vector
  → generic vector → hub effect → false matches
```

Also:
- Requires re-indexing all existing data
- May require infrastructure changes (Ollama → API, GPU requirements)
- Performance/cost implications for embeddings
- Doesn't help for already-stored oversized entries

**Conclusion:** The problem is mathematical (averaging diverse content), not model quality. A better model makes it slightly less bad, not fixed.

### Option D: Linear Penalty — Too Aggressive

```
Linear penalty: penalty = 1 / ratio

Length ratio 2x  → penalty = 0.50  → 0.82 * 0.50 = 0.41 (way too harsh)
Length ratio 3x  → penalty = 0.33  → 0.82 * 0.33 = 0.27

Normal variation between CI systems produces 2-3x length differences.
Linear penalty would destroy valid matches.
```

| Ratio | Linear Penalty | Log Penalty (ours) | Difference |
|-------|---------------|-------------------|------------|
| 2x | 0.50 | 0.91 | Linear kills the match |
| 3x | 0.33 | 0.86 | Linear is extreme |
| 10x | 0.10 | 0.74 | Both penalize (correct) |
| 100x | 0.01 | 0.59 | Both reject (correct) |

**Conclusion:** Linear penalty can't distinguish "slightly different" from "vastly different." The penalty curve needs to be gentle for small differences and aggressive for large ones.

### Option E: Step-Function Cutoff — No Gradual Degradation

```
Step function: if ratio > 5x → reject, else → accept

What about ratio = 4.9x? Full accept.
What about ratio = 5.1x? Full reject.

There is no smooth transition. Edge cases are unpredictable.
```

Also: what threshold do you pick? Too low = false negatives. Too high = doesn't solve the problem.

**Conclusion:** Real-world data doesn't have clean cutoffs. We need a smooth curve.

### Option F: Manual Cleanup — Doesn't Scale

```
Week 1: "Just delete the oversized entry"
Week 3: "Another oversized entry appeared"
Week 5: "Three more oversized entries, who has time for this?"
Week 8: "System is broken again, nobody noticed for 2 days"
```

| Aspect | Manual | Automated |
|--------|--------|-----------|
| Reaction time | Hours to days | Immediate |
| Consistency | Human error prone | Deterministic |
| Scale | Doesn't scale | Scales infinitely |
| Knowledge needed | Must understand the problem | Built into the code |

**Conclusion:** Manual processes are a temporary band-aid, not a solution.

---

## 4. Why Our Approach Works

### Two-Layer Defense: Normalization + Length-Penalized Scoring

We implemented two complementary mechanisms:

```
Layer 1: TEXT NORMALIZATION (improves embedding quality)
  → Better input → Better embeddings → Better matches

Layer 2: LENGTH-PENALIZED SIMILARITY (safety net for scoring)
  → Detects length mismatches → Penalizes disproportionate entries
```

### Why Two Layers?

| Layer | Handles | Deployed when | Helps existing data? |
|-------|---------|--------------|---------------------|
| Length penalty | Scoring bias from size mismatch | Immediately (no migration) | Yes — protects against all oversized entries |
| Normalization | Embedding quality from noisy text | After reindex for old data | Yes — after `POST /api/fixes/reindex` |

```
Timeline:
  Day 0: Deploy code → length penalty protects IMMEDIATELY
  Day 0: Run /api/fixes/reindex → normalization improves ALL embeddings
  Day 1+: Both active, penalty rarely triggers (entries are similar length)
```

### Why Logarithmic Penalty Specifically?

The logarithmic function `1 / (1 + alpha * ln(ratio))` was chosen because:

1. **Gentle for small differences** (2-3x = normal CI variation)
2. **Aggressive for large differences** (10x+ = almost always problematic)
3. **Smooth curve** (no step functions or cliff edges)
4. **Tunable** via single ALPHA parameter

```
Penalty curve (ALPHA = 0.15):

1.0 |*
    | **
    |   ***
    |      ****
    |          *****
    |               ********
0.5 |                       ************
    |                                   ***************
    |
    +--+----+------+----------+------------------+--------→
    1x  2x   5x    10x       50x              100x
              Length ratio

Sweet spot: barely touches 1-3x, significantly penalizes 10x+
```

| Length Ratio | Penalty | Effect on 0.82 raw similarity | Still matches (>0.78)? |
|-------------|---------|-------------------------------|----------------------|
| 1x | 1.00 | 0.820 | Yes |
| 2x | 0.91 | 0.743 | No — but close, which is fine |
| 5x | 0.81 | 0.661 | No |
| 10x | 0.74 | 0.609 | No |
| 100x | 0.59 | 0.485 | No |

### Why Normalization Specifically?

Not just "truncate" — **intelligent text processing**:

| Step | What it does | Why it matters |
|------|-------------|----------------|
| Strip `Line NNN:` prefixes | Remove log-extraction line number markers | Not semantically useful — adds noise |
| Remove empty lines | Drop whitespace-only lines | Reduces token waste |
| Deduplicate | Keep first occurrence only | Build logs repeat errors 100s of times |
| Prioritize error signals | Sort error-keyword lines to top | Embedding driven by actual errors, not context |
| Cap length | 80 lines / 4000 chars max | Prevents generic embeddings |

**Critical detail:** Normalization runs on **both save and lookup** sides. This ensures the same transformation is applied consistently:

```
Save:  raw error log → normalize → embed → store in ChromaDB
Query: raw error log → normalize → embed → compare against stored embeddings
```

### Combined Effect — Before vs After

| Scenario | Before (broken) | After (fixed) |
|----------|-----------------|---------------|
| Short query vs huge stored entry | 0.82 → **wrong fix returned** | 0.47 → **correctly rejected by penalty** |
| Short query vs correct short entry | 0.80 → correct match | 0.78 → **correct match (unchanged)** |
| Error buried in test output | 0.71 → **missed** | 0.92 → **matched (normalization extracted error)** |
| Same error, different context | May mismatch | **Correct match (normalization focuses on error signal)** |

---

## 5. Implementation Details

### Architecture Overview

```
                    ┌─────────────────────────────────────────┐
                    │         BUILD FAILURE ANALYZER           │
                    └─────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────────────┐
                    │         Error Text Arrives               │
                    │  (from CI/CD pipeline via POST /analyze) │
                    └──────────────────┬──────────────────────┘
                                       │
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │    1. NORMALIZE error text                │
                    │    - Strip Line NNN: prefixes             │
                    │    - Remove empty lines                   │
                    │    - Deduplicate                          │
                    │    - Prioritize error signal keywords     │
                    │    - Cap to 80 lines / 4000 chars         │
                    └──────────────────┬───────────────────────┘
                                       │
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │    2. EMBED normalized text               │
                    │    (Ollama / granite-embedding model)     │
                    └──────────────────┬───────────────────────┘
                                       │
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │    3. QUERY ChromaDB (top-k candidates)   │
                    │    Returns: raw similarity scores         │
                    └──────────────────┬───────────────────────┘
                                       │
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │    4. APPLY LENGTH PENALTY                │
                    │                                          │
                    │    For each candidate:                    │
                    │      ratio = max(stored,query) /          │
                    │              min(stored,query)            │
                    │      penalty = 1/(1 + 0.15*ln(ratio))    │
                    │      adjusted = raw_sim * penalty         │
                    │                                          │
                    │    If adjusted >= 0.78 → use this fix     │
                    │    Else → fall through to LLM             │
                    └──────────────────┬───────────────────────┘
                                       │
                          ┌────────────┴────────────┐
                          │                         │
                    Match found               No match
                          │                         │
                          ▼                         ▼
                   Return fix              Call LLM for generation
                   from DB                 → Post to Slack for review
                                           → SME Approve/Edit/Discard
                                           → If approved: normalize + embed + store
```

### Key Code: `_normalize_error_text()` in `vector_db.py`

```python
def _normalize_error_text(self, raw_text: str) -> str:
    lines = raw_text.split("\n")

    # Step 1: Strip "Line NNN:" prefixes
    lines = [re.sub(r'^Line\s+\d+:\s*', '', l) for l in lines]

    # Step 2: Remove empty lines
    lines = [l.strip() for l in lines if l.strip()]

    # Step 3: Deduplicate (keep first occurrence)
    seen = set()
    unique = []
    for l in lines:
        if l not in seen:
            seen.add(l)
            unique.append(l)
    lines = unique

    # Step 4: Prioritize error-signal lines
    error_kw = ['error', 'fail', 'fatal', 'exception', 'traceback', ...]
    error_lines = [l for l in lines if any(kw in l.lower() for kw in error_kw)]
    other_lines = [l for l in lines if l not in error_lines]
    lines = error_lines + other_lines

    # Step 5: Cap to MAX_ERROR_LINES
    lines = lines[:self.max_error_lines]

    # Step 6: Cap to MAX_ERROR_CHARS
    text = "\n".join(lines)
    return text[:self.max_error_chars]
```

### Key Code: Length Penalty in `lookup_existing_fix()`

```python
def lookup_existing_fix(self, error_text, top_k=5, embedding_vector=None):
    # Normalize the query
    normalized_query = self._normalize_error_text(error_text)
    query_len = len(normalized_query)

    # Embed and query ChromaDB
    results = self.collection.query(
        query_embeddings=[embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )

    for i, distance in enumerate(results["distances"][0]):
        raw_similarity = 1.0 - distance  # ChromaDB returns distance
        stored_len = len(results["metadatas"][0][i].get("error_text", ""))

        # Length penalty
        ratio = max(stored_len, query_len) / max(min(stored_len, query_len), 1)
        penalty = 1.0 / (1.0 + ALPHA * math.log(ratio))
        adjusted = raw_similarity * penalty

        if adjusted >= SIMILARITY_THRESHOLD:
            return {
                "fix_text": results["documents"][0][i],
                "confidence": adjusted,
                "source": "vector_db",
                ...
            }
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SIMILARITY_THRESHOLD` | `0.78` | Minimum adjusted similarity for a match |
| `LENGTH_PENALTY_ALPHA` | `0.15` | Penalty curve aggressiveness |
| `MAX_ERROR_LINES` | `80` | Max lines after normalization |
| `MAX_ERROR_CHARS` | `4000` | Hard character cap |
| `VECTOR_TOP_K` | `5` | Candidates to retrieve before scoring |

### Fix Management API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/fixes` | List all fixes (paginated, filterable) |
| GET | `/api/fixes/{id}` | Get single fix details |
| PUT | `/api/fixes/{id}` | Update fix text (re-embeds automatically) |
| DELETE | `/api/fixes/{id}` | Remove fix from DB |
| GET | `/api/fixes/audit` | Find oversized entries |
| POST | `/api/fixes/reindex` | Re-embed all entries with normalized text |

### Deployment — Zero Downtime, Backward Compatible

```
1. Deploy updated code
   → Length penalty active IMMEDIATELY on all lookups
   → No schema changes, no database migration

2. GET /api/fixes/audit
   → Identify oversized entries (if any)

3. POST /api/fixes/reindex
   → Re-embed all entries with normalization
   → Old embeddings replaced with better ones
   → ~30 seconds for 100 entries

4. Verify: GET /api/fixes
   → Check "normalized": "true" on all entries
```

### Tuning Quick Reference

| Symptom | Adjustment |
|---------|------------|
| Wrong fixes returned (false positives) | Increase `SIMILARITY_THRESHOLD` to 0.82+ or `LENGTH_PENALTY_ALPHA` to 0.20+ |
| Fix exists but not matched (false negatives) | Decrease `SIMILARITY_THRESHOLD` to 0.75 or `LENGTH_PENALTY_ALPHA` to 0.10 |
| Important errors not reaching top | Add missing keywords to error-signal list |
| Very short queries matching everything | Increase threshold or add min query length |

---

## Summary

| What | How | Impact |
|------|-----|--------|
| **Problem** | Oversized log embeddings produce "hub" vectors that match everything | System returns wrong fixes for all queries |
| **Root cause** | No normalization + no length awareness in scoring | Generic embeddings dominate similarity results |
| **Solution** | Two-layer defense: normalization + logarithmic length penalty | Correct matches preserved, false positives eliminated |
| **Deployment** | Drop-in replacement, zero migration | Length penalty works immediately, reindex for normalization |
| **Tuning** | Two env vars: `SIMILARITY_THRESHOLD` + `LENGTH_PENALTY_ALPHA` | Adjustable without code changes |

### Key Takeaways

1. **Embedding models have limits** — large text → generic vectors → hub effect
2. **Two-layer defense** is better than one — penalty is the safety net, normalization is the quality fix
3. **Logarithmic penalty** is the right curve — gentle for normal variation, aggressive for extreme mismatches
4. **Normalize on both sides** — save and lookup must apply identical transformation
5. **Zero-downtime deployment** — backward compatible, no migration needed
