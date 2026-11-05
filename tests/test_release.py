import json
import zipfile
from pathlib import Path

import pytest

from scripts.build_github_release import ROOT, allowed, build, check_contents, digest


@pytest.mark.parametrize("name", [
    ".env", ".env.local", "data/rag.sqlite3", "data/models/config.json",
    ".venv/pyvenv.cfg", "tmp/notes.md", "output/report.docx",
    "rag_agent/__pycache__/app.pyc", "docs/.hidden/credentials.md",
    "evaluation/chunking_examples/research_raw/page.html",
    "evaluation/enterprise_v1/results/private.json",
])
def test_release_excludes_runtime_and_unrelated_files(name):
    assert not allowed(Path(name))


def test_release_rejects_credentials_in_environment_template(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("DEEPSEEK_API_KEY=do-not-package-this\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be empty"):
        check_contents(example)


def test_release_archive_matches_manifest_and_preserves_existing_output(tmp_path):
    destination = tmp_path / "release"
    result = build(ROOT, destination)
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    paths = {entry["path"] for entry in manifest["files"]}
    assert {"run.py", ".env.example", ".github/workflows/ci.yml", "docs/images/login.png"} <= paths
    assert not any(path.split("/")[0] in {"data", ".venv", "tmp", "output"} for path in paths)
    assert ".env" not in paths
    assert digest(Path(result["archive"])) == manifest["archive"]["sha256"]
    with zipfile.ZipFile(result["archive"]) as archive:
        assert set(archive.namelist()) == {f"release/{path}" for path in paths}
        for entry in manifest["files"]:
            assert digest(destination / entry["path"]) == entry["sha256"]
            assert archive.read(f"release/{entry['path']}") == (destination / entry["path"]).read_bytes()
    before = (destination / "README.md").read_bytes()
    with pytest.raises(FileExistsError):
        build(ROOT, destination)
    assert (destination / "README.md").read_bytes() == before
