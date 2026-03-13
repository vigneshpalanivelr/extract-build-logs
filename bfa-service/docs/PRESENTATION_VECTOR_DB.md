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

---

## 6. Proposed Enhancements

### Current Gaps

| Gap | Impact | Priority |
|-----|--------|----------|
| No fix versioning — updates overwrite previous fixes | If a wrong edit is made, the original fix is lost forever | High |
| No team/domain segregation — all fixes in a single flat collection | A DevOps fix for "permission denied" could match a Security team's "permission denied" (different root cause, different fix) | High |
| No fix lifecycle management — no way to deprecate, expire, or supersede fixes | Outdated fixes (e.g., for deprecated tools) remain active and get returned forever | Medium |
| No confidence feedback loop — no tracking of whether returned fixes actually helped | System can't learn which fixes work and which don't | Medium |
| No conflict detection — two similar errors can have contradicting fixes | SMEs may approve conflicting fixes without knowing | Medium |

---

### Enhancement 1: Fix Versioning & Edit History

**Problem:** When an SME updates a fix via `PUT /api/fixes/{id}` or Slack Edit, the previous fix text is overwritten. If the new fix is wrong, the original is lost. There's no way to answer "what was the fix before someone changed it?"

**Proposed Solution: Append-Only Version Log**

Store a version history array in metadata for every fix. Each edit appends a version entry rather than overwriting.

```
Current behavior (destructive):
  fix_text: "Add -lpthread"  →  PUT update  →  fix_text: "Add -pthread"
  (original "Add -lpthread" is GONE)

Proposed behavior (versioned):
  fix_text: "Add -pthread"              ← current/active version
  metadata.versions: [                  ← append-only history
    {
      "version": 1,
      "fix_text": "Add -lpthread",
      "edited_by": "alice",
      "timestamp": "2026-03-10 14:30:00",
      "reason": "Initial SME approval"
    },
    {
      "version": 2,
      "fix_text": "Add -pthread",
      "edited_by": "bob",
      "timestamp": "2026-03-13 09:15:00",
      "reason": "Updated: -lpthread is deprecated, use -pthread"
    }
  ]
```

**New API Endpoints:**

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/fixes/{id}/history` | List all versions of a fix |
| POST | `/api/fixes/{id}/revert/{version}` | Revert to a specific version (creates new version entry) |

**Benefits:**
- Full audit trail — know who changed what and when
- Safe rollback — revert bad edits without losing anything
- Accountability — SMEs can see the evolution of a fix over time

**Implementation Note:** ChromaDB metadata must be flat primitives, so the version array would be stored as a JSON string in a `versions` metadata field and parsed on read.

---

### Enhancement 2: Fix Domain Segregation

**Problem:** All fixes live in a single flat ChromaDB collection. A "permission denied" error in a Docker build (DevOps domain) and a "permission denied" error in an API gateway (IT domain) are completely different problems with different fixes — but they match each other with high similarity because the error text is nearly identical.

**Proposed Solution: Domain-Scoped Fix Search with Metadata Filtering**

Every fix is tagged with a **Fix Domain** — the domain of expertise the fix belongs to. This domain is set during Slack approval (see Enhancement 6 for the Slack flow) and used as a ChromaDB `where` filter at query time.

#### Fix Domain Values

| Fix Domain | Scope | Example Errors |
|------------|-------|---------------|
| `Product` | Application code, frontend/backend, business logic | Compilation errors, test failures, runtime exceptions |
| `DevOps` | CI/CD pipelines, Docker, Kubernetes, infrastructure | Build failures, container errors, deployment issues |
| `IT` | Internal tooling, network, access management | VPN errors, proxy failures, certificate issues |

> **Note:** Additional domains (e.g., `Security`, `Data`, `Platform`) can be added later by updating the Slack dropdown options and domain-inference rules. Starting with three keeps the SME workflow simple.

#### How Domain Filtering Works

```
Store (on Slack Approve/Edit):
  fix_text: "Run chmod +x on the deploy script"
  metadata: {
    error_text: "permission denied: ./deploy.sh",
    fix_domain: "DevOps",            ← set by SME via Slack dropdown
    ...
  }

Query (on /api/analyze):
  error_text: "permission denied: ./deploy.sh"
  where: { "fix_domain": "DevOps" }  ← ChromaDB where clause
  → Only DevOps fixes are searched
