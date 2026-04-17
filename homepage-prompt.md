Hi! I want you to reshape my current academic website available at: https://gabrieletolomei.netlify.app/ based on my colleague Fabrizio Silvestri's:

- **Live site**: https://fabsilvestri.github.io/
- **Source**: https://github.com/fabsilvestri/fabsilvestri.github.io

Please study that repo first (especially `index.html`, `assets/css/style.css`,
`assets/js/publications.js`, `scripts/fetch_publications.py`,
`data/venues.yml`, `data/topics.yml`, and the two workflows under
`.github/workflows/`). Then scaffold an equivalent site for me, keeping the
same architecture and aesthetic but customised to my identity.

## Architecture to replicate

Single-page static site, no framework, no build step. Deployed to GitHub Pages
from a repo named `<username>.github.io`. File layout:

```
index.html
robots.txt
sitemap.xml
assets/css/style.css                  # "glass-light" theme
assets/js/publications.js             # renderer with dual filter dimensions
assets/js/publications-data.js        # GENERATED — window.PUBLICATIONS
assets/img/profile.jpg                # my photo, resized
assets/img/favicon.png                # 128×128 from the photo
data/venues.yml                       # A*/Q1 venue classification (editable)
data/topics.yml                       # research topic regex patterns (editable)
data/publications.json                # GENERATED — canonical dump
scripts/fetch_publications.py         # PyYAML-based DBLP fetch + classify
scripts/requirements.txt              # PyYAML only
.github/workflows/update-publications.yml   # nightly cron 04:00 UTC
.github/workflows/pages.yml           # deploy on push to main
```

## Features the reference site has and I want

- Sticky frosted-glass navigation pill; sections About / Research /
  Publications / Teaching / Contact / News (use the order that you believe is the most suitable)
- Hero: name with gradient accent on the surname, short bio, stats
  (total pubs / A* conference papers / years active), circular profile
  photo with gradient ring
- Use a professional color palette, fonts and font size that help also visually-impaired users. Prepare a light and a corresponding dark theme, switching from light to dark at 6:00 PM UTC and back to light at 6:00 AM UTC   
- **Publications section with two AND-combined filter dimensions**:
  - **Type** (rounded pills, purple gradient active): A* Conferences /
    Q1 Journals / Other Conferences & Journals / Workshops / Preprints
  - **Topic** (small square chips with `#` prefix, emerald green active):
    research topics with counts, populated from `data/topics.yml` at
    build time
- Each paper shows a colored **venue badge** (green = conference,
  blue = journal, amber = workshop, red = preprint), the venue
  abbreviation as the badge text, the author list with my name bolded,
  venue + year, and topic chips you can click to filter
- Classification rules (in `data/venues.yml`):
  - `a_star_confs` / `q1_journals`: lists of DBLP venue abbreviations
  - `skip_title_patterns`: regex list to drop non-papers (workshop
    organizing entries, editorials, prefaces, "Acronym Year:" prefaces,
    `X @ Venue` workshop shorthands)
  - `skip_keys`: explicit DBLP keys to drop (for invited talks / panels)
  - Copy the reference values and then tune
- Topic classifier (`data/topics.yml`) auto-tags each paper via regex
  over title + venue; a `misc` catch-all slug (empty patterns) is
  auto-assigned to any paper matching nothing else, so every paper
  shows at least one chip
- Workshops: detected by `workshops?` in the booktitle OR an `@` in
  the booktitle (the "X@Y" satellite-event shorthand)
- Full SEO head: keyword-rich `<meta description>`, Open Graph +
  Twitter Card tags, a Schema.org Person JSON-LD block with `worksFor`
  / `alumniOf` / `sameAs` / `knowsAbout`
- `sitemap.xml` + `robots.txt`; the fetch script rewrites `sitemap.xml`'s
  `<lastmod>` daily so crawlers treat the page as freshly updated
- Favicon derived from the profile photo
- **Fully responsive** — the layout must work on a 390px-wide mobile
  viewport: nav becomes horizontally scrollable, filter rows become
  horizontal carousels, hero photo centered and sized to viewport

## What I'll provide — please ask me for these in order

1. **Identity**: full name, current position and institution, short
   promotional bio (or draft one and let me edit), email, office
   address, phone (optional), a 2–4 sentence hero lede describing my
   research in one line
2. **DBLP PID**: the URL path segment; e.g. `t/GabrieleTolomei` if my
   DBLP XML is at `https://dblp.org/pid/t/GabrieleTolomei.xml` — find
   mine at https://dblp.org/search?q=<my+name> and grab the URL
3. **Profile photo**: the local path to my photo file (you'll resize
   it to 600×600)
4. **GitHub username**: so the repo goes to `<username>.github.io` and
   the site lives at `https://<username>.github.io/`
5. **External profiles**: Google Scholar author ID, ORCID, LinkedIn
   URL, Twitter/X handle, ResearchGate, Wikidata Q-ID (all optional —
   include what I have)
6. **Venue preferences**: start from the reference site's `venues.yml`
   (CORE 2023 A* for CS, Scimago Q1 CS journals) and ask me to confirm
   / adjust the lists
7. **Research topics**: propose 6–12 topics based on what you find in
   my DBLP record; I'll approve / rename / prune
8. **Teaching**: courses I currently teach, with public course pages
   if any
9. **Twitter handle**: for the Twitter Card `site`/`creator`
   attribution

## Build process

1. Scaffold the project in a new empty directory
2. Resize the photo with `sips` (macOS) or Pillow
3. Write `data/venues.yml` and `data/topics.yml` copied from the
   reference site, then tuned for me
4. Write `scripts/fetch_publications.py` mirroring the reference
   implementation (uses `yaml.safe_load`, stdlib
   `xml.etree.ElementTree`, stdlib `urllib.request`)
5. Run `python3 scripts/fetch_publications.py` locally and sanity-check
   the counts (total / A* / Q1 / workshop / preprint / topic coverage)
6. Take a screenshot via headless Chrome at both desktop (1200px) and
   mobile (390px) widths to verify visually
7. Ask me to audit the Q1 list against the Scimago Computer Science Q1
   category specifically — **when I say "Q1" I mean Scimago Q1 in a CS
   category**, not Q1 in any subject area; some journals (e.g. IEEE
   Access, JASIST) are Q1 in broader non-CS categories but Q2/Q3 in
   narrow CS ones
8. Ask me to call out any entries that are non-papers (workshop
   organisation listings, editorials, invited talks) so you can filter
   them via `skip_title_patterns` / `skip_keys`
9. Once approved: `git init`, commit, create the repo with
   `gh repo create <username>.github.io --public --source=. --push`,
   enable Pages via
   `gh api -X PUT /repos/<username>/<username>.github.io/pages -f build_type=workflow`
10. Wait for the first workflow run and curl the live URL to confirm
    HTTP 200

## Non-negotiables

- **Nightly cron must work end-to-end**: the workflow has
  `permissions: contents: write` and pushes via the default
  `GITHUB_TOKEN`. Install `requirements.txt` before running the script.
- **No secrets in the repo**
- **No framework** (no React, no Astro, no Next.js, no Jekyll) —
  plain HTML/CSS/JS only, so a graduate student can fork it and edit
  a `.yml` file
- **The fetch script must be importable**
  (`from fetch_publications import load_venues, load_topics, classify_topics`)
  so I can unit-test it later

Start by asking me the items in "What I'll provide" — don't generate
placeholder content, wait for my real answers.
