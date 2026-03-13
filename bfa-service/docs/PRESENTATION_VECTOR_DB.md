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

We implemented two complementary mechanisms that solve different aspects of the problem:

```
Layer 1: TEXT NORMALIZATION (improves embedding quality)
  What: Build-log-specific structural cleaning before embedding
  How:  Strip line prefixes → remove empty lines → deduplicate → prioritize errors → cap length
  Why:  Better input → Better embeddings → Better matches
  See:  "Why Normalization Specifically?" below for detailed explanation

Layer 2: LENGTH-PENALIZED SIMILARITY (safety net for scoring)
  What: Logarithmic penalty applied to similarity scores based on text length mismatch
  How:  penalty = 1 / (1 + α × ln(ratio)), where ratio = max(stored,query) / min(stored,query)
  Why:  Even after normalization, if a stored entry is vastly longer than the query,
        the embedding is likely more generic → the match is less trustworthy
```

### Why Two Layers?

Neither layer alone is sufficient — they cover each other's blind spots:

| Layer | What it prevents | Limitation alone | Deployed when | Helps existing data? |
|-------|-----------------|------------------|--------------|---------------------|
| **Normalization** | Noisy text producing generic embeddings | Can't catch entries that were stored before normalization was deployed | After reindex for old data | Yes — after `POST /api/fixes/reindex` |
| **Length penalty** | Oversized entries dominating similarity scores | Doesn't improve embedding quality — just adjusts scoring | Immediately (no migration) | Yes — protects against all oversized entries instantly |

```
Together:
  - Normalization ensures embeddings are HIGH QUALITY (precise, not generic)
  - Length penalty ensures scoring is FAIR (long entries don't get unfair advantage)

Timeline:
  Day 0: Deploy code → length penalty protects IMMEDIATELY (zero migration)
  Day 0: Run /api/fixes/reindex → normalization improves ALL stored embeddings
  Day 1+: Both active — normalization makes entries similar in length,
           so penalty rarely triggers (it's a safety net, not the primary defense)
```

### Why Logarithmic Penalty Specifically?

**What is Length-Penalized Scoring?**

Length-Penalized Scoring is a post-retrieval adjustment to similarity scores that accounts for the length difference between a query error text and a stored error text. The core insight: when a stored entry is significantly longer than the query, its embedding is more "generic" (averaged across many diverse tokens), so a high cosine similarity score is **misleading** — it doesn't mean the errors are actually similar, it means the stored entry is similar to *everything*.

**How it works — step by step:**

```
1. ChromaDB returns raw cosine similarity (converted from distance):
     raw_similarity = 1.0 - distance

2. Calculate length ratio between stored entry and query:
     ratio = max(stored_len, query_len) / min(stored_len, query_len)
     (Always ≥ 1.0 — a ratio of 1.0 means identical length)

3. Apply logarithmic penalty:
     penalty = 1.0 / (1.0 + ALPHA × ln(ratio))
     where ALPHA = 0.15 (configurable via LENGTH_PENALTY_ALPHA env var)

4. Compute adjusted similarity:
     adjusted_similarity = raw_similarity × penalty

5. Compare against threshold:
     if adjusted_similarity ≥ 0.78 → return this fix
     else → skip this candidate, try next or fall through to LLM
```

**Why logarithmic (not linear, exponential, or step-function)?**

The logarithmic function `1 / (1 + α × ln(ratio))` was chosen because its curve naturally matches the real-world relationship between length difference and match reliability:

1. **Gentle for small differences** (2-3x ratio) — the same error from different CI systems (Jenkins vs GitHub Actions) naturally varies 2-3x in length due to different formatting, timestamps, and context. These are legitimate matches that should NOT be penalized heavily.

2. **Aggressive for large differences** (10x+ ratio) — a 100-char query matching a 15,000-char stored entry is almost certainly a false positive caused by the hub effect. These should be penalized significantly.

3. **Smooth curve** — no step functions or cliff edges. A 4.9x ratio and 5.1x ratio get almost identical penalties, unlike a step-function cutoff where one passes and the other fails completely.

4. **Tunable** via single `ALPHA` parameter — increasing ALPHA makes the penalty more aggressive (penalizes smaller ratios), decreasing makes it more lenient.

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

**Concrete example with numbers:**

| Length Ratio | ln(ratio) | Penalty Formula | Penalty | Effect on 0.82 raw similarity | Still matches (>0.78)? |
|-------------|-----------|-----------------|---------|-------------------------------|----------------------|
| 1x (identical) | 0.00 | 1/(1 + 0.15×0.00) | 1.00 | 0.820 | Yes |
| 2x | 0.69 | 1/(1 + 0.15×0.69) | 0.91 | 0.743 | No — but close, which is fine |
| 5x | 1.61 | 1/(1 + 0.15×1.61) | 0.81 | 0.661 | No |
| 10x | 2.30 | 1/(1 + 0.15×2.30) | 0.74 | 0.609 | No |
| 100x (hub effect) | 4.61 | 1/(1 + 0.15×4.61) | 0.59 | 0.485 | No |

