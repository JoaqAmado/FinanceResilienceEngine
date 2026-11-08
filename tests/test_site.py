"""The landing page in site/ keeps the wording rules, every link and asset in it resolves, and every number in its
text (alt text included) is recomputed here by the engine, the same way tests/test_docs.py pins the docs.
"""
import importlib.util
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from resilience import benchmark as BM
from resilience import evidence as E
from resilience import warning as W
from resilience.core import (BASELINE, EI_2026_MAX_WEEKLY, FURNACE, LAID_OFF_EI, LAID_OFF_EI_CAPPED, apply_shock,
                              backup_ladder, build_metrics)
from resilience.portfolio import INCOME_LABELS, QUARTER_CUT_PCT, build_all
from test_docs import BILLS_PCT, DEFINITIONS, EI_PCT, TARGET, needs_data, numbers

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PAGE = SITE / "index.html"
IMG_BUDGET_BYTES = 2_000_000
DEMO_MINUTES = "2"  # "the 2-minute demo": the video's length, not a figure
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class Page(HTMLParser):
    """The page's text as a reader gets it (title, body text, alt text), its links and assets, ids and tags."""
    INLINE = {"a", "span", "strong", "em", "b", "i", "abbr"}
    SKIP = {"script", "style"}

    def __init__(self, html: str):
        super().__init__()
        self.parts, self.refs, self.ids, self.tags, self._skip = [], [], set(), [], 0
        self.feed(html)
        self.text = re.sub(r"\s+", " ", "".join(self.parts)).strip()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if tag in self.SKIP:
            self._skip += 1
        if tag not in self.INLINE:
            self.parts.append(" ")
        if a.get("id"):
            self.ids.add(a["id"])
        for key in ("href", "src"):
            if a.get(key):
                self.refs.append(a[key])
        if a.get("srcset"):
            self.refs += [c.strip().split()[0] for c in a["srcset"].split(",")]
        for key in ("alt", "aria-label", "title"):
            if a.get(key):
                self.parts.append(f" {a[key]} ")
        if tag == "meta" and a.get("name") == "description":
            self.parts.append(f" {a['content']} ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip -= 1
        if tag not in self.INLINE:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


@pytest.fixture(scope="module")
def page():
    return Page(PAGE.read_text(encoding="utf-8"))


# ------------------------------------------------------------- wording, links, assets

def test_page_keeps_the_wording_rules():
    text = PAGE.read_text(encoding="utf-8").lower()
    for phrase in ("predicts default", "salary", "high earner", "income", "discretionary", "every customer"):
        assert phrase not in text, phrase
    assert not re.search(r"\bauc\b", text), "AUC"


def _is_url(ref: str) -> bool:
    return bool(re.match(r"[a-z][a-z+.-]*:", ref))


def test_every_relative_link_and_asset_exists(page):
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    refs = page.refs + re.findall(r"url\(\s*['\"]?([^'\")]+)", css)
    assert refs
    for ref in refs:
        if ref.startswith("#"):
            assert ref[1:] in page.ids, f"no element with id {ref}"
        elif ref.startswith("data:"):
            continue
        elif _is_url(ref):
            assert ref.startswith("https://"), ref
        elif ref == "app/":
            # the web app, built next to the page by scripts/build_site.py
            assert (ROOT / "web" / "index.html").is_file() and _build_site().APP_DIR == "app"
        else:
            assert not ref.startswith("/"), f"{ref}: keep links relative so the site works from any sub-path"
            assert (SITE / ref.split("#")[0]).is_file(), ref


def test_every_image_has_alt_text_and_a_size(page):
    imgs = [a for tag, a in page.tags if tag == "img"]
    assert imgs
    for a in imgs:
        assert a.get("alt", "").strip(), a["src"]
        assert a.get("width") and a.get("height"), a["src"]


def test_images_are_small_and_web_ready():
    files = [p for p in (SITE / "img").rglob("*") if p.is_file()]
    assert files and all(p.suffix in {".webp", ".jpg", ".jpeg"} for p in files)
    assert sum(p.stat().st_size for p in files) < IMG_BUDGET_BYTES


def test_page_has_landmarks_and_one_h1(page):
    tags = [t for t, _ in page.tags]
    for landmark in ("header", "nav", "main", "footer"):
        assert landmark in tags, landmark
    assert tags.count("h1") == 1
    assert ("html", {"lang": "en"}) in page.tags


def test_demo_video_id_lives_in_one_data_attribute(page):
    demos = [a for tag, a in page.tags if a.get("id") == "demo"]
    assert len(demos) == 1 and "data-youtube-id" in demos[0]
    vid = demos[0]["data-youtube-id"]
    assert vid == "" or YOUTUBE_ID.match(vid), vid
    html = PAGE.read_text(encoding="utf-8")
    assert len(re.findall(r'\sdata-youtube-id="', html)) == 1               # one place to paste the id ...
    assert "getAttribute('data-youtube-id')" in html                         # ... which the page's script reads
    assert "youtube-nocookie.com/embed/" in html


def test_page_names_the_links_judges_need(page):
    for url in ("https://github.com/JoaqAmado/FinanceResilienceEngine", "https://devpost.com/software/tangerine-68ojg5"):
        assert url in page.refs, url
    assert page.refs.count("app/") >= 2
    assert "Built at Sheridan Datathon 2026 · Tangerine track" in page.text


def test_social_preview_points_at_an_image_in_site(page):
    from PIL import Image
    meta = {a.get("property") or a.get("name"): a.get("content") for tag, a in page.tags if tag == "meta"}
    base = "https://twin-runway.vercel.app/"
    assert meta["og:url"] == base and meta["twitter:card"] == "summary_large_image"
    assert all(meta[k].strip() for k in ("og:title", "og:description", "og:image:alt"))
    image = meta["og:image"]
    assert image.startswith(base), image
    with Image.open(SITE / image[len(base):]) as im:
        assert im.size == (int(meta["og:image:width"]), int(meta["og:image:height"]))


def test_vercel_sends_app_to_its_trailing_slash():
    # the app is built with --base=./, so at /app (no slash) ./assets and data/ would resolve against the site root
    assert json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))["trailingSlash"] is True


