#!/usr/bin/env python3
"""
remove_emojis_safe.py

Recursively remove specific emojis and normalize special symbols in:
 - file contents
 - file names
 - directory names

Additional functionality:
 - Replaces ✅ → ✓
 - Replaces ❌ → ✗
 - Replaces ⚠️ → !

Excludes:
 - Hidden directories and files
 - User-specified directories via --exclude-dir
 - User-specified files via --exclude-files
 - This script itself (default)

Usage examples:
    python3 remove_emojis_safe.py            # cleans current directory
    python3 remove_emojis_safe.py --dry-run  # preview only
    python3 remove_emojis_safe.py --exclude-dir node_modules,dist --exclude-files README.md
"""

import os
import argparse

# Emojis to remove
EMOJIS = [
    "📊 ", "📈 ", "🔀 ", "🎯 ", "🏗️ ", "✨ ", "📁 ", "🔄 ", "🎉 ", "🚫 ", "📚 ",
    "🚀 ", "🐳 ", "⚙️ ", "📖 ", "📡 ", "🧪 ", "📝 ", "🤝 ", "📄 ", "📋 ", "🔧 "
]

# Symbol replacements
SYMBOL_REPLACEMENTS = {
    "✅ ": "✓ ",
    "❌ ": "✗ ",
    "⚠️ ": "! ",
    "❓ ": "? "
}

# Default files to exclude (this script itself)
DEFAULT_EXCLUDE_FILES = {os.path.basename(__file__)}


def normalize_symbols(text: str) -> str:
    """Replace special symbols with simpler versions."""
    for old, new in SYMBOL_REPLACEMENTS.items():
        text = text.replace(old, new)
    return text


def remove_emojis_from_text(text: str) -> str:
    """Remove all listed emojis from a string."""
    for e in EMOJIS:
        text = text.replace(e, "")
    return text


def is_hidden(name: str) -> bool:
    """Check if a file or directory is hidden."""
    return name.startswith(".")


def is_binary_file(path: str, blocksize: int = 1024) -> bool:
    """Heuristic check for binary files."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(blocksize)
            if b'\x00' in chunk:
                return True
            nontext = sum(1 for b in chunk if b < 9 or (b > 126 and b < 160))
            return (nontext / max(1, len(chunk))) > 0.30
    except Exception:
        return True


def safe_read_text(path: str) -> str:
    """Safely read text file with utf-8 fallback."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def safe_write_text(path: str, content: str):
    """Safely overwrite file."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def process_directory(root: str, dry_run=False, extensions=None, exclude_dirs=None, exclude_files=None):  # noqa: C901
    """Recursively process the given directory."""
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        # Exclude hidden dirs and user-defined ones
        original_dirs = list(dirnames)
        dirnames[:] = [
            d for d in dirnames
            if not is_hidden(d) and d not in exclude_dirs
        ]
        excluded = set(original_dirs) - set(dirnames)
        for d in excluded:
            print(f"✗ Skipping directory: {os.path.join(dirpath, d)}")

        # Rename directories
        for dirname in list(dirnames):
            new_dirname = remove_emojis_from_text(dirname)
            new_dirname = normalize_symbols(new_dirname)
            if new_dirname != dirname:
                old_path = os.path.join(dirpath, dirname)
                new_path = os.path.join(dirpath, new_dirname)
                if dry_run:
                    print(f"[DRY-RUN] Would rename folder: {old_path} -> {new_path}")
                else:
                    try:
                        os.rename(old_path, new_path)
                        print(f"✓ Renamed folder: {old_path} -> {new_path}")
                        dirnames[dirnames.index(dirname)] = new_dirname
                    except Exception as e:
                        print(f"! Failed to rename directory {old_path}: {e}")

        # Process files
        for filename in filenames:
            if is_hidden(filename) or filename in exclude_files:
                print(f"✗ Skipping file: {os.path.join(dirpath, filename)}")
                continue

            old_path = os.path.join(dirpath, filename)
            new_filename = remove_emojis_from_text(filename)
            new_filename = normalize_symbols(new_filename)
            new_path = os.path.join(dirpath, new_filename)

            # Rename file if needed
            if new_filename != filename:
                if dry_run:
                    print(f"[DRY-RUN] Would rename file: {old_path} -> {new_path}")
                else:
                    try:
                        os.rename(old_path, new_path)
                        print(f"✓ Renamed file: {old_path} -> {new_path}")
                    except Exception as e:
                        print(f"! Failed to rename file {old_path}: {e}")
                old_path = new_path

            # Skip binary or excluded extensions
            if is_binary_file(old_path):
                continue
            if extensions:
                ext = os.path.splitext(old_path)[1].lstrip(".").lower()
                if ext not in extensions:
                    continue

            # Clean file content
            try:
                content = safe_read_text(old_path)
                cleaned = remove_emojis_from_text(content)
                cleaned = normalize_symbols(cleaned)
                if cleaned != content:
                    if dry_run:
                        print(f"[DRY-RUN] Would clean content: {old_path}")
                    else:
                        safe_write_text(old_path, cleaned)
                        print(f"✓ Cleaned content: {old_path}")
            except Exception as e:
                print(f"! Skipped {old_path}: {e}")


def parse_comma_list(value):
    """Parse comma-separated list into a set."""
    if not value:
        return set()
    return set(v.strip() for v in value.split(",") if v.strip())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Recursively remove emojis and normalize symbols in files and directories."
    )
    parser.add_argument(
        "--extensions", "-e",
        help="Comma-separated file extensions to limit content cleanup (e.g. txt,md,py)."
    )
    parser.add_argument(
        "--exclude-dir", "-x",
        help="Comma-separated directory names to skip (e.g. node_modules,dist,build)."
    )
    parser.add_argument(
        "--exclude-files", "-f",
        help="Comma-separated filenames to skip (e.g. remove_emojis_safe.py,README.md)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files."
    )

    args = parser.parse_args()

    # Default to current directory
    root = os.getcwd()
    extensions = parse_comma_list(args.extensions)
    exclude_dirs = parse_comma_list(args.exclude_dir)
    exclude_files = parse_comma_list(args.exclude_files) | DEFAULT_EXCLUDE_FILES

    print(f"Starting cleanup in current directory: {root}")
    if exclude_dirs:
        print(f"Excluding directories: {', '.join(exclude_dirs)}")
    if exclude_files:
        print(f"Excluding files: {', '.join(exclude_files)}")
    if extensions:
        print(f"Limiting file types to: {', '.join(extensions)}")
    if args.dry_run:
        print("Dry-run mode: no changes will be made.\n")

    process_directory(
        root=root,
        dry_run=args.dry_run,
        extensions=extensions,
        exclude_dirs=exclude_dirs,
        exclude_files=exclude_files
    )

    print("\n✓ Done cleaning emojis and normalizing symbols!")
