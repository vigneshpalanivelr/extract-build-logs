#!/home/build-failure-analyzer/build-failure-analyzer/.venv/bin/python3

import os
import json
import time
import logging
import hashlib
from typing import List, Optional, Dict, Any

import redis
import jwt
from fastapi import FastAPI, Header, HTTPException, Request, Depends, Form, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier
import csv
from io import StringIO, BytesIO
from fastapi import UploadFile, File
from error_notifier import notify_global_error
# Local imports
from resolver_agent import ResolverAgent
from slack_helper import send_error_message, get_fix, store_fix, summarize_error_with_ai
from slack_helper import client as slack, redis_conn
from vector_db import init_vector_db
from llm_openwebui_client import analyze_with_llm, LLMInfraError

# Domain RAG imports
from pipeline_context_rag import (
    load_domain_context,
    init_context_collection,
    index_domain_patterns,
    lookup_domain_matches,
)

load_dotenv()

# -------------------------------------------------------------------
# Slack / Auth setup
# -------------------------------------------------------------------
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
sig_verifier = SignatureVerifier(signing_secret=SLACK_SIGNING_SECRET)
client = WebClient(token=SLACK_BOT_TOKEN)

# -------------------------------------------------------------------
# App + Logging
# -------------------------------------------------------------------
app = FastAPI(title="Build Failure Analyzer (Unified)")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("analyzer")

# -------------------------------------------------------------------
# Redis + Resolver
# -------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:1111/0")
r = redis.from_url(REDIS_URL, decode_responses=True)
resolver = ResolverAgent(redis_client=r)

# -------------------------------------------------------------------
# JWT setup
# -------------------------------------------------------------------
PUBLIC_KEY_PATH = os.getenv("JWT_PUBLIC_KEY_PATH",
                            "/home/build-failure-analyzer/public.pem")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "build-failure-analyzer")
with open(PUBLIC_KEY_PATH, "r") as f:
    JWT_PUBLIC_KEY = f.read()

# Redis key constants
AI_FIX_KEY = "ai:fix:{}"
SME_FIX_KEY = "sme:fix:{}"

# -------------------------------------------------------------------
# Vector DB + Domain RAG configuration
# -------------------------------------------------------------------
# NOTE: CHROMA_DB_PATH is shared with fix_embeddings; we create a separate
# collection "pipeline_context" in the same persistence dir.
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "/var/lib/redis/bfa-data")
DOMAIN_CONTEXT_PATH = os.getenv(
    "DOMAIN_CONTEXT_PATH",
    "/home/build-failure-analyzer/build-failure-analyzer/context/domain_context_patterns.json",
)

_domain_ctx_db: Any = None
_domain_ctx_loaded: bool = False
_domain_ctx_data: Optional[Dict[str, Any]] = None


def init_domain_rag_if_needed() -> None:
    """
    Ensure domain context is loaded and indexed into a dedicated Chroma collection.
    Safe to call multiple times; it will no-op after the first.
    """
    global _domain_ctx_db, _domain_ctx_loaded, _domain_ctx_data

    if _domain_ctx_loaded:
        return

    try:
        ctx_data = load_domain_context(DOMAIN_CONTEXT_PATH)
        logger.info("[RAG] Loaded domain context from %s", DOMAIN_CONTEXT_PATH)
    except FileNotFoundError:
        logger.warning(
            "[RAG] Domain context file not found at %s – domain RAG will be disabled",
            DOMAIN_CONTEXT_PATH,
        )
        _domain_ctx_loaded = True
        _domain_ctx_db = None
        _domain_ctx_data = None
        return
    except Exception:
        logger.exception("[RAG] Failed to load domain context file")
        _domain_ctx_loaded = True
        _domain_ctx_db = None
        _domain_ctx_data = None
        return

    # Create / reuse "pipeline_context" collection in same CHROMA_DB_PATH
    try:
        ctx_db = init_context_collection(CHROMA_DB_PATH)
    except Exception:
        logger.exception(
            "[RAG] Failed to initialize domain context collection")
        _domain_ctx_loaded = True
        _domain_ctx_db = None
        _domain_ctx_data = None
        return

    # Index patterns only if collection is empty
    try:
        existing = ctx_db.collection.get(include=["metadatas"])
        ids = existing.get("ids", []) or []
        if not ids:
            index_domain_patterns(ctx_data, ctx_db)
        else:
            logger.info(
                "[RAG] Domain context collection already has %d vectors, skipping index",
                len(ids),
            )
    except Exception:
        logger.exception(
            "[RAG] Failed while checking/indexing domain context collection")

    _domain_ctx_db = ctx_db
    _domain_ctx_data = ctx_data
    _domain_ctx_loaded = True
    logger.info("[RAG] Domain context RAG initialized successfully")


def build_domain_rag_snippet(domain_matches: List[Dict[str, Any]]) -> str:
    """
    Convert domain RAG matches into a compact markdown string that
    the ResolverAgent can drop into the LLM system prompt.
    """
    if not domain_matches:
        return ""

    lines = ["Domain knowledge (historical patterns):"]
    for match in domain_matches:
        cat = match.get("category", "Unknown")
        failure = (match.get("failure") or "").strip()
        solution = (match.get("solution") or "").strip()
        sim = match.get("similarity", 0.0)

        if len(failure) > 200:
            failure = failure[:197] + "..."

        lines.append(
            f"- [{cat}] \"{failure}\" — similarity ≈ {sim:.2f}\n"
            f"  Suggested handling: {solution}"
        )

    return "\n".join(lines)


@app.on_event("startup")
async def on_startup() -> None:
    """
    FastAPI startup hook – warm up domain RAG. Errors are logged
    but do not prevent the service from starting.
    """
    init_domain_rag_if_needed()