# ------------------------------------------------------------- the figures

@pytest.fixture(scope="module")
def figures():
    """The sentences the page quotes, all computed from data/raw/."""
    m = build_metrics()
    t = build_all(m)
    h, acc = t["headlines"].iloc[0], t["accounts"]
    n, fail = int(h["accounts"]), int(h["fail_6mo_ei55"])
    bands = t["income_bands"].set_index("income_band")
    low, high = bands.loc[INCOME_LABELS[0]], bands.loc[INCOME_LABELS[-1]]

    a = m.loc[77743]
    furnace = apply_shock(a, FURNACE)
    assert apply_shock(a, BASELINE).no_shortfall                                  # "never runs short"
    assert furnace.buffer_left < 0 and furnace.one_off > a["B"]                   # "more than the buffer"
    retiree, capped = m.loc[98952], m.loc[20331]
    ladder = backup_ladder(capped, LAID_OFF_EI)
    step = ladder.rungs[ladder.first_sufficient].step
    assert "cut non-fixed spending" in step
    step_pct = re.search(r"(\d+)%", step).group(1)

    failing = acc["runway_ei55"] < TARGET
    cuts = t["cut_histogram"].set_index("cut_as_share_of_spending")["accounts"]
    quarter = int(cuts["<= 10%"] + cuts["10-25%"])
    positive = int((failing & (acc["B"] > 0)).sum())
    assert QUARTER_CUT_PCT == 25  # "a quarter of spending"

    ev = E.build_evidence()
    es, lift = ev["summary"], ev["lift"].set_index("list_pct").loc[E.HEADLINE_LIST_PCT]
    bm = BM.cached_benchmark()
    bh = bm.row(BM.HEADLINE_BUDGET)
    assert int(bh.light) == int(lift.light) and int(bh.list_accounts) == int(lift.list_accounts)
    shared = int(bh.gradient_boosting) - int(bh.gradient_boosting_only)
    assert shared == int(bh.light) - int(bh.light_only)
    assert int(bh.gradient_boosting_only) == int(bh.light_only)                  # "each catches 9 the other misses"
    sizes = ev["lift"]["list_pct"]                                               # the lift chart's watch-list sizes
    versus = BM.versus(int(bh.gradient_boosting), int(bh.light), int(bh.gradient_boosting_only), int(bh.light_only))
    pct, went = E.HEADLINE_LIST_PCT, es["went_overdrawn"]

    sentences = [
        f"{fail:,} of {n:,} accounts ({fail / n:.1%}) can't last {TARGET} months on EI at {EI_PCT}%",
        f"{fail / n:.1%}",
        # the finding
        f"{low['fail_6mo_ei55_pct']:.1f}% → {high['fail_6mo_ei55_pct']:.1f}%",
        f"from the lowest money-in band (under {INCOME_LABELS[0][2:]} a month) to the highest "
        f"({INCOME_LABELS[-1][3:]} a month and up)",
        f"{low['median_buffer_months']:.1f} → {high['median_buffer_months']:.1f}",
        f"${a['I']:,.0f} a month comes in, yet the buffer covers only {a['B'] / a['S']:.1f} months of spending",
        f"leaves it ${-furnace.buffer_left:,.0f} short, and the judges' runway reads {furnace.months:.1f} months",
        f"so the judges' runway reads {furnace.months:.1f} months",
        f"money in ${a['I']:,.0f} a month, spending ${a['S']:,.0f} a month, buffer ${a['B']:,.0f}, which is "
        f"{a['B'] / a['S']:.1f} months of spending",
        # how it works
        f"laid off on EI at {EI_PCT}%, a furnace repair of one month's spending, or a job loss with household bills "
        f"up {BILLS_PCT}%",
        f"the real 2026 EI cap (${EI_2026_MAX_WEEKLY:,.0f} a week)",
        f"with the pension kept on job loss, the runway with the check is "
        f"{apply_shock(retiree, LAID_OFF_EI.with_(pension_aware=True)).months:.1f} months beside the judges' "
        f"{apply_shock(retiree, LAID_OFF_EI).months:.1f}",
        f"with the real 2026 EI cap, the runway with the check is {apply_shock(capped, LAID_OFF_EI_CAPPED).months:.1f}"
        f" months beside the judges' {apply_shock(capped, LAID_OFF_EI).months:.1f}",
        f"the backup ladder reaches {TARGET} months at a {step_pct}% cut of non-fixed spending",
        f"{quarter:,} of the {positive:,} failing accounts that still have a buffer get back to {TARGET} months by "
        f"cutting a quarter of spending or less",
        f"one point for each of {len(W.RULES)} rules over the account's last {W.WINDOW_ROWS} months, and from "
        f"{E.WATCH_POINTS} points the apps show it as a warning",
        *(r.label for r in W.RULES),
        # the 2025 evidence
        f"as it stood at the {es['snapshot']} snapshot, on the {es['accounts']:,} accounts rated then and still active "
        f"in {es['label_year']}. Of those, {went} first went overdrawn in {es['label_year']}, and "
        f"{es['passed_ei55']} of those {went} had passed the judges' {TARGET}-month test at the snapshot",
        f"On a {pct}% watch-list ({int(lift.list_accounts):,} of {es['accounts']:,} accounts), how many of the {went} "
        f"each ranking catches",
        f"Early-warning light, {len(W.RULES)} rules {int(lift.light)}",
        f"Buffer months, fewest first {int(lift.buffer_months)}",
        f"The judges' runway, shortest first {int(lift.ei55_runway)}",
        f"at the {pct}% list it holds {int(lift.light)} against {int(lift.ei55_runway)} and {int(lift.buffer_months)}",
        f"Gradient boosting on {len(BM.FEATURES)} features, trained on {bm.train.label_year}'s outcomes, catches "
        f"{int(bh.gradient_boosting)} on the same {pct}% watch-list: {versus} the light, but not all the same ones. "
        f"Both lists catch {shared} of them, and each catches {int(bh.gradient_boosting_only)} the other misses.",
        f"for watch-lists from {sizes.min()}% to {sizes.max()}% of the accounts",
        f"so both apps keep the {len(W.RULES)} rules anyone can read",
        # how it's built
        f"The judges' numbers match on all {n:,} accounts in Python, TypeScript and SQL (DuckDB).",
    ]
    bars = {"bar-light": int(lift.light), "bar-buffer": int(lift.buffer_months), "bar-judges": int(lift.ei55_runway)}
    return {"sentences": sentences, "accounts": set(m.index), "bars": bars, "went": went}


