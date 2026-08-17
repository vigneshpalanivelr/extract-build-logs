# Presenting the Hybrid Proposal — Speaker Notes

A walkthrough script for presenting `HYBRID_PROPOSAL.md` to the team,
with anticipated questions and prepared answers for each section.

This is **your** preparation document. Not for the team meeting itself.

Recommended meeting length: 45 minutes. 25 min walkthrough, 15 min
Q&A, 5 min decisions / next steps.

---

## How to open the meeting (3 minutes)

### 1. Frame the meeting goal in one sentence

> "I want to walk you through a proposed redesign of the
> build-failure-analyzer to fix the wrong-fix issue we've been seeing,
> and get your sign-off on the approach before I start implementation."

### 2. Briefly remind the team of the symptom

> "For the last few days, the analyzer has been returning the same fix
> for unrelated errors. A developer with an npm peer-dep failure gets
> the same advice as someone with a Maven artifact-missing failure. It
> looks like the system is broken — and it is, but in a specific way
> that we can fix without throwing the whole thing away."

### 3. Tell them what they need to leave the meeting having decided

Display this list on screen:

> By end of meeting we need decisions on:
> 1. Approve the Hybrid approach (vs Full Agentic / vs Deterministic only)
> 2. Confirm Phase 0 (eval harness) ownership
> 3. Confirm we salvage existing approved fixes via migration
> 4. Confirm A3 `adjusted_fix` review path (developer-direct vs SME re-review)
> 5. Bedrock migration scope — same PR or follow-up?

This puts the team in "decision mode" from minute one rather than
"audience mode".

---

## How to walk through the document (22 minutes)

Don't read the document line by line. Walk the team through these six
beats. Keep your finger on the document so people can scroll along.

### Beat 1 — The problem is structural, not tuning (3 min)

Open `HYBRID_PROPOSAL.md` §3 (Root Cause).

Talking points:
- "There are four bugs. Let me show you each one in code."
- Walk through §3.1 (blob embedding), §3.2 (L2 vs cosine), §3.3
  (salted hash IDs), §3.4 (SHA-of-blob cache).
- After each: "If we just changed the threshold or the model, this
  would still be broken because of *this*."
- Close: "These compound. Fixing any one alone leaves the others
  active. We need to fix all four."

Why open with code: it short-circuits "have you tried adjusting the
similarity threshold?" type questions — the team sees that's not the
problem.

### Beat 2 — The Hybrid design has two layers (5 min)

Jump to `HYBRID_PROPOSAL.md` §4 (Overview) and show the diagram.

Talking points:
- "Layer 1 is deterministic — fixes the four bugs. No LLM. Handles
  about 85% of traffic on its own."
- "Layer 2 is one LLM agent — A3 — that fires only when Layer 1's
  retrieval returns a candidate that's meaningful but not clearly
  exact. About 15% of traffic."
- Show the per-request flow chart in §4.1. Trace it with your finger:
  "Cache hit, done. Clear hit, done. Ambiguous → A3. Miss → LLM.
  Multiple candidates → A3 in parallel."

Anchor sentence: "We pay for the LLM only where pure vector math
isn't enough."

### Beat 3 — Layer 1 details, fast (5 min)

Jump to §5. Walk it as a list, not in depth:
- 5.1 Wire change — split error from context
- 5.2 Normalize before embedding
- 5.3 Cosine + deterministic IDs
- 5.4 Store only the error
- 5.5 Context-cosine for tie-breaking
- 5.6 Update-not-insert on Slack approval

Show §5.7 ("What the foundation alone fixes") — this table is the
key visual. It tells the team "Layer 1 alone gets us 85% of the way
there".

### Beat 4 — Layer 2 (A3): why one agent, not seven (4 min)

Jump to §6.

Talking points:
- "We considered a full multi-agent design — seven agents. We
  rejected it. Six of them are either redundant with deterministic
  code or YAGNI."
- Show §6.1 table — for each candidate agent, why we drop it.
- "A3 is the one where natural-language reasoning beats geometry. It
  reads a new error, a stored error, and a stored fix, and decides
  whether the stored fix applies — and if it needs adjustments, it
  proposes them."
- Show §6.6 examples (the variant table). "Here's where A3 earns its
  cost."

### Beat 5 — Past errors and migration (3 min)

Jump to §7.

Talking points:
- "We don't throw away the existing approved fixes. They're the
  reason the system is economical at all."
- Show §7.2 (preserving them is high-value) — the table comparing
  empty DB vs populated.