# -------------------------------------------------------------------
# Models
# -------------------------------------------------------------------


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


class RateMyMRPayload(BaseModel):
    repo: str
    branch: str
    author: str
    commit: str
    prompt: str
    mr_url: Optional[str] = None  # optional link to MR


class ManualFixPayload(BaseModel):
    """
    Payload for manually inserting a single error+fix pair into the vector DB.
    Extra fields are treated as metadata.
    """
    error_text: str
    fix_text: str
    approver: Optional[str] = None
    status: Optional[str] = "manual"
    metadata: Optional[Dict[str, Any]] = None

# -------------------------------------------------------------------
# JWT validation
# -------------------------------------------------------------------


def require_jwt(auth_header: str = Header(None, alias="Authorization")):
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header")
    token = auth_header.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_PUBLIC_KEY, algorithms=[
                             "RS256"], audience=JWT_AUDIENCE)
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception as e:
        raise HTTPException(
            status_code=401, detail=f"Token validation failed: {e}")


# -------------------------------------------------------------------
# Token Generation (for internal Jenkins/DMZ use)
# -------------------------------------------------------------------
@app.post("/api/token")
async def generate_token(data: dict):
    from jwt_dmz_issuer import create_jwt
    try:
        subject = data.get("subject", "jenkins-runner")
        token = create_jwt(subject)
        return {"token": token}
    except Exception as e:
        logger.exception("Token generation failed")
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------------
# Analyzer Endpoint with RAG integration
# -------------------------------------------------------------------
@app.post("/api/analyze")
async def analyze(payload: AnalyzePayload, claims=Depends(require_jwt)):
    if not payload.failed_steps:
        raise HTTPException(status_code=400, detail="No failed steps provided")

    # Ensure domain RAG is ready (safe if already initialized)
    init_domain_rag_if_needed()

    results = []

    for step in payload.failed_steps:
        step_name = step.step_name or "Unknown Step"
        for error_line in step.error_lines:
            error_text = error_line.strip()
            if not error_text:
                continue

            error_hash = hashlib.sha256(error_text.encode()).hexdigest()
            metadata: Dict[str, Any] = {
                "repo": payload.repo,
                "branch": payload.branch,
                "commit": payload.commit,
                "job_name": payload.job_name,
                "pipeline_id": payload.pipeline_id,
                "step_name": step_name,
                "triggered_by": payload.triggered_by,
            }

            # -----------------------------
            # SME cache check
            # -----------------------------
            sme_cached = r.get(SME_FIX_KEY.format(error_hash))
            if sme_cached:
                cached_obj = {}
                try:
                    cached_obj = json.loads(sme_cached)
                except Exception:
                    cached_obj = {}

                fix_text_for_dm = (
                    cached_obj.get("fix_text")
                    or cached_obj.get("fix")
                    or str(cached_obj)
                )

                # DM developer with SME-cached fix
                send_dev_dm_fix(
                    triggered_by=payload.triggered_by,
                    error_text=error_text,
                    fix_text=fix_text_for_dm,
                    metadata=metadata,
                    source="sme_cache",
                )

                results.append({
                    "step_name": step_name,
                    "error_text": error_text,
                    "error_hash": error_hash,
                    "source": "sme_cache",
                    "fix": cached_obj,
                })
                continue

            # -----------------------------
            # AI cache check
            # -----------------------------
            ai_cached = r.get(AI_FIX_KEY.format(error_hash))
            if ai_cached:
                cached_obj = {}
                try:
                    cached_obj = json.loads(ai_cached)
                except Exception:
                    cached_obj = {}

                fix_text_for_dm = (
                    cached_obj.get("fix_text")
                    or cached_obj.get("fix")
                    or str(cached_obj)
                )

                # DM developer with AI-cached fix
                send_dev_dm_fix(
                    triggered_by=payload.triggered_by,
                    error_text=error_text,
                    fix_text=fix_text_for_dm,
                    metadata=metadata,
                    source="ai_cache",
                )

                results.append({
                    "step_name": step_name,
                    "error_text": error_text,
                    "error_hash": error_hash,
                    "source": "ai_cache",
                    "fix": cached_obj,
                })
                continue

            # -------------------------------------------------
            # RAG: Domain context + SME fix_embeddings (top 5)
            # -------------------------------------------------
            domain_matches: List[Dict[str, Any]] = []
            domain_snippet = ""

            if _domain_ctx_db is not None:
                try:
                    domain_matches = lookup_domain_matches(
                        error_text=error_text,
                        ctx_db=_domain_ctx_db,
                        threshold=0.55,
                        top_k=5,
                    )
                    domain_snippet = build_domain_rag_snippet(domain_matches)
                except Exception:
                    logger.exception(
                        "[RAG] Failed to lookup domain context matches")

            # Pass RAG hints into resolver via metadata.
            # ResolverAgent is responsible for:
            #  - using vector_top_k to query fix_embeddings (top-5 SME-approved fixes)
            #  - injecting domain_rag_snippet into the LLM system prompt before calling LLM
            metadata["domain_rag_snippet"] = domain_snippet
            metadata["domain_rag_matches"] = domain_matches
            metadata["vector_top_k"] = 5

            # -------------------------------------------------
            # Delegate to ResolverAgent (vector DB + LLM)
            # -------------------------------------------------
            candidate = resolver.resolve(
                [error_text],
                embedding_vector=getattr(step, "embedding_vector", None),
                metadata=metadata,
            ) or {}

            if candidate and candidate.get("source") in ("vector_db", "ai_cache", "sme_cache"):
                src = candidate.get("source") or "unknown"
                fix_text_for_dm = (
                    candidate.get("fix_text")
                    or candidate.get("fix")
                    or str(candidate)
                )

                # DM developer with reused fix (vector_db / cache)
                send_dev_dm_fix(
                    triggered_by=payload.triggered_by,
                    error_text=error_text,
                    fix_text=fix_text_for_dm,
                    metadata=metadata,
                    source=src,
                )

                results.append({
                    "step_name": step_name,
                    "error_text": error_text,
                    "error_hash": error_hash,
                    "source": src,
                    "fix": candidate,
                })
                continue
            # -------------------------------------------------
            # AI-generated path → Slack + AI cache
            # -------------------------------------------------
            # ResolverAgent currently uses "generated" as source;
            # we normalize it to "ai_generated" at the API level.
            source = candidate.get("source") or "unknown"
            if source in ("generated", "ai_generated") or fix_text:

                # Generate fix via LLM (resolver likely wraps this)
                # ai_fix_text = fix_text or str(candidate)
                ai_fix_text = candidate.get("fix_text", str(candidate))

                # Post error + fix to DevOps SME channel
                send_error_message(error_text, ai_fix_text,
                                   error_hash, metadata)

                # Also DM the developer with newly generated fix
                send_dev_dm_fix(
                    triggered_by=payload.triggered_by,
                    error_text=error_text,
                    fix_text=ai_fix_text,
                    metadata=metadata,
                    source="ai_generated",
                )

                # Persist fix + metadata for SME lifecycle
                store_fix(
                    error_id=error_hash,
                    error_title=error_text,
                    ai_fix_text=ai_fix_text,
                    source="ai_generated",
                    approver=None,
                    message_ts=None,
                    channel_id=None,
                    triggered_by=payload.triggered_by,
                    metadata=metadata,
                )

                # Cache the fix for this exact error_hash
                try:
                    r.setex(
                        AI_FIX_KEY.format(error_hash),
                        86400,
                        json.dumps({"fix_text": ai_fix_text,
                                   "source": "ai_generated"}),
                    )
                except Exception:
                    logger.exception(
                        "Failed to cache AI fix in Redis for %s", error_hash)

                results.append({
                    "step_name": step_name,
                    "error_text": error_text,
                    "error_hash": error_hash,
                    "source": "ai_generated",
                    "fix": ai_fix_text,
                })
                continue

            # Fallback: unknown source; still return whatever we got
            results.append({
                "step_name": step_name,
                "error_text": error_text,
                "error_hash": error_hash,
                "source": source or "unknown",
                "fix": candidate,
            })

    return {"status": "ok", "results": results}


