#!/usr/bin/env python3
import argparse
from textwrap import indent
import sys
# --- Compatibility patch for refactored vector_db.py ---
import importlib
try:
    from vector_db import init_vector_db
except ImportError:
    # In new version, init_vector_db() may have been removed; fallback to VectorDBClient
    vector_db = importlib.import_module("vector_db")
    if hasattr(vector_db, "VectorDBClient"):
        def init_vector_db(persist_directory="/home/build-failure-analyzer/data/chroma"):
            """Shim for backward compatibility with helper scripts"""
            # Instantiate without passing persist_directory if constructor doesn't expect it
            try:
                client = vector_db.VectorDBClient(
                    persist_directory=persist_directory)
            except TypeError:
                client = vector_db.VectorDBClient()
            # Return collection if available; otherwise, client itself
            return getattr(client, "collection", client)
    else:
        raise ImportError(
            "init_vector_db() not found in vector_db.py and no VectorDBClient class detected."
        )
# --- End patch ---


def list_docs(db):
    # ⚠️ Do NOT include "ids" in include list — Chroma returns IDs automatically
    all_docs = db.collection.get(include=["documents", "metadatas"])
    ids = all_docs.get("ids", [])
    docs = all_docs.get("documents", [])
    metadatas = all_docs.get("metadatas", [])
    if not ids:
        print("No documents found in vector DB.")
        return
    print(f"\n📄 Found {len(ids)} document(s) in Vector DB:\n")
    for i, doc_id in enumerate(ids):
        meta = metadatas[i] or {}
        # ✅ Correct field names as stored in vector_db.py
        error = meta.get("error_text", "N/A")
        fix = docs[i] or "(empty fix)"
        status = meta.get("status", "unknown")
        approved_by = meta.get("approved_by", "N/A")
        print("=" * 80)
        print(f"🆔  ID: {doc_id}")
        print(f"⚙️  Status: {status}")
        print(f"👤 Approved by: {approved_by}")
        print(f"❌ Error:")
        print(indent(error, "   "))
        print(f"🧩 Fix:")
        print(indent(fix, "   "))
    print("=" * 80)


def delete_docs_by_id(db, doc_ids, preview=False):
    """
    Delete documents by their IDs.
    If preview=True, shows the documents first and asks for confirmation.
    """
    # Fetch all documents to find the ones we want
    all_docs = db.collection.get(include=["documents", "metadatas"])
    ids = all_docs.get("ids", [])
    docs = all_docs.get("documents", [])
    metadatas = all_docs.get("metadatas", [])

    # Filter to only the requested IDs
    matched = []
    for doc_id in doc_ids:
        if doc_id in ids:
            idx = ids.index(doc_id)
            matched.append((doc_id, docs[idx], metadatas[idx]))
        else:
            print(f"⚠️  Document ID '{doc_id}' not found in database.")

    if not matched:
        return

    # Preview mode
    if preview:
        print(f"\n🔍 Preview: {len(matched)} document(s) will be deleted:\n")
        for doc_id, doc, meta in matched:
            meta = meta or {}
            error = meta.get("error_text", "N/A")
            fix = doc or "(empty fix)"
            status = meta.get("status", "unknown")
            approved_by = meta.get("approved_by", "N/A")
            print("=" * 80)
            print(f"🆔  ID: {doc_id}")
            print(f"⚙️  Status: {status}")
            print(f"👤 Approved by: {approved_by}")
            print(f"❌ Error:")
            print(indent(error, "   "))
            print(f"🧩 Fix:")
            print(indent(fix, "   "))
        print("=" * 80)

        response = input(
            f"\n⚠️  Delete these {len(matched)} document(s)? Type 'yes' to confirm: ")
        if response.lower() != 'yes':
            print("❌ Deletion cancelled.")
            return

    # Perform deletion
    for doc_id, _, _ in matched:
        try:
            db.collection.delete(ids=[doc_id])
            print(f"✅ Deleted document with ID: {doc_id}")
        except Exception as e:
            print(f"❌ Error deleting document {doc_id}: {e}")


