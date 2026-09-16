#!/usr/bin/env python3
"""
fetch_publications.py — OpenAlex fetch + classify for gtolomei.github.io

DBLP put its per-author XML endpoint behind an "Anubis" bot-wall
(https://github.com/TecharoHQ/anubis) sometime around early Sept 2026 —
it returns an HTML JS-challenge page instead of XML to any non-browser
client, unconditionally. No amount of retry/backoff/headers gets past
that, so as of v2.0 this script sources data from the OpenAlex API
(https://openalex.org) instead, keyed on the author's ORCID.

Usage:
    python3 scripts/fetch_publications.py

Outputs:
    data/publications.json          canonical JSON dump
    data/sync_status.json           last-run bookkeeping (for CI alerting)
    assets/js/publications-data.js  window.PUBLICATIONS for the browser
    sitemap.xml                     <lastmod> updated to today

Importable:
    from fetch_publications import load_venues, load_topics, classify_topics
"""

import concurrent.futures
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests
import yaml
from scholarly import scholarly

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).resolve().parent.parent
VENUES_YML  = ROOT / "data" / "venues.yml"
TOPICS_YML  = ROOT / "data" / "topics.yml"
PUB_JSON    = ROOT / "data" / "publications.json"
PUB_JS      = ROOT / "assets" / "js" / "publications-data.js"
GOOGLE_SCHOLAR_JSON = ROOT / "data" / "scholar.json"
GOOGLE_SCHOLAR_ID   = "Y2R2DXEAAAAJ"
GOOGLE_SCHOLAR_URL  = f"https://scholar.google.com/citations?user={GOOGLE_SCHOLAR_ID}"
SITEMAP_XML       = ROOT / "sitemap.xml"
SYNC_STATUS_JSON  = ROOT / "data" / "sync_status.json"

# Consecutive failed nights before the workflow flags it via a GitHub Issue.
# One bad night stays quiet; a real stall gets surfaced instead of silently
# sitting there (this is how the sync went stale for ~2 weeks unnoticed).
FAILURE_ALERT_THRESHOLD = 3

# ── OpenAlex source ──────────────────────────────────────────────────────
OPENALEX_ORCID     = "0000-0001-7471-6659"
OPENALEX_MAILTO    = "tolomei@di.uniroma1.it"  # puts requests in OpenAlex's "polite pool"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
OWNER_NAME         = "Gabriele Tolomei"

# ── Useful stuff ──────────────────────────────────────────────────────────────────
ACRONYMS = {"IoT", "AI", "NLP", "GPU", "CPU", "LLM", "GNN", "XAI", "KG"}
SMALL_WORDS = {"a", "an", "and", "at", "but", "by", "for", "from", "in", "of", "on", "or", "the", "through", "to", "via", "with"}

# ── Public loaders (importable for unit tests) ─────────────────────────────

def load_venues(path: Path = VENUES_YML) -> dict:
    """Load and return the venues YAML as a plain dict."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    # normalise all venue lists to lowercase sets for O(1) lookup
    for key in ("a_star_confs", "a_confs", "q1_journals"):
        data[key] = {v.lower() for v in data.get(key) or []}
    data.setdefault("skip_keys", [])
    data.setdefault("skip_title_patterns", [])
    # venue_aliases: acronym -> {"patterns": [...], "exclude": [...]} —
    # regex overrides for venues whose OpenAlex source name doesn't
    # literally contain the acronym (e.g. "icml" -> the source is named
    # "International Conference on Machine Learning", not "ICML").
    data["venue_aliases"] = {
        k.lower(): v for k, v in (data.get("venue_aliases") or {}).items()
    }
    return data


def load_topics(path: Path = TOPICS_YML) -> list:
    """Load and return the topics YAML as a list of topic dicts."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def classify_publication(work_type: str, venue_full: str, doi: str, venues: dict,) -> tuple[str, str | None]:
    """Return (publication_type, venue_acronym)."""
    work_type = (work_type or "").lower()
    venue_full = venue_full or ""

    if (work_type == "preprint" or "10.48550" in doi or "arxiv" in venue_full.casefold()):
        return "preprint", None

    if _is_workshop(venue_full):
        return "workshop", None

    if work_type == "proceedings-article":
        tier, acronym = classify_venue_tier(venue_full, venues)

        if tier in ("a_star", "a_conf"):
            return tier, acronym

        return "other", None

    if work_type in ("article", "review"):
        tier, acronym = classify_venue_tier(venue_full, venues)
        if tier == "q1":
            return "q1", acronym
        
        return "other", None

    return "other", None