**Benefits of Length-Penalized Scoring:**

1. **Eliminates the hub effect** — oversized entries that sit near the center of the vector space can no longer dominate search results, because their inflated similarity scores are reduced proportionally to the length mismatch
2. **Zero migration required** — the penalty is applied at query time on raw ChromaDB results, so it works immediately on all existing data without re-embedding
3. **Preserves correct matches** — entries with similar lengths (ratio close to 1x) receive almost no penalty, so legitimate matches are unaffected
4. **Bidirectional protection** — the ratio uses `max/min`, so it penalizes both cases: short query vs long stored entry, AND long query vs short stored entry
5. **Works with normalization as a safety net** — after normalization, most entries are similar in length (80 lines / 4000 chars max), so the penalty rarely activates. But if a pre-normalization entry or an edge case slips through, the penalty catches it

### Why Normalization Specifically?

> **Important:** This is NOT traditional NLP normalization (lowercasing, removing noise like URLs/HTML/punctuation, tokenization, stop-word removal, stemming, or lemmatization). Those techniques are designed for natural language — sentences, paragraphs, documents written by humans.
>
> Build logs are **machine-generated structured output**, not natural language. Applying NLP normalization would destroy the very signals we need (e.g., lowercasing would lose `FATAL ERROR` vs `fatal error` distinction in some contexts, stemming `"compilation"` to `"compil"` would hurt embedding quality, and removing "stop words" could strip important log tokens like `"not"` in `"module not found"`).

**Our normalization is build-log-specific structural cleaning** — it removes noise that is unique to CI/CD log output while preserving the actual error signal:

| Step | What it does | Why it matters |
|------|-------------|----------------|
| Strip `Line NNN:` prefixes | Remove log-extraction line number markers (e.g., `Line 42: FATAL ERROR...` → `FATAL ERROR...`) | These are artifacts of our log-extraction service, not part of the actual error — they add noise to embeddings |
| Remove empty lines | Drop whitespace-only lines | Build logs are full of blank separator lines — they waste embedding tokens without adding meaning |
| Deduplicate | Keep first occurrence of each unique line only | Build logs often repeat the same error hundreds of times (e.g., a compiler warning repeated per file). Duplicates inflate the embedding toward that single repeated message |
| Prioritize error signals | Move lines containing error keywords (`error`, `fail`, `fatal`, `exception`, `traceback`, etc.) to the top | Embedding models weight earlier tokens more heavily. By putting error-signal lines first, the embedding is driven by actual errors rather than pages of `"Installing package X..."` setup noise |
| Cap length | 80 lines / 4000 chars max | Prevents the "hub effect" — without a cap, a 500-line log produces a generic embedding that sits near the center of the vector space and falsely matches everything |

**Why this works better than NLP normalization:**

```
NLP normalization on a build log:
  Input:  "FATAL ERROR: heap out of memory at 0x7fff5fbff8c0"
  After:  "fatal error heap memori 0x7fff5fbff8c0"    ← stemmed, lowered, stop-words removed
  Result: Worse embedding — "memori" is not a real token, loses semantic meaning

Our normalization on a build log:
  Input:  "Line 450: FATAL ERROR: heap out of memory at 0x7fff5fbff8c0"
  After:  "FATAL ERROR: heap out of memory at 0x7fff5fbff8c0"    ← only stripped line prefix
  Result: Clean, meaningful text — embedding model understands "heap out of memory" perfectly
```

**Critical detail:** Normalization runs on **both save and lookup** sides. This ensures the same transformation is applied consistently:

```
Save:  raw error log → normalize → embed → store in ChromaDB
Query: raw error log → normalize → embed → compare against stored embeddings

If only one side normalized, embeddings would be in different "spaces"
and similarity scores would be unreliable.
```

**Benefits of this approach:**

1. **Preserves semantic meaning** — the embedding model receives clean, meaningful error text instead of noisy log output
2. **Reduces dimensionality collapse** — shorter, focused text produces precise embeddings instead of generic "center of space" vectors
3. **Handles real-world log variation** — the same error from different CI systems (Jenkins, GitHub Actions, GitLab CI) may have different line prefixes, whitespace, and surrounding context, but after normalization they converge to the same core error text
4. **Idempotent** — normalizing already-normalized text produces the same result, so it's safe to apply multiple times

### Combined Effect — Before vs After