# -------------------------------------------------------------------
# New API: Rate My MR (Code Review / Quality Analysis)
# -------------------------------------------------------------------
def format_vulnerabilities(vulns):
    """Format structured LLM findings for Slack"""
    if not vulns:
        return "_No major vulnerabilities found._"
    formatted = []
    for v in vulns:
        if isinstance(v, dict):
            t = v.get("type", "Unknown")
            s = v.get("severity", "N/A")
            d = v.get("description", "").strip()
            line = v.get("line", "")
            part = f"• *[{s}]* {t} — {d}"
            if line:
                part += f"\n   → `{line}`"
            formatted.append(part)
        else:
            formatted.append(f"• {v}")
    return "\n".join(formatted)


@app.post("/api/rate-my-mr")
async def rate_my_mr(payload: RateMyMRPayload, claims=Depends(require_jwt)):
    """
    Analyze developer MR diff using LLM and send the summarized metrics directly to the author's Slack DM.
    Falls back to skipping DM if user is not found.
    """

    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")

    prompt = payload.prompt
    logging.info(f"[RateMyMR] Payload: {prompt}")
    try:

        # Call LLM
        RATE_MY_MR_SYSTEM_PROMPT = """
You are an expert software code reviewer.

You are given a git diff from a merge request.
Your task is to analyze the changes and return a STRICT JSON object
with the following schema ONLY (no markdown, no explanations):

{
  "quality_score": number,
  "security_score": number,
  "maintainability_score": number,
  "overall_summary": string,
  "potential_vulnerabilities": array of strings,
  "recommended_improvements": array of strings
}

Rules:
- Always return valid JSON
- Never ask for more input
- Never explain what you are doing
- If the diff is incomplete or unclear, infer best-effort scores
- If no vulnerabilities are found, return an empty array
- Scores must be between 0 and 10
- Do NOT include backticks, markdown, or commentary
"""
        try:
            llm_response = analyze_with_llm(
                prompt,
                system_prompt=RATE_MY_MR_SYSTEM_PROMPT
            )
        except LLMInfraError as e:
            logging.error(
                "[RateMyMR] LLM infrastructure failure — triggering global notifier",
                exc_info=True,
            )

            # 🚨 Trigger your global error notifier here
            notify_global_error(
                source="Build Failure Analyzer",
                error=str(e),
                context={
                    "repo": payload.repo,
                    "branch": payload.branch,
                    "commit": payload.commit,
                },
            )

            raise HTTPException(
                status_code=503,
                detail="LLM infrastructure unavailable. Maintainers have been notified.",
            )
        except Exception as e:
            logger.exception("[LLM] analyze_with_llm() content failure: %s", e)

        if not llm_response:
            raise HTTPException(status_code=500, detail="No response from LLM")

        required_keys = {"quality_score",
                         "security_score", "maintainability_score"}

        if not isinstance(llm_response, dict) or not required_keys.intersection(llm_response):
            logging.error(
                "[RateMyMR] Invalid LLM response for MR scoring. "
                "Likely upstream payload or prompt mismatch.",
                extra={"llm_keys": list(llm_response.keys()) if isinstance(
                    llm_response, dict) else type(llm_response).__name__}
            )

            # Graceful but explicit fallback
            llm_response = {
                "summary_text": (
                    "MR analysis could not be scored because the input payload "
                    "was not compatible with RateMyMR evaluation. "
                    "This is likely an upstream integration issue."
                )
            }

        # Extract metrics safely
        quality = llm_response.get("quality_score", "N/A")
        security = llm_response.get("security_score", "N/A")
        maintainability = llm_response.get("maintainability_score", "N/A")
        summary = llm_response.get(
            "overall_summary", llm_response.get("summary_text", "(no summary)"))
        vulns = llm_response.get("potential_vulnerabilities", [])
        improvements = llm_response.get("recommended_improvements", [])

        # --------------------------------------------------------------------
        # Format Slack Message
        # --------------------------------------------------------------------
        branch_emoji = "🌿"
        commit_emoji = "🔖"
        repo_emoji = "📁"
        author_emoji = "👤"
        mr_emoji = "🔗"
        quality_emoji = "🧩"
        security_emoji = "🛡️"
        maintain_emoji = "🔧"
        alert_emoji = "🚨"
        bulb_emoji = "💡"

        vulnerabilities_text = format_vulnerabilities(vulns)
        improvements_text = "\n".join(
            [f"• {i}" for i in improvements]) or "_No recommendations provided._"

        slack_message = f"""
*🧠 MR Review Summary for `{payload.repo}`*
{author_emoji} *Author:* {payload.author}
{branch_emoji} *Branch:* `{payload.branch}`
{commit_emoji} *Commit:* `{payload.commit}`

📊 *Scores*
{quality_emoji} Quality: *{quality}/10*
{security_emoji} Security: *{security}/10*
{maintain_emoji} Maintainability: *{maintainability}/10*

{alert_emoji} *Findings:*
{vulnerabilities_text}

{bulb_emoji} *Recommendations:*
{improvements_text}

📝 *Summary:*
> {summary}

{mr_emoji} <{payload.mr_url or 'N/A'}|View Merge Request>
        """

        # --------------------------------------------------------------------
        # Send Direct Message to Author
        # --------------------------------------------------------------------
        def get_user_id(author_identifier: str):
            """Try resolving Slack user via email or display name"""
            try:
                # Attempt email lookup
                if "@" in author_identifier:
                    resp = client.users_lookupByEmail(email=author_identifier)
                    return resp["user"]["id"]
            except SlackApiError as err:
                logging.warning(
                    f"[RateMyMR] Slack email lookup failed: {err.response.get('error')}")
            except Exception as err:
                logging.warning(
                    f"[RateMyMR] Slack lookup error for {author_identifier}: {err}")

            # Fallback: try fuzzy name match
            try:
                users = client.users_list().get("members", [])
                for u in users:
                    if author_identifier.lower() in (
                        u.get("real_name", "").lower(),
                        u.get("name", "").lower(),
                    ):
                        return u["id"]
            except SlackApiError as e:
                logging.warning(
                    f"[RateMyMR] Slack user lookup failed: {e.response.get('error')}")
            return None

        user_id = get_user_id(payload.author)
        logging.info(f"[RateMyMR] Slack user id --> {user_id}")
        if user_id:
            client.chat_postMessage(channel=user_id, text=slack_message)
            logging.info(
                f"[RateMyMR] Sent MR review details to {payload.author} ({user_id}) on Slack DM.")
        else:
            logging.info(
                f"[RateMyMR] Slack user not found for {payload.author}; skipping Slack message.")

        # --------------------------------------------------------------------
        # Return API Response
        # --------------------------------------------------------------------
        return {
            "status": "ok",
            "repo": payload.repo,
            "branch": payload.branch,
            "commit": payload.commit,
            "author": payload.author,
            "metrics": llm_response,
            "sent_to": user_id or "user not found in slack directory!",
        }

    except Exception as e:
        logging.exception("[RateMyMR] Failed to process MR rating request")
        raise HTTPException(
            status_code=500, detail=f"LLM analysis or Slack DM failed: {e}")


