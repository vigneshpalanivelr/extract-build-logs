import builtins
import pytest
from types import SimpleNamespace

import vector_helper


# -------------------------------------------------
# Fixtures
# -------------------------------------------------

@pytest.fixture
def fake_collection(mocker):
    col = SimpleNamespace()
    col.get = mocker.Mock()
    return col


@pytest.fixture
def fake_db(fake_collection, mocker):
    db = SimpleNamespace()
    db.collection = fake_collection
    db.delete = mocker.Mock()
    return db


@pytest.fixture
def capture_print(mocker):
    return mocker.patch.object(builtins, "print")


# -------------------------------------------------
# list_docs
# -------------------------------------------------

def test_list_docs_no_documents(fake_db, capture_print):
    fake_db.collection.get.return_value = {
        "ids": [],
        "documents": [],
        "metadatas": [],
    }

    vector_helper.list_docs(fake_db)

    capture_print.assert_any_call("No documents found in vector DB.")


def test_list_docs_prints_documents(fake_db, capture_print):
    fake_db.collection.get.return_value = {
        "ids": ["id-1"],
        "documents": ["fix steps"],
        "metadatas": [{
            "error_text": "build failed",
            "status": "approved",
            "approved_by": "alice",
        }],
    }

    vector_helper.list_docs(fake_db)

    printed = " ".join(str(c[0]) for c in capture_print.call_args_list)
    assert "id-1" in printed
    assert "build failed" in printed
    assert "fix steps" in printed
    assert "approved" in printed
    assert "alice" in printed


# -------------------------------------------------
# delete_docs_by_id
# -------------------------------------------------

def test_delete_docs_by_id_success(fake_db, capture_print):
    vector_helper.delete_docs_by_id(fake_db, ["doc-1", "doc-2"])

    assert fake_db.delete.call_count == 2
    capture_print.assert_any_call("✅ Deleted document with ID: doc-1")
    capture_print.assert_any_call("✅ Deleted document with ID: doc-2")


def test_delete_docs_by_id_failure(fake_db, capture_print, mocker):
    fake_db.delete.side_effect = Exception("delete failed")

    vector_helper.delete_docs_by_id(fake_db, ["doc-1"])

    capture_print.assert_any_call("❌ Error deleting document doc-1: delete failed")


# -------------------------------------------------
# delete_docs_by_error
# -------------------------------------------------

def test_delete_docs_by_error_no_match(fake_db, capture_print):
    fake_db.collection.get.return_value = {
        "ids": ["1"],
        "metadatas": [{"error_text": "compile error"}],
    }

    vector_helper.delete_docs_by_error(fake_db, "network")

    capture_print.assert_any_call(
        "No documents found containing error: 'network'"
    )


def test_delete_docs_by_error_preview(fake_db, capture_print):
    fake_db.collection.get.return_value = {
        "ids": ["1", "2"],
        "metadatas": [
            {"error_text": "disk full"},
            {"error_text": "Disk quota exceeded"},
        ],
    }

    vector_helper.delete_docs_by_error(
        fake_db,
        "disk",
        preview=True,
    )

    fake_db.delete.assert_not_called()
    capture_print.assert_any_call(
        "⚠️ Preview mode: 2 document(s) would be deleted:"
    )


def test_delete_docs_by_error_executes_delete(fake_db, capture_print):
    fake_db.collection.get.return_value = {
        "ids": ["1"],
        "metadatas": [{"error_text": "disk full"}],
    }

    vector_helper.delete_docs_by_error(
        fake_db,
        "disk",
        preview=False,
    )

    fake_db.delete.assert_called_once_with(ids=["1"])
    capture_print.assert_any_call("✅ Deleted document with ID: 1")


# -------------------------------------------------
# preview_docs_by_error
# -------------------------------------------------

def test_preview_docs_by_error_no_match(fake_db, capture_print):
    fake_db.collection.get.return_value = {
        "ids": ["1"],
        "documents": ["fix"],
        "metadatas": [{"error_text": "compile error"}],
    }

    vector_helper.preview_docs_by_error(fake_db, "network")

    capture_print.assert_any_call(
        "🔍 No entries found matching error substring: 'network'"
    )


def test_preview_docs_by_error_prints_matches(fake_db, capture_print):
    fake_db.collection.get.return_value = {
        "ids": ["1"],
        "documents": ["rebuild cache"],
        "metadatas": [{
            "error_text": "cache corrupted",
            "status": "approved",
            "approved_by": "bob",
        }],
    }

    vector_helper.preview_docs_by_error(fake_db, "cache")

    printed = " ".join(str(c[0]) for c in capture_print.call_args_list)
    assert "cache corrupted" in printed
    assert "rebuild cache" in printed
    assert "approved" in printed
    assert "bob" in printed
