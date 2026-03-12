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
            "metadatas": [[{"status": "approved", "error_text": "gcc failed"}]],
            "distances": [[0.05]],
        }
    )

    result = vector_db.lookup_existing_fix("gcc failed")

    assert isinstance(result, dict)
    assert result["source"] == "vector_db"
    assert result["fix_text"] == "Fix gcc"
    assert "raw_confidence" in result


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


# -------------------------------------------------------
# Normalization tests
# -------------------------------------------------------
class TestNormalizeErrorText:
    """Tests for _normalize_error_text method."""

    def test_short_text_unchanged(self, vector_db):
        """Short error text without line prefixes passes through mostly unchanged."""
        text = "ERROR: gcc compilation failed"
        result = vector_db._normalize_error_text(text)
        assert "gcc compilation failed" in result

    def test_strips_line_number_prefixes(self, vector_db):
        """Line NNN: prefixes from log-extraction service are stripped."""
        text = "Line 100: Starting build\nLine 101: ERROR: npm install failed\nLine 102: exit code 1"
        result = vector_db._normalize_error_text(text)
        assert "Line 100:" not in result
        assert "Line 101:" not in result
        assert "Starting build" in result
        assert "npm install failed" in result

    def test_deduplicates_lines(self, vector_db):
        """Duplicate lines are removed, keeping first occurrence."""
        text = "ERROR: build failed\nsome context\nERROR: build failed\nERROR: build failed"
        result = vector_db._normalize_error_text(text)
        # Should appear only once
        assert result.count("ERROR: build failed") == 1
        assert "some context" in result

    def test_prioritizes_error_lines(self, vector_db):
        """Error-signal lines appear before context lines."""
        text = "context line 1\ncontext line 2\nERROR: something failed\nFATAL: OOM killed"
        result = vector_db._normalize_error_text(text)
        lines = result.split("\n")
        # Error lines should be before context lines
        error_idx = None
        context_idx = None
        for i, line in enumerate(lines):
            if "ERROR:" in line and error_idx is None:
                error_idx = i
            if "context line 1" in line and context_idx is None:
                context_idx = i
        assert error_idx is not None
        assert context_idx is not None
        assert error_idx < context_idx

    def test_caps_at_max_lines(self, mocker, vector_db):
        """Text is capped at MAX_ERROR_LINES."""
        mocker.patch("vector_db.MAX_ERROR_LINES", 5)
        lines = [f"line {i}" for i in range(100)]
        text = "\n".join(lines)
        result = vector_db._normalize_error_text(text)
        result_lines = [line for line in result.split("\n") if line.strip()]
        assert len(result_lines) <= 5

    def test_caps_at_max_chars(self, mocker, vector_db):
        """Text is capped at MAX_ERROR_CHARS."""
        mocker.patch("vector_db.MAX_ERROR_CHARS", 100)
        text = "ERROR: " + "x" * 500
        result = vector_db._normalize_error_text(text)
        assert len(result) <= 100

    def test_removes_empty_lines(self, vector_db):
        """Empty and whitespace-only lines are removed."""
        text = "ERROR: fail\n\n   \n\nsome context"
        result = vector_db._normalize_error_text(text)
        lines = result.split("\n")
        for line in lines:
            assert line.strip() != ""

    def test_handles_empty_input(self, vector_db):
        """Empty input returns empty string."""
        assert vector_db._normalize_error_text("") == ""
        assert vector_db._normalize_error_text("   \n  \n  ") == ""


