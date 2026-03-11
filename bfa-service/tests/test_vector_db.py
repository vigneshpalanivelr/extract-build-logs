import pytest
from unittest.mock import MagicMock
from vector_db import VectorDBClient


@pytest.fixture
def vector_db(mocker):
    mocker.patch("vector_db.chromadb.PersistentClient")
    db = VectorDBClient(persist_path="/tmp/chroma-test")

    # Mock collection
    db.collection = MagicMock()
    return db


def test_save_fix_to_db(mocker, vector_db):
    mocker.patch.object(
        vector_db,
        "_get_embedding",
        return_value=[0.1, 0.2, 0.3]
    )

    ok = vector_db.save_fix_to_db(
        error_text="gcc failed",
        fix_text="Install gcc",
        approver="SME",
        status="approved",
        metadata={"repo": "repo1"}
    )

    assert ok is True
    vector_db.collection.add.assert_called_once()


def test_lookup_existing_fix_returns_result(mocker, vector_db):
    mocker.patch.object(
        vector_db,
        "_get_embedding",
        return_value=[0.1, 0.2, 0.3]
    )

    mocker.patch.object(
        vector_db.collection,
        "query",
        return_value={
            "ids": [["id1"]],
            "documents": [["Fix gcc"]],
            "metadatas": [[{"status": "approved"}]],
            "distances": [[0.05]],
        }
    )

    result = vector_db.lookup_existing_fix("gcc failed")

    assert isinstance(result, dict)
    assert result["source"] == "vector_db"
    assert result["fix_text"] == "Fix gcc"


def test_lookup_respects_top_k(mocker, vector_db):
    mocker.patch.object(vector_db, "_get_embedding", return_value=[0.1])

    query_spy = mocker.patch.object(
        vector_db.collection,
        "query",
        return_value={
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
    )

    vector_db.lookup_existing_fix("timeout", top_k=3)

    query_spy.assert_called_once()
    assert query_spy.call_args.kwargs["n_results"] == 3


def test_lookup_returns_none_when_no_hits(mocker, vector_db):
    mocker.patch.object(vector_db, "_get_embedding", return_value=[0.1])

    mocker.patch.object(
        vector_db.collection,
        "query",
        return_value={
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
    )

    result = vector_db.lookup_existing_fix("unknown error")
    assert result is None


def test_save_fix_with_minimal_metadata(mocker, vector_db):
    mocker.patch.object(vector_db, "_get_embedding", return_value=[0.1])

    ok = vector_db.save_fix_to_db(
        error_text="error",
        fix_text="fix",
        status="approved"
    )

    assert ok is True
    vector_db.collection.add.assert_called_once()


def test_vector_db_handles_embedding_failure(mocker, vector_db):
    mocker.patch.object(vector_db, "_get_embedding", return_value=None)

    ok = vector_db.save_fix_to_db(
        error_text="error",
        fix_text="fix",
        status="approved"
    )

    assert ok is False