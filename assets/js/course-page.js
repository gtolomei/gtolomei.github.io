/**
 * course-page.js
 * Shared behaviour for Teaching sub-pages (teaching/os.html, teaching/bdc.html):
 *   - theme toggle (mirrors the logic in assets/js/publications.js)
 *   - scroll-spy nav highlighting
 * Kept separate from publications.js so course pages don't load publication
 * rendering logic they don't need.
 */
(function () {
  "use strict";

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

  function initScrollSpy() {
    const sections = document.querySelectorAll("section[id]");
    const navLinks = document.querySelectorAll(".nav-pill a[href^='#']");
    if (!sections.length || !navLinks.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const id = entry.target.getAttribute("id");
            navLinks.forEach((a) => {
              a.classList.toggle("active", a.getAttribute("href") === `#${id}`);
            });
          }
        });
      },
      { rootMargin: "-40% 0px -55% 0px" }
    );

    sections.forEach((s) => observer.observe(s));
  }

  function initFooterYear() {
    const el = document.getElementById("footer-year");
    if (el) el.textContent = new Date().getFullYear();
  }

  document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    initScrollSpy();
    initFooterYear();
  });
})();