| Scenario | Before (broken) | After (fixed) |
|----------|-----------------|---------------|
| Short query vs huge stored entry | 0.82 → **wrong fix returned** | 0.47 → **correctly rejected by penalty** |
| Short query vs correct short entry | 0.80 → correct match | 0.78 → **correct match (unchanged)** |
| Error buried in test output | 0.71 → **missed** | 0.92 → **matched (normalization extracted error)** |
| Same error, different context | May mismatch | **Correct match (normalization focuses on error signal)** |

### What Happens When an Identical Error Occurs Again?

One of the most common scenarios: a build fails with the **exact same error** that was previously resolved and stored in ChromaDB. Here's the complete search flow:

```
┌──────────────────────────────────────────────────────────────┐
│  INCOMING: "ERROR: gcc compilation failed                     │
│            /src/main.c:42: undefined reference to 'pthread'"  │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  STEP 1: AI Cache Check (Redis)                               │
│                                                               │
│  Hash the error text → check Redis key "ai:fix:<hash>"        │
│                                                               │
│  If the EXACT same text was recently resolved by LLM,         │
│  the fix is cached here. Returns immediately.                 │
│                                                               │
│  Cache HIT  → return fix (source: "ai_cache") → DONE         │
│  Cache MISS → continue to Step 2                              │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  STEP 2: Normalize the error text                             │
│                                                               │
│  Strip "Line NNN:" prefixes → remove empty lines →            │
│  deduplicate → prioritize error keywords → cap length         │
│                                                               │
│  Input:  "Line 42: ERROR: gcc compilation failed\n            │
│           Line 43: /src/main.c:42: undefined reference..."    │
│  Output: "ERROR: gcc compilation failed\n                     │
│           /src/main.c:42: undefined reference to 'pthread'"   │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  STEP 3: Embed the normalized text                            │
│                                                               │
│  Send normalized text to Ollama (granite-embedding model)     │
│  → Returns a 768-dimension float vector                       │
│                                                               │
│  For identical error text, the embedding will be              │
│  IDENTICAL to what was stored (deterministic model)           │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  STEP 4: Query ChromaDB (top-k=5 candidates)                  │
│                                                               │
│  ChromaDB computes cosine distance between query embedding    │
│  and all stored embeddings. Returns top 5 closest matches.    │
│                                                               │
│  For an IDENTICAL error:                                      │
│    cosine distance ≈ 0.0 → raw_similarity ≈ 1.0              │
│    (perfect or near-perfect match)                            │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  STEP 5: Apply Length Penalty                                  │
│                                                               │
│  For an identical error, stored_len ≈ query_len               │
│    ratio = max(120, 120) / min(120, 120) = 1.0               │
│    penalty = 1 / (1 + 0.15 × ln(1.0)) = 1 / (1 + 0) = 1.0  │
│    adjusted_similarity = 1.0 × 1.0 = 1.0                     │
│                                                               │
│  The penalty has ZERO effect on identical-length entries.      │
│  This is by design — the penalty only activates for           │
│  length mismatches.                                           │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  STEP 6: Threshold Check                                      │
│                                                               │
│  adjusted_similarity (1.0) ≥ threshold (0.78) → MATCH!       │
│                                                               │
│  Return: {                                                    │
│    fix_text: "Add -lpthread to LDFLAGS",                      │
│    confidence: 1.0,                                           │
│    source: "vector_db"                                        │
│  }                                                            │
│                                                               │
│  → Fix returned instantly, NO LLM call needed                 │
└──────────────────────────────────────────────────────────────┘
```

**Key takeaway:** When the same error occurs again, the system returns the stored fix with near-perfect confidence (~1.0) and zero length penalty. The fix is returned directly from ChromaDB without calling the LLM, making the response **fast** (milliseconds vs seconds) and **consistent** (same error always gets the same approved fix).

**What about "almost identical" errors?**

Real-world builds rarely produce *byte-for-byte identical* errors. More commonly, the same root cause produces slightly different text (different file paths, line numbers, timestamps). Here's how that plays out:

```
Stored:  "ERROR: gcc compilation failed\n/src/main.c:42: undefined reference to 'pthread_create'"
Query:   "ERROR: gcc compilation failed\n/src/utils.c:15: undefined reference to 'pthread_create'"

After normalization: both are clean, similar-length text
Embedding similarity: ~0.95 (very high — same error pattern, different file/line)
Length ratio: ~1.0 (similar length after normalization)
Penalty: ~1.0 (no penalty)
Adjusted similarity: ~0.95 → well above 0.78 threshold → CORRECT MATCH
```

This is where normalization shines — by stripping noise and focusing on error signals, two instances of the same root cause produce highly similar embeddings even when the surrounding context differs.

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