# -------------------------------------------------------------------
# API: Manually insert a single error+fix into vector DB
# -------------------------------------------------------------------
@app.post("/api/vector/manual-fix")
async def add_manual_fix(payload: ManualFixPayload, claims=Depends(require_jwt)):
    """
    Insert a single error+fix pair into Chroma (fix_embeddings).
    - JWT required (same as /api/analyze).
    - Metadata:
        - source = "manual_api_single"
        - status defaults to "manual" unless overridden.
    """
    entry: Dict[str, Any] = {
        "error_text": payload.error_text,
        "fix_text": payload.fix_text,
        "approver": payload.approver,
        "status": payload.status or "manual",
    }
    # Merge in any extra metadata fields
    if payload.metadata:
        entry.update(payload.metadata)
    result = _save_manual_fix_entry(entry, source="manual_api_single")
    if result["status"] == "failed":
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save manual fix: {result.get('reason', 'unknown error')}",
        )
    if result["status"] == "skipped":
        raise HTTPException(
            status_code=400,
            detail=result.get("reason", "Invalid payload"),
        )
    return {
        "status": "ok",
        "record": result,
    }


# -------------------------------------------------------------------
# API: Bulk insert fixes from file (JSON / CSV / optional Excel)
# -------------------------------------------------------------------
@app.post("/api/vector/manual-fix/bulk")
async def bulk_manual_fix(
    file: UploadFile = File(...),
    claims=Depends(require_jwt),
):
    """
    Bulk-load error+fix pairs into vector DB from a file.
    Supported formats:
      - .json : either a list of objects, or { "entries": [...] }
      - .csv  : header row with at least error_text, fix_text (or error, fix)
      - .xlsx/.xls : optional, requires openpyxl; sheet header as for CSV.
    For each row/entry:
      - error_text / error : required
      - fix_text / fix : required
      - approver / approved_by : optional
      - status : optional (defaults to 'manual')
      - all other columns are treated as metadata.
    Records are tagged with:
      metadata["source"] = "manual_api_bulk"
      metadata["ingestion_mode"] = "manual"
    """
    filename = (file.filename or "").lower()
    content = await file.read()
    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    entries: List[Dict[str, Any]] = []
    # ---------------------
    # JSON
    # ---------------------
    if filename.endswith(".json"):
        try:
            data = json.loads(content.decode("utf-8"))
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid JSON file: {e}")
        if isinstance(data, list):
            entries = data
        elif isinstance(data, dict):
            # allow {"entries":[...]} or {"items":[...]} or just one object
            if "entries" in data and isinstance(data["entries"], list):
                entries = data["entries"]
            elif "items" in data and isinstance(data["items"], list):
                entries = data["items"]
            else:
                entries = [data]
        else:
            raise HTTPException(
                status_code=400, detail="JSON must be a list or object")
    # ---------------------
    # CSV
    # ---------------------
    elif filename.endswith(".csv"):
        try:
            text = content.decode("utf-8")
            reader = csv.DictReader(StringIO(text))
            entries = list(reader)
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid CSV file: {e}")
    # ---------------------
    # Excel (optional, openpyxl)
    # ---------------------
    elif filename.endswith(".xlsx") or filename.endswith(".xls"):
        try:
            import openpyxl  # type: ignore
        except ImportError:
            raise HTTPException(
                status_code=400,
                detail="Excel support requires 'openpyxl' to be installed in the environment.",
            )
        try:
            wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
            ws = wb.active  # use first sheet by default
            rows = list(ws.rows)
            if not rows:
                raise HTTPException(
                    status_code=400, detail="Excel file has no rows")
            headers = [str(c.value).strip()
                       if c.value is not None else "" for c in rows[0]]
            entries = []
            for row in rows[1:]:
                values = [c.value for c in row]
                entry = {}
                for h, v in zip(headers, values):
                    if h:
                        entry[h] = v
                entries.append(entry)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid Excel file: {e}")
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type for '{filename}'. Use .json, .csv, .xlsx, or .xls.",
        )
    if not entries:
        raise HTTPException(status_code=400, detail="No entries found in file")
    # ---------------------
    # Save all entries
    # ---------------------
    results: List[Dict[str, Any]] = []
    imported = failed = skipped = 0
    for raw in entries:
        result = _save_manual_fix_entry(raw, source="manual_api_bulk")
        status = result.get("status")
        if status == "imported":
            imported += 1
        elif status == "failed":
            failed += 1
        elif status == "skipped":
            skipped += 1
        results.append(result)
    return {
        "status": "ok",
        "file": filename,
        "total": len(entries),
        "imported": imported,
        "failed": failed,
        "skipped": skipped,
        "details": results,
    }
