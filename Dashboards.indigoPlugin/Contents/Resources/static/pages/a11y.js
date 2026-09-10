// Shared accessibility layer (v2.39.0) — loaded on every dashboard page,
// runs in ALL browsers (unlike standalone-nav.js, which early-returns outside
// iOS standalone mode). Pure progressive enhancement: it adds a skip link, a
// main landmark, accessible names for icon-only controls, polite live regions
// for status/alert text, and hides purely-decorative glyphs from screen
// readers. Everything is idempotent and wrapped so an a11y tweak can never
// break a page. No markup changes to the pages themselves are needed.
(function () {
    "use strict";
    function ready(fn) {
        if (document.readyState !== "loading") fn();
        else document.addEventListener("DOMContentLoaded", fn);
    }
    function treat() {
        try {
            // ── 1. Inject the skip-link + sr-only styles once. ──
            if (!document.getElementById("a11y-style")) {
                var st = document.createElement("style");
                st.id = "a11y-style";
                st.textContent =
                    ".a11y-skip{position:fixed;left:8px;top:-64px;z-index:1000;" +
                    "background:var(--accent,#5856d6);color:#fff;padding:10px 14px;" +
                    "border-radius:10px;font:600 14px/1 -apple-system,BlinkMacSystemFont,sans-serif;" +
                    "text-decoration:none;transition:top .15s ease}" +
                    ".a11y-skip:focus{top:8px;outline:2px solid #fff;outline-offset:2px}" +
                    "main[tabindex='-1']:focus,[role='main'][tabindex='-1']:focus{outline:none}";   // the landmark only, not every focusable region on the page
                document.head.appendChild(st);
            }

            // ── 2. Main landmark: tag the primary content region. ──
            var main = document.querySelector("main")
                || document.querySelector(".main, #content, .container, #grid");
            if (main) {
                if (main.tagName.toLowerCase() !== "main" && !main.getAttribute("role")) {
                    main.setAttribute("role", "main");
                }
                if (!main.id) main.id = "main-content";
                if (!main.hasAttribute("tabindex")) main.setAttribute("tabindex", "-1");
            }

            // ── 3. Skip-to-content link as the first focusable element. ──
            if (main && !document.querySelector(".a11y-skip")) {
                var skip = document.createElement("a");
                skip.className = "a11y-skip";
                skip.href = "#" + main.id;
                skip.textContent = "Skip to content";
                skip.addEventListener("click", function (e) {
                    e.preventDefault();
                    main.focus();
                    main.scrollIntoView();
                });
                document.body.insertBefore(skip, document.body.firstChild);
            }

            // ── 4. Header landmark. ──
            var hdr = document.querySelector("header, .topbar");
            if (hdr && !hdr.getAttribute("role") && hdr.tagName.toLowerCase() !== "header") {
                hdr.setAttribute("role", "banner");
            }

            // ── 5. Accessible names for icon-only controls. A control with no
            //     letters/digits in its text (an arrow, cog, ⤓, ✕…) gets its
            //     name from the title attribute where one exists. ──
            var hasWord = function (el) {
                return ((el.textContent || "").replace(/[^\p{L}\p{N}]/gu, "").length) > 0;
            };
            document.querySelectorAll("button, a[role='button'], a.nav-btn, .cam-btn, .info-btn")
                .forEach(function (el) {
                    if (el.getAttribute("aria-label") || el.getAttribute("aria-labelledby")) return;
                    if (hasWord(el)) return;              // has real visible text — already named
                    var t = el.getAttribute("title");
                    if (t) el.setAttribute("aria-label", t);
                });

            // ── 6. Hide purely-decorative glyph containers from screen readers
            //     (they sit next to a real text label). ──
            document.querySelectorAll(".card-icon, .hero-icon")
                .forEach(function (el) {
                    if (!el.hasAttribute("aria-hidden")) el.setAttribute("aria-hidden", "true");
                });

            // ── 7. Polite live regions for the messages that matter (NOT the
            //     per-second clock, which would be announced endlessly). ──
            ["#alert-bar", "#save-msg", ".hero-verdict"].forEach(function (sel) {
                document.querySelectorAll(sel).forEach(function (el) {
                    if (!el.getAttribute("aria-live")) el.setAttribute("aria-live", "polite");
                });
            });
        } catch (e) {
            /* never break a page over an accessibility enhancement */
        }
    }
    ready(function () {
        treat();
        // Every dashboard page renders most of its content AFTER load (the
        // 3 s polls rebuild whole sections), so a single DOMContentLoaded
        // pass left dynamic content untreated — icon-only buttons unnamed,
        // decorative glyphs read aloud. Re-run the (idempotent) treatment on
        // a debounced mutation observer instead.
        try {
            var pending = null;
            new MutationObserver(function () {
                if (pending) return;
                pending = setTimeout(function () { pending = null; treat(); }, 400);
            }).observe(document.body, { childList: true, subtree: true });
        } catch (e) { /* enhancement only */ }
    });
})();