# -------------------------------------------------------
# Length penalty tests
# -------------------------------------------------------
class TestLengthPenalty:
    """Tests for length-penalized similarity scoring in lookup_existing_fix."""

    def test_rejects_oversized_stored_entry(self, mocker, vector_db):
        """A huge stored entry should be penalized below threshold for a short query."""
        mocker.patch.object(vector_db, "_get_embedding", return_value=[0.1])

        # Simulate: stored entry has 15000-char error_text, raw similarity = 0.82
        huge_error = "x" * 15000
        mocker.patch.object(
            vector_db.collection,
            "query",
            return_value={
                "ids": [["id-huge"]],
                "documents": [["Increase Node memory"]],
                "metadatas": [[{"status": "approved", "error_text": huge_error}]],
                "distances": [[0.18]],  # raw_sim = 1 - 0.18 = 0.82
            }
        )

        # Short query (100 chars) — length ratio ~150x, penalty ~0.57
        short_query = "ERROR: gcc compilation failed\nundefined reference to 'sqrt'"
        result = vector_db.lookup_existing_fix(short_query)

        # Should be rejected: 0.82 * 0.57 = ~0.47, well below 0.78
        assert result is None

    def test_preserves_same_length_match(self, mocker, vector_db):
        """Entries with similar length should not be penalized."""
        mocker.patch.object(vector_db, "_get_embedding", return_value=[0.1])

        stored_error = "ERROR: gcc compilation failed\nundefined reference to 'pthread_create'"
        mocker.patch.object(
            vector_db.collection,
            "query",
            return_value={
                "ids": [["id-gcc"]],
                "documents": [["Add -lpthread to LDFLAGS"]],
                "metadatas": [[{"status": "approved", "error_text": stored_error}]],
                "distances": [[0.08]],  # raw_sim = 0.92
            }
        )

        query = "ERROR: gcc compilation failed\nundefined reference to 'sqrt'"
        result = vector_db.lookup_existing_fix(query)

        # Length ratio ~1.1x, penalty ~0.99 — should still match
        assert result is not None
        assert result["source"] == "vector_db"
        assert result["confidence"] > 0.78

    def test_correct_entry_wins_over_oversized(self, mocker, vector_db):
        """When both a correct short entry and an oversized entry are candidates,
        the correct entry should win after length penalty."""
        mocker.patch.object(vector_db, "_get_embedding", return_value=[0.1])

        huge_error = "x" * 10000
        correct_error = "ERROR: docker pull access denied for myapp"
        mocker.patch.object(
            vector_db.collection,
            "query",
            return_value={
                "ids": [["id-huge", "id-correct"]],
                "documents": [["Increase memory", "Run docker login"]],
                "metadatas": [[
                    {"status": "approved", "error_text": huge_error},
                    {"status": "approved", "error_text": correct_error},
                ]],
                "distances": [[0.15, 0.20]],  # raw: 0.85, 0.80
            }
        )

        query = "ERROR: docker pull access denied for backend-api"
        result = vector_db.lookup_existing_fix(query)

        # huge entry: raw=0.85, penalty heavy → adjusted well below 0.78
        # correct entry: raw=0.80, penalty ~1.0 → adjusted ~0.80
        assert result is not None
        assert result["fix_text"] == "Run docker login"


# -------------------------------------------------------
# Save normalization tests
# -------------------------------------------------------
class TestSaveNormalization:
    """Tests that save_fix_to_db normalizes before embedding."""

    def test_save_embeds_normalized_text(self, mocker, vector_db):
        """Verify _get_embedding is called with normalized (not raw) text."""
        embed_mock = mocker.patch.object(
            vector_db, "_get_embedding", return_value=[0.1, 0.2]
        )

        raw_error = "Line 100: Starting build\nLine 200: ERROR: npm install failed"
        vector_db.save_fix_to_db(
            error_text=raw_error,
            fix_text="Run npm install manually",
            status="approved",
        )

        # _get_embedding should be called with normalized text (no Line prefixes)
        call_arg = embed_mock.call_args[0][0]
        assert "Line 100:" not in call_arg
        assert "Line 200:" not in call_arg
        assert "npm install failed" in call_arg

    def test_save_stores_original_error_in_metadata(self, mocker, vector_db):
        """Original error_text is preserved in metadata for display and length penalty."""
        mocker.patch.object(vector_db, "_get_embedding", return_value=[0.1])

        raw_error = "Line 100: ERROR: build failed"
        vector_db.save_fix_to_db(
            error_text=raw_error,
            fix_text="Fix the build",
            status="approved",
        )

        # Check the metadata passed to collection.add
        call_args = vector_db.collection.add.call_args
        metadata = call_args.kwargs.get("metadatas") or call_args[1].get("metadatas")
        if metadata is None:
            metadata = call_args[0][0] if call_args[0] else None
        # metadatas is a list of dicts
        meta = metadata[0] if metadata else {}
        assert meta.get("error_text") == raw_error
        assert meta.get("normalized") == "true"
        assert meta.get("original_error_length") == len(raw_error)