- "Migration script drops poisoning rows and duplicates. ~70% of
  existing rows carry over."

### Beat 6 — Phased rollout and what changes (4 min)

Jump to §10 (rollout) and §9 (file changes).

Talking points:
- "Five phases. Each is feature-flagged. Each is revertible in under
  60 seconds."
- "Phase 0 builds the regression harness. Phase 1 lands the
  deterministic foundation. Phase 2 adds A3 in shadow mode. Phase 3
  is 10% rollout. Phase 4 is 100%."
- "About 1,100 lines of new product code, plus 300 lines of tests.
  Two to three weeks for one engineer."

End the walkthrough by jumping to §11 (Open Questions). Read the
seven questions out loud. Tell the team: "These are the decisions I
need from you."

---

## Decision-asks slide (final 2 min before Q&A)

Re-display the same checklist from the opening. Now read each one
and ask for the decision in real time, or at least mark which ones
need follow-up off-meeting.

> 1. Hybrid approach approved? __ yes / __ no / __ defer
> 2. Phase 0 owner? __ name
> 3. Salvage migration approved? __ yes / __ no
> 4. A3 adjusted_fix review path? __ direct / __ SME re-review / __ light thumbs-up
> 5. Bedrock migration in this PR or separate? __ same / __ separate

---

## Anticipated Q&A — quick-reference

The next sections are the answers I would prepare for. Each one maps
to a specific section of HYBRID_PROPOSAL.md so the team can follow
along while you explain.

---

## Anticipated Q&A — group 1: the problem and the bug

### Q1. "Have you tried just adjusting the similarity threshold?"

**Short answer:** Yes, and it doesn't help.

**How to explain:** The threshold (0.78) is interpreting an L2
distance as if it were cosine. When the similarity math is wrong
*and* the embedding is dominated by context noise, no threshold value
works — too low you accept everything, too high you reject everything
including good matches. We have to fix the metric and the embedding,
not the threshold.

Point to: §3.2 (the `1 - dist` line in `vector_db.py:212`).

### Q2. "Why don't we just delete the bad row from the DB?"

**Short answer:** Deleting one row buys us a day, maybe a week. The
underlying bugs cause more bad rows to appear.

**How to explain:** The salted-hash ID (§3.3) means even the same
fix re-approved later inserts a new row. The blob embedding (§3.1)
means any sufficiently large log creates a new poisoning row. We can
delete today's offender, but the bug guarantees another will appear.
The migration script (§7.4) does delete the bad rows — but it also
fixes the bugs that caused them, so they don't come back.

Point to: §3.3 (salted hash), §7.4 (migration script).

### Q3. "How long has this been broken? Why didn't we catch it?"

**Short answer:** ~5–7 days. We didn't catch it because for the first
few days the DB was nearly empty — every request fell through to the
LLM, which gave reasonable fresh answers. The bug only manifests
after a large blob gets stored once. We had no automated regression
suite to detect it; SMEs noticed it manually.

**How to explain:** This is exactly why Phase 0 (eval harness) is
non-negotiable. Without it we have no way to detect this class of
regression early. The 50 seed pairs become pass/fail assertions in
CI.

Point to: §10 Phase 0, §13 Track 1.

### Q4. "Is the LLM the problem? Should we switch models?"

**Short answer:** No. The LLM is fine. The bug is in the retrieval
layer (vector DB), which runs *before* the LLM ever sees a request.

**How to explain:** When retrieval returns the wrong stored fix from
the vector DB, the analyzer believes it's a high-confidence match and
returns it directly — the LLM is never consulted. So no LLM swap can
fix this. The Hybrid design fixes retrieval first; LLM behavior is
unchanged.

### Q5. "How big is the affected DB? How bad is the contamination?"

**Short answer:** We can run a one-line script in staging to count
rows >5 KB and rows with duplicate fingerprints under the new
normalizer.

**How to explain:** Until we run the migration in dry-run mode we
don't have exact numbers. The migration script (§7.4) prints a
dry-run report: total rows, rows kept, rows dropped (and why), and
duplicate count by fingerprint. Phase 1 starts with that dry run.

If pressed for an estimate: ~70% carry-over expected, based on the
proportion of normal-sized SME-approved fixes versus poisoning
outliers in similar systems. Real number ships with Phase 1.

### Q6. "Why are we calling SHA-of-blob a 'bug'? It's just a cache key choice."

**Short answer:** It's a bug because the cache it represents almost
never hits, defeating the purpose of having a cache.

