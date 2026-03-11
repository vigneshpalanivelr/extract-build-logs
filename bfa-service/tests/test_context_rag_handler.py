import json
import pytest
from types import SimpleNamespace

import pipeline_context_rag


# -------------------------------------------------
# Fixtures
# -------------------------------------------------

@pytest.fixture
def sample_domain_context():
    return {
        "IT": [
            {"failure": "disk full", "solution": "cleanup disk"},
            {"failure": "permission denied", "solution": "fix permissions"},
        ],
        "Devops": [
            {"failure": "docker build failed", "solution": "check Dockerfile"}
        ],
    }


@pytest.fixture
def fake_ctx_db(mocker):
    """
    Fake VectorDBClient with mocked embedding + collection.
    """
    db = SimpleNamespace()

    db._get_embedding = mocker.Mock(return_value=[0.1, 0.2, 0.3])

    db.collection = SimpleNamespace()
    db.collection.add = mocker.Mock()
    db.collection.query = mocker.Mock()

    return db


# -------------------------------------------------
# load_domain_context
# -------------------------------------------------

def test_load_domain_context_success(tmp_path, sample_domain_context):
    path = tmp_path / "domain.json"
    path.write_text(json.dumps(sample_domain_context))

    data = pipeline_context_rag.load_domain_context(str(path))

    assert data == sample_domain_context


def test_load_domain_context_missing_file():
    with pytest.raises(FileNotFoundError):
        pipeline_context_rag.load_domain_context("/no/such/file.json")


# -------------------------------------------------
# init_context_collection
# -------------------------------------------------

def test_init_context_collection_overrides_collection(mocker):
    fake_client = mocker.Mock()
    fake_collection = mocker.Mock()

    fake_client.get_or_create_collection.return_value = fake_collection

    mocker.patch(
        "pipeline_context_rag.VectorDBClient",
        return_value=SimpleNamespace(
            client=fake_client,
            collection=None,
        ),
    )

    ctx_db = pipeline_context_rag.init_context_collection("/tmp/chroma")

    fake_client.get_or_create_collection.assert_called_once_with(
        name="pipeline_context"
    )
    assert ctx_db.collection == fake_collection


# -------------------------------------------------
# index_domain_patterns
# -------------------------------------------------

def test_index_domain_patterns_adds_entries(sample_domain_context, fake_ctx_db):
    pipeline_context_rag.index_domain_patterns(
        sample_domain_context,
        fake_ctx_db,
    )

    # 3 valid failures → 3 inserts
    assert fake_ctx_db.collection.add.call_count == 3


def test_index_domain_patterns_skips_empty_failure(fake_ctx_db):
    data = {
        "IT": [
            {"failure": "", "solution": "noop"},
            {"failure": "valid error", "solution": "fix"},
        ]
    }

    pipeline_context_rag.index_domain_patterns(data, fake_ctx_db)

    fake_ctx_db.collection.add.assert_called_once()


def test_index_domain_patterns_skips_when_embedding_none(mocker, fake_ctx_db):
    fake_ctx_db._get_embedding = mocker.Mock(return_value=None)

    data = {
        "IT": [{"failure": "disk error", "solution": "fix disk"}]
    }

    pipeline_context_rag.index_domain_patterns(data, fake_ctx_db)

    fake_ctx_db.collection.add.assert_not_called()


def test_index_domain_patterns_handles_add_exception(mocker, fake_ctx_db):
    fake_ctx_db.collection.add.side_effect = Exception("chroma down")

    data = {
        "IT": [{"failure": "disk error", "solution": "fix disk"}]
    }

    # Should NOT raise
    pipeline_context_rag.index_domain_patterns(data, fake_ctx_db)


# -------------------------------------------------
# lookup_domain_matches
# -------------------------------------------------

def test_lookup_domain_matches_returns_matches(fake_ctx_db):
    fake_ctx_db.collection.query.return_value = {
        "documents": [["disk full"]],
        "metadatas": [[{"solution": "cleanup", "category": "IT"}]],
        "distances": [[0.1]],  # similarity = 0.9
    }

    results = pipeline_context_rag.lookup_domain_matches(
        error_text="disk full error",
        ctx_db=fake_ctx_db,
        threshold=0.5,
        top_k=5,
    )

    assert len(results) == 1
    assert results[0]["failure"] == "disk full"
    assert results[0]["solution"] == "cleanup"
    assert results[0]["category"] == "IT"
    assert results[0]["similarity"] > 0.5


def test_lookup_domain_matches_respects_threshold(fake_ctx_db):
    fake_ctx_db.collection.query.return_value = {
        "documents": [["disk full"]],
        "metadatas": [[{"solution": "cleanup", "category": "IT"}]],
        "distances": [[0.9]],  # similarity = 0.1
    }

    results = pipeline_context_rag.lookup_domain_matches(
        "disk full",
        fake_ctx_db,
        threshold=0.5,
    )

    assert results == []


def test_lookup_domain_matches_returns_empty_when_ctx_db_none():
    results = pipeline_context_rag.lookup_domain_matches(
        "error",
        ctx_db=None,
    )

    assert results == []


def test_lookup_domain_matches_returns_empty_when_embedding_none(mocker, fake_ctx_db):
    fake_ctx_db._get_embedding = mocker.Mock(return_value=None)

    results = pipeline_context_rag.lookup_domain_matches(
        "error",
        fake_ctx_db,
    )

    assert results == []


def test_lookup_domain_matches_handles_query_exception(mocker, fake_ctx_db):
    fake_ctx_db.collection.query.side_effect = Exception("query failed")

    results = pipeline_context_rag.lookup_domain_matches(
        "error",
        fake_ctx_db,
    )

    assert results == []