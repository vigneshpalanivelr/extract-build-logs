#!/home/build-failure-analyzer/build-failure-analyzer/.venv/bin/python3

"""
- VectorDBClient: wrapper around Chroma collection + Ollama embedding
- init_vector_db(): initializer
- save_fix_to_db(): function wrapper
"""

import os
import re
import math
import json
import time
import hashlib
import logging
from typing import List, Dict, Optional, Any, Tuple

import chromadb
import requests
import subprocess

from dotenv import load_dotenv

load_dotenv()

# Environment / defaults
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "/home/build-failure-analyzer/data/chroma")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "fix_embeddings")
OLLAMA_HTTP_URL = os.getenv("OLLAMA_HTTP_URL", "http://127.0.0.1:99999")
OLLAMA_CLI_PATH = os.getenv("OLLAMA_CLI_PATH", "ollama")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "granite-embedding")
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.78"))

# Normalization limits
MAX_ERROR_LINES = int(os.getenv("MAX_ERROR_LINES", "80"))
MAX_ERROR_CHARS = int(os.getenv("MAX_ERROR_CHARS", "4000"))

# Length penalty for similarity scoring
LENGTH_PENALTY_ALPHA = float(os.getenv("LENGTH_PENALTY_ALPHA", "0.15"))

# Regex: strip "Line 123: " prefixes added by log-extraction service
_LINE_PREFIX_RE = re.compile(r"^Line\s+\d+:\s*", re.IGNORECASE)

# Error-signal keywords (case-insensitive match)
_ERROR_KEYWORDS = re.compile(
    r"(?i)\b("
    r"error|err!|fail|fatal|exception|traceback|panic|denied|timeout|refused|"
    r"killed|oom|segfault|abort|critical|undefined.reference|cannot.find|"
    r"no.such.file|permission|not.found|exit.code|returned.\d+|"
    r"compilation.error|build.failed|npm.err|syntaxerror|"
    r"importerror|modulenotfounderror|keyerror|typeerror|"
    r"valueerror|attributeerror|runtimeerror|nullpointer|"
    r"outofmemory|stacktrace|coredump|signal.\d+"
    r")\b"
)

# Logging
logger = logging.getLogger("vector_db")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