**How to explain:** Build logs contain timestamps and incremental
counters. Two failures of the same Jenkins job two minutes apart
produce different blobs (different timestamps), so different SHAs,
so different cache keys. The cache is doing zero useful work today.
With the deterministic fingerprint key, the *same root cause* lands
on the *same key* regardless of timestamps — which is what cache
keys are supposed to do.

Point to: §3.4 (cache key), §5.2 (fingerprint).

---

## Anticipated Q&A — group 2: design choices

### Q7. "Why not full agentic? It's the trend. Won't we look behind the curve if we don't go all-in?"

**Short answer:** The cost-benefit doesn't work at our volume. Hybrid
gets the same accuracy on the part that matters at one-tenth the
cost. We can revisit if volume or accuracy requirements change.

**How to explain:** Walk them through §8.2 of HYBRID_PROPOSAL.md.
Numbers:
- Full agentic: ~$30–40 per 1k requests, 12 s p50, 2,500 LoC,
  non-deterministic on every request.
- Hybrid: ~$3 per 1k requests, 400 ms p50, 900 LoC, deterministic on
  85% of requests.
- Variant accuracy is roughly the same because A3 (which Hybrid
  keeps) is the agent doing the heavy lifting. The other six agents
  add cost and complexity without measurable accuracy lift.

Point to: §8.2.

### Q8. "Why exactly one agent and not two? The Validator (A6) sounds important."

**Short answer:** A6 is YAGNI until we have evidence we need it. We
can add it as Phase 5 if a real safety incident occurs.

**How to explain:** A6's job is to block dangerous outputs (rm -rf,
curl pipe sh, references to unrelated repos). For the immediate
threat surface — accidental dangerous commands — a 30-line regex
catches the obvious cases. A6 would catch subtler issues like
hallucinated repo names, but we have no evidence yet that those
happen at a rate worth a per-request LLM call. We bake the regex in
now; we add A6 the day we hit a real incident.

Point to: §6.1 (table of dropped agents), §10 Phase 5.

### Q9. "What if A3 hallucinates an adjusted_fix that breaks something?"

**Short answer:** A3's role is bounded — it can only adjust
parameters in an already-approved fix, not invent new steps. And
adjusted fixes go through a lighter SME review (recommendation in
§11 Q4) before being marked approved.

**How to explain:** A3 sees the stored fix and the new error. It is
prompted to refuse to invent new steps — if the stored fix doesn't
mostly apply, it must return `partial` or `no_match` and let the
LLM Synthesizer handle generation. So the worst-case A3 output is
"this stored fix with version number X swapped for Y", not a
freshly-invented procedure.

The team can also opt for the more conservative path (§11 Q4 (b)):
adjusted fixes go through a fresh SME Approve cycle. Slower
flywheel but zero risk of unreviewed advice reaching developers.

Point to: §6.2 ("A3 must not invent new fixes"), §11 Q4.

### Q10. "Why cosine and not Euclidean? We were using L2 before."

**Short answer:** Cosine is the standard for sentence-embedding
similarity. L2 was never appropriate for this — it was a default we
inherited.

**How to explain:** Embedding models are trained so that
*direction* in vector space encodes semantic similarity, not
distance. Two semantically equivalent sentences have nearly parallel
vectors but possibly different magnitudes. Cosine ignores magnitude;
L2 doesn't. With L2, longer texts produce smaller-magnitude vectors,
which appear "closer" to everything — exactly the symptom we have.

For granite-embedding specifically, the model card recommends cosine.

Point to: §5.3.

### Q11. "Why do we need to split error_lines from context_lines on the wire? Why not just split server-side?"

**Short answer:** We could, but the extractor already has the
information cleanly. Re-deriving it server-side from a glued blob is
fragile.

**How to explain:** In `src/log_error_extractor.py`, the extractor
internally distinguishes "matched error line" from "surrounding
context" — it tracks both as separate variables, and only joins
them at the very end (`return ['\n'.join(sections)]`). Sending the
already-separated structure over the wire is essentially free
(maybe 30 LoC delta) and lets the analyzer trust the boundary
without re-parsing.

The legacy `error_lines` field stays in place for one release for
back-compat with old extractor clients.

Point to: §5.1, `src/log_error_extractor.py:138`.

### Q12. "Why deterministic IDs from sha256? What if two different errors normalize to the same fingerprint?"

**Short answer:** That's a feature, not a bug — that's exactly the
case where they should share a fix.

**How to explain:** If `npm err code eresolve peer dep <VERSION>
<PATH>` is the normalized form of two different builds' errors,
those two builds have the *same root cause* by construction. They
should resolve to the same stored fix. The deterministic ID
guarantees we look up the same row from the DB for both — which is
the correct retrieval behavior.

