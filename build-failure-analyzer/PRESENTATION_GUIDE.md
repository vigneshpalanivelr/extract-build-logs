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

(Continued in next chunks — Q&A grouped by topic.)
