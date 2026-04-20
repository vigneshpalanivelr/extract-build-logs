# Agentic Approach — Design & Comparison

Companion to `SOLUTION_PROPOSAL.md` (deterministic fix) and `CURRENT_FLOW.md`
(existing implementation). This doc answers: "What if we redesign the
build-failure-analyzer as a multi-agent system?"

Status: **Design only. No code changes.**

Chunks:
1. Agent architecture design ← this chunk
2. Implementation plan (next)
3. Comparison matrix (next)
4. Recommendation + hybrid path (next)

---

## Chunk 1 — Agent architecture design

### 1.1 What "agentic" means here

An **agent** = an LLM call bounded to a specific role, with:
- a focused system prompt
- a narrow set of tools it may call (via function-calling / tool-use)
- structured output (JSON schema)
- a termination condition

An **agentic system** = several such agents composed by an **orchestrator**
that decides the next agent to invoke based on each agent's output. This is
different from a single prompt that tries to do everything.

The Bedrock Claude Sonnet used today (`anthropic.claude-sonnet-4-20250514-v1:0`
via OpenWebUI, see `llm_openwebui_client.py:17`) supports tool use, so
agent wiring is feasible without switching providers.

### 1.2 Candidate agents (full set — we will trim in chunk 4)

| # | Agent | Role | Input | Output | LLM needed? |
|---|---|---|---|---|---|
| A1 | **Error Classifier** | Parse raw error blob → canonical fingerprint + category + severity + key tokens | `error_lines`, `context_lines` (raw) | `{ category, subcategory, fingerprint, severity, key_tokens[] }` | Light model (Haiku) |
| A2 | **Retrieval** | Query vector DB + domain RAG with fingerprint, return ranked candidates | fingerprint, category, top_k | `[{ candidate_id, stored_error, stored_fix, cosine_sim, meta }]` | **No** — pure tool call. Agent only if we want LLM to re-rank. |
| A3 | **Deviation Analyzer** | For each candidate, decide: `exact_match` / `applicable_with_adjustments` / `partial` / `no_match`. If adjustments needed, specify them. | current error, candidate.stored_error, candidate.stored_fix | `{ match_quality, reasoning, adjusted_fix?, confidence }` | Yes — this is the high-value agent |
| A4 | **Context Disambiguator** | When A3 returns multiple `applicable` candidates, pick the best using pipeline metadata (repo, branch, job history) | candidates with `applicable` status, pipeline metadata | `{ chosen_candidate_id, reasoning }` | Maybe — simple rules may suffice |
| A5 | **Solution Synthesizer** | No good match → generate a fresh fix. Can borrow from partial matches in A3. | current error, context, domain snippet, partial matches | `{ fix_text, confidence, rationale, cited_candidates[] }` | Yes — replaces today's `call_llm` in `resolver_agent.py:167` |
| A6 | **Validator** | Sanity check final answer: not hallucinated repo, no dangerous commands, cites the right file | final fix, current error | `{ pass, warnings[], adjusted_fix? }` | Optional light model |
| A7 | **Reporter / Slack Formatter** | Convert final structured output to Slack blocks + developer DM | structured fix | Slack payload | No — deterministic formatting |

### 1.3 How agents fit the existing flow

Replace the single body of `/api/analyze` loop (`analyzer_service.py:277`)
with an orchestrator that calls the agents above.

```
POST /api/analyze
  │
  ▼
[Orchestrator] state machine:
  │
  ├─ Redis sme:fix:<hash> / ai:fix:<hash>   (unchanged, pre-agent shortcut)
  │    └─ HIT → format via A7, done
  │
  ├─ A1 Classifier
  │    └─ produces fingerprint for everything downstream
  │
  ├─ A2 Retrieval  (tool-use, not a real LLM reasoning call)
  │    ├─ if 0 candidates  → skip to A5
  │    └─ else
  │
  ├─ A3 Deviation Analyzer (per candidate, parallel, bounded to top-3)
  │    ├─ any exact_match                          → pick it, skip A4/A5
  │    ├─ >=2 applicable_with_adjustments          → A4
  │    ├─ 1 applicable_with_adjustments            → apply, skip A5
  │    └─ all no_match / partial                   → A5
  │
  ├─ A4 Context Disambiguator  (only on multi-applicable)
  │
  ├─ A5 Solution Synthesizer   (only when no reusable fix)
  │
  ├─ A6 Validator              (final gate, optional)
  │
  └─ A7 Reporter               (Slack/DM formatting)
```

### 1.4 Agent boundaries — what each agent must NOT do

- **A1 Classifier** must not propose fixes or call tools. Pure parsing.
- **A3 Deviation Analyzer** must not invent entirely new fixes. Only judge + minor-tweak. Keeps tokens bounded.
- **A5 Synthesizer** must cite which candidates it borrowed from (for explainability and SME review).
- **A6 Validator** must not rewrite content, only flag and optionally block.
- Orchestrator must enforce max-agent-calls budget per request (e.g., 5) to prevent runaway cost.

### 1.5 State passed between agents

```json
{
  "request_id": "uuid",
  "payload": { ... AnalyzePayload ... },
  "fingerprint": null,              // filled by A1
  "category": null,                 // filled by A1
  "candidates": [],                 // filled by A2
  "analyzed_candidates": [],        // filled by A3
  "chosen": null,                   // filled by A3/A4
  "synthesized": null,              // filled by A5
  "validation": null,               // filled by A6
  "audit_trail": [                  // for observability
    { "agent": "A1", "tokens_in": N, "tokens_out": M, "ms": T, "result_summary": "..." }
  ]
}
```

The audit_trail is critical — without it, debugging an agentic system is
nearly impossible. Every agent appends one entry.

### 1.6 Failure handling

- Any agent raises `LLMInfraError` → circuit-break: return cached fix if any, else 503.
- Any agent returns malformed JSON → retry once, then skip that agent (degrade gracefully).
- Orchestrator timeout: 45 s total budget per request (vs today's ~10 s LLM call).

### 1.7 What *doesn't* change

- The wire contract from `SOLUTION_PROPOSAL.md` (split `error_lines` / `context_lines` / `error_fingerprint`) is still required. The classifier agent (A1) becomes cheaper if the extractor already provides these.
- Vector DB fixes (cosine space, deterministic ID, update-not-add) from `SOLUTION_PROPOSAL.md` are still required. Agents don't solve poisoning on their own.
- Slack approve/edit loop in `slack_reviewer.py` unchanged.
- JWT auth, Redis caches unchanged.

**Key insight**: the agentic approach *layers on top of* the deterministic fix,
it doesn't replace it. The vector-DB poisoning bug must be fixed regardless.

---

(Chunks 2, 3, 4 to follow.)