```

#### Query Flow with Domain Filtering

```
┌──────────────────────────────────────────────────────┐
│  INCOMING ERROR                                       │
│  error_text: "permission denied: ./deploy.sh"         │
│  metadata: { repo: "infra/deploy-scripts",            │
│              job_name: "deploy-staging" }              │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│  STEP 1: DETERMINE FIX DOMAIN                        │
│                                                       │
│  Priority order:                                      │
│    1. Explicit domain from CI config / API payload    │
│       (e.g., payload.fix_domain = "DevOps")           │
│    2. Auto-infer from pipeline metadata:              │
│       - repo contains "infra/" → DevOps               │
│       - job_name contains "deploy" → DevOps           │
│       - step_name contains "unit-test" → Product      │
│       - job_name contains "vpn" or "proxy" → IT       │
│    3. LLM auto-classification (Enhancement 6)         │
│    4. Fallback: search ALL domains (no filter)        │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│  STEP 2: SCOPED QUERY                                 │
│                                                       │
│  collection.query(                                    │
│    query_embeddings=[vector],                         │
│    n_results=5,                                       │
│    where={"fix_domain": "DevOps"}                     │
│  )                                                    │
│                                                       │
│  Only DevOps fixes are evaluated as candidates.       │
│  IT domain's "permission denied" fix is NEVER         │
│  even compared — eliminating cross-domain             │
│  false positives entirely.                            │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│  STEP 3: CROSS-DOMAIN FALLBACK                        │
│                                                       │
│  If scoped query returns no match above threshold:    │
│    → Retry WITHOUT domain filter (search all)         │
│    → If match found, return it with a flag:           │
│      "cross_domain_match": true                       │
│                                                       │
│  This handles:                                        │
│    - Fixes tagged under wrong domain                  │
│    - New domain that doesn't have fixes yet           │
│    - Generic errors that span domains                 │
└──────────────────────────────────────────────────────┘
```

#### Approach B: Separate Collections per Domain (For Scale)

If the fix database grows large (1000+ fixes per domain), separate ChromaDB collections provide better query performance:

```
Collections:
  fix_embeddings_product     ← Product fixes only
  fix_embeddings_devops      ← DevOps fixes only
  fix_embeddings_it          ← IT fixes only
  fix_embeddings_global      ← Cross-domain / untagged fixes
```

**Recommendation:** Start with metadata filtering (Approach A). Migrate to separate collections only if performance degrades.

#### New/Updated API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/fixes?fix_domain=DevOps` | List fixes filtered by domain |
| PUT | `/api/fixes/{id}` | Update fix including domain reassignment |
| GET | `/api/domains` | List all fix domains with counts |
| GET | `/api/domains/{domain}/stats` | Stats per domain: total fixes, avg confidence, top errors |

#### Changes to `lookup_existing_fix()`

```
New parameter: fix_domain (optional str)

def lookup_existing_fix(self, error_text, top_k=5, fix_domain=None, ...):
    ...
    query_kwargs = {
        "query_embeddings": [vector],
        "n_results": top_k,
        "include": ["metadatas", "documents", "distances"],
    }
    if fix_domain:
        query_kwargs["where"] = {"fix_domain": fix_domain}

    res = self.collection.query(**query_kwargs)
    ...
    # If no match and fix_domain was set → retry without filter
    if not candidates and fix_domain:
        return self.lookup_existing_fix(error_text, top_k=top_k, fix_domain=None, ...)
```

---

### Enhancement 3: Fix Lifecycle Management

**Problem:** Fixes never expire. A fix approved for Node.js 14 remains active even after the team migrates to Node.js 20. Outdated fixes get returned and confuse developers.

**Proposed Solution: Fix States with Lifecycle Transitions**

```
                  ┌──────────┐
                  │  ACTIVE   │ ← Default state after approval
                  └─────┬────┘
                        │
          ┌─────────────┼─────────────┐
          │             │             │
          ▼             ▼             ▼
   ┌────────────┐ ┌──────────┐ ┌────────────┐
   │ DEPRECATED │ │ SUPERSEDED│ │  ARCHIVED  │
   │            │ │           │ │            │
   │ Still      │ │ Replaced  │ │ Fully      │
   │ returned   │ │ by newer  │ │ hidden     │
   │ but with   │ │ fix — new │ │ from       │
   │ warning    │ │ fix is    │ │ search     │
   │ label      │ │ returned  │ │ results    │
   └────────────┘ └───────────┘ └────────────┘
```

