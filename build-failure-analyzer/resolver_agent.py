#!/home/build-failure-analyzer/build-failure-analyzer/.venv/bin/python3

import json
import hashlib
from typing import List, Dict, Optional, Any

import redis
import os
from dotenv import load_dotenv

from vector_db import VectorDBClient
from llm_openwebui_client import call_llm

load_dotenv()

# Path to enterprise infra overview 
GLOBAL_CONTEXT_PATH = os.getenv(
    "GLOBAL_CONTEXT_PATH",
    "/home/build-failure-analyzer/build-failure-analyzer/context/infra_overview.md",
)

def _load_global_context() -> str:
    """
    Loads enterprise CI/CD infra background (non-RAG).
    This is not embedded — appended directly to LLM system_prompt.
    """
    try:
        if os.path.exists(GLOBAL_CONTEXT_PATH):
            with open(GLOBAL_CONTEXT_PATH, "r") as f:
                content = f.read().strip()
                # Optional: cap to avoid runaway memory
                return content[:6000]  
    except Exception:
        pass
    return ""

GLOBAL_CONTEXT_TEXT = _load_global_context()
REDIS_TTL_AI = int(60 * 60 * 24)  # 24h, can be env var later


class ResolverAgent:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.vector = VectorDBClient()

    # -----------------------------
    #  Redis AI cache helpers
    # -----------------------------
    def _ai_cache_get(self, error_hash: str) -> Optional[Dict[str, Any]]:
        v = self.redis.get(f"ai:fix:{error_hash}")
        if v:
            try:
                return json.loads(v)
            except Exception:
                return None
        return None

    def _ai_cache_set(self, error_hash: str, payload: Dict[str, Any]) -> None:
        self.redis.setex(f"ai:fix:{error_hash}", REDIS_TTL_AI, json.dumps(payload))

    # -----------------------------
    #  Main resolution pipeline
    # -----------------------------
    def resolve(
        self,
        error_lines: List[str],
        embedding_vector: Optional[List[float]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Resolution logic:

        1. Normalize error_text & compute hash.
        2. Check AI cache (ai:fix:<hash>).
        3. Query vector DB (fix_embeddings) using top_k from metadata (default 5).
        4. If still no fix, call LLM with:
           - error context (repo/branch/job/step/etc.)
           - domain_rag_snippet (if provided by analyzer_service)
        5. Cache LLM-generated fix back into Redis (AI cache).

        NOTE:
        - This class does NOT write into vector DB; that only happens on Slack Approve/Edit.
        - Domain RAG lookup is done upstream (analyzer_service) and passed via metadata.
        """
        metadata = metadata or {}
        # 1) Normalize error text
        error_text = "\n".join([l.strip() for l in error_lines if l.strip()])
        error_hash = self._hash(error_text)

        # 2) AI cache check (in addition to analyzer-level cache)
        cached = self._ai_cache_get(error_hash)
        if cached:
            cached["source"] = "ai_cache"
            return cached

        # 3) Vector DB lookup (fix_embeddings) with configurable top_k
        top_k = int(metadata.get("vector_top_k", 5) or 5)
        vec_result = self.vector.lookup_existing_fix(
            error_text,
            top_k=top_k,
            embedding_vector=embedding_vector,
        )
        if vec_result:
            # vec_result already carries source="vector_db"
            return vec_result

        # 4) Prepare LLM prompt with domain RAG snippet (if any)
        domain_snippet = metadata.get("domain_rag_snippet", "")

        # Build a compact context header for the LLM
        ctx_lines = []
        if metadata.get("repo"):
            ctx_lines.append(f"Repository: {metadata['repo']}")
        if metadata.get("branch"):
            ctx_lines.append(f"Branch: {metadata['branch']}")
        if metadata.get("commit"):
            ctx_lines.append(f"Commit: {metadata['commit']}")
        if metadata.get("job_name"):
            ctx_lines.append(f"Job: {metadata['job_name']}")
        if metadata.get("step_name"):
            ctx_lines.append(f"Step: {metadata['step_name']}")
        if metadata.get("pipeline_id"):
            ctx_lines.append(f"Pipeline ID: {metadata['pipeline_id']}")
        if metadata.get("triggered_by"):
            ctx_lines.append(f"Triggered by: {metadata['triggered_by']}")

        context_header = "\n".join(ctx_lines) if ctx_lines else "(no extra pipeline metadata)"

        # System prompt guides global behavior + how to use domain knowledge
        system_prompt_parts = [
            "You are an expert CI/CD build failure resolver for an enterprise GitLab/Jenkins environment.",
            "You receive pipeline metadata, raw error logs, and optional domain knowledge snippets.",
            "Your job is to produce a short, actionable markdown response with sections:",
            "1. Summary (1–3 sentences)",
            "2. Steps (bullet list of concrete actions)",
            "3. Code Fix (only if code change is clearly needed, otherwise say 'N/A')",
            "4. Quick Checks (simple validations the engineer can perform)",
            "",
            "If domain knowledge is provided below, you MUST consider it first and adapt it to the current error.",
        ]

        if domain_snippet:
            system_prompt_parts.append("")
            system_prompt_parts.append("Domain knowledge snippet:")
            system_prompt_parts.append(domain_snippet)
        # ----------------------------------
        # Append Global (non-RAG) Infra Doc
        # ----------------------------------
        if GLOBAL_CONTEXT_TEXT:
            system_prompt_parts.append("")
            system_prompt_parts.append("Enterprise CI/CD infrastructure overview (internal docs):")
            system_prompt_parts.append(GLOBAL_CONTEXT_TEXT)
            
        system_prompt = "\n".join(system_prompt_parts)

        user_prompt = (
            "Pipeline context:\n"
            f"{context_header}\n\n"
            "Error log:\n"
            "--------------------\n"
            f"{error_text}\n"
            "--------------------\n"
            "\n"
            "Now propose a fix as described in the system instructions."
        )
        print(f"user_prompt: {user_prompt}\n===========================\nsystem_prompt: {system_prompt}")
        generated_text = call_llm(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            max_tokens=512,
        )

        res: Dict[str, Any] = {
            "fix_text": generated_text,
            "confidence": 0.6,
            "source": "generated",
            "error_hash": error_hash,
        }

        # Cache AI suggestion
        self._ai_cache_set(error_hash, res)

        # Resolver does NOT save to vector DB; that is done only after SME approve/edit via Slack.
        return res

    # -----------------------------
    #  Hash helper
    # -----------------------------
    def _hash(self, s: str) -> str:
        return hashlib.sha256(s.encode("utf-8")).hexdigest()