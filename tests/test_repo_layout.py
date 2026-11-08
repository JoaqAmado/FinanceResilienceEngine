"""The repo stays as the README describes it. Needs no track data."""
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MARKDOWN = [ROOT / "README.md", *sorted(DOCS.glob("*.md"))]
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
GENERATED_DATA = ("data/", "web/public/data/", "web/test/vectors.json")
NOTES_DIR = "research" + "/"  # built in two parts so this file doesn't match itself


def test_pyproject_dependencies_match_requirements():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    declared = project["dependencies"] + project["optional-dependencies"]["dev"]
    lines = (ROOT / "requirements.txt").read_text().splitlines()
    required = [x.strip() for x in lines if x.strip() and not x.strip().startswith("#")]
    assert sorted(declared) == sorted(required)


def test_every_path_in_the_repo_map_exists():
    section = (ROOT / "README.md").read_text().split("## Repo map", 1)[1].split("\n## ", 1)[0]
    paths = re.findall(r"^\| `([^`]+)` \|", section, re.M)
    assert len(paths) >= 5
    missing = [p for p in paths if not (ROOT / p).exists()]
    assert not missing, missing


def test_the_docs_exist():
    names = {p.name for p in DOCS.glob("*.md")}
    assert {"findings.md", "method.md", "model_card.md", "data_dictionary.md", "warehouse.md"} <= names


@pytest.mark.parametrize("md", MARKDOWN, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_relative_link_resolves(md):
    for target in LINK.findall(md.read_text()):
        if re.match(r"[a-z][a-z+.-]*:", target) or target.startswith("#"):
            continue  # a URL or an anchor on the same page
        assert (md.parent / target.split("#")[0]).exists(), f"{md.name}: {target}"


@pytest.mark.parametrize("md", MARKDOWN, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_docs_keep_the_wording_rules(md):
    prose = CODE.sub(" ", md.read_text()).lower()  # column names such as `average_salary` are code
    for phrase in ("predicts default", "salary", "high earner"):
        assert phrase not in prose, f"{md.name}: {phrase!r}"
    assert not re.search(r"\bauc\b", prose), f"{md.name}: AUC"


def _repo_text_files():
    if not shutil.which("git") or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, check=True).stdout.decode()
    for rel in sorted(set(out.split("\0"))):
        if not rel or rel.startswith(GENERATED_DATA):
            continue
        try:
            yield rel, (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue  # binary, or deleted in the working tree


def test_no_repo_file_points_at_private_notes():
    hits = [rel for rel, text in _repo_text_files() if NOTES_DIR in text]
    assert not hits, hits