Pathological collisions (genuinely different errors normalizing the
same way) are possible but rare; the SME would notice when reviewing
the fix and Edit it appropriately, which the update-not-insert path
preserves.

Point to: §5.2 (normalization), §5.3 (deterministic ID), §5.6
(update-not-insert).

### Q13. "Won't 0.90 cosine reject too many true matches?"

**Short answer:** It's stricter than what we have today (0.78 on
miscalibrated L2), but it's calibrated for the *normalized* fingerprint
which is short and specific, so 0.90 is the right ballpark.

**How to explain:** 0.78 today is interpreted on a metric that goes
negative for unrelated vectors — the "0.78" doesn't mean what we
think. On normalized cosine of a short fingerprint, 0.90 means "the
two errors are essentially the same root cause with at most cosmetic
differences". Pairs that fall in `[0.90, 0.95)` are exactly where A3
fires to decide whether the differences matter.

We can tune per-team if needed (§11 Q3).

Point to: §5.3, §6.3.

---

## Anticipated Q&A — group 3: rollout, cost, operations

### Q14. "Two to three weeks for one engineer — is that realistic?"

**Short answer:** Yes for the code, plus 1 week of Phase 0 eval
work that someone has to own.

**How to explain:** Show §9 (file change list, ~1,130 LoC product +
300 tests). Most LoC delta is contained in two files (`vector_db.py`
and `log_error_extractor.py`). The new files
(`agents/`, `orchestrator.py`, prompts) are small and isolated.
Phase 0 (eval) is the wildcard — it's tooling work plus dataset
curation; can be parallelized with Phase 1 development if a second
person owns it.

If pressed: "Worst case, 4 weeks if Phase 0 takes longer than a week
or if migration script reveals more contamination than expected."

Point to: §9, §10.

### Q15. "What if Phase 0 reveals that Hybrid isn't actually better than deterministic alone?"

**Short answer:** Then we ship deterministic alone. Phase 2 is
feature-flagged precisely so we can stop after Phase 1 if the data
says so.

**How to explain:** This is the value of the phased approach. After
Phase 1 we have:
- The four root-cause bugs fixed.
- ~85% accuracy on the cache-hit and clear-match buckets.
- A regression suite in CI.

If shadow-mode A3 in Phase 2 doesn't show meaningful lift, we don't
flip the flag to `on`. We ship Phase 1 + the rest of the rollout
becomes "deterministic only". No money lost.

Point to: §10 (Phase 2 gate is "shadow ≥80% match with SME"), §10.1
(non-negotiables include feature flags).

### Q16. "What does this cost run-rate look like at production scale?"

**Short answer:** ~$90/month at 1,000 requests/day. ~$900/month at
10,000/day. Linear with volume.

**How to explain:** From §1 headline numbers:
- Hybrid: ~$3 per 1,000 requests.
- Today (broken): ~$15 per 1,000 (every request hits LLM because
  cache never hits).

So Hybrid at our current volume is *cheaper* than today's broken
system, plus dramatically more accurate. The cost story actually
sells itself.

If they ask about Bedrock pricing assumptions: ~$3/M input tokens,
~$15/M output tokens for Claude Sonnet. Numbers from §7.1 of
PROPOSAL.md.

### Q17. "What's the migration risk? Could we lose approved fixes?"

**Short answer:** Low risk. The old collection stays on disk for
rollback. The new collection is built additively from the old.

**How to explain:** Walk them through §7.4:
1. Migration is read-only on the source collection.
2. Output goes to a new collection name (`fix_embeddings_v2`).
3. Switching is a single env-var change.
4. Rolling back is the same single env-var change in reverse.

Worst case: we run migration, find it's wrong somehow, leave the env
var pointed at the old collection. No data loss. No downtime.

Point to: §7.4, §10 Phase 1 rollback.

### Q18. "Who's on call when A3 starts misbehaving in production?"

**Short answer:** Same on-call rotation that owns the analyzer
today. A3 failure is bounded — it falls back to the LLM Synthesizer.

**How to explain:** A3 failure modes (timeout, malformed JSON, low
confidence) all degrade to "behave like the foundation alone". So
the worst-case A3 incident looks like Phase 1's behavior — not a
service outage. The feature flag flip (`AGENTIC_MODE=off`) is the
escape hatch; Phase 3 is feature-flagged at 10% specifically so
this scenario is detected on a small slice before it reaches
everyone.

Point to: §6.5, §10 Phase 3.