| State | Visible in Search? | Returned to Developers? | Use Case |
|-------|--------------------|------------------------|----------|
| `active` | Yes | Yes (normal) | Current, valid fix |
| `deprecated` | Yes | Yes, with warning: "This fix may be outdated" | Tool/version changed but fix might still work |
| `superseded` | Yes (for audit) | No — the superseding fix is returned instead | Better fix discovered, old one replaced |
| `archived` | No | No | Completely irrelevant (e.g., deleted repo, retired service) |

**New API Endpoints:**

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/fixes/{id}/deprecate` | Mark fix as deprecated (with optional reason) |
| POST | `/api/fixes/{id}/supersede` | Mark fix as superseded, link to new fix ID |
| POST | `/api/fixes/{id}/archive` | Archive fix (remove from search results) |
| POST | `/api/fixes/{id}/activate` | Reactivate a deprecated/archived fix |

---

### Enhancement 4: Confidence Feedback Loop

**Problem:** The system returns fixes but never learns whether they actually helped. A fix with 0.85 confidence might be wrong 50% of the time, but there's no mechanism to track this.

**Proposed Solution: Developer Feedback + Confidence Adjustment**

```
Current flow (open loop):
  Error → Fix returned → Developer receives fix → ???
  (System never learns if the fix worked)

Proposed flow (closed loop):
  Error → Fix returned → Developer receives fix
                              │
                              ▼
                     ┌─────────────────┐
                     │ Did this help?   │
                     │ [👍 Yes] [👎 No] │
                     └────────┬────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
              Increment            Increment
              success_count        failure_count
                    │                   │
                    └─────────┬─────────┘
                              │
                              ▼
                    Compute effectiveness:
                    score = successes / (successes + failures)

                    If score < 0.5 after 10+ ratings:
                      → Flag for SME review
                      → Reduce similarity boost (less likely to be returned)
```

**New Metadata Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success_count` | int | Times developers confirmed this fix helped |
| `failure_count` | int | Times developers said this fix didn't help |
| `effectiveness_score` | float | success / (success + failure), updated on each vote |
| `last_feedback_at` | string | Timestamp of most recent feedback |
| `flagged_for_review` | bool | Auto-set when effectiveness drops below threshold |

**New API Endpoints:**

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/fixes/{id}/feedback` | Submit thumbs-up/thumbs-down feedback |
| GET | `/api/fixes/flagged` | List fixes flagged for review (low effectiveness) |
| GET | `/api/fixes/stats` | Overall system stats: accuracy rate, top-performing fixes, worst-performing fixes |

---

### Enhancement 5: Conflict Detection

**Problem:** Two SMEs might approve contradicting fixes for similar errors. Error A: "ENOMEM: heap out of memory" → Fix 1: "Increase Node memory" and Fix 2: "Fix memory leak in module X". Both are stored, and which one gets returned depends on which embedding is slightly closer — essentially random.

**Proposed Solution: Pre-Save Conflict Check with Slack Resolution Flow**

#### When Conflict Detection Triggers

Conflict detection runs **before** saving to ChromaDB — during Slack Approve or Edit actions. It checks whether a similar error already has a different fix stored.

```
CONFLICT_SIMILARITY_THRESHOLD = 0.85  (higher than search threshold of 0.78)
```

#### Complete Conflict Detection Flow

```
┌──────────────────────────────────────────────────────────┐
│  SME clicks [Approve] or submits [Edit] in Slack          │
│                                                           │
│  New fix:                                                 │
│    error_text: "ENOMEM: heap out of memory"               │
│    fix_text: "Fix memory leak in module X"                 │
│    fix_domain: "Product"                                   │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 1: PRE-SAVE SIMILARITY CHECK                        │
│                                                           │
│  Before saving, query ChromaDB:                           │
│    - Normalize + embed the new error_text                 │
│    - Search with CONFLICT threshold (0.85)                │
│    - Filter by same fix_domain if set                     │
│                                                           │
│  Query: collection.query(                                 │
│    query_embeddings=[new_embedding],                      │
│    n_results=3,                                           │
│    where={"fix_domain": "Product"}                        │
│  )                                                        │
└──────────────────────┬───────────────────────────────────┘
                       │
              ┌────────┴────────┐
              │                 │
        No matches         Matches found
        above 0.85         (similarity > 0.85)
              │                 │
              ▼                 ▼