def delete_docs_by_error(db, error_text, preview=False):
    """
    Delete documents matching error text.
    If preview=True, shows the documents first and asks for confirmation.
    """
    all_docs = db.collection.get(include=["documents", "metadatas"])
    ids = all_docs.get("ids", [])
    docs = all_docs.get("documents", [])
    metadatas = all_docs.get("metadatas", [])

    matched = []
    for i, meta in enumerate(metadatas):
        err = meta.get("error_text", "")
        if error_text.lower() in err.lower():
            matched.append((ids[i], err, docs[i], meta))

    if not matched:
        print(f"No documents found containing error: '{error_text}'")
        return

    # Preview mode
    if preview:
        print(f"\n🔍 Preview: {len(matched)} document(s) will be deleted:\n")
        for doc_id, err, fix, meta in matched:
            print("=" * 80)
            print(f"🆔  ID: {doc_id}")
            print(f"❌ Error:")
            print(indent(err or "N/A", "   "))
            print(f"🧩 Fix:")
            print(indent(fix or "(empty fix)", "   "))
            print(f"⚙️ Status: {meta.get('status', 'unknown')}")
            print(f"👤 Approved by: {meta.get('approved_by', 'N/A')}")
        print("=" * 80)

        response = input(
            f"\n⚠️  Delete these {len(matched)} document(s)? Type 'yes' to confirm: ")
        if response.lower() != 'yes':
            print("❌ Deletion cancelled.")
            return

    # Perform deletion
    for doc_id, _, _, _ in matched:
        try:
            db.collection.delete(ids=[doc_id])
            print(f"✅ Deleted document with ID: {doc_id}")
        except Exception as e:
            print(f"❌ Error deleting document {doc_id}: {e}")


def delete_all_docs(db, force=False, preview=False):
    """
    Delete all documents from the vector database.
    Requires confirmation unless --force is used.
    If preview=True, only shows what would be deleted.
    """
    # Don't include "ids" - Chroma returns them automatically
    all_docs = db.collection.get(include=["documents", "metadatas"])
    ids = all_docs.get("ids", [])
    docs = all_docs.get("documents", [])
    metadatas = all_docs.get("metadatas", [])

    if not ids:
        print("✅ No documents found in vector DB. Nothing to delete.")
        return

    if preview:
        print(f"\n🔍 Preview: {len(ids)} document(s) will be deleted:\n")
        for i, doc_id in enumerate(ids):
            meta = metadatas[i] or {}
            error = meta.get("error_text", "N/A")
            fix = docs[i] or "(empty fix)"
            status = meta.get("status", "unknown")
            approved_by = meta.get("approved_by", "N/A")
            print("=" * 80)
            print(f"🆔  ID: {doc_id}")
            print(f"⚙️  Status: {status}")
            print(f"👤 Approved by: {approved_by}")
            print(f"❌ Error: {error[:100]}..." if len(
                error) > 100 else f"❌ Error: {error}")
            print(f"🧩 Fix: {fix[:100]}..." if len(
                fix) > 100 else f"🧩 Fix: {fix}")
        print("=" * 80)

        if not force:
            response = input(
                f"\n⚠️  Delete ALL {len(ids)} document(s)? Type 'yes' to confirm: ")
            if response.lower() != 'yes':
                print("❌ Deletion cancelled.")
                return
    else:
        print(
            f"⚠️  WARNING: This will delete ALL {len(ids)} document(s) from the vector database!")

        if not force:
            response = input(
                "Are you sure you want to continue? Type 'yes' to confirm: ")
            if response.lower() != 'yes':
                print("❌ Deletion cancelled.")
                return

    try:
        db.collection.delete(ids=ids)
        print(
            f"✅ Successfully deleted all {len(ids)} document(s) from the vector database.")
    except Exception as e:
        print(f"❌ Error deleting all documents: {e}")