db = init_vector_db()

# -------------------------------------------------------------------
# Helper: save one manual fix entry into vector DB
# -------------------------------------------------------------------
MANUAL_BASE_FIELDS = {"error_text", "error", "fix_text",
                      "fix", "approver", "approved_by", "status"}


def _save_manual_fix_entry(entry: Dict[str, Any], source: str = "manual_api") -> Dict[str, Any]:
    """
    Normalizes a dict into (error_text, fix_text, approver, status, metadata)
    and saves it into the vector DB using db.save_fix_to_db(...).
    Returns a small result dict with status and error_text for reporting.
    """
    # 1) Normalize keys
    error_text = (
        entry.get("error_text")
        or entry.get("error")
        or ""
    )
    fix_text = (
        entry.get("fix_text")
        or entry.get("fix")
        or ""
    )
    approver = entry.get("approver") or entry.get("approved_by")
    status = entry.get("status") or "manual"
    if not error_text or not fix_text:
        return {
            "error_text": error_text or "(missing error_text)",
            "status": "skipped",
            "reason": "error_text or fix_text missing",
        }
    # 2) Collect extra metadata (all other keys)
    extra_meta: Dict[str, Any] = {}
    for k, v in entry.items():
        if k in MANUAL_BASE_FIELDS:
            continue
        extra_meta[k] = v
    # 3) Tag manual ingestion
    # distinguish from BFA Slack ("slack")
    extra_meta["source"] = source
    extra_meta.setdefault("ingestion_mode", "manual")
    # 4) Write into Chroma
    try:
        ok = db.save_fix_to_db(
            error_text=error_text,
            fix_text=fix_text,
            approver=approver,
            status=status,
            metadata=extra_meta,
        )
        return {
            "error_text": error_text,
            "status": "imported" if ok else "failed",
        }
    except Exception as e:
        logger.exception("[ManualFix] Failed to save manual fix")
        return {
            "error_text": error_text,
            "status": "failed",
            "reason": str(e),
        }

# -------------------------------------------------------------------
# API: Fix Management — browse, search, edit, delete, reindex, audit
# -------------------------------------------------------------------


class UpdateFixPayload(BaseModel):
    fix_text: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@app.get("/api/fixes")
async def list_fixes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="Text search in error_text and fix_text"),
    status: Optional[str] = Query(None, description="Filter by status (approved, edited, manual)"),
    approver: Optional[str] = Query(None, description="Filter by approved_by"),
    claims=Depends(require_jwt),
):
    """
    List all stored fixes with optional filtering and pagination.
    Results sorted by error_text_length descending (largest first).
    """
    return db.get_all_fixes(
        page=page,
        page_size=page_size,
        search=search,
        status=status,
        approver=approver,
    )