┌──────────────────┐  ┌────────────────────────────────────┐
│  NO CONFLICT      │  │  STEP 2: COMPARE FIX TEXTS          │
│                   │  │                                      │
│  Save normally    │  │  Existing fix: "Increase Node memory │
│  to ChromaDB      │  │    NODE_OPTIONS=--max-old-space=4096"│
│  (current flow)   │  │  New fix: "Fix memory leak in        │
│                   │  │    module X — see PR #1234"           │
│  → Approve msg    │  │                                      │
│  → DM developer   │  │  Are these semantically different?   │
└──────────────────┘  │  Use simple heuristic:                │
                      │    - Jaccard similarity of fix words   │
                      │    - If word overlap < 40% → CONFLICT │
                      │    - If word overlap > 70% → SIMILAR  │
                      │      (likely same fix, minor edit)     │
                      └────────────────┬───────────────────────┘
                                       │
                              ┌────────┴────────┐
                              │                 │
                        Word overlap        Word overlap
                        < 40%               > 70%
                        (CONFLICT)          (SIMILAR)
                              │                 │
                              ▼                 ▼
┌──────────────────────────────────┐  ┌─────────────────────┐
│  STEP 3: POST CONFLICT ALERT     │  │  NO CONFLICT         │
│  IN SLACK THREAD                  │  │                      │
│                                   │  │  Treat as update to  │
│  Bot replies in the same thread:  │  │  existing fix.       │
│                                   │  │  Save normally.      │
│  ⚠️ *Conflict Detected*           │  └─────────────────────┘
│                                   │
│  A similar error already has a    │
│  different fix in the database:   │
│                                   │
│  *Existing fix (by @alice):*      │
│  > Increase Node memory:          │
│  > NODE_OPTIONS=--max-old-space   │
│                                   │
│  *Your new fix:*                  │
│  > Fix memory leak in module X    │
│                                   │
│  Similarity: 0.92                 │
│                                   │
│  ┌───────────┐ ┌──────────────┐   │
│  │ Replace   │ │ Keep Both    │   │
│  │ Existing  │ │              │   │
│  └───────────┘ └──────────────┘   │
│  ┌───────────┐ ┌──────────────┐   │
│  │ Cancel    │ │ Merge        │   │
│  │           │ │              │   │
│  └───────────┘ └──────────────┘   │
└──────────────────┬────────────────┘
                   │
     SME clicks one of the 4 buttons
                   │
     ┌─────────┬───┴────┬──────────┐
     │         │        │          │
     ▼         ▼        ▼          ▼
  Replace   Keep Both  Cancel    Merge
     │         │        │          │
     ▼         ▼        ▼          ▼
┌─────────┐┌────────┐┌────────┐┌────────────────────┐
│ Old fix  ││ Both   ││ New    ││ Bot prompts SME    │
│ marked   ││ fixes  ││ fix    ││ to reply in thread │
│ as       ││ saved  ││ NOT    ││ with merged fix    │
│ "super-  ││ to DB  ││ saved  ││ text.              │
│ seded"   ││        ││        ││                    │
│ (life-   ││ System ││ Orig   ││ On reply: save     │
│ cycle    ││ returns││ approve││ merged fix, mark   │
│ change)  ││ higher ││ stands ││ BOTH old entries   │
│          ││ confi- ││        ││ as "superseded"    │
│ New fix  ││ dence  ││        ││ by merged fix      │
│ saved as ││ match  ││        ││                    │
│ active   ││        ││        ││                    │
└─────────┘└────────┘└────────┘└────────────────────┘
```

#### Conflict Resolution Options

| Action | What happens | When to use |
|--------|-------------|-------------|
| **Replace existing** | Old fix → `superseded` state (Enhancement 3). New fix saved as `active`. Old fix no longer returned in searches. | The new fix is clearly better or more accurate |
| **Keep both** | Both fixes stored as `active`. System returns whichever has higher adjusted similarity for a given query. | Both fixes are valid for different sub-cases of the same error (e.g., OOM in Node vs OOM in Docker) |
| **Cancel** | New fix is NOT saved. Original approval/edit is abandoned. Existing fix remains unchanged. | SME realizes the existing fix is already correct |
| **Merge** | Bot prompts SME to reply in thread with a combined fix. On reply: merged fix is saved, both original entries marked `superseded`. | Both fixes have useful information that should be combined into one comprehensive fix |

#### Conflict Detection Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CONFLICT_SIMILARITY_THRESHOLD` | `0.85` | Minimum similarity to trigger conflict check (higher than search threshold) |
| `CONFLICT_FIX_OVERLAP_LOW` | `0.40` | Below this word overlap → definitely a conflict |
| `CONFLICT_FIX_OVERLAP_HIGH` | `0.70` | Above this word overlap → probably same fix, no conflict |