# ── Venue/type helpers ─────────────────────────────────────────────────────

def _is_workshop(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"workshop", text, re.IGNORECASE)) or " @ " in text


def _venue_matches(acronym: str, venue_full: str, venue_aliases: dict) -> bool:
    """Does venue_full correspond to the given tier-list acronym?

    Tries the acronym itself as a whole word first, then any configured
    alias patterns for it, honoring an optional exclude list (needed to
    tell e.g. 'sp' — IEEE S&P — apart from 'eurosp' — its European
    sibling — since both source names contain "Security and Privacy").
    """
    if not venue_full:
        return False

    cfg = venue_aliases.get(acronym, {})
    for exc in cfg.get("exclude", []):
        try:
            if re.search(exc, venue_full, re.IGNORECASE):
                return False
        except re.error:
            pass

    patterns = [rf"\b{re.escape(acronym)}\b"] + list(cfg.get("patterns", []))
    for pat in patterns:
        try:
            if re.search(pat, venue_full, re.IGNORECASE):
                return True
        except re.error:
            pass
    return False


def classify_venue_tier(venue_full: str, venues: dict):
    """Return (tier, matched_acronym); tier is one of a_star/a_conf/q1/None."""
    aliases = venues.get("venue_aliases", {})
    for acronym in venues.get("a_star_confs", set()):
        if _venue_matches(acronym, venue_full, aliases):
            return "a_star", acronym
    for acronym in venues.get("a_confs", set()):
        if _venue_matches(acronym, venue_full, aliases):
            return "a_conf", acronym
    for acronym in venues.get("q1_journals", set()):
        if _venue_matches(acronym, venue_full, aliases):
            return "q1", acronym
    return None, None


def classify_type(work_type: str, venue_full: str, doi: str, venues: dict) -> str:
    """Return one of: preprint | workshop | a_star | a_conf | q1 | other."""
    work_type = (work_type or "").lower()
    venue_full = venue_full or ""

    # 1. Preprint: arXiv (by DOI prefix or venue name) or OpenAlex's own flag
    if work_type == "preprint" or "10.48550" in doi or "arxiv" in venue_full.casefold():
        return "preprint"

    # 2. Workshop: venue name contains 'workshop' or the ' @ ' shorthand
    if _is_workshop(venue_full):
        return "workshop"

    # 3. Conference papers
    if work_type == "proceedings-article":
        tier, _ = classify_venue_tier(venue_full, venues)
        return tier if tier in ("a_star", "a_conf") else "other"

    # 4. Journal articles (and reviews)
    if work_type in ("article", "review"):
        tier, _ = classify_venue_tier(venue_full, venues)
        return "q1" if tier == "q1" else "other"

    return "other"


# ── Topic classifier ───────────────────────────────────────────────────────

def classify_topics(title: str, venue_full: str, topics: list) -> list:
    """Return list of matching topic slugs for a paper.

    Each topic whose patterns (OR-combined, case-insensitive) match the
    concatenated title + venue string is included.  The catch-all entry
    (empty patterns list) is used only when nothing else matches.
    """
    text = f"{title} {venue_full}".lower()
    matched = []
    catchall = None

    for topic in topics:
        slug     = topic.get("slug", "misc")
        patterns = topic.get("patterns") or []

        if not patterns:
            catchall = slug
            continue

        for pat in patterns:
            try:
                if re.search(pat, text, re.IGNORECASE):
                    matched.append(slug)
                    break
            except re.error:
                pass  # skip malformed patterns

    return matched if matched else ([catchall] if catchall else ["misc"])


# ── Skip logic ────────────────────────────────────────────────────────────

