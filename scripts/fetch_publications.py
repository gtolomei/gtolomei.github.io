#!/usr/bin/env python3
"""
fetch_publications.py — DBLP fetch + classify for gtolomei.github.io

Usage:
    python3 scripts/fetch_publications.py

Outputs:
    data/publications.json          canonical JSON dump
    assets/js/publications-data.js  window.PUBLICATIONS for the browser
    sitemap.xml                     <lastmod> updated to today

Importable:
    from fetch_publications import load_venues, load_topics, classify_topics
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from scholarly import scholarly

import yaml

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).resolve().parent.parent
VENUES_YML  = ROOT / "data" / "venues.yml"
TOPICS_YML  = ROOT / "data" / "topics.yml"
PUB_JSON    = ROOT / "data" / "publications.json"
PUB_JS      = ROOT / "assets" / "js" / "publications-data.js"
GOOGLE_SCHOLAR_JSON    = ROOT / "data" / "scholar.json"
GOOGLE_SCHOLAR_ID     = "Y2R2DXEAAAAJ" 
GOOGLE_SCHOLAR_URL = f"https://scholar.google.com/citations?user={GOOGLE_SCHOLAR_ID}"
SITEMAP_XML = ROOT / "sitemap.xml"

DBLP_PID     = "72/7456"
DBLP_XML_URL = f"https://dblp.org/pid/{DBLP_PID}.xml"
OWNER_NAME   = "Gabriele Tolomei"

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
    return data


def load_topics(path: Path = TOPICS_YML) -> list:
    """Load and return the topics YAML as a list of topic dicts."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Venue/type helpers ─────────────────────────────────────────────────────

def _venue_abbrev(key: str) -> str:
    """Extract venue abbreviation from a DBLP key.

    Examples
    --------
    conf/sigir/TolomeiS17   → sigir
    journals/tkde/TolomeiS21 → tkde
    corr/abs/2305.01234      → corr
    """
    parts = key.split("/")
    return parts[1].lower() if len(parts) >= 2 else ""


def _is_workshop(booktitle: str) -> bool:
    if not booktitle:
        return False
    return bool(re.search(r"workshop", booktitle, re.IGNORECASE)) or " @ " in booktitle


def classify_type(key: str, booktitle: str, publtype: str, venues: dict) -> str:
    """Return one of: preprint | workshop | a_star | a_conf | q1 | other."""
    abbrev = _venue_abbrev(key)

    # 1. Preprint: DBLP informal flag OR CoRR
    if publtype == "informal" or abbrev == "corr":
        return "preprint"

    # 2. Workshop: booktitle contains 'workshop' or ' @ ' shorthand
    if _is_workshop(booktitle):
        return "workshop"

    # 3. Conference papers
    if key.startswith("conf/"):
        if abbrev in venues.get("a_star_confs", set()):
            return "a_star"
        if abbrev in venues.get("a_confs", set()):
            return "a_conf"
        return "other"

    # 4. Journal articles
    if key.startswith("journals/"):
        if abbrev in venues.get("q1_journals", set()):
            return "q1"
        return "other"

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

def _should_skip(key: str, title: str, venues: dict) -> bool:
    if key in venues.get("skip_keys", []):
        return True
    for pattern in venues.get("skip_title_patterns", []):
        try:
            if re.search(pattern, title, re.IGNORECASE):
                return True
        except re.error:
            pass
    return False


# ── XML parsing ────────────────────────────────────────────────────────────

def _remove_trailing_numbers(s):
    return re.sub(r'\s*\d+$', '', s)

def _parse_authors(element) -> list:
    return [
        _remove_trailing_numbers((a.text or "").strip())
        for a in element.findall("author")
        if (a.text or "").strip()
    ]


def _get_ee(element) -> str:
    """Return first <ee> URL, preferring non-paywall links."""
    ees = [e.text or "" for e in element.findall("ee") if e.text]
    if not ees:
        return ""
    # prefer non-paywall: doi.org links last
    non_doi = [u for u in ees if "doi.org" not in u]
    return (non_doi or ees)[0]

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


