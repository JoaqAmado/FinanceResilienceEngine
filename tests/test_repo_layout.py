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


# ------------------------------------------------ regressions from the review of the reorganized repo

def _readme_commands():
    """Each command line of the README's bash blocks, comments stripped."""
    for block in re.findall(r"```bash\n(.*?)```", (ROOT / "README.md").read_text(), re.S):
        for line in block.splitlines():
            line = line.split("  #", 1)[0].strip()
            if line:
                yield line


def test_readme_commands_run_from_the_repo_root():
    """The quickstart's web line used to `cd web` in the shell itself, so the next block's relative .venv/bin
    paths failed. A `cd` into a folder must run in a subshell `( ... )`."""
    lines = list(_readme_commands())
    assert any(".venv/bin/" in x for x in lines) and any("cd web" in x for x in lines)
    for line in lines:
        if line.startswith("("):
            continue                                    # a subshell: its cd ends with it
        for part in line.split("&&"):
            part = part.strip()
            if part.startswith("cd "):
                assert part == "cd FinanceResilienceEngine", f"leaves the shell outside the repo root: {line}"


APP_TEXT = [ROOT / "app.py", *sorted((ROOT / "resilience").glob("*.py")),
            *sorted((ROOT / "web" / "src").rglob("*.ts")), *sorted((ROOT / "web" / "src").rglob("*.tsx"))]


@pytest.mark.parametrize("path", APP_TEXT, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_app_text_keeps_the_wording_rules(path):
    """Review fix: the wording check read only the Markdown, so a 'high earner' button in app.py got through."""
    text = path.read_text(encoding="utf-8").lower()
    for phrase in ("predicts default", "salary", "high earner"):
        assert phrase not in text, f"{path.name}: {phrase!r}"
    assert not re.search(r"\bauc\b", text), f"{path.name}: AUC"


@pytest.mark.parametrize("md", MARKDOWN, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_docs_never_deny_the_scores_they_describe(md):
    """Review fix: the model card said 'no scores' next to the backtest's scores; it means no credit scores."""
    prose = CODE.sub(" ", md.read_text()).lower()
    assert "no scores" not in prose, md.name


def test_web_readme_names_every_ported_engine_module():
    """Review fix: web/README listed core, narrative and warning as the ports, but not evidence."""
    text = (ROOT / "web" / "README.md").read_text()
    ports = set()
    for ts in sorted((ROOT / "web" / "src" / "engine").glob("*.ts")):
        ports |= set(re.findall(r"port of (resilience/\w+\.py)", ts.read_text()[:400]))
    assert {"resilience/core.py", "resilience/warning.py", "resilience/evidence.py"} <= ports
    for py in sorted(ports):
        assert f"`{py}`" in text, py
        assert f"`src/engine/{Path(py).stem}.ts`" in text, py
    for word in ("backtest evidence", "lift chart", "irregular money in", "realistic cuts", "dollar cushion"):
        assert word in text, word


@pytest.mark.parametrize("module", ["resilience.portfolio", "resilience.warning", "resilience.evidence"])
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_cli_help_prints_usage_and_writes_nothing(tmp_path, module, flag):
    """Review fix: `python -m resilience.evidence --help` used to write its CSVs into a folder named --help."""
    import os
    import sys
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    out = subprocess.run([sys.executable, "-m", module, flag], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith(f"usage: python -m {module} [-h] [out_dir]")
    assert not list(tmp_path.iterdir())
    bad = subprocess.run([sys.executable, "-m", module, "--bogus"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert bad.returncode == 2 and "unrecognized arguments" in bad.stderr
    assert not list(tmp_path.iterdir())