#### Changes Required

| File | Change |
|------|--------|
| `vector_db.py` | Add `check_conflicts()` method — query + compare fix texts |
| `analyzer_service.py` | In `/bfa/slack/actions` approve handler — call `check_conflicts()` before `save_fix_to_db()` |
| `slack_helper.py` | Add `build_conflict_block()` — constructs the conflict alert message with 4 resolution buttons |
| `analyzer_service.py` | Add conflict resolution action handlers (`replace_`, `keepboth_`, `cancel_`, `merge_`) |

---

### Enhancement 6: Fix Domain Tagging via Slack Approval Flow

**Problem:** For domain-scoped search (Enhancement 2) to work, every fix needs a `fix_domain` tag. Requiring SMEs to manually type this is tedious and error-prone. We need it to be part of the natural approval flow — not an extra step.

**Proposed Solution: Fix Domain Dropdown in Slack + LLM Auto-Suggestion**

The Slack message that posts a fix for review will include a **Fix Domain** dropdown alongside the existing Approve/Edit/Discard buttons. The LLM pre-selects a suggested domain, but the SME can override before approving.

#### Updated Slack Message Layout

```
Current Slack message:
┌──────────────────────────────────────────────────┐
│  *Error Summary (ID: abc123)*                     │
│  • gcc compilation failed                         │
│  • undefined reference to 'pthread_create'        │
│                                                   │
│  *Pipeline:* pipeline-456                         │
│  *Repo:* infra/deploy-scripts                     │
│  *Branch:* main                                   │
│                                                   │
│  *Suggested Fix:*                                 │
│  Add -lpthread to LDFLAGS in the Makefile...      │
│                                                   │
│  [Approve]  [Edit]  [Discard]                     │
└──────────────────────────────────────────────────┘

Proposed Slack message (with Fix Domain):
┌──────────────────────────────────────────────────┐
│  *Error Summary (ID: abc123)*                     │
│  • gcc compilation failed                         │
│  • undefined reference to 'pthread_create'        │
│                                                   │
│  *Pipeline:* pipeline-456                         │
│  *Repo:* infra/deploy-scripts                     │
│  *Branch:* main                                   │
│                                                   │
│  *Suggested Fix:*                                 │
│  Add -lpthread to LDFLAGS in the Makefile...      │
│                                                   │
│  Fix Domain: [DevOps ▼]  ← static_select dropdown│
│                            (LLM pre-selected)     │
│                                                   │
│  [Approve]  [Edit]  [Discard]                     │
└──────────────────────────────────────────────────┘
```

#### Slack Block Kit Implementation

The Fix Domain dropdown uses Slack's `static_select` element in a `section` block, placed between the fix content and the action buttons:

```
Fix Domain dropdown block:
{
  "type": "section",
  "block_id": "fix_domain_<error_id>",
  "text": {
    "type": "mrkdwn",
    "text": "*Fix Domain:*"
  },
  "accessory": {
    "type": "static_select",
    "action_id": "fix_domain_select_<error_id>",
    "placeholder": {
      "type": "plain_text",
      "text": "Select domain..."
    },
    "initial_option": {                    ← LLM-suggested default
      "text": { "type": "plain_text", "text": "DevOps" },
      "value": "DevOps"
    },
    "options": [
      {
        "text": { "type": "plain_text", "text": "Product" },
        "value": "Product"
      },
      {
        "text": { "type": "plain_text", "text": "DevOps" },
        "value": "DevOps"
      },
      {
        "text": { "type": "plain_text", "text": "IT" },
        "value": "IT"
      }
    ]
  }
}

Updated blocks array:
  [summary_block]
  + [context_block]
  + [fix_content_blocks...]
  + [fix_domain_dropdown_block]    ← NEW
  + [action_buttons_block]
```

#### Complete Flow: From Error to Domain-Tagged Fix