def edit_fix(db, doc_id, new_fix=None, interactive=False):
    """
    Edit the fix/solution for a given document ID.

    Args:
        db: Database connection
        doc_id: Document ID to edit
        new_fix: New fix text (if provided via command line)
        interactive: If True, opens an editor for multi-line input
    """
    # Fetch the document
    all_docs = db.collection.get(include=["documents", "metadatas"])
    ids = all_docs.get("ids", [])
    docs = all_docs.get("documents", [])
    metadatas = all_docs.get("metadatas", [])

    if doc_id not in ids:
        print(f"❌ Document ID '{doc_id}' not found in database.")
        return

    idx = ids.index(doc_id)
    current_fix = docs[idx] or ""
    metadata = metadatas[idx] or {}
    error_text = metadata.get("error_text", "N/A")

    # Display current document
    print("\n" + "=" * 80)
    print(f"🆔  ID: {doc_id}")
    print(f"❌ Error:")
    print(indent(error_text, "   "))
    print(f"\n🧩 Current Fix:")
    print(indent(current_fix, "   "))
    print("=" * 80)

    # Get new fix
    if new_fix is None:
        if interactive:
            print(
                "\n✏️  Enter new fix (press Ctrl+D or Ctrl+Z when done, Ctrl+C to cancel):")
            print("-" * 80)
            lines = []
            try:
                while True:
                    line = input()
                    lines.append(line)
            except EOFError:
                new_fix = "\n".join(lines)
            except KeyboardInterrupt:
                print("\n❌ Edit cancelled.")
                return
        else:
            print(
                "\n✏️  Enter new fix (single line, or use --interactive for multi-line):")
            try:
                new_fix = input("> ")
            except KeyboardInterrupt:
                print("\n❌ Edit cancelled.")
                return

    if not new_fix or not new_fix.strip():
        print("❌ Fix cannot be empty. Edit cancelled.")
        return

    # Show preview of change
    print("\n" + "=" * 80)
    print("📝 PREVIEW OF CHANGE:")
    print("-" * 80)
    print("OLD Fix:")
    print(indent(current_fix, "   "))
    print("-" * 80)
    print("NEW Fix:")
    print(indent(new_fix, "   "))
    print("=" * 80)

    # Confirm
    response = input("\n⚠️  Apply this change? Type 'yes' to confirm: ")
    if response.lower() != 'yes':
        print("❌ Edit cancelled.")
        return

    # Update the document
    try:
        db.collection.update(
            ids=[doc_id],
            documents=[new_fix],
            metadatas=[metadata]  # Keep existing metadata
        )
        print(f"\n✅ Successfully updated fix for document ID: {doc_id}")
    except Exception as e:
        print(f"\n❌ Error updating document: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Vector DB helper: list, preview, edit, or delete documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all documents
  python3 vector_helper.py

  # Edit fix for a document (single line)
  python3 vector_helper.py --edit <doc_id>

  # Edit fix with inline text
  python3 vector_helper.py --edit <doc_id> --fix "New solution text"

  # Edit fix with multi-line editor
  python3 vector_helper.py --edit <doc_id> --interactive

  # Preview before deleting
  python3 vector_helper.py --id <doc_id> --preview

  # Delete by error text
  python3 vector_helper.py --error "cmake" --preview

  # Delete all documents
  python3 vector_helper.py --delete-all
        """
    )
    parser.add_argument("--id", nargs="+",
                        help="One or more document IDs to delete")
    parser.add_argument(
        "--error", type=str, help="Delete documents matching this error text (case-insensitive)")
    parser.add_argument("--preview", action="store_true",
                        help="Preview deletion and confirm before deleting (works with --id, --error, and --delete-all)")
    parser.add_argument("--delete-all", action="store_true",
                        help="Delete ALL documents from the vector database (requires confirmation)")
    parser.add_argument("--force", action="store_true",
                        help="Skip confirmation prompt (use with --delete-all)")
    parser.add_argument("--edit", type=str, metavar="DOC_ID",
                        help="Edit the fix/solution for the given document ID")
    parser.add_argument("--fix", type=str,
                        help="New fix text (used with --edit)")
    parser.add_argument("--interactive", action="store_true",
                        help="Use multi-line input mode for editing (used with --edit)")

    args = parser.parse_args()

    db = init_vector_db()

    if args.edit:
        edit_fix(db, args.edit, new_fix=args.fix, interactive=args.interactive)
    elif args.delete_all:
        delete_all_docs(db, force=args.force, preview=args.preview)
    elif args.id:
        delete_docs_by_id(db, args.id, preview=args.preview)
    elif args.error:
        delete_docs_by_error(db, args.error, preview=args.preview)
    else:
        list_docs(db)