# -------------------------------------------------------
# Management method tests
# -------------------------------------------------------
class TestFixManagement:
    """Tests for get_all_fixes, get_fix_by_id, update_fix, delete_fix, reindex, audit."""

    def _mock_collection_data(self, vector_db):
        """Set up mock collection.get() with sample data."""
        vector_db.collection.get.return_value = {
            "ids": ["fix-001", "fix-002", "fix-003"],
            "documents": ["Fix A", "Fix B", "Fix C"],
            "metadatas": [
                {"error_text": "short error", "status": "approved", "approved_by": "alice"},
                {"error_text": "x" * 5000, "status": "edited", "approved_by": "bob"},
                {"error_text": "another error", "status": "manual", "approved_by": "alice"},
            ],
        }

    def test_get_all_fixes_returns_paginated(self, vector_db):
        self._mock_collection_data(vector_db)
        result = vector_db.get_all_fixes(page=1, page_size=2)
        assert result["total"] == 3
        assert result["page"] == 1
        assert result["page_size"] == 2
        assert len(result["fixes"]) == 2

    def test_get_all_fixes_search_filter(self, vector_db):
        self._mock_collection_data(vector_db)
        result = vector_db.get_all_fixes(search="short error")
        assert result["total"] == 1
        assert result["fixes"][0]["id"] == "fix-001"

    def test_get_all_fixes_status_filter(self, vector_db):
        self._mock_collection_data(vector_db)
        result = vector_db.get_all_fixes(status="approved")
        assert result["total"] == 1
        assert result["fixes"][0]["status"] == "approved"

    def test_get_all_fixes_approver_filter(self, vector_db):
        self._mock_collection_data(vector_db)
        result = vector_db.get_all_fixes(approver="alice")
        assert result["total"] == 2

    def test_get_fix_by_id(self, vector_db):
        vector_db.collection.get.return_value = {
            "ids": ["fix-001"],
            "documents": ["Fix A"],
            "metadatas": [{"error_text": "err", "status": "approved"}],
        }
        result = vector_db.get_fix_by_id("fix-001")
        assert result is not None
        assert result["id"] == "fix-001"
        assert result["fix_text"] == "Fix A"

    def test_get_fix_by_id_not_found(self, vector_db):
        vector_db.collection.get.return_value = {"ids": []}
        result = vector_db.get_fix_by_id("nonexistent")
        assert result is None

    def test_delete_fix(self, vector_db):
        ok = vector_db.delete_fix("fix-001")
        assert ok is True
        vector_db.collection.delete.assert_called_once_with(ids=["fix-001"])

    def test_update_fix(self, mocker, vector_db):
        mocker.patch.object(vector_db, "_get_embedding", return_value=[0.5])
        vector_db.collection.get.return_value = {
            "ids": ["fix-001"],
            "documents": ["Old fix"],
            "metadatas": [{"error_text": "some error", "status": "approved"}],
        }

        ok = vector_db.update_fix("fix-001", fix_text="New fix")
        assert ok is True
        vector_db.collection.update.assert_called_once()

    def test_audit_oversized(self, vector_db):
        self._mock_collection_data(vector_db)
        results = vector_db.audit_oversized(max_chars=100)
        # Only fix-002 has error_text > 100 chars (5000 chars)
        assert len(results) == 1
        assert results[0]["id"] == "fix-002"
        assert results[0]["error_text_length"] == 5000

    def test_reindex_all(self, mocker, vector_db):
        mocker.patch.object(vector_db, "_get_embedding", return_value=[0.5])
        self._mock_collection_data(vector_db)

        result = vector_db.reindex_all()
        assert result["total"] == 3
        assert result["reindexed"] == 3
        assert result["failed"] == 0
        assert result["skipped"] == 0
        assert vector_db.collection.update.call_count == 3
