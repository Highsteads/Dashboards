// Filename:    test_dash_message.mjs
// Description: Contract test for DashUI.message (v3.28.0) — the one way a page
//              calls this plugin. It must refuse while the plugin restarts
//              (the five-minute IWS wedge), send the Bearer key, retry a
//              pending 503, surface the server's own error text, time out, and
//              flag an auth failure.
// Author:      CliveS & Claude Opus 5.5
// Date:        23-09-2026
// Version:     1.0
//
// Run: node tests/test_dash_message.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                                      "Resources", "static", "pages", "dashboards-ui.js"), "utf8");
function page({ gate = "up", key = "k123", replies = [] } = {}) {
    const calls = [];
    const win = { setTimeout, clearTimeout, setInterval, clearInterval, Date, Math, JSON, Promise,
                  AbortController, INDIGO_CONFIG: { apiKey: key },
                  DashGate: { check: async () => gate } };
    win.window = win;
    win.fetch = async (url, opts) => {
        calls.push({ url, opts });
        const r = replies.shift();
        if (r instanceof Error) throw r;
        if (r === "hang") {
            return new Promise((res, rej) => opts.signal.addEventListener("abort",
                () => { const e = new Error("aborted"); e.name = "AbortError"; rej(e); }));
        }
        return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body };
    };
    vm.createContext(win);
    vm.runInContext(src, win);
    return { M: win.DashUI.message, calls };
}

{
    const { M, calls } = page({ replies: [{ status: 200, body: { ok: true, v: 1 } }] });
    const d = await M("carbonAdvisor", { a: 1 });
    check("resolves to the parsed reply", d.v === 1);
    check("posts to the plugin's endpoint", calls[0].url === "/message/com.clives.indigoplugin.dashboards/carbonAdvisor/");
    check("sends the Bearer key", calls[0].opts.headers.Authorization === "Bearer k123");
    check("sends the body as JSON", calls[0].opts.body === '{"a":1}' && calls[0].opts.method === "POST");
}
{
    const { M, calls } = page({ gate: "down", replies: [{ status: 200, body: {} }] });
    let err = null; try { await M("x"); } catch (e) { err = e; }
    check("refuses while the plugin restarts, without a request", err && /restarting/.test(err.message) && calls.length === 0);
}
{
    const { M, calls } = page({ key: "" });
    let err = null; try { await M("x"); } catch (e) { err = e; }
    check("no key, no request", err && calls.length === 0);
}
{
    let waited = 0;
    const { M, calls } = page({ replies: [
        { status: 503, body: { ok: false, pending: true, error: "building" } },
        { status: 503, body: { ok: false, pending: true, error: "building" } },
        { status: 200, body: { ok: true, done: 1 } }] });
    const d = await M("timelineDay", {}, { everyMs: 5, onWait: () => waited++ });
    check("retries a pending 503 until the answer lands", d.done === 1 && calls.length === 3);
    check("calls onWait once", waited === 1);
}
{
    const { M } = page({ replies: Array(50).fill({ status: 503, body: { pending: true, error: "still building" } }) });
    let err = null; try { await M("x", {}, { everyMs: 5, pendingMs: 40 }); } catch (e) { err = e; }
    check("gives up on pending after pendingMs", err && err.status === 503 && /still building/.test(err.message));
}
{
    const { M } = page({ replies: [{ status: 503, body: { error: "SigenEnergyManager is not installed" } }] });
    let err = null; try { await M("sigenApi"); } catch (e) { err = e; }
    check("a 503 that is not pending is an error, not a retry", err && err.status === 503 && /not installed/.test(err.message));
}
{
    const { M } = page({ replies: [{ status: 400, body: { ok: false, error: "date must be YYYY-MM-DD" } }] });
    let err = null; try { await M("timelineDay", { date: "x" }); } catch (e) { err = e; }
    check("the server's own error text reaches the page", err && err.message === "date must be YYYY-MM-DD" && err.status === 400);
    check("and the body comes with it", err && err.body && err.body.ok === false);
}
{
    const { M } = page({ replies: [{ status: 401, body: null }] });
    let err = null; try { await M("x"); } catch (e) { err = e; }
    check("401 is flagged as an auth failure", err && err.auth === true && err.status === 401);
}
{
    const { M } = page({ replies: ["hang"] });
    let err = null; const t0 = Date.now();
    try { await M("x", {}, { timeoutMs: 50 }); } catch (e) { err = e; }
    check("times out rather than hanging", err && /timed out/.test(err.message) && Date.now() - t0 < 1000);
}
{
    const { M } = page({ replies: [new TypeError("Failed to fetch")] });
    let err = null; try { await M("x"); } catch (e) { err = e; }
    check("a network failure says so", err && /network error/.test(err.message));
}
done();