class VectorDBClient:
    def __init__(self, persist_path: Optional[str] = None):
        """
        Initialize Chroma persistent client and collection.
        """
        self.persist_path = persist_path or CHROMA_DB_PATH
        try:
            # Persistent client; path should be writable
            self.client = chromadb.PersistentClient(path=self.persist_path)
            self.collection = self.client.get_or_create_collection(name=CHROMA_COLLECTION)
            logger.info(f"[VectorDB] Connected to Chroma collection '{CHROMA_COLLECTION}' (path={self.persist_path})")
        except Exception as e:
            logger.exception(f"[VectorDB] Failed to initialize Chroma client: {e}")
            raise

    # -----------------------
    # Embedding helpers
    # -----------------------
    def _get_embedding_ollama_http(self, text: str) -> Optional[List[float]]:
        """
        Call Ollama HTTP embedding endpoint: POST {OLLAMA_HTTP_URL}/api/embed
        Accepts multiple response shapes returned by various Ollama versions.
        """
        try:
            url = f"{OLLAMA_HTTP_URL.rstrip('/')}/api/embed"
            payload = {"model": OLLAMA_EMBED_MODEL, "input": text}
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # Known response shapes:
            # 1) {"model": "...", "embeddings": [[...]], ...}
            # 2) {"embedding": [...]} (single embedding)
            # 3) {"data": [{"embedding": [...]}]}
            if isinstance(data, dict):
                if "embeddings" in data and isinstance(data["embeddings"], list) and len(data["embeddings"]) > 0:
                    # Return first embedding
                    return data["embeddings"][0]
                if "embedding" in data and isinstance(data["embedding"], list):
                    return data["embedding"]
                if "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
                    candidate = data["data"][0]
                    if isinstance(candidate, dict) and "embedding" in candidate:
                        return candidate["embedding"]
            # fallback
            logger.debug("[VectorDB] Ollama HTTP embed returned unexpected shape: %s", data)
            return None
        except Exception as e:
            logger.debug(f"[VectorDB] Ollama HTTP embedding failed: {e}")
            return None

    def _get_embedding_ollama_cli(self, text: str) -> Optional[List[float]]:
        """
        Fallback using ollama CLI. Behavior depends on CLI version/flags.
        Try a safe invocation and parse JSON output if present.
        """
        try:
            # Try to call `ollama api/embed <model>` with stdin if available
            # CLI differences make this a best-effort fallback.
            # We will attempt `ollama api/embed <model>` (newer) or `ollama embed <model>` (older)
            try_cmds = [
                [OLLAMA_CLI_PATH, "api", "embed", OLLAMA_EMBED_MODEL, "--json"],
                [OLLAMA_CLI_PATH, "embed", OLLAMA_EMBED_MODEL, "--json"],
                [OLLAMA_CLI_PATH, "run", OLLAMA_EMBED_MODEL, "--json"],
            ]
            for cmd in try_cmds:
                try:
                    proc = subprocess.run(cmd, input=text.encode("utf-8"), capture_output=True, timeout=30)
                except TypeError:
                    # older Python versions may need text param
                    proc = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=30)
                if proc.returncode == 0:
                    out = proc.stdout.decode("utf-8") if isinstance(proc.stdout, (bytes, bytearray)) else proc.stdout
                    if out:
                        try:
                            parsed = json.loads(out)
                            # parse same shapes as HTTP
                            if "embeddings" in parsed and parsed["embeddings"]:
                                return parsed["embeddings"][0]
                            if "embedding" in parsed:
                                return parsed["embedding"]
                            if "data" in parsed and parsed["data"]:
                                return parsed["data"][0].get("embedding")
                        except Exception:
                            # Not JSON? ignore and continue
                            logger.debug("[VectorDB] Ollama CLI returned non-JSON output")
                # if returncode nonzero, try next
            logger.debug("[VectorDB] Ollama CLI did not produce an embedding")
            return None
        except Exception as e:
            logger.debug(f"[VectorDB] Ollama CLI embedding failed: {e}")
            return None

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """
        Try HTTP endpoint first, then CLI fallback.
        """
        emb = self._get_embedding_ollama_http(text)
        if emb:
            logger.debug("[VectorDB] Obtained embedding from Ollama HTTP")
            return emb
        emb = self._get_embedding_ollama_cli(text)
        if emb:
            logger.debug("[VectorDB] Obtained embedding from Ollama CLI")
            return emb
        logger.warning("[VectorDB] No embedding available from Ollama (HTTP+CLI).")
        return None

    # -----------------------
    # Text normalization
    # -----------------------
    def _normalize_error_text(self, error_text: str) -> str:
        """
        Normalize error text before embedding to improve match quality.

        Steps:
        1. Strip 'Line NNN:' prefixes (added by log-extraction, not useful for matching)
        2. Remove empty / whitespace-only lines
        3. Deduplicate exact-match lines (keep first occurrence)
        4. Prioritize lines containing error-signal keywords
        5. Cap at MAX_ERROR_LINES and MAX_ERROR_CHARS

        This ensures embeddings are driven by actual error signals rather than
        pages of build output, preventing oversized logs from creating generic
        embeddings that match everything.
        """
        lines = error_text.split("\n")

        # Step 1+2: Strip line-number prefixes and remove empty lines
        cleaned = []
        for line in lines:
            stripped = _LINE_PREFIX_RE.sub("", line).strip()
            if stripped:
                cleaned.append(stripped)

        # Step 3: Deduplicate (preserve order, keep first occurrence)
        seen = set()
        deduped = []
        for line in cleaned:
            if line not in seen:
                seen.add(line)
                deduped.append(line)

        # Step 4: Separate error-signal lines from context lines
        error_lines = []
        context_lines = []
        for line in deduped:
            if _ERROR_KEYWORDS.search(line):
                error_lines.append(line)
            else:
                context_lines.append(line)

        # Step 5: Fill slots — error-signal lines first, then context
        selected = error_lines[:MAX_ERROR_LINES]
        remaining_slots = MAX_ERROR_LINES - len(selected)
        if remaining_slots > 0:
            selected.extend(context_lines[:remaining_slots])

        result = "\n".join(selected)

        # Hard character cap
        if len(result) > MAX_ERROR_CHARS:
            result = result[:MAX_ERROR_CHARS]

        return result

    # -----------------------
    # ID helper
    # -----------------------
    def _generate_id(self, error_text: str) -> str:
        """
        Deterministic id for an error_text. If you prefer unique IDs per save, append timestamp.
        """
        h = hashlib.sha1(error_text.encode("utf-8")).hexdigest()
        return f"fix-{h}"

    # -----------------------
    # Core ops
    # -----------------------
    def lookup_existing_fix(
        self,
        error_text: str,
        top_k: int = 5,   # keep default for compatibility
        similarity_threshold: float = SIMILARITY_THRESHOLD,
        embedding_vector: Optional[List[float]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Query Chroma for similar fixes to error_text.
        Returns dict {fix_text, confidence, source, metadata} or None.
        Ensures padded/empty Chroma entries are ignored.
        Only BEST valid match is considered.
        """

        # Keep original length for length-penalty calculation
        original_query_len = len(error_text)

        # Normalize query text before embedding (same normalization as save)
        normalized_query = self._normalize_error_text(error_text)

        # Compute embedding for the normalized query
        if embedding_vector is None:
            vector = self._get_embedding(normalized_query)
            if vector is None:
                logger.info("[VectorDB] No embedding produced, skipping lookup.")
                return None
        else:
            vector = embedding_vector

        # Query Chroma
        try:
            res = self.collection.query(
                query_embeddings=[vector],
                n_results=top_k,
                include=["metadatas", "documents", "distances"],
            )
        except Exception as e:
            logger.exception(f"[VectorDB] Query failed: {e}")
            return None

        ids = res.get("ids", [])
        if not ids or not ids[0]:
            return None

        distances = res.get("distances", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]

        # Build list of valid candidates with length-penalized scoring
        candidates = []  # (adjusted_sim, raw_sim, index)
        for i, dist in enumerate(distances):
            doc = docs[i]
            meta = metas[i] or {}

            # Skip empty / padded chroma entries
            if not doc or doc.strip() == "" or doc.strip() == "(empty fix)":
                continue

            try:
                raw_sim = 1 - dist
            except Exception:
                continue

            # Length-aware penalty: if stored error_text is much longer than
            # query, the match is less trustworthy because the embedding is
            # more generic. See ENHANCED_VECTOR_DB.md for detailed examples.
            stored_error = meta.get("error_text") or ""
            stored_len = len(stored_error)
            query_len = original_query_len

            if stored_len > 0 and query_len > 0:
                length_ratio = max(stored_len, query_len) / max(min(stored_len, query_len), 1)
                penalty = 1.0 / (1.0 + LENGTH_PENALTY_ALPHA * math.log(max(length_ratio, 1.0)))
                adjusted_sim = raw_sim * penalty
            else:
                adjusted_sim = raw_sim
                penalty = 1.0

            logger.debug(
                f"[VectorDB] Candidate {i}: raw_sim={raw_sim:.4f}, "
                f"stored_len={stored_len}, query_len={query_len}, "
                f"penalty={penalty:.4f}, adjusted_sim={adjusted_sim:.4f}"
            )
            candidates.append((adjusted_sim, raw_sim, i))

        # No valid candidates
        if not candidates:
            return None

        # From all candidates -> pick BEST adjusted similarity only
        candidates.sort(reverse=True, key=lambda x: x[0])
        best_adjusted, best_raw, idx = candidates[0]

        logger.info(
            f"============== Best Similarity Score: {best_adjusted:.4f} "
            f"(raw: {best_raw:.4f}) ============="
        )

        # Validate threshold using adjusted score
        if best_adjusted <= similarity_threshold:
            return None

        # Return in your required format
        return {
            "fix_text": docs[idx],
            "confidence": best_adjusted,
            "raw_confidence": best_raw,
            "source": "vector_db",
            "metadata": metas[idx],
        }

    def save_fix_to_db(self, error_text, fix_text, approver=None, status=None, metadata=None):
        """
        Save a fix to the vector database with optional metadata for approver and status.
        Ensures all metadata is Chroma-safe (flat + primitive types only).
        """
        metadata = metadata or {}
        # Always ensure error_text and fix_text have valid string values
        error_text = error_text or "(missing error)"
        fix_text = fix_text or "(no fix provided)"

        # Attach approver + status into metadata
        if approver:
            metadata["approved_by"] = approver
        if status:
            metadata["status"] = status

        # Flatten nested dicts, keep only Chroma-safe primitives
        flat_metadata = {}
        for key, value in metadata.items():
            if isinstance(value, dict):
                for subkey, subval in value.items():
                    flat_metadata[f"{key}_{subkey}"] = str(subval)
            elif isinstance(value, (str, int, float, bool)) or value is None:
                flat_metadata[key] = value
            else:
                # catchall: convert unsupported types (lists, tuples, objects) to string
                flat_metadata[key] = str(value)

        try:
            # Normalize error text for embedding quality; keep original in metadata
            normalized_error = self._normalize_error_text(error_text)
            flat_metadata["original_error_length"] = len(error_text)
            flat_metadata["normalized"] = "true"

            embedding = self._get_embedding(normalized_error)
            if not embedding:
                logging.warning("[VectorDB] No embedding available, skipping save.")
                return False

            # Deterministic, readable ID
            unique_id = f"fix-{abs(hash(error_text)) & ((1 << 128) - 1):032x}"

            logging.info(f"[VectorDB] Saving fix: id={unique_id}, approver={approver}, fields={len(flat_metadata)}")

            # Guaranteed non-empty fields in Chroma
            self.collection.add(
                documents=[fix_text],
                metadatas=[{
                    "error_text": error_text,
                    **flat_metadata,
                }],
                embeddings=[embedding],
                ids=[unique_id],
            )

            logging.info(f"[VectorDB] Saved fix to DB id={unique_id} approver={approver} status={status}")
            return True

        except Exception as e:
            logging.exception(f"[VectorDB] save_fix_to_db() failed: {e}")
            return False

    # -----------------------
    # Fix management methods
    # -----------------------
    def get_all_fixes(
        self,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        status: Optional[str] = None,
        approver: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetch all fixes with optional filtering and pagination.
        ChromaDB doesn't support complex queries, so we filter in Python.
        """
        all_docs = self.collection.get(include=["documents", "metadatas"])
        ids = all_docs.get("ids", [])
        docs = all_docs.get("documents", [])
        metas = all_docs.get("metadatas", [])

        # Build result list with filtering
        fixes = []
        for i, doc_id in enumerate(ids):
            meta = metas[i] or {}
            error_text = meta.get("error_text", "")
            fix_text = docs[i] or ""

            # Apply filters
            if search and search.lower() not in error_text.lower() and search.lower() not in fix_text.lower():
                continue
            if status and meta.get("status", "") != status:
                continue
            if approver and meta.get("approved_by", "") != approver:
                continue

            fixes.append({
                "id": doc_id,
                "error_text": error_text,
                "error_text_length": len(error_text),
                "fix_text": fix_text,
                "status": meta.get("status", "unknown"),
                "approved_by": meta.get("approved_by", ""),
                "normalized": meta.get("normalized", "false"),
                "metadata": meta,
            })

        # Sort by error_text_length descending (largest first for visibility)
        fixes.sort(key=lambda x: x["error_text_length"], reverse=True)

        total = len(fixes)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "fixes": fixes[start:end],
        }

    def get_fix_by_id(self, fix_id: str) -> Optional[Dict[str, Any]]:
        """Get a single fix by its ID."""
        try:
            result = self.collection.get(ids=[fix_id], include=["documents", "metadatas"])
            ids = result.get("ids", [])
            if not ids:
                return None
            meta = (result.get("metadatas") or [{}])[0] or {}
            doc = (result.get("documents") or [""])[0] or ""
            return {
                "id": fix_id,
                "error_text": meta.get("error_text", ""),
                "error_text_length": len(meta.get("error_text", "")),
                "fix_text": doc,
                "status": meta.get("status", "unknown"),
                "approved_by": meta.get("approved_by", ""),
                "normalized": meta.get("normalized", "false"),
                "metadata": meta,
            }
        except Exception:
            return None

    def update_fix(self, fix_id: str, fix_text: Optional[str] = None, metadata_updates: Optional[Dict] = None) -> bool:
        """
        Update a fix's document and/or metadata. Re-embeds with normalized error text.
        """
        try:
            existing = self.collection.get(ids=[fix_id], include=["documents", "metadatas"])
            if not existing.get("ids"):
                return False

            current_doc = (existing.get("documents") or [""])[0] or ""
            current_meta = (existing.get("metadatas") or [{}])[0] or {}

            new_doc = fix_text if fix_text is not None else current_doc
            new_meta = dict(current_meta)
            if metadata_updates:
                new_meta.update(metadata_updates)

            # Re-embed with normalized error text
            error_text = new_meta.get("error_text", "")
            normalized = self._normalize_error_text(error_text)
            embedding = self._get_embedding(normalized)

            new_meta["normalized"] = "true"
            new_meta["original_error_length"] = len(error_text)

            update_kwargs = {
                "ids": [fix_id],
                "documents": [new_doc],
                "metadatas": [new_meta],
            }
            if embedding:
                update_kwargs["embeddings"] = [embedding]

            self.collection.update(**update_kwargs)
            return True
        except Exception as e:
            logger.exception(f"[VectorDB] update_fix failed: {e}")
            return False

    def delete_fix(self, fix_id: str) -> bool:
        """Delete a fix by ID."""
        try:
            self.collection.delete(ids=[fix_id])
            return True
        except Exception as e:
            logger.exception(f"[VectorDB] delete_fix failed: {e}")
            return False

    def reindex_all(self) -> Dict[str, Any]:
        """
        Re-embed all entries using normalized error text.
        Returns summary of reindexed/failed/skipped counts.
        """
        all_docs = self.collection.get(include=["documents", "metadatas"])
        ids = all_docs.get("ids", [])
        docs = all_docs.get("documents", [])
        metas = all_docs.get("metadatas", [])

        reindexed = 0
        failed = 0
        skipped = 0

        for i, doc_id in enumerate(ids):
            meta = metas[i] or {}
            error_text = meta.get("error_text", "")
            if not error_text:
                skipped += 1
                continue

            normalized = self._normalize_error_text(error_text)
            embedding = self._get_embedding(normalized)
            if not embedding:
                failed += 1
                continue

            try:
                updated_meta = dict(meta)
                updated_meta["normalized"] = "true"
                updated_meta["original_error_length"] = len(error_text)

                self.collection.update(
                    ids=[doc_id],
                    embeddings=[embedding],
                    metadatas=[updated_meta],
                )
                reindexed += 1
            except Exception as e:
                logger.warning(f"[VectorDB] Failed to reindex {doc_id}: {e}")
                failed += 1

        return {
            "total": len(ids),
            "reindexed": reindexed,
            "failed": failed,
            "skipped": skipped,
        }

    def audit_oversized(self, max_chars: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        List entries where error_text exceeds max_chars, sorted by length descending.
        Helps identify problematic entries that may cause generic matching.
        """
        threshold = max_chars or MAX_ERROR_CHARS
        all_docs = self.collection.get(include=["documents", "metadatas"])
        ids = all_docs.get("ids", [])
        docs = all_docs.get("documents", [])
        metas = all_docs.get("metadatas", [])

        oversized = []
        for i, doc_id in enumerate(ids):
            meta = metas[i] or {}
            error_text = meta.get("error_text", "")
            if len(error_text) > threshold:
                oversized.append({
                    "id": doc_id,
                    "error_text_length": len(error_text),
                    "error_text_preview": error_text[:200] + "..." if len(error_text) > 200 else error_text,
                    "fix_text_preview": (docs[i] or "")[:200],
                    "status": meta.get("status", "unknown"),
                    "approved_by": meta.get("approved_by", ""),
                    "normalized": meta.get("normalized", "false"),
                })

        oversized.sort(key=lambda x: x["error_text_length"], reverse=True)
        return oversized

    # -----------------------
    # Passthrough helpers (so helper scripts can keep using collection methods)
    # -----------------------
    def get(self, **kwargs):
        """Return collection.get(...)"""
        return self.collection.get(**kwargs)

    def delete(self, **kwargs):
        """Delete documents from the collection"""
        return self.collection.delete(**kwargs)

    def count(self) -> int:
        try:
            info = self.collection.count()
            # Some Chroma versions return dict/number
            if isinstance(info, dict) and "count" in info:
                return int(info["count"])
            if isinstance(info, int):
                return info
            return 0
        except Exception:
            return 0


# -----------------------
# Backwards-compatible utilities
# -----------------------
def init_vector_db(persist_directory: Optional[str] = None) -> VectorDBClient:
    """
    Instantiate and return VectorDBClient (backwards-compatible name).
    """
    persist_directory = persist_directory or CHROMA_DB_PATH
    client = VectorDBClient(persist_path=persist_directory)
    logger.info(f"[VectorDB] init_vector_db() -> {persist_directory}")
    return client


def save_fix_to_db(db_client, error_text, fix_text, approver=None, status="generated", metadata=None):
    """
    Prevents premature saves when called from resolver or AI generation stages.
    Only allow writes for 'approved' or 'edited' fixes.
    """
    # Guard: skip if it's a generated or empty fix
    if status not in ("approved", "edited"):
        logging.info(f"[VectorDB] Skipping save_fix_to_db() wrapper call — premature status '{status}'")
        return False

    if not fix_text or not fix_text.strip():
        logging.info("[VectorDB] Skipping save_fix_to_db() wrapper call — empty fix_text")
        return False

    if not hasattr(db_client, "save_fix_to_db"):
        raise AttributeError("db_client has no method save_fix_to_db")
    
    return db_client.save_fix_to_db(
        error_text=error_text,
        fix_text=fix_text,
        approver=approver,
        status=status,
        metadata=metadata,
    )


# If this module is executed directly, allow a basic sanity check
if __name__ == "__main__":
    c = init_vector_db()
    print("Collection count:", c.count())