```
┌──────────────────────────────────────────────────────────┐
│  PHASE 1: ERROR ARRIVES (/api/analyze)                    │
│                                                           │
│  1. ResolverAgent generates fix via LLM                   │
│  2. BEFORE posting to Slack, ask LLM to classify domain:  │
│                                                           │
│     Prompt: "Given this error and fix, classify the       │
│     fix domain as one of: Product, DevOps, IT             │
│                                                           │
│     Error: gcc compilation failed...                      │
│     Fix: Add -lpthread to LDFLAGS...                      │
│                                                           │
│     Respond with ONLY the domain name."                   │
│                                                           │
│  3. LLM responds: "DevOps"                                │
│  4. Store suggested domain in Redis alongside fix:        │
│     fix:<error_id> → { ..., suggested_domain: "DevOps" }  │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  PHASE 2: POST TO SLACK                                   │
│                                                           │
│  send_error_message() builds blocks with:                 │
│    - Error summary (existing)                             │
│    - Pipeline context (existing)                          │
│    - Fix content (existing)                               │
│    - Fix Domain dropdown (NEW) ← pre-set to "DevOps"     │
│    - Approve/Edit/Discard buttons (existing)              │
│                                                           │
│  SME sees the message and can:                            │
│    a) Accept the suggested domain (just click Approve)    │
│    b) Change domain via dropdown THEN click Approve       │
│    c) Click Edit (domain selection preserved)             │
│    d) Click Discard (domain irrelevant)                   │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  PHASE 3: SME CHANGES DOMAIN (optional)                   │
│                                                           │
│  If SME selects a different domain from dropdown:         │
│    → Slack fires action: fix_domain_select_<error_id>     │
│    → /bfa/slack/actions handler catches this action       │
│    → Updates Redis: fix:<error_id>.fix_domain = "Product" │
│    → NO message update needed (dropdown already shows     │
│      the new selection in Slack UI)                       │
│                                                           │
│  This is a "soft" action — no save, no approval.          │
│  Just records the SME's domain choice for when they       │
│  eventually click Approve.                                │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  PHASE 4: SME CLICKS APPROVE                              │
│                                                           │
│  /bfa/slack/actions handler:                              │
│                                                           │
│  1. Read fix_domain from Redis (set by Phase 1 or 3):    │
│     fix_domain = redis.get(fix:<error_id>).fix_domain     │
│     → "Product" (if SME changed it) or "DevOps" (default)│
│                                                           │
│  2. Run conflict detection (Enhancement 5):               │
│     check_conflicts(error_text, fix_text, fix_domain)     │
│     → If conflict: post conflict resolution buttons       │
│     → If no conflict: continue to step 3                  │
│                                                           │
│  3. Save to ChromaDB WITH domain:                         │
│     db.save_fix_to_db(                                    │
│       error_text=error_text,                              │
│       fix_text=fix_text,                                  │
│       approver=approver,                                  │
│       status="approved",                                  │
│       metadata={                                          │
│         "source": "slack",                                │
│         "fix_domain": fix_domain,     ← DOMAIN SAVED     │
│         "approved_by": approver,                          │
│         "timestamp": "2026-03-13 10:30:00",               │
│       }                                                   │
│     )                                                     │
│                                                           │
│  4. Update Slack message:                                 │
│     "Approved by @bob | Fix Domain: DevOps"               │
│                                                           │
│  5. DM developer with fix + domain tag                    │
└──────────────────────────────────────────────────────────┘
```

#### Edit Flow with Domain

```
┌──────────────────────────────────────────────────────────┐
│  SME clicks [Edit]                                        │
│                                                           │
│  1. Bot prompts: "Please reply in thread with updated fix"│
│  2. SME replies with new fix text in thread                │
│  3. /bfa/slack/events handler captures the reply          │
│  4. Reads fix_domain from Redis (set during Phase 1 or 3) │
│  5. Saves to ChromaDB with status="edited" + fix_domain   │
│  6. DM developer with edited fix + domain tag             │
└──────────────────────────────────────────────────────────┘
```

#### LLM Auto-Classification Prompt

```
System: You are a build failure classifier. Given a CI/CD error and its fix,
classify the Fix Domain as exactly one of: Product, DevOps, IT

Rules:
- Product: Application code issues — compilation errors, test failures,
  dependency conflicts, runtime exceptions, code-level bugs
- DevOps: Infrastructure and pipeline issues — Docker/container errors,
  deployment failures, CI config problems, resource limits (OOM, disk),
  Kubernetes issues, build tool configuration
- IT: Internal tooling and access issues — VPN/proxy errors, certificate
  problems, network connectivity, access permissions, SSO/auth failures

Respond with ONLY the domain name. No explanation.

User:
Error: {error_text}
Fix: {fix_text}
```