### Q19. "How do we know it's working in production?"

**Short answer:** SME approval rate, repeat-error rate, developer
thumbs-up rate.

**How to explain:** Three concrete metrics:
1. **SME approval rate per AI-suggested fix.** Today this is the
   primary signal. If Hybrid is sending better suggestions, this
   rate goes up.
2. **Repeat-error rate.** How often does the same developer hit the
   same error twice in 14 days? Should drop because the second
   occurrence resolves via cache/vector hit and the developer fixes
   it the first time.
3. **Developer thumbs-up / thumbs-down on the DM.** New telemetry
   added in Phase 1 (one-line addition). Tracks whether the
   delivered fix was useful.

Plus the audit trail captures every A3 decision — we can replay any
production request offline if a specific incident comes up.

Point to: §6.4 (caching → measurable hit rate), §10 Phase 3 gate.

### Q20. "Is this the eventual end state, or does it grow into Full Agentic later?"

**Short answer:** Not the end state. Hybrid is what makes sense at
1,000–10,000 requests/day. Full Agentic becomes attractive when
volume is much higher or when we have a labeled dataset large
enough to fine-tune a small classifier.

**How to explain:** Walk through §10 Phase 5 (optional). We can add
agents one at a time, each behind its own flag, each gated on a
≥5% lift on the eval suite. The architecture supports adding A1,
A4, A6 later without rewriting Hybrid. So this is "ship the
high-leverage 80%, layer the rest in over time as data justifies it".

Point to: §10 Phase 5.

---

## Closing the meeting (5 minutes)

### Restate the asks

> "I need three things from this meeting:
>
> 1. Approval to proceed with the Hybrid approach.
> 2. A name for Phase 0 ownership — eval harness + golden set.
> 3. Decisions on the open questions in §11 — or a follow-up to
>    decide them in the next 48 hours so I don't block."

### What you'll send after the meeting

> "I'll follow up by EOD with:
> - Meeting notes capturing decisions and any open items.
> - Proposed Phase 0 plan with a target completion date.
> - Updated open-questions list for offline decisions."

### Tone for closing

You want to end on momentum, not uncertainty. Even if some open
questions are unresolved, you have a clear Phase 0 to start, and
that's enough to begin without waiting.

> "Whether or not every detail is decided, Phase 0 is independent
> work. I can start on the eval harness this week — that's the
> single biggest risk-reduction step regardless of which exact
> decisions land. Once we have it, every later phase has something
> to verify against."

---

## A few things NOT to do in the meeting

1. **Don't read the doc aloud.** Walk the team through it. They can
   read it on their own time.
2. **Don't volunteer to do agents we said we'd skip.** A6 (Validator)
   is a YAGNI. Don't let a stakeholder talk you into "while you're
   in there, why not also..." Stick to the scoped plan.
3. **Don't promise specific accuracy numbers.** Until Phase 0 runs,
   the 85% / 90% numbers are educated estimates. Use phrases like
   "expected to land in the X–Y range" not "we will hit X%".
4. **Don't leave the meeting without owners.** If you can't get
   commitments in the room, get them via DM within 24 hours.
   Phase 0 ownership is the critical one.

---

## One-page cheat sheet (print or pin)

If you want a single-page printout for the meeting, here's the
TL;DR you can refer to without scrolling:

```
PROBLEM
  Wrong fixes since vector DB poisoning by 1 large blob.
  4 compounding bugs (blob embedding, L2 vs cosine, salted
  hash IDs, blob SHA cache).

SOLUTION (Hybrid, two layers)
  Layer 1 (deterministic): split error/context, normalize,
                            cosine, sha256 IDs, update-not-insert
  Layer 2 (one agent A3):   fires on ambiguous matches only
                            (~15% of traffic)

NUMBERS
  Today:   $15/1k, 5–8s p50, ~80% wrong on variants
  Hybrid:  $3/1k,  400ms p50, ~13–15% wrong on variants
  Code:    ~900 LoC + 300 tests, 2–3 weeks one engineer

ROLLOUT
  Phase 0 — eval harness  (1 week)
  Phase 1 — foundation    (1 week)
  Phase 2 — A3 in shadow  (1 week)
  Phase 3 — 10% rollout   (2 weeks)
  Phase 4 — 100%          (1 week)
  All feature-flagged. <60s revert.

DECISIONS NEEDED TODAY
  1. Approve Hybrid approach
  2. Phase 0 ownership
  3. Salvage existing fixes via migration
  4. A3 adjusted_fix review path
  5. Bedrock migration scope
```