def _should_skip(key: str, doi: str, title: str, venues: dict) -> bool:
    skip_keys = venues.get("skip_keys", [])
    if key in skip_keys or (doi and doi in skip_keys):
        return True
    for pattern in venues.get("skip_title_patterns", []):
        try:
            if re.search(pattern, title, re.IGNORECASE):
                return True
        except re.error:
            pass
    return False


# ── Title casing ────────────────────────────────────────────────────────────

def _remove_trailing_numbers(s):
    return re.sub(r'\s*\d+$', '', s)

def _smart_title(text):
    words = text.split()
    result = []

    for i, word in enumerate(words):
        is_first = (i == 0)

        # 1. Preserve ALL-CAPS words (user requirement)
        if word.isupper():
            result.append(word)
            continue

        # 2. Preserve known acronyms (even if not all caps)
        if word in ACRONYMS:
            result.append(word)
            continue

        # 3. Handle hyphenated words recursively
        if "-" in word:
            parts = word.split("-")
            titled = "-".join(_smart_title_part(p, is_first=True) for p in parts)
            result.append(titled)
            continue

        # 4. Small words lowercase (unless first word)
        if not is_first and word.lower() in SMALL_WORDS:
            result.append(word.lower())
            continue

        # 5. Default title case
        result.append(_smart_title_part(word, is_first))

    return " ".join(result)

def _smart_title_part(word, is_first):
    # preserve ALL CAPS inside hyphen handling too
    if word.isupper():
        return word
    if word in ACRONYMS:
        return word
    return word.capitalize()


# ── OpenAlex fetch ──────────────────────────────────────────────────────────

def fetch_and_parse(orcid: str = OPENALEX_ORCID, mailto: str = OPENALEX_MAILTO) -> list:
    """Fetch every OpenAlex work for `orcid` and return a list of raw paper dicts."""
    print(f"Fetching OpenAlex works for ORCID {orcid} …", flush=True)

    headers = {
        "User-Agent": (
            f"gtolomei.github.io-publications-bot/2.0 "
            f"(mailto:{mailto}; +https://gtolomei.github.io)"
        ),
        "Accept": "application/json",
    }
    base_params = {
        "filter": f"author.orcid:{orcid}",
        "per-page": 200,
        "mailto": mailto,
        "select": "id,doi,title,display_name,publication_year,type,primary_location,authorships",
    }

    all_results = []
    cursor = "*"
    page = 1

    while cursor:
        params = dict(base_params, cursor=cursor)
        data = None
        last_err = None

        for attempt in range(1, 4):
            try:
                # (10, 30): 10 s to establish the TCP connection, 30 s per read
                # chunk.  A plain scalar timeout=30 only covers the read phase
                # and does not protect against slow DNS / TCP stalls on CI.
                resp = requests.get(
                    OPENALEX_WORKS_URL, params=params, headers=headers,
                    timeout=(10, 30),
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except (requests.RequestException, ValueError) as e:
                last_err = e
                print(f"  attempt {attempt}/3 failed ({e}); retrying…", flush=True)
                time.sleep(5 * attempt)

        if data is None:
            raise RuntimeError(
                f"Could not fetch OpenAlex works (page {page}) after 3 attempts: {last_err}"
            )

        results = data.get("results", [])
        all_results.extend(results)
        print(f"  page {page}: {len(results)} works (total so far: {len(all_results)})", flush=True)

        cursor = (data.get("meta") or {}).get("next_cursor")
        page += 1
        if not results:
            break

    if not all_results:
        raise RuntimeError(
            f"OpenAlex returned zero works for ORCID {orcid} — "
            "check that the ORCID/filter is still correct."
        )

    papers = []
    for w in all_results:
        title = _smart_title((w.get("title") or w.get("display_name") or "").strip().rstrip("."))
        if not title:
            continue

        year = w.get("publication_year") or 0
        doi  = (w.get("doi") or "").strip()
        oa_id = (w.get("id") or "").rsplit("/", 1)[-1]  # e.g. "W2741809807"
        key = oa_id or doi or title  # stable-ish unique key, replaces the old DBLP key

        primary    = w.get("primary_location") or {}
        source     = primary.get("source") or {}

        # Prefer the structured source name; fall back to the raw string that
        # OpenAlex records even when it cannot resolve a source entity.  This
        # rescues ~27 papers whose primary_location.source is null but whose
        # raw_source_name contains the real conference/journal name.
        venue_full = (
            source.get("display_name")
            or primary.get("raw_source_name")
            or ""
        ).strip()

        # OpenAlex sometimes labels conference papers as type="article".
        # raw_type (inside primary_location) is closer to the publisher's own
        # classification and is more reliable for proceedings-article detection.
        raw_type = (primary.get("raw_type") or "").strip()

        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in (w.get("authorships") or [])
            if (a.get("author") or {}).get("display_name")
        ]

        url_paper = primary.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else "")
        if not url_paper and oa_id:
            url_paper = f"https://openalex.org/{oa_id}"

        # replace CoRR/arXiv venue names with a consistent short label
        if "arxiv" in venue_full.casefold() or "10.48550" in doi:
            venue_full = "arXiv"

        papers.append({
            "key":           key,
            "title":         title,
            "authors":       authors,
            "year":          year,
            "venue_full":    venue_full,
            "openalex_type": w.get("type") or "",
            "raw_type":      raw_type,
            "doi":           doi,
            "url":           url_paper,
        })

    return papers


