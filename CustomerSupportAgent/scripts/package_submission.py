"""Build a clean submission zip and refuse to ship secrets.

Usage (from the project root):
    python scripts/package_submission.py                 # writes ../capstone_project_submission.zip
    python scripts/package_submission.py my_submission.zip

What it does
  - Excludes .env (real keys), the virtualenv, the local vector store, caches, and git data.
    The sanitized .env.example IS included.
  - Scans every included text file for API-key-looking strings (OpenAI, LangSmith) and aborts
    without writing the zip if it finds one, so a key pasted into a doc or log can't slip through.
"""
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_DIRS = {".venv", "venv", ".qdrant", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
EXCLUDED_FILES = {".env"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
# Scratch files regenerated on every demo/evaluation run; not evidence.
EXCLUDED_NAMES = {"demo_feedback.json", "eval_feedback.json"}

SECRET_PATTERNS = {
    "OpenAI API key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "LangSmith API key": re.compile(r"\b(?:lsv2_(?:pt|sk)_[A-Za-z0-9]{10,}|ls__[A-Za-z0-9]{10,})"),
}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".jsonl", ".yml", ".yaml", ".toml", ".log", ".example", ".cfg", ".ini"}


def included_files() -> list[Path]:
    files = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        if path.name in EXCLUDED_FILES or path.name in EXCLUDED_NAMES or path.suffix in EXCLUDED_SUFFIXES:
            continue
        files.append(path)
    return files


def find_secrets(files: list[Path]) -> list[str]:
    findings = []
    for path in files:
        if path.suffix not in TEXT_SUFFIXES and path.name != ".env.example":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{label} pattern in {path.relative_to(ROOT)}")
    return findings


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "capstone_project_submission.zip"
    files = included_files()

    findings = find_secrets(files)
    if findings:
        print("ABORTED: possible secrets found, nothing was written:")
        for finding in findings:
            print(f"  - {finding}")
        return 1

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path("capstone_project") / path.relative_to(ROOT))

    size_mb = target.stat().st_size / 1e6
    print(f"Wrote {target} ({len(files)} files, {size_mb:.1f} MB)")
    print("Excluded: .env, .venv, .qdrant, caches, .git. Included: .env.example (sanitized).")
    print("Reminder: rotate any API key that was ever stored in .env before sharing the project.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
