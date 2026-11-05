"""Build a clean GitHub source directory and ZIP using an explicit allowlist.

Does not read the live database, copy .env, initialize Git, or push anything.
Existing destinations are preserved. Requires only Python's standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    ".gitignore", ".gitattributes", ".env.example", "README.md",
    "CONTRIBUTING.md", "SECURITY.md", "NOTICE.md", "LICENSE", "RELEASE_CHECKLIST.md",
    "requirements.txt", "requirements-dev.txt", "requirements-local-model.txt",
    "pytest.ini", "run.py", "start.ps1", "evaluation/__init__.py",
)
TREES = {
    "rag_agent": {".py"},
    "web": {".js", ".css", ".html"},
    "scripts": {".py"},
    "tests": {".py", ".cjs"},
    "docs": {".md", ".png"},
    ".github": {".yml", ".yaml", ".md"},
}
ENTERPRISE_FILES = {
    "__init__.py", "README.md", "build_sources.py", "build_questions.py",
    "evaluate.py", "articles.json", "metadata.json", "questions.jsonl",
    "sources.json", "validation_report.json", "题库与标准答案.md",
    "仅上传知识库_10份制度资料.zip",
}
CHUNKING_FILES = {
    "README.md", "collect_sources.py", "preview.py", "sources.json",
    "validation_report.json", "切分预览.md",
}
REQUIRED = ROOT_FILES + (
    "rag_agent/app.py", "web/index.html", ".github/workflows/ci.yml",
    "docs/usage.md", "docs/images/login.png", "docs/images/documents.png",
    "evaluation/enterprise_v1/questions.jsonl",
    "evaluation/enterprise_v1/sources_raw/财政部_企业内部控制应用指引_官方原文.pdf",
    "evaluation/chunking_examples/sources.json",
)
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".css", ".html", ".md", ".json", ".jsonl", ".yml", ".yaml", ".txt", ".ps1"}


def allowed(relative: Path) -> bool:
    name = relative.as_posix()
    if name in ROOT_FILES:
        return True
    if any(part.startswith(".") or part == "__pycache__" for part in relative.parts[1:]):
        return False
    for directory, suffixes in TREES.items():
        if len(relative.parts) > 1 and relative.parts[0] == directory:
            return relative.suffix.lower() in suffixes
    if relative.parent.as_posix() == "evaluation/enterprise_v1":
        return relative.name in ENTERPRISE_FILES
    if relative.parent.as_posix() == "evaluation/enterprise_v1/corpus":
        return relative.suffix == ".md"
    if name == "evaluation/enterprise_v1/sources_raw/财政部_企业内部控制应用指引_官方原文.pdf":
        return True
    if relative.parent.as_posix() == "evaluation/chunking_examples":
        return relative.name in CHUNKING_FILES
    if relative.parent.as_posix() == "evaluation/chunking_examples/public_sources":
        return relative.suffix == ".md"
    return False


def source_files(root: Path):
    # Traverse only selected trees; never descend into data/, .venv/, or outputs.
    candidates = [root / name for name in ROOT_FILES]
    for directory in (*TREES, "evaluation/enterprise_v1", "evaluation/chunking_examples"):
        directory_path = root / directory
        candidates.extend(directory_path.rglob("*") if directory_path.is_dir() else [])
    selected = []
    for path in sorted(set(candidates)):
        relative = path.relative_to(root)
        if not allowed(relative) or not path.is_file():
            continue
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root):
            raise ValueError(f"Symlinks cannot be packaged: {relative.as_posix()}")
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Source escapes project: {relative.as_posix()}")
        selected.append(path)
    missing = [name for name in REQUIRED if root / name not in selected]
    if missing:
        raise ValueError("Required release files missing: " + ", ".join(missing))
    return selected


def check_contents(path: Path):
    if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".env.example":
        return
    text = path.read_text(encoding="utf-8-sig")
    if re.search(r"\bsk-[A-Za-z0-9_-]{20,}\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", text):
        raise ValueError(f"Potential credential in {path.name}; review before packaging.")
    if path.name == ".env.example":
        for line in text.splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() in {"DEEPSEEK_API_KEY", "BGE_API_KEY", "RAG_ADMIN_PASSWORD"} and value.strip():
                raise ValueError("Credential fields in .env.example must be empty.")


def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(root: Path, destination: Path):
    root, destination = root.resolve(), destination.resolve()
    archive = destination.with_suffix(".zip")
    manifest_path = destination.with_name(destination.name + ".manifest.json")
    if destination == root or root.is_relative_to(destination):
        raise ValueError("Destination cannot replace the project or one of its parents.")
    if any(path.exists() for path in (destination, archive, manifest_path)):
        raise FileExistsError("Destination, ZIP or manifest already exists; choose a new --output.")
    files = source_files(root)
    if any(path.is_relative_to(destination) for path in files):
        raise ValueError("Destination overlaps selected sources.")
    for path in files:
        check_contents(path)
    destination.mkdir(parents=True)
    entries = []
    for path in files:
        relative = path.relative_to(root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        entries.append({"path": relative.as_posix(), "bytes": target.stat().st_size, "sha256": digest(target)})
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for entry in entries:
            bundle.write(destination / entry["path"], f"{destination.name}/{entry['path']}")
    manifest = {
        "format": 1, "directory": destination.name, "files": entries,
        "file_count": len(entries), "source_bytes": sum(e["bytes"] for e in entries),
        "archive": {"filename": archive.name, "bytes": archive.stat().st_size, "sha256": digest(archive)},
        "excluded": [".env", "data/", ".venv/", "tmp/", "output/", "test-results/", "research_raw/", "Git history"],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"directory": str(destination), "archive": str(archive), "manifest": str(manifest_path),
            "files": len(entries), "archive_bytes": archive.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "github-release/zhixu-rag-agent")
    args = parser.parse_args()
    try:
        result = build(ROOT, args.output)
    except (ValueError, FileExistsError) as exc:
        parser.exit(1, f"Release not built: {exc}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
