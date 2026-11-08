"""Build the static site: the landing page at the root, the web app behind it at app/.

    .venv/bin/python scripts/build_site.py              # -> site_dist/
    .venv/bin/python scripts/build_site.py OUT_DIR

Writes
    <out>/index.html, styles.css, img/   a copy of site/, the landing page
    <out>/app/                           the web app, built by Vite with a relative base (--base=./), so it runs
                                         from any sub-path; it fetches data/... relative to app/

Needs Node 24 / npm 11 and `npm install` already run in web/. vite.config.ts and the app code are not changed.
Serve the result with any static server, for example:
    .venv/bin/python -m http.server 8000 --directory site_dist
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
WEB = ROOT / "web"
DEFAULT_OUT = ROOT / "site_dist"
APP_DIR = "app"


def copy_site(out: Path) -> list[Path]:
    """Copy site/ into out (files of an earlier build are overwritten). Returns the copied files."""
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SITE, out, dirs_exist_ok=True)
    return sorted(out / p.relative_to(SITE) for p in SITE.rglob("*") if p.is_file())


def vite_command(out: Path) -> list[str]:
    npx = shutil.which("npx")
    if npx is None:
        raise SystemExit("npx not found: install Node 24 / npm 11 to build the web app")
    return [npx, "vite", "build", "--base=./", "--outDir", str((out / APP_DIR).resolve()), "--emptyOutDir"]


def build_app(out: Path) -> None:
    if not (WEB / "node_modules").is_dir():
        raise SystemExit("web/node_modules is missing: run `npm install` in web/ first")
    subprocess.run(vite_command(out), cwd=WEB, check=True)
    for need in ("index.html", "data/accounts.json", "data/portfolio.json"):
        if not (out / APP_DIR / need).is_file():
            raise SystemExit(f"the app build is missing {APP_DIR}/{need}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python scripts/build_site.py",
                                     description="Build the landing page and the web app into one static folder.")
    parser.add_argument("out_dir", nargs="?", default=str(DEFAULT_OUT),
                        help="output folder (default: site_dist/ in the repo)")
    out = Path(parser.parse_args(argv).out_dir).resolve()
    if out == ROOT or out.is_relative_to(SITE) or out.is_relative_to(WEB):
        raise SystemExit(f"refusing to build into {out}: pick a folder outside site/ and web/, such as site_dist/")
    files = copy_site(out)
    build_app(out)
    print(f"landing page: {len(files)} files -> {out}")
    print(f"web app: {out / APP_DIR}")


if __name__ == "__main__":
    main(sys.argv[1:])
