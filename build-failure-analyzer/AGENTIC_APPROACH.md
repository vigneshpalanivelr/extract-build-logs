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

## Chunk 2 — Implementation plan

### 2.1 Framework choice

Three options evaluated:

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Hand-rolled orchestrator** using direct `call_llm` + JSON schema output | No new deps. Same HTTP path (`llm_openwebui_client.py`). Easy to debug. | Must implement retries, schema validation, tool-use loop ourselves. | **Recommended** — matches existing code style |
| **LangGraph** | State machine out of the box, graphviz visualization, replay | New dep, tight coupling to LangChain universe, more surface area | Overkill for 5 agents |
| **Claude Agent SDK** | First-class tool-use loop, memory, subagents | Currently routes to Anthropic API directly; would bypass OpenWebUI/Bedrock gateway | Re-evaluate if OpenWebUI gets dropped |

Going with option 1. OpenWebUI's `/api/v1/chat/completions` already supports
the `tools` parameter (OpenAI-style function calling) which Bedrock Claude
Sonnet honors. We pass tool schemas in request, parse `tool_calls` from
response, execute tools server-side, feed result back as a `tool` role
message — standard loop.

### 2.2 New files / changes

```
build-failure-analyzer/
├── agents/
│   ├── __init__.py
│   ├── base.py                  # Agent base class, retry, JSON validation, audit
│   ├── classifier.py            # A1
│   ├── retrieval.py             # A2 (tool-using, wraps VectorDBClient)
│   ├── deviation.py             # A3
│   ├── disambiguator.py         # A4
│   ├── synthesizer.py           # A5
│   ├── validator.py             # A6
│   └── reporter.py              # A7 (no LLM)
├── orchestrator.py              # State machine, routing, budget enforcement
├── prompts/
│   ├── classifier.md
│   ├── deviation.md
│   ├── disambiguator.md
│   ├── synthesizer.md
│   └── validator.md
├── tool_schemas.py              # JSON schemas for agent outputs + tools
└── analyzer_service.py          # modified: /api/analyze delegates to orchestrator
```

Shared code reused from today: `vector_db.py`, `pipeline_context_rag.py`,
`slack_helper.py`, `slack_reviewer.py`, `llm_openwebui_client.py`.

### 2.3 Agent base class sketch

```python
# agents/base.py
class Agent:
    name: str
    model: str = OPENWEBUI_MODEL     # override per-agent if needed
    temperature: float = 0.2
    max_tokens: int = 512
    output_schema: dict              # JSON schema
    system_prompt_path: str          # file in prompts/
    tools: list[dict] = []           # OpenAI-style function schemas

    def run(self, state: dict) -> dict:
        """
        1. Build user prompt from state
        2. Call OpenWebUI with tools + schema
        3. Execute any tool_calls, feed back, repeat (bounded loop, max 3 iters)
        4. Validate final output against schema
        5. Append audit_trail entry
        6. Return structured dict (merged into state)
        """

    def _call_with_tools(self, messages, tools):
        # tool-use loop
        ...

    def _validate_output(self, raw_json) -> dict:
        # jsonschema.validate; on failure, one retry with "your output was invalid, try again"
        ...
```

### 2.4 Per-agent specs

#### A1 Classifier
```python
class ClassifierAgent(Agent):
    model = "claude-haiku-4-5-20251001"    # cheap & fast
    max_tokens = 256
    output_schema = {
        "type": "object",
        "required": ["category", "fingerprint", "severity"],
        "properties": {
            "category":    {"enum": ["network", "dependency", "compile",
                                     "test", "infra", "auth", "config",
                                     "resource", "unknown"]},
            "subcategory": {"type": "string"},
            "fingerprint": {"type": "string", "maxLength": 512},
            "severity":    {"enum": ["low", "medium", "high", "fatal"]},
            "key_tokens":  {"type": "array", "items": {"type": "string"},
                            "maxItems": 10}
        }
    }
```
Prompt (sketch): "You are a CI/CD log classifier. Given `error_lines` and
`context_lines`, emit the strict JSON above. The fingerprint must be a
short canonical string (<256 chars) with timestamps, paths, SHAs, and
build IDs stripped."

#### A3 Deviation Analyzer (the high-value one)
```python
class DeviationAgent(Agent):
    max_tokens = 512
    output_schema = {
        "type": "object",
        "required": ["match_quality", "confidence", "reasoning"],
        "properties": {
            "match_quality": {"enum": ["exact_match", "applicable_with_adjustments",
                                       "partial", "no_match"]},
            "confidence":    {"type": "number", "minimum": 0, "maximum": 1},
            "reasoning":     {"type": "string"},
            "adjusted_fix":  {"type": "string"},
            "adjustments":   {"type": "array", "items": {"type": "string"}}
        }
    }
```
Prompt (sketch): "Compare the CURRENT error with a STORED error and its
approved STORED fix. Decide whether the stored fix applies. Output JSON.
- exact_match: identical root cause; fix applies verbatim
- applicable_with_adjustments: same root cause, needs small edits (version
  numbers, paths); provide `adjusted_fix`