# ── Sync status tracking (for failure visibility) ──────────────────────────

def load_sync_status() -> dict:
    """Load the last known sync status, or sensible defaults if absent/corrupt."""
    if SYNC_STATUS_JSON.exists():
        try:
            with open(SYNC_STATUS_JSON, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "last_success": None,
        "last_attempt": None,
        "consecutive_failures": 0,
        "last_error": None,
    }


def write_sync_status(status: dict) -> None:
    SYNC_STATUS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(SYNC_STATUS_JSON, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)
    print(f"  → {SYNC_STATUS_JSON}", flush=True)


def record_success(status: dict) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status["last_success"] = ts
    status["last_attempt"] = ts
    status["consecutive_failures"] = 0
    status["last_error"] = None
    return status


def record_failure(status: dict, error: str) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status["last_attempt"] = ts
    status["consecutive_failures"] = status.get("consecutive_failures", 0) + 1
    status["last_error"] = error
    return status


# ── Main pipeline ──────────────────────────────────────────────────────────

def build(venues: dict, topics: list, papers_raw: list) -> list:
    """Filter, classify, and enrich raw paper dicts."""
    result = []
    unclassified = []  # for the post-run audit report

    for p in papers_raw:
        key, title, doi = p["key"], p["title"], p["doi"]

        if not title:
            continue

        if _should_skip(key, doi, title, venues):
            print(f"  SKIP  {title[:72]}", flush=True)
            continue

        # Use raw_type as a fallback when OpenAlex's top-level type is
        # misleading (e.g. "article" for a proceedings paper).  This fixes
        # conference papers such as CIKM entries that arrive as type=article.
        effective_type = p["openalex_type"] or p.get("raw_type", "")
        if (p["openalex_type"] == "article" and p.get("raw_type") == "proceedings-article"):
            effective_type = "proceedings-article"

        pub_type, venue_acronym = classify_publication(effective_type, p["venue_full"], doi, venues,)
        if venue_acronym:
            print(f"  MATCH  {venue_acronym:12s} ← {p['venue_full']}", flush=True,)

        topics_list = classify_topics(title, p["venue_full"], topics,)

        if pub_type == "other" and p["venue_full"]:
            print(f"  OTHER  {p['venue_full']}", flush=True,)
            unclassified.append((p["venue_full"], title[:60]))

        result.append({
            "key": key,
            "title": title,
            "authors": p["authors"],
            "year": p["year"],
            "venue": venue_acronym or p["venue_full"],
            "venue_full": p["venue_full"],
            "type": pub_type,
            "topics": topics_list,
            "url": p["url"],
            })

    # Sort: newest first, then alphabetical within year
    result.sort(key=lambda x: (-x["year"], x["title"].lower()))

    if unclassified:
        print(
            f"\n  NOTE: {len(unclassified)} conference/journal paper(s) classified as "
            "'other' (no a_star/a_conf/q1 match) — review venue_aliases in data/venues.yml:",
            flush=True,
        )
        seen_venues = {}
        for vf, t in unclassified:
            seen_venues.setdefault(vf, t)
        for vf, t in list(seen_venues.items())[:40]:
            print(f"    - {vf}   (e.g. {t}…)", flush=True)

    return result