@app.get("/api/fixes/audit")
async def audit_fixes(
    max_chars: int = Query(4000, ge=100, description="Char threshold for oversized detection"),
    claims=Depends(require_jwt),
):
    """
    Find oversized entries that may cause generic matching problems.
    Returns entries where error_text exceeds max_chars, sorted by length descending.
    """
    entries = db.audit_oversized(max_chars=max_chars)
    return {
        "threshold": max_chars,
        "oversized_count": len(entries),
        "entries": entries,
    }


@app.get("/api/fixes/{fix_id}")
async def get_fix_detail(fix_id: str, claims=Depends(require_jwt)):
    """Get full details of a single fix by ID."""
    result = db.get_fix_by_id(fix_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Fix '{fix_id}' not found")
    return result


@app.put("/api/fixes/{fix_id}")
async def update_fix_endpoint(
    fix_id: str,
    payload: UpdateFixPayload,
    claims=Depends(require_jwt),
):
    """
    Update a fix's text and/or metadata. Re-embeds with normalized error text.
    """
    existing = db.get_fix_by_id(fix_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Fix '{fix_id}' not found")

    ok = db.update_fix(
        fix_id=fix_id,
        fix_text=payload.fix_text,
        metadata_updates=payload.metadata,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update fix")
    return {"status": "ok", "id": fix_id}


@app.delete("/api/fixes/{fix_id}")
async def delete_fix_endpoint(fix_id: str, claims=Depends(require_jwt)):
    """Delete a fix from the vector database by ID."""
    existing = db.get_fix_by_id(fix_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Fix '{fix_id}' not found")

    ok = db.delete_fix(fix_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete fix")
    return {"status": "ok", "id": fix_id}


@app.post("/api/fixes/reindex")
async def reindex_fixes(claims=Depends(require_jwt)):
    """
    Re-embed all entries using normalized error text.
    Run this once after deploying normalization to fix existing oversized entries.
    """
    result = db.reindex_all()
    return {"status": "ok", **result}


# -------------------------------------------------------------------
#  Slack: Events + Interactivity
# -------------------------------------------------------------------

#  Utility: get user display name


def get_user_display_name(user_id: str):
    try:
        resp = client.users_info(user=user_id)
        user = resp.get("user", {})
        return user.get("real_name") or user.get("name") or user_id
    except Exception as e:
        print(
            f"[SlackReviewer] Failed to fetch display name for {user_id}: {e}")
        return user_id


#  Slack Event handler (for thread replies to edit fixes)
@app.post("/bfa/slack/events")
async def slack_events(request: Request):
    raw = await request.body()
    headers = request.headers

    # Signature validation
    if not sig_verifier.is_valid_request(raw, headers):
        return JSONResponse(content={"error": "invalid request"}, status_code=403)

    data = await request.json()

    # Slack challenge
    if data.get("type") == "url_verification":
        return JSONResponse(content={"challenge": data.get("challenge")}, status_code=200)

    event = data.get("event", {})
    if event.get("type") == "message" and not event.get("bot_id"):
        channel_id = event.get("channel")
        user_id = event.get("user")
        thread_ts = event.get("thread_ts")
        text = (event.get("text") or "").strip()

        # Identify if user is in edit mode
        pattern = f"last_edit:{channel_id}:*"
        keys = redis_conn.keys(pattern)
        error_id = None
        for key in keys:
            if redis_conn.get(key) == user_id:
                error_id = key.split(":")[-1]
                break

        if not error_id:
            return JSONResponse(content={"status": "ignored"}, status_code=200)

        # Require thread reply
        if not thread_ts:
            client.chat_postMessage(
                channel=channel_id,
                text="⚠️ Please reply *in the thread* of the original fix message to submit your edit.",
                thread_ts=event.get("ts"),
            )
            return JSONResponse(content={"status": "must_reply_in_thread"}, status_code=200)

        # Verify correct thread mapping
        mapped_error_id = redis_conn.get(
            f"thread_map:{channel_id}:{thread_ts}")
        if not mapped_error_id or mapped_error_id != error_id:
            return JSONResponse(content={"status": "wrong_thread"}, status_code=200)

        # Retrieve original error
        stored = get_fix(error_id)
        error_text = stored.get("error", "")
        if not error_text:
            client.chat_postMessage(
                channel=channel_id,
                text="⚠️ Could not find the original error context.",
                thread_ts=thread_ts,
            )
            return JSONResponse(content={"status": "missing_error"}, status_code=200)

        # Save edited fix
        new_fix_text = text
        display_name = get_user_display_name(user_id)
        try:
            db.save_fix_to_db(
                error_text=error_text,
                fix_text=new_fix_text,
                approver=display_name,
                status="edited",
                metadata={
                    "source": "slack",
                    "edited_by": display_name,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
            # --------------------------------------------------------
            # SME CACHE INSERTION
            # --------------------------------------------------------
            message_ts = stored.get("message_ts")
            triggered_by = stored.get("triggered_by")
            existing_meta = stored.get("metadata", {})

            store_fix(
                error_id,
                error_text,
                new_fix_text,
                source="edited",
                approver=display_name,
                message_ts=message_ts,
                channel_id=channel_id,
                triggered_by=triggered_by,
                metadata=existing_meta
            )
            print(
                f"[SlackReviewer] Saved edited fix for {error_text[:50]}... by {display_name}")
            client.chat_postMessage(
                channel=channel_id,
                text="✅ Your edited fix has been saved.",
                thread_ts=thread_ts,
            )
            # --------------------------------------------------------
            # DM DEVELOPER ABOUT SME APPROVAL
            # --------------------------------------------------------
            triggered_by = stored.get("triggered_by")
            if triggered_by:
                send_dev_dm_fix(
                    triggered_by=triggered_by,
                    error_text=error_text,
                    fix_text=new_fix_text,
                    metadata=existing_meta,
                    source="sme_edited",
                )
        except Exception as e:
            print("Error saving edited fix:", e)
            client.chat_postMessage(
                channel=channel_id,
                text=f"❌ Failed to save your edited fix: {e}",
                thread_ts=thread_ts,
            )

        # 6️⃣ Cleanup edit intent
        redis_conn.delete(f"last_edit:{channel_id}:{error_id}")

    return JSONResponse(content={"status": "ok"}, status_code=200)


#  Slack Interactive Actions handler
@app.post("/bfa/slack/actions")
async def slack_actions(request: Request):
    raw = await request.body()
    headers = request.headers

    # Slack signature validation
    if not sig_verifier.is_valid_request(raw, headers):
        return JSONResponse(content={"error": "invalid request"}, status_code=403)

    # Slack sends payload as form
    form_data = await request.form()
    payload_raw = form_data.get("payload")
    if not payload_raw:
        return JSONResponse(content={"error": "missing payload"}, status_code=400)

    payload = json.loads(payload_raw)
    action = payload["actions"][0]
    user_obj = payload.get("user", {})
    user_id = user_obj.get("id")
    approver = get_user_display_name(user_id)
    print(f"[SlackReviewer] Approver name: {approver}")

    action_id = action.get("action_id", "")
    if "_" in action_id:
        action_name, error_id = action_id.split("_", 1)
    else:
        action_name = action_id
        error_id = action.get("value")

    channel_id = payload.get("channel", {}).get("id")
    stored = get_fix(error_id)
    error_text = stored.get("error", "")
    fix_text = stored.get("fix", "")

    if not error_text:
        client.chat_postMessage(
            channel=channel_id, text="⚠️ Original error text not found. Cannot process this action."
        )
        return JSONResponse(content={"status": "missing_error"}, status_code=200)

    response_text = ""

    if action_name == "approve":
        db.save_fix_to_db(
            error_text=error_text,
            fix_text=fix_text,
            approver=approver,
            status="approved",
            metadata={
                "source": "slack",
                "approved_by": approver,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        response_text = f"✅ Fix approved by *{approver}*"
        message_ts = stored.get("message_ts")
        existing_meta = stored.get("metadata", {})
        # Attempt retrieving original triggered_by from stored record
        triggered_by = stored.get("triggered_by") or stored.get("author")
        store_fix(
            error_id,
            error_text,
            fix_text,
            source="approved",
            approver=approver,
            message_ts=message_ts,
            channel_id=channel_id,
            triggered_by=triggered_by,
            metadata=existing_meta
        )
        # --------------------------------------------------------
        # SME CACHE INSERTION
        # --------------------------------------------------------
        error_hash = hashlib.sha256(error_text.encode()).hexdigest()
        sme_key = SME_FIX_KEY.format(error_hash)

        sme_record = {
            "error_text": error_text,
            "fix_text": fix_text,
            "approved_by": approver,
            "timestamp": int(time.time()),
            "source": "sme_approved",
        }

        try:
            r.set(sme_key, json.dumps(sme_record))
            print(f"[SlackReviewer] SME fix stored at {sme_key}")
        except Exception as e:
            print(f"[SlackReviewer] Failed storing SME cache: {e}")

        # --------------------------------------------------------
        # DM DEVELOPER ABOUT SME APPROVAL
        # --------------------------------------------------------
        merged_metadata = stored.get("metadata", {})
        merged_metadata["approved_by"] = approver
        try:
            send_dev_dm_fix(
                triggered_by=triggered_by,
                error_text=error_text,
                fix_text=fix_text,
                metadata=merged_metadata,
                source="sme_approved",
            )
            print(f"[SlackReviewer] DM sent to developer for SME-approved fix")
        except Exception as e:
            print(f"[SlackReviewer] Failed sending developer DM: {e}")

    elif action_name == "edit":
        last_edit_key = f"last_edit:{channel_id}:{error_id}"
        redis_conn.set(last_edit_key, user_id)
        original_ts = stored.get("message_ts") or payload.get(
            "message", {}).get("ts")
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=original_ts,
            text=f"✏️ <@{user_id}> please enter the updated fix here.",
        )
        response_text = f"✏️ Edit mode opened in thread for <@{approver}>"

    elif action_name == "discard":
        response_text = f"🚫 Fix discarded by *{approver}*. It will not be saved."
        redis_conn.delete(f"fix:{error_id}")

    else:
        response_text = "Unknown action."

    #  Disable buttons on original message
    try:
        original_ts = payload.get("message", {}).get("ts")
        old_blocks = payload.get("message", {}).get("blocks", [])
        new_blocks = [b for b in old_blocks if not b.get(
            "block_id", "").startswith("actions_")]
        new_blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"🛑 Reviewed by <@{user_id}> — *{get_past_tense(action_name).upper()}*"}],
            }
        )

        client.chat_update(
            channel=channel_id,
            ts=original_ts,
            text=f"Fix {action_name}d by {approver}",
            blocks=new_blocks,
        )
    except SlackApiError as e:
        print("Slack post error:", e.response.get("error"))

    return JSONResponse(content={"status": "ok"}, status_code=200)


def get_past_tense(action):
    if action.endswith('e'):
        return action + 'd'
    else:
        return action + 'ed'


# -------------------------------------------------------------------
# HEALTHCHECK
# -------------------------------------------------------------------
@app.get("/healthz")
async def health_check():
    status = {"redis": False, "vector_db": False,
              "slack": False, "domain_rag": False}

    # Redis check
    try:
        r.ping()
        status["redis"] = True
    except Exception as e:
        status["redis"] = str(e)

    # Vector DB check
    try:
        if db:
            if hasattr(db, "list_collections"):
                db.list_collections()
            status["vector_db"] = True
        else:
            status["vector_db"] = False
    except Exception as e:
        status["vector_db"] = str(e)

    # Slack check — handles cases where slack variable might not exist
    try:
        if "slack" in globals() and slack:
            slack_client = getattr(slack, "client", None)
            if slack_client and getattr(slack_client, "token", None):
                status["slack"] = "ok"
            else:
                status["slack"] = "client not initialized"
        else:
            status["slack"] = "not configured"
    except Exception as e:
        status["slack"] = str(e)

    # Domain RAG check
    try:
        if _domain_ctx_loaded and _domain_ctx_db is not None:
            status["domain_rag"] = True
        else:
            status["domain_rag"] = False
    except Exception as e:
        status["domain_rag"] = str(e)

    # Determine overall status
    overall_status = (
        "ok" if status["redis"] is True and status["vector_db"] is True else "error"
    )

    return {"status": overall_status, **status}


# -------------------------------------------------------------------
# Middleware for Error notifications
# -------------------------------------------------------------------
@app.middleware("http")
async def global_error_notifier(request: Request, call_next):
    try:
        return await call_next(request)

    except Exception as exc:
        # 🔥 Send Slack DM + Email to alert recipients
        await notify_global_error(exc, request)

        # Return safe JSON error to CI caller
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error occurred in BFA."}
        )


# -------------------------------------------------------------------
# Sample end-point to test email/slack notifications when errors traced
# -------------------------------------------------------------------
@app.get("/api/test/alert")
def test_alert():
    raise RuntimeError("TEST: BFA global alert mechanism")


# Resolve Slack user ID from identifier (email or name) and DM suggested fix
def send_dev_dm_fix(
    triggered_by: Optional[str],
    error_text: str,
    fix_text: str,
    metadata: Dict[str, Any],
    source: str,
):
    """
    Send suggested fix as a direct Slack message to the developer
    whose pipeline failed.

    - triggered_by: expected to be email or username from CI payload
    - source: where this fix came from ("sme_cache", "ai_cache", "vector_db", "ai_generated", etc.)
    - Never raises; logs on failure.
    """
    if not triggered_by:
        logger.info(
            "[DevDM] No 'triggered_by' provided; skipping developer DM.")
        return

    identifier = triggered_by.strip()
    if not identifier:
        logger.info(
            "[DevDM] Empty 'triggered_by' after strip; skipping developer DM.")
        return

    # 1) Resolve Slack user
    user_id = None
    try:
        # Prefer email if it looks like one
        if "@" in identifier:
            resp = client.users_lookupByEmail(email=identifier)
            user_id = resp["user"]["id"]
    except SlackApiError as err:
        logger.warning(
            f"[DevDM] Slack email lookup failed for '{identifier}': {err.response.get('error')}")
    except Exception as e:
        logger.warning(
            f"[DevDM] Unexpected error during email lookup for '{identifier}': {e}")

    # Fallback: fuzzy match by real_name / name
    if not user_id:
        try:
            users = client.users_list().get("members", [])
            ident_lower = identifier.lower()
            for u in users:
                real_name = (u.get("real_name") or "").lower()
                username = (u.get("name") or "").lower()
                if ident_lower in real_name or ident_lower in username:
                    user_id = u["id"]
                    break
        except SlackApiError as e:
            logger.warning(
                f"[DevDM] Slack users_list lookup failed: {e.response.get('error')}")
        except Exception as e:
            logger.warning(
                f"[DevDM] Unexpected error during users_list lookup: {e}")

    if not user_id:
        logger.info(
            f"[DevDM] Could not resolve Slack user for identifier '{identifier}'; skipping DM.")
        return

    # 2) Build DM message text
    repo = metadata.get("repo") or "N/A"
    branch = metadata.get("branch") or "N/A"
    commit = metadata.get("commit") or "N/A"
    job_name = metadata.get("job_name") or "N/A"
    step_name = metadata.get("step_name") or "N/A"
    pipeline_id = metadata.get("pipeline_id") or "N/A"

    # Summarize the error to keep DM compact
    short_error = (error_text or "").strip()
    if len(error_text) > 300 or "\n" in error_text:
        short_error = summarize_error_with_ai(error_text)
    else:
        short_error = f"{error_text}"

    # Decide whether to show disclaimer
    disclaimer = ""
    if source in ("ai_generated", "ai_cache"):
        disclaimer = """
---

⚠️ *Disclaimer:*
This fix is *AI-generated and not yet DevOps-approved*.
If you do not want to wait for SME review, you may try these steps to unblock your pipeline —
but please validate the fix and use engineering judgment.

DevOps will follow up with an official approved fix if required.
        """.strip()

    dm_text = f"""
🧠 *Build Failure Analyzer – Suggested Fix*

📁 *Repo:* `{repo}`
🌿 *Branch:* `{branch}`
🔖 *Commit:* `{commit}`
⚙️ *Job:* `{job_name}`
🧩 *Step:* `{step_name}`
📌 *Pipeline ID:* `{pipeline_id}`
🔍 *Fix source:* `{source}`

❌ *Error (Summary):*
> {short_error}

✅ *Suggested fix:*

{fix_text}

{disclaimer}
    """.strip()

    # 3) Send DM (non-fatal on error)
    try:
        client.chat_postMessage(channel=user_id, text=dm_text)
        logger.info(
            f"[DevDM] Sent suggested fix DM to '{identifier}' (user_id={user_id}) source={source}.")
    except SlackApiError as e:
        logger.warning(
            f"[DevDM] Failed to send DM to '{identifier}' (user_id={user_id}): {e.response.get('error')}")
    except Exception as e:
        logger.warning(
            f"[DevDM] Unexpected error sending DM to '{identifier}' (user_id={user_id}): {e}")


# -------------------------------------------------------------------
# Entrypoint
# -------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("analyzer_service:app", host="0.0.0.0", port=8000, reload=True)
