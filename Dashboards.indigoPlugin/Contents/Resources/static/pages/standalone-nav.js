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
    document.addEventListener("click", function (e) {
        const a = e.target.closest && e.target.closest("a");
        if (!a || !a.href) return;
        // Modifier clicks → user wants a new tab/window; don't intercept.
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        if (a.target && a.target !== "_self") return;
        let url;
        try { url = new URL(a.href, location.href); } catch (_) { return; }
        if (url.origin !== location.origin) return;       // external — keep default behaviour
        e.preventDefault();
        location.href = url.href;
    }, true);
})();