- partial: some steps of the stored fix apply; list which
- no_match: different root cause
Do not invent new fixes."

Called once per top-K candidate (K=3). Requests run in parallel (orchestrator
uses `asyncio.gather`) so latency = max(3 calls) not sum.

#### A5 Synthesizer
Replaces the LLM branch in `resolver_agent.py:167`. Same prompt structure,
but augmented with cited partial matches from A3:

```
## Partial matches (for reference, adapt not copy)
- candidate X: similarity 0.78, stored fix: "..."
- candidate Y: similarity 0.72, stored fix: "..."

## Current error
...

Generate a fix citing which partial matches you drew from.
```

#### A6 Validator
```python
output_schema = {
    "type": "object",
    "required": ["pass", "warnings"],
    "properties": {
        "pass":     {"type": "boolean"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "block_reasons": {"type": "array", "items": {"type": "string"}}
    }
}
```
Used as a hard gate for commands containing `rm -rf /`, `curl | sh`,
credential references, etc. Could be deterministic regex before LLM.

### 2.5 Orchestrator

```python
# orchestrator.py
class Orchestrator:
    MAX_AGENT_CALLS = 6
    TOTAL_TIMEOUT_S = 45

    def __init__(self, vector_db, redis_client, ctx_db):
        self.agents = {
            "classifier":    ClassifierAgent(),
            "retrieval":     RetrievalAgent(vector_db, ctx_db),
            "deviation":     DeviationAgent(),
            "disambiguator": DisambiguatorAgent(),
            "synthesizer":   SynthesizerAgent(),
            "validator":     ValidatorAgent(),
        }
        self.redis = redis_client

    async def handle(self, payload) -> dict:
        state = init_state(payload)

        # 0. Pre-agent cache shortcuts (unchanged from today)
        if cached := self._cache_lookup(state): return cached

        # 1. Classify
        state.update(await self.agents["classifier"].run(state))

        # 2. Retrieve
        state.update(await self.agents["retrieval"].run(state))
        if not state["candidates"]:
            state.update(await self.agents["synthesizer"].run(state))
            return self._finalize(state)

        # 3. Deviation (parallel across top-K)
        state["analyzed_candidates"] = await asyncio.gather(*[
            self.agents["deviation"].run({**state, "candidate": c})
            for c in state["candidates"][:3]
        ])

        # 4. Route based on deviation results
        exact = [c for c in state["analyzed_candidates"] if c["match_quality"] == "exact_match"]
        applicable = [c for c in state["analyzed_candidates"] if c["match_quality"] == "applicable_with_adjustments"]

        if exact:
            state["chosen"] = exact[0]
        elif len(applicable) == 1:
            state["chosen"] = applicable[0]
        elif len(applicable) >= 2:
            state.update(await self.agents["disambiguator"].run(state))
        else:
            state.update(await self.agents["synthesizer"].run(state))

        # 5. Validate (optional per config)
        if VALIDATE_ENABLED:
            state["validation"] = await self.agents["validator"].run(state)

        return self._finalize(state)
```

### 2.6 Caching strategy for agents

Agent calls are expensive; cache aggressively in Redis:

| Cache key | Value | TTL | Purpose |
|---|---|---|---|
| `agent:classifier:<sha(error)>` | A1 output | 24 h | Skip A1 re-run on retries |
| `agent:deviation:<sha(query_fp+candidate_id)>` | A3 output | 7 d | A3 output is stable per (query, candidate) pair |
| `agent:synth:<sha(fingerprint)>` | A5 output | 24 h | Existing AI cache, just renamed |

A3 cache in particular is high-impact: if two developers hit the same
error pattern within 7 days, the deviation analysis is reused, saving ~3
LLM calls per subsequent request.

### 2.7 Observability

- Each `run()` appends to `state["audit_trail"]` with `agent`, `ms`, `tokens_in`, `tokens_out`, `tool_calls[]`, `result_summary`.
- Log full audit trail JSON per request (at INFO level, aggregated ID).
- Prometheus metrics:
  - `bfa_agent_latency_seconds{agent=...}` histogram
  - `bfa_agent_tokens_total{agent=...,direction=in|out}` counter
  - `bfa_agent_errors_total{agent=...,reason=...}` counter
  - `bfa_agent_cache_hits_total{agent=...}` counter
- Grafana dashboard showing per-request flow + cumulative cost.

### 2.8 Rollout plan

1. Land `SOLUTION_PROPOSAL.md` deterministic fixes first (non-negotiable — without these, agents are reasoning over poisoned data).
2. Implement `agents/base.py` + `agents/deviation.py` + orchestrator wiring as feature-flagged path: `AGENTIC_MODE=off|deviation_only|full`.
3. Deploy in `deviation_only` mode — only A3 + A5 active, rest of pipeline unchanged.
4. Measure (see chunk 3) for 2 weeks vs deterministic baseline.
5. If A3 produces >15% accuracy lift, add A1 classifier to enrich retrieval. Otherwise stop.
6. Only add A6 Validator if security review requests it.

---

(Chunks 3, 4 to follow.)