def write_outputs(publications: list, google_scholar_stats: dict) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1) data/publications.json
    PUB_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(PUB_JSON, "w", encoding="utf-8") as f:
        json.dump(publications, f, indent=2, ensure_ascii=False)
    print(f"  → {PUB_JSON}  ({len(publications)} entries)", flush=True)

    # 2) data/scholar.json
    GOOGLE_SCHOLAR_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(GOOGLE_SCHOLAR_JSON, "w", encoding="utf-8") as f:
        json.dump(google_scholar_stats, f, indent=2, ensure_ascii=False)
    print(f"  → {GOOGLE_SCHOLAR_JSON}  ({len(google_scholar_stats)} entries)", flush=True)

    # 3) assets/js/publications-data.js
    PUB_JS.parent.mkdir(parents=True, exist_ok=True)
    js_blob = json.dumps(publications, indent=2, ensure_ascii=False)
    scholar_blob = json.dumps(google_scholar_stats, indent=2, ensure_ascii=False)
    with open(PUB_JS, "w", encoding="utf-8") as f:
        f.write(f"// AUTO-GENERATED — do not edit manually\n")
        f.write(f"// Last updated: {ts}\n")
        f.write(f"window.PUBLICATIONS = {js_blob};\n")
        f.write(f"window.SCHOLAR = {scholar_blob};\n")
        f.write(f"window.PUBLICATIONS_TS = \"{ts}\"\n")
    print(f"  → {PUB_JS}", flush=True)

    # 4) sitemap.xml — update <lastmod>
    today = date.today().isoformat()
    if SITEMAP_XML.exists():
        xml_text = SITEMAP_XML.read_text(encoding="utf-8")
        xml_text = re.sub(
            r"<lastmod>[^<]+</lastmod>",
            f"<lastmod>{today}</lastmod>",
            xml_text,
        )
        SITEMAP_XML.write_text(xml_text, encoding="utf-8")
        print(f"  → sitemap.xml lastmod → {today}", flush=True)


def print_stats(publications: list, google_scholar_stats: dict) -> None:
    total    = len(publications)
    a_star   = sum(1 for p in publications if p["type"] == "a_star")
    a_conf   = sum(1 for p in publications if p["type"] == "a_conf")
    q1       = sum(1 for p in publications if p["type"] == "q1")
    workshop = sum(1 for p in publications if p["type"] == "workshop")
    preprint = sum(1 for p in publications if p["type"] == "preprint")
    other    = sum(1 for p in publications if p["type"] == "other")
    years    = sorted({p["year"] for p in publications if p["year"] > 0})
    misc_cov = sum(1 for p in publications if p["topics"] == ["misc"])

    print(f"\n{'─'*52}")
    print(f"  Total papers  : {total}")
    print(f"  A* conf       : {a_star}")
    print(f"  A conf        : {a_conf}")
    print(f"  Q1 journals   : {q1}")
    print(f"  Other conf/j  : {other}")
    print(f"  Workshops     : {workshop}")
    print(f"  Preprints     : {preprint}")
    if years:
        print(f"  Year range    : {min(years)} – {max(years)}")
    print(f"  Misc-only tag : {misc_cov}/{total}")
    print()

    citations = google_scholar_stats["citations"]
    h_index   = google_scholar_stats["h_index"]
    i10_index = google_scholar_stats["i10_index"]

    print(f"  ***** Google Scholar {GOOGLE_SCHOLAR_ID} *****")
    print(f"  N. of citations  : {citations}")
    print(f"  h-index          : {h_index}")
    print(f"  i10-index        : {i10_index}")
    print(f"  ***************************************")
    print(f"{'─'*52}\n")


