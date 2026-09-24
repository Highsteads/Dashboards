// Keep iOS-standalone navigation in standalone mode.
//
// When the dashboard is added to the iPhone/iPad home screen and launched
// from there, the page opens in "standalone" mode (no URL bar, no Safari
// navigation chrome). But tapping any <a href> on the page would normally
// hand the destination off to regular Safari, dropping you back into the
// full browser UI for sub-pages.
//
// This interceptor catches click events on same-origin links and navigates
// via location.href instead, which iOS preserves as in-app navigation —
// the destination page also opens standalone.
//
// External links (different origin), middle-clicks, and target="_blank"
// links are left alone so they behave normally.
(function () {
    if (!window.navigator.standalone) return;
    // BUBBLE phase, and it honours defaultPrevented. It used to listen in the
    // capture phase and, being registered while the page was still parsing,
    // ran BEFORE DashUI's tap guard (wired at DOMContentLoaded). It had already
    // started the navigation by the time the guard cancelled a scroll-touch,
    // so brushing a link while scrolling still changed page in the home-screen
    // app. The guard runs in the capture phase and stops propagation, so a
    // rejected click never reaches this listener at all now.
    document.addEventListener("click", function (e) {
        if (e.defaultPrevented) return;
        const a = e.target.closest && e.target.closest("a");
        if (!a || !a.href) return;
        // Modifier clicks → user wants a new tab/window; don't intercept.
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        if (a.target && a.target !== "_self") return;
        if (a.hasAttribute("download")) return;           // a save, not a navigation
        let url;
        try { url = new URL(a.href, location.href); } catch (_) { return; }
        if (url.origin !== location.origin) return;       // external — keep default behaviour
        // A fragment-only link (#top, a skip-link) targets THIS page — let the
        // browser scroll to it; assigning location.href forced a full reload.
        if (url.pathname === location.pathname && url.search === location.search && url.hash) return;
        e.preventDefault();
        location.href = url.href;
    }, false);
})();