@needs_data
def test_page_quotes_the_engine_figures(page, figures):
    for sentence in figures["sentences"]:
        assert sentence in page.text, sentence


@needs_data
def test_no_number_on_the_page_is_hand_typed(page, figures):
    allowed = set().union(*(numbers(s) for s in figures["sentences"])) | DEFINITIONS | {BILLS_PCT, DEMO_MINUTES}
    ids = {x for x in numbers(page.text) if re.fullmatch(r"\d{5}", x)}
    assert ids and {int(x) for x in ids} <= figures["accounts"]  # account ids are real accounts
    stray = numbers(page.text) - allowed - ids
    assert not stray, f"site/index.html: numbers not computed by the engine: {sorted(stray)}"


@needs_data
def test_bars_are_drawn_to_the_numbers_they_show(page, figures):
    lift = [a for tag, a in page.tags if "lift" in a.get("class", "").split()]
    assert len(lift) == 1 and lift[0]["style"] == f"--max: {figures['went']}"
    drawn = {}
    for tag, a in page.tags:
        classes = a.get("class", "").split()
        if "bar" in classes:
            (name,) = [c for c in classes if c != "bar"]
            drawn[name] = int(re.fullmatch(r"--v: (\d+)", a["style"]).group(1))
    assert drawn == figures["bars"]


