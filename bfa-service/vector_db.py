#!/home/build-failure-analyzer/build-failure-analyzer/.venv/bin/python3

"""
- VectorDBClient: wrapper around Chroma collection + Ollama embedding
- init_vector_db(): initializer
- save_fix_to_db(): function wrapper
"""

import os
import json
import time
import hashlib
import logging
from typing import List, Dict, Optional, Any

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

        # Compute embedding for the query
        if embedding_vector is None:
            vector = self._get_embedding(error_text)
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

        # Build list of valid candidates
        candidates = []
        for i, dist in enumerate(distances):
            doc = docs[i]
            meta = metas[i]

            # Skip empty / padded chroma entries
            if not doc or doc.strip() == "" or doc.strip() == "(empty fix)":
                continue

            try:
                sim = 1 - dist
            except Exception:
                continue

            candidates.append((sim, i))

        # No valid candidates
        if not candidates:
            return None

        # From all candidates → pick BEST similarity only
        candidates.sort(reverse=True, key=lambda x: x[0])
        best_sim, idx = candidates[0]

        logger.info(f"============== Best Similarity Score: {best_sim} =============")

        # Validate threshold
        if best_sim <= similarity_threshold:
            return None

        # Return in your required format
        return {
            "fix_text": docs[idx],
            "confidence": best_sim,
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
            # Always embed based on error_text
            embedding = self._get_embedding(error_text)
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