#!/home/build-failure-analyzer/build-failure-analyzer/.venv/bin/python3

import json
from typing import List, Dict, Any

from vector_db import VectorDBClient  # reuse embedding + Chroma client
from logging_config import get_logger
from config_loader import config as cfg

DOMAIN_CONTEXT_COLLECTION = cfg.domain_context_collection

logger = get_logger("pipeline_context_rag")


# -------------------------------
#  Load Domain Context File
# -------------------------------
def load_domain_context(path: str) -> Dict[str, List[Dict[str, str]]]:
    """
    Load domain_context.txt which is a JSON file in the form:

    {
      "IT": [
        {"failure": "...", "solution": "..."},
        ...
      ],
      "Product": [...],
      "Devops": [...]
    }
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Domain context file not found: {path}")

    with open(path, "r") as f:
        return json.load(f)


# -------------------------------
#  Create a Separate Chroma Collection
# -------------------------------
def init_context_collection(persist_dir: str) -> VectorDBClient:
    """
    Create a VectorDBClient pointing at the same Chroma DB path,
    but switch its .collection to a dedicated 'pipeline_context' collection.

    This:
      - reuses the same embedding logic (Ollama)
      - keeps fix_embeddings collection used by existing code untouched
    """
    ctx_db = VectorDBClient(persist_path=persist_dir)

    # By default, VectorDBClient uses CHROMA_COLLECTION (fix_embeddings).
    # Here we override just the collection to a different name.
    try:
        # ctx_db.client is the underlying chromadb.PersistentClient
        ctx_db.collection = ctx_db.client.get_or_create_collection(
            name=DOMAIN_CONTEXT_COLLECTION
        )
        logger.info(
            "[RAG] Initialized domain context collection 'pipeline_context' at %s",
            persist_dir,
        )
    except Exception:
        logger.exception("[RAG] Failed to create/use 'pipeline_context' collection")
        raise

    return ctx_db


# -------------------------------
#  Index Domain Patterns
# -------------------------------
def index_domain_patterns(context_data: Dict[str, Any], ctx_db: VectorDBClient) -> None:
    """
    Insert each (failure → solution) pair into Chroma.

    document = failure (pattern snippet from domain_context.txt)
    metadata = { "solution": ..., "category": ... }
    """
    total = 0
    for category, items in context_data.items():
        for entry in items:
            failure = entry.get("failure") or ""
            solution = entry.get("solution") or ""

            if not failure.strip():
                continue

            try:
                embedding = ctx_db._get_embedding(failure)
            except Exception:
                logger.exception("[RAG] Failed to embed domain pattern, skipping")
                continue

            if embedding is None:
                continue

            try:
                ctx_db.collection.add(
                    documents=[failure],
                    embeddings=[embedding],
                    metadatas=[{
                        "category": category,
                        "solution": solution,
                    }],
                    ids=[f"context-{abs(hash(failure))}"],
                )
                total += 1
            except Exception:
                logger.exception(
                    "[RAG] Failed to add domain pattern to Chroma, skipping"
                )

    logger.info(f"[RAG] Indexed domain patterns: {total}")


# -------------------------------
#  Query Relevant Patterns
# -------------------------------
def lookup_domain_matches(
    error_text: str,
    ctx_db: VectorDBClient,
    threshold: float = 0.55,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Query domain context collection for patterns similar to the given error_text.

    Returns:
      [
         {
            "failure": "...",
            "solution": "...",
            "similarity": 0.91,
            "category": "IT"
         }
      ]
    """
    if ctx_db is None:
        return []

    vector = ctx_db._get_embedding(error_text)
    if vector is None:
        return []

    try:
        res = ctx_db.collection.query(
            query_embeddings=[vector],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        logger.exception(f"[RAG] Domain context query failed: {e}")
        return []

    docs = (res.get("documents") or [[]])[0] or []
    metas = (res.get("metadatas") or [[]])[0] or []
    distances = (res.get("distances") or [[]])[0] or []

    matches: List[Dict[str, Any]] = []
    for i, dist in enumerate(distances):
        similarity = 1 - dist
        if similarity < threshold:
            continue

        matches.append({
            "failure": docs[i],
            "solution": metas[i].get("solution"),
            "category": metas[i].get("category"),
            "similarity": similarity,
        })

    return matches