# scholarly.fill() can hang indefinitely on CI/cloud IPs (Google Scholar
# rate-limits / CAPTCHAs with no timeout).  Run the fetch in a thread so
# we can enforce a hard deadline and fall back to cached data on a hang.
_SCHOLAR_TIMEOUT_SECONDS = 60


def _do_fetch_google_scholar_stats() -> dict:
    """Inner fetch — runs in a thread so it can be killed on timeout."""
    author = scholarly.search_author_id(GOOGLE_SCHOLAR_ID)
    author = scholarly.fill(author)
    return {
        "citations": author.get("citedby", 0),
        "h_index":   author.get("hindex", 0),
        "i10_index": author.get("i10index", 0),
    }


def fetch_google_scholar_stats() -> dict:
    """Fetch Google Scholar stats, falling back to cached scholar.json on failure or timeout."""
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_fetch_google_scholar_stats)
            data = future.result(timeout=_SCHOLAR_TIMEOUT_SECONDS)
        print("  Google Scholar stats fetched successfully.", flush=True)
        return data

    except concurrent.futures.TimeoutError:
        print(
            f"  WARNING: Google Scholar fetch timed out after {_SCHOLAR_TIMEOUT_SECONDS}s "
            "(likely blocked by rate-limiting or CAPTCHA on this IP).",
            flush=True,
        )
    except Exception as e:
        print(f"  WARNING: Could not fetch Google Scholar stats: {e}", flush=True)

    if GOOGLE_SCHOLAR_JSON.exists():
        print(f"  Falling back to cached {GOOGLE_SCHOLAR_JSON} …", flush=True)
        with open(GOOGLE_SCHOLAR_JSON, encoding="utf-8") as f:
            return json.load(f)

    print("  No cached scholar.json found — returning zeroed stats.", flush=True)
    return {"citations": 0, "h_index": 0, "i10_index": 0}


def main():
    venues = load_venues()
    topics = load_topics()
    print(
        f"Loaded {len(venues.get('a_star_confs', []))} A* confs, "
        f"{len(venues.get('a_confs', []))} A confs, "
        f"{len(venues.get('q1_journals', []))} Q1 journals, "
        f"{len(topics)} topic classifiers",
        flush=True,
    )

    status = load_sync_status()

    # Hard wall-clock deadline for the OpenAlex fetch.  Even with per-request
    # timeouts, DNS stalls or trickle-slow connections on CI can hold up the
    # entire pagination loop for 10+ minutes.  180 s is generous for a ~77-
    # work corpus while still being well within GitHub Actions' 6-hour limit.
    _OPENALEX_DEADLINE = 180

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
            _fut = _ex.submit(fetch_and_parse)
            try:
                papers_raw = _fut.result(timeout=_OPENALEX_DEADLINE)
            except concurrent.futures.TimeoutError:
                raise RuntimeError(
                    f"OpenAlex fetch timed out after {_OPENALEX_DEADLINE}s "
                    "(network stall on CI — will retry next run)."
                )
        publications = build(venues, topics, papers_raw)
    except Exception as e:
        # Leave the previously-published data/publications.json and
        # assets/js/publications-data.js untouched, and exit 0 so the
        # nightly workflow doesn't go red — it will simply try again on
        # the next scheduled run. data/sync_status.json tracks how many
        # nights this has happened in a row, and the workflow opens a
        # GitHub Issue once FAILURE_ALERT_THRESHOLD is hit.
        print(f"  WARNING: Could not fetch/parse OpenAlex data: {e}", flush=True)
        print(
            "  Leaving existing publications data untouched for this run "
            "(will retry on the next scheduled run).",
            flush=True,
        )
        status = record_failure(status, str(e))
        write_sync_status(status)
        print(
            f"  consecutive_failures={status['consecutive_failures']} "
            f"(alert threshold: {FAILURE_ALERT_THRESHOLD})",
            flush=True,
        )
        sys.exit(0)

    # Fetching Google Scholar's stats with `scholarly` is very unreliable
    google_scholar_stats = fetch_google_scholar_stats()

    print_stats(publications, google_scholar_stats)
    write_outputs(publications, google_scholar_stats)
    status = record_success(status)
    write_sync_status(status)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()