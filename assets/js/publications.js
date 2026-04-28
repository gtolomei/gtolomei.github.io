/**
 * publications.js — Renders window.PUBLICATIONS with AND-combined filters.
 *
 * Depends on:
 *   window.PUBLICATIONS  — array injected by publications-data.js
 *
 * Filter dimensions:
 *   TYPE  — rounded pills, purple-gradient active
 *   TOPIC — square chips with # prefix, emerald-green active
 *
 * Both filters are AND-combined: a paper must match the selected type
 * AND include the selected topic to appear.
 */

(function () {
  "use strict";

  /* ── Constants ──────────────────────────────────────────────── */
  const OWNER = "Gabriele Tolomei";

  const TYPE_META = [
    { slug: "all",      label: "All" },
    { slug: "a_star",   label: "A* Conferences" },
    { slug: "a_conf",   label: "A Conferences" },
    { slug: "q1",       label: "Q1 Journals" },
    { slug: "other",    label: "Other Conf. & Journals" },
    { slug: "workshop", label: "Workshops" },
    { slug: "preprint", label: "Preprints" },
  ];

  const BADGE_CLASS = {
    a_star:   "badge-conf",
    a_conf:   "badge-conf",
    q1:       "badge-journal",
    other:    "badge-other",
    workshop: "badge-workshop",
    preprint: "badge-preprint",
  };

  /* ── State ──────────────────────────────────────────────────── */
  let activeType  = "all";
  let activeTopic = "all";

  /* ── DOM refs (resolved after DOMContentLoaded) ─────────────── */
  let typeRow, topicRow, pubList, pubCountEl;

  /* ── Helper: escape HTML ────────────────────────────────────── */
  function esc(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* ── Author list: bold my name ──────────────────────────────── */
  function renderAuthors(authors) {
    return authors
      .map((a) =>
        a === OWNER
          ? `<strong class="me">${esc(a)}</strong>`
          : esc(a)
      )
      .join(", ");
  }

  /* ── Compute topic counts across all publications ───────────── */
  function topicCounts(pubs) {
    const counts = {};
    for (const p of pubs) {
      for (const t of p.topics || []) {
        counts[t] = (counts[t] || 0) + 1;
      }
    }
    return counts;
  }

  /* ── Collect ordered unique topics ─────────────────────────── */
  function orderedTopics(pubs) {
    const seen = new Set();
    const list = [];
    for (const p of pubs) {
      for (const t of p.topics || []) {
        if (!seen.has(t)) { seen.add(t); list.push(t); }
      }
    }
    return list;
  }

  /* ── Topic label map from window.TOPIC_LABELS (optional) ───── */
  function topicLabel(slug) {
    if (window.TOPIC_LABELS && window.TOPIC_LABELS[slug]) {
      return window.TOPIC_LABELS[slug];
    }
    // fallback: title-case the slug
    return slug.charAt(0).toUpperCase() + slug.slice(1).replace(/-/g, " ");
  }

  /* ── Filter logic ───────────────────────────────────────────── */
  function matchesType(pub) {
    return activeType === "all" || pub.type === activeType;
  }

  function matchesTopic(pub) {
    return activeTopic === "all" || (pub.topics || []).includes(activeTopic);
  }

  function filtered(pubs) {
    return pubs.filter((p) => matchesType(p) && matchesTopic(p));
  }

  /* ── Render a single pub card ────────────────────────────────── */
  function renderCard(pub) {
    const badgeCls = BADGE_CLASS[pub.type] || "badge-other";
    const chips = (pub.topics || [])
      .map(
        (t) =>
          `<button class="pub-chip${t === activeTopic ? " active" : ""}"
                  data-topic="${esc(t)}"
                  aria-pressed="${t === activeTopic}">${esc(topicLabel(t))}</button>`
      )
      .join("");

    const titleEl = pub.url
      ? `<a href="${esc(pub.url)}" target="_blank" rel="noopener">${esc(pub.title)}</a>`
      : esc(pub.title);

    // DOI link if URL contains doi.org
    let doiLink = "";
    if (pub.url && pub.url.includes("doi.org")) {
      doiLink = `<a href="${esc(pub.url)}" class="pub-doi" target="_blank" rel="noopener">DOI ↗</a>`;
    }

    // Normalize arXiv label
    const venueLabel = (pub.venue || "").toUpperCase() === "ARXIV" ? "arXiv" : pub.venue;

    const metadataItems = [
      esc(pub.venue_full || venueLabel),
      pub.year ? esc(String(pub.year)) : "",
      doiLink
    ].filter(Boolean);

    return `
<article class="pub-card" data-type="${esc(pub.type)}" data-topics="${esc((pub.topics||[]).join(','))}">
  <div class="pub-badge">
    <span class="badge-pill ${badgeCls}">${esc(venueLabel)}</span>
    <span class="badge-year">${esc(String(pub.year))}</span>
  </div>
  <div class="pub-body">
    <p class="pub-title">${titleEl}</p>
    <p class="pub-authors">${renderAuthors(pub.authors)}</p>
    <p class="pub-venue-line">${metadataItems.join(" · ")}</p>
    ${chips ? `<div class="pub-chips">${chips}</div>` : ""}
  </div>
</article>`;
  }

  /* ── Render the publications list ────────────────────────────── */
  function render(pubs) {
    const visible = filtered(pubs);
    pubCountEl.textContent = `Showing ${visible.length} of ${pubs.length} publications`;

    if (visible.length === 0) {
      pubList.innerHTML =
        `<p class="pub-empty">No publications match the current filters.</p>`;
      return;
    }

    let html = "";
    let lastYear = null;

    for (const pub of visible) {
      // Add year header if year changes
      if (pub.year !== lastYear) {
        html += `<h3 class="pub-year-header">${esc(String(pub.year))}</h3>`;
        lastYear = pub.year;
      }
      html += renderCard(pub);
    }

    pubList.innerHTML = html;

    // Wire up inline topic chips (must do after setting innerHTML)
    pubList.querySelectorAll(".pub-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        const topic = btn.dataset.topic;
        activeTopic = activeTopic === topic ? "all" : topic;
        updateTopicFilter(pubs);
        render(pubs);
      });
    });
  }

  /* ── Build / update type filter row ─────────────────────────── */
  function buildTypeFilter(pubs) {
    // Count per type
    const counts = {};
    for (const p of pubs) counts[p.type] = (counts[p.type] || 0) + 1;

    const label = document.createElement("span");
    label.className = "filter-label";
    label.textContent = "Type";
    typeRow.appendChild(label);

    for (const { slug, label: lbl } of TYPE_META) {
      const count = slug === "all" ? pubs.length : (counts[slug] || 0);
      if (slug !== "all" && count === 0) continue;  // hide empty types

      const btn = document.createElement("button");
      btn.className = "type-pill" + (slug === activeType ? " active" : "");
      btn.dataset.type = slug;
      btn.setAttribute("aria-pressed", String(slug === activeType));
      btn.textContent = slug === "all" ? lbl : `${lbl} (${count})`;

      btn.addEventListener("click", () => {
        activeType = slug;
        updateTypeFilter();
        render(pubs);
      });
      typeRow.appendChild(btn);
    }
  }

  function updateTypeFilter() {
    typeRow.querySelectorAll(".type-pill").forEach((btn) => {
      const active = btn.dataset.type === activeType;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-pressed", String(active));
    });
  }

  /* ── Build / update topic filter row ────────────────────────── */
  function buildTopicFilter(pubs) {
    const counts = topicCounts(pubs);
    const topics = orderedTopics(pubs);

    const label = document.createElement("span");
    label.className = "filter-label";
    label.textContent = "Topic";
    topicRow.appendChild(label);

    // "All topics" chip
    const allBtn = document.createElement("button");
    allBtn.className = "topic-chip" + (activeTopic === "all" ? " active" : "");
    allBtn.dataset.topic = "all";
    allBtn.setAttribute("aria-pressed", String(activeTopic === "all"));
    allBtn.textContent = "All";  // Changed from "all" to "All"
    allBtn.style.cssText = "--before-content: ''";
    allBtn.insertAdjacentText("afterbegin", ""); // label-only, # is pseudo

    // Override: "all" chip shouldn't show #
    allBtn.classList.add("topic-chip-all");
    allBtn.style.removeProperty("--before-content");
    // We'll strip the ::before via a specific class
    topicRow.appendChild(allBtn);

    allBtn.addEventListener("click", () => {
      activeTopic = "all";
      updateTopicFilter(pubs);
      render(pubs);
    });

    for (const slug of topics) {
      const btn = document.createElement("button");
      btn.className = "topic-chip" + (slug === activeTopic ? " active" : "");
      btn.dataset.topic = slug;
      btn.setAttribute("aria-pressed", String(slug === activeTopic));
      const cnt = counts[slug] || 0;
      btn.textContent = `${topicLabel(slug)} (${cnt})`;

      btn.addEventListener("click", () => {
        activeTopic = slug;
        updateTopicFilter(pubs);
        render(pubs);
      });
      topicRow.appendChild(btn);
    }
  }

  function updateTopicFilter(pubs) {
    topicRow.querySelectorAll(".topic-chip").forEach((btn) => {
      const active = btn.dataset.topic === activeTopic;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-pressed", String(active));
    });
  }

  /* ── Hero stats ──────────────────────────────────────────────── */
  function fillHeroStats(pubs) {
    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };

    const total  = pubs.length;
    const astar  = pubs.filter((p) => p.type === "a_star").length;
    const aconf  = pubs.filter((p) => p.type === "a_conf").length;
    const q1     = pubs.filter((p) => p.type === "q1").length;
    const years  = pubs.map((p) => p.year).filter(Boolean);
    const minYr  = years.length ? Math.min(...years) : "—";
    const maxYr  = years.length ? Math.max(...years) : "—";
    //const span   = years.length ? `${minYr}–${maxYr}` : "—";
    const span = years.length ? (maxYr - minYr + 1) : "—";

    set("stat-total",   total);
    set("stat-astar",   astar + aconf + q1); // overall statistics about top-tier venues summing A/A* conferences and Q1 journals
    set("stat-q1",      q1);
    set("stat-years", span);
  }

  /* ── Google Scholar stats ──────────────────────────────────────────────── */
  // Unreliable
  // function loadScholarStats(scholar) {
  //   document.getElementById("stat-citations").textContent = scholar.citations ?? 0;
  //   document.getElementById("stat-hindex").textContent = scholar.h_index ?? 0;
  //   /*document.getElementById("stat-i10").textContent = scholar.i10_index ?? 0;*/
  // }

  /* ── Active nav highlight on scroll ─────────────────────────── */
  function setupScrollSpy() {
    const sections = document.querySelectorAll("section[id]");
    const navLinks = document.querySelectorAll(".nav-pill a[href^='#']");

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const id = entry.target.id;
            navLinks.forEach((a) => {
              a.classList.toggle("active", a.getAttribute("href") === `#${id}`);
            });
          }
        }
      },
      { rootMargin: "-40% 0px -55% 0px" }
    );

    sections.forEach((s) => observer.observe(s));
  }

  /* ── Theme toggle ────────────────────────────────────────────── */
  function initTheme() {
    const root = document.documentElement;
    const btn  = document.getElementById("theme-toggle");
    if (!btn) return;

    function applyTheme(theme) {
      root.setAttribute("data-theme", theme);
      btn.textContent = theme === "dark" ? "☀" : "🌙";
      btn.title       = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
      try { localStorage.setItem("theme-pref", theme); } catch (_) {}
    }

    // Auto-detect: dark 18:00–06:00 UTC
    const utcHour = new Date().getUTCHours();
    const auto    = (utcHour >= 18 || utcHour < 6) ? "dark" : "light";

    let stored = null;
    try { stored = localStorage.getItem("theme-pref"); } catch (_) {}

    applyTheme(stored || auto);

    btn.addEventListener("click", () => {
      const current = root.getAttribute("data-theme");
      applyTheme(current === "dark" ? "light" : "dark");
    });
  }

  /* ── Boot ────────────────────────────────────────────────────── */
  document.addEventListener("DOMContentLoaded", () => {
    typeRow    = document.getElementById("type-filter");
    topicRow   = document.getElementById("topic-filter");
    pubList    = document.getElementById("pub-list");
    pubCountEl = document.getElementById("pub-count");

    initTheme();
    setupScrollSpy();

    const pubs = window.PUBLICATIONS;
    if (!Array.isArray(pubs) || pubs.length === 0) {
      if (pubList) pubList.innerHTML = `<p class="pub-empty">Publications loading…</p>`;
      return;
    }

    // Sort by year descending (newest first)
    pubs.sort((a, b) => (b.year || 0) - (a.year || 0));

    fillHeroStats(pubs);
    buildTypeFilter(pubs);
    buildTopicFilter(pubs);
    render(pubs);

    // Unreliable
    // const scholar = window.SCHOLAR
    // loadScholarStats(scholar);

    // Update "last updated" span
    const luEl = document.getElementById("pub-last-updated");
    let lastUpdated = "Last updated —";

    if (luEl && window.PUBLICATIONS_TS) {
      const d = new Date(window.PUBLICATIONS_TS);
      const formattedDate = d.toLocaleDateString("en-GB", {
        year: "numeric",
        month: "long",
        day: "numeric",
        timeZone: "UTC"
      });
      lastUpdated = `Last updated ${formattedDate}.`;
    }
    if (luEl) {
      luEl.textContent = lastUpdated;
    }
  });

  // Hide # from "all" topic chip via a dynamic style rule
  (function injectAllChipStyle() {
    const s = document.createElement("style");
    s.textContent = ".topic-chip-all::before { content: '' !important; }";
    document.head.appendChild(s);
  })();
})();