# ------------------------------------------------------------- the build script

def _build_site():
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_copies_the_page_and_builds_the_app_with_a_relative_base(tmp_path):
    bs = _build_site()
    out = tmp_path / "dist"
    copied = bs.copy_site(out)
    expected = sorted(out / p.relative_to(SITE) for p in SITE.rglob("*") if p.is_file())
    assert copied == expected and all(p.is_file() for p in copied)
    assert (out / "index.html").read_bytes() == PAGE.read_bytes()
    if bs.shutil.which("npx"):
        cmd = bs.vite_command(out)
        assert cmd[1:4] == ["vite", "build", "--base=./"] and cmd[-1] == "--emptyOutDir"
        assert cmd[cmd.index("--outDir") + 1] == str((out / "app").resolve())


@pytest.mark.parametrize("bad", ["site", "site/dist", "web/dist", ".", "docs", "resilience", ".."])
def test_build_refuses_to_write_into_the_sources(bad):
    with pytest.raises(SystemExit, match="refusing"):
        _build_site().main([str(ROOT / bad)])


def test_build_checks_the_web_app_before_writing_anything(tmp_path):
    bs = _build_site()
    bs.WEB = tmp_path / "web"  # no node_modules
    out = tmp_path / "dist"
    with pytest.raises(SystemExit, match="node_modules"):
        bs.main([str(out)])
    assert not out.exists()


def test_site_dist_is_ignored():
    assert "site_dist/" in (ROOT / ".gitignore").read_text().splitlines()