def fetch_and_parse(url: str = DBLP_XML_URL) -> list:
    """Fetch the DBLP author XML and return a list of raw paper dicts."""
    print(f"Fetching {url} …", flush=True)
    with urlopen(url, timeout=30) as resp:
        xml_bytes = resp.read()

    root = ET.fromstring(xml_bytes)
    papers = []

    for el in root.findall(".//r/*"):
        tag = el.tag

        if tag not in ("inproceedings", "article", "incollection"):
            continue

        key      = el.get("key", "")
        publtype = el.get("publtype", "")
        title    = _smart_title((el.findtext("title") or "").strip().rstrip("."))
        year_str = el.findtext("year") or "0"

        try:
            year = int(year_str)
        except ValueError:
            year = 0

        authors      = _parse_authors(el)
        booktitle    = (el.findtext("booktitle") or "").strip()
        journal      = (el.findtext("journal") or "").strip()
        venue_full   = booktitle or journal or _venue_abbrev(key).upper()
        venue_short  = _venue_abbrev(key).upper()
        url_paper    = _get_ee(el) or f"https://dblp.org/rec/{key}"

        # replace CoRR with arXiv
        if "arxiv".casefold() in url_paper.casefold():
            venue_full = venue_short = "arXiv"

        papers.append({
            "key":        key,
            "title":      title,
            "authors":    authors,
            "year":       year,
            "venue":      venue_short,
            "venue_full": venue_full,
            "booktitle":  booktitle,
            "publtype":   publtype,
            "url":        url_paper,
        })

    return papers


# ── Main pipeline ──────────────────────────────────────────────────────────

def build(venues: dict, topics: list, papers_raw: list) -> list:
    """Filter, classify, and enrich raw paper dicts."""
    result = []

    for p in papers_raw:
        key   = p["key"]
        title = p["title"]

        if not title:
            continue

        if _should_skip(key, title, venues):
            print(f"  SKIP  {title[:72]}", flush=True)
            continue

        pub_type = classify_type(key, p["booktitle"], p["publtype"], venues)
        topics_list = classify_topics(title, p["venue_full"], topics)

        result.append({
            "key":        key,
            "title":      title,
            "authors":    p["authors"],
            "year":       p["year"],
            "venue":      p["venue"],
            "venue_full": p["venue_full"],
            "type":       pub_type,
            "topics":     topics_list,
            "url":        p["url"],
        })

    # Sort: newest first, then alphabetical within year
    result.sort(key=lambda x: (-x["year"], x["title"].lower()))
    return result


def write_outputs(publications: list, google_scholar_stats: map) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1) data/publications.json
    PUB_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(PUB_JSON, "w", encoding="utf-8") as f:
        json.dump(publications, f, indent=2, ensure_ascii=False)
    print(f"  → {PUB_JSON}  ({len(publications)} entries)", flush=True)

    # 2) data/google_scholar.json
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


def print_stats(publications: list, google_scholar_stats: map) -> None:
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
    #print(f"{'─'*52}\n")
    print()

    # Google Scholar
    citations = google_scholar_stats["citations"]
    h_index   = google_scholar_stats["h_index"]
    i10_index = google_scholar_stats["i10_index"] 

    #print(f"\n{'─'*52}")
    print(f"  ***** Google Scholar {GOOGLE_SCHOLAR_ID} *****")
    print(f"  N. of citations  : {citations}")
    print(f"  h-index          : {h_index}")
    print(f"  i10-index        : {i10_index}")
    print(f"  ***************************************")
    print(f"{'─'*52}\n")


def fetch_google_scholar_stats() -> dict:
    """Fetch Google Scholar stats, falling back to cached scholar.json on failure."""
    try:
        author = scholarly.search_author_id(GOOGLE_SCHOLAR_ID)
        author = scholarly.fill(author)
        data = {
            "citations": author.get("citedby", 0),
            "h_index":   author.get("hindex", 0),
            "i10_index": author.get("i10index", 0),
        }
        print("  Google Scholar stats fetched successfully.", flush=True)
        return data

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

    papers_raw   = fetch_and_parse()
    publications = build(venues, topics, papers_raw)
    # Fetching Google Scholar's stats with `scholarly` is very unreliable
    google_scholar_stats = fetch_google_scholar_stats()

    print_stats(publications, google_scholar_stats)
    write_outputs(publications, google_scholar_stats)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