#### Manual API Support

For fixes added via `POST /api/vector/manual-fix` or bulk import, the `fix_domain` field is accepted as an optional parameter:

```
POST /api/vector/manual-fix
{
  "error_text": "permission denied: ./deploy.sh",
  "fix_text": "Run chmod +x on the deploy script",
  "fix_domain": "DevOps",        ← explicit domain
  "approver": "admin"
}
```

If `fix_domain` is omitted, the LLM auto-classification runs as a background step after save.

#### Changes Required

| File | Change |
|------|--------|
| `slack_helper.py` | Add `build_fix_domain_block(error_id, suggested_domain)` — builds the dropdown block |
| `slack_helper.py` | Update `send_error_message()` — insert domain block before action buttons |
| `analyzer_service.py` | In `/api/analyze` — call LLM to classify domain before posting to Slack |
| `analyzer_service.py` | In `/bfa/slack/actions` — handle `fix_domain_select_*` action (store to Redis) |
| `analyzer_service.py` | In `/bfa/slack/actions` approve handler — read `fix_domain` from Redis, pass to `save_fix_to_db()` |
| `analyzer_service.py` | In `/bfa/slack/events` edit handler — read `fix_domain` from Redis, pass to `save_fix_to_db()` |
| `vector_db.py` | `save_fix_to_db()` — store `fix_domain` in metadata (already supported via flat metadata) |
| `resolver_agent.py` | Add `classify_fix_domain()` method — LLM prompt for domain classification |

---

### Enhancement Summary

| # | Enhancement | Effort | Impact | Depends On |
|---|------------|--------|--------|------------|
| 1 | **Fix Versioning & Edit History** | Medium | High — prevents data loss, enables safe edits | None |
| 2 | **Fix Domain Segregation** | Medium | High — eliminates cross-domain false positives | Enhancement 6 (domain tagging) |
| 3 | **Fix Lifecycle Management** | Low | Medium — handles stale fixes gracefully | None |
| 4 | **Confidence Feedback Loop** | Medium | Medium — system improves over time | None |
| 5 | **Conflict Detection** | Medium | High — prevents contradicting fixes, with Slack resolution | Enhancement 3 (lifecycle for "superseded" state) |
| 6 | **Fix Domain Tagging via Slack** | Medium | High — enables domain segregation via natural approval flow | None |

**Recommended Implementation Order:**

```
Phase 1 (Immediate):
  Enhancement 6 (Fix Domain Tagging via Slack)
  + Enhancement 2 (Fix Domain Segregation)
  → Add Fix Domain dropdown to Slack approval flow
  → Add domain-scoped ChromaDB queries
  → Together: SME selects domain on approve → lookup scoped by domain
  → Eliminates cross-domain false positives (e.g., DevOps vs IT "permission denied")

Phase 2 (Short-term):
  Enhancement 5 (Conflict Detection)
  + Enhancement 3 (Fix Lifecycle Management)
  → Conflict detection needs lifecycle states (superseded) for "Replace" action
  → Together: detect conflicts on save → resolve via Slack buttons → manage fix states

Phase 3 (Medium-term):
  Enhancement 1 (Fix Versioning)
  + Enhancement 4 (Confidence Feedback Loop)
  → Version history for safe rollbacks
  → Developer feedback to identify low-quality fixes
  → Together: track fix evolution + measure fix effectiveness over time
```

**Phase 1 Implementation Checklist:**

```
Files to modify:
  □ slack_helper.py
    - Add build_fix_domain_block()
    - Update send_error_message() to include domain dropdown

  □ resolver_agent.py
    - Add classify_fix_domain() — LLM classification prompt

  □ analyzer_service.py
    - /api/analyze: call classify_fix_domain(), store in Redis
    - /bfa/slack/actions: handle fix_domain_select_* action
    - /bfa/slack/actions approve: read fix_domain, pass to save_fix_to_db()
    - /bfa/slack/events edit: read fix_domain, pass to save_fix_to_db()

  □ vector_db.py
    - lookup_existing_fix(): add fix_domain parameter + where clause
    - Add cross-domain fallback when scoped search returns no match

  □ config_loader.py
    - Add FIX_DOMAINS list config (default: ["Product", "DevOps", "IT"])
```
