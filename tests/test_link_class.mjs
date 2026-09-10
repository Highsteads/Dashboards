// Filename:    test_link_class.mjs
// Description: Contract test for DashUI.linkClass / measuredClass — how the
//              dashboards decide whether to open live camera streams.
//
//              WHY THIS EXISTS
//              "The cameras stop when I'm not on home broadband" survived three
//              attempts at fixing it, and every one of them keyed off
//              location.hostname. That cannot work: this tailnet has an Apple TV
//              advertising 192.168.1.0/24 as a subnet route, so a phone on
//              mobile data opening the bookmarked http://192.168.1.10:8176/
//              reaches the server through the tunnel while the hostname still
//              reads 192.168.1.10. The page concluded "home", opened six live
//              MJPEG streams and pushed 5.5 MB/s (44 Mbit/s) down a mobile
//              connection — which is what actually stalled the tiles.
//
//              A LAN address behind a VPN route is byte-identical to the LAN, so
//              the class has to be MEASURED. The case that matters most in here
//              is "192.168.1.10 at 85ms -> vpn": address says home, link says
//              otherwise, link wins.
//
//              Extracts the real functions from the shipped dashboards-ui.js so
//              this locks what ships rather than a copy of it.
// Author:      CliveS & Claude Opus 5
// Date:        29-07-2026
// Version:     1.0
//
// Run: node tests/test_link_class.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                      "Resources", "static", "pages", "dashboards-ui.js");
const src = fs.readFileSync(SRC, "utf8");

function grab(name) {
    const start = src.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`could not find function ${name} in dashboards-ui.js`);
    let depth = 0, end = -1;
    for (let j = src.indexOf("{", start); j < src.length; j++) {
        if (src[j] === "{") depth++;
        else if (src[j] === "}") { depth--; if (depth === 0) { end = j + 1; break; } }
    }
    return src.slice(start, end);
}

// The threshold is read from the shipped source too, so tightening it there
// cannot silently invalidate these expectations.
const RTT_HOME_MS = Number(/RTT_HOME_MS\s*=\s*(\d+)/.exec(src)[1]);

function makeSandbox(hostname, fakeRtt) {
    const store = {};
    const box = {
        store,
        sessionStorage: {
            getItem: k => (k in store ? store[k] : null),
            setItem: (k, v) => { store[k] = v; },
        },
        root: { location: { hostname }, performance: null },
        // Each fetch advances a fake clock by the link's round trip, so the
        // median is computed from the same code path the browser drives.
        NOW: 0,
        console,
    };
    box.Date = { now: () => box.NOW };
    // A REAL promise, and three samples that DIFFER (v2.95.3). The old fake
    // was a hand-rolled thenable that advanced the clock inside then() — the
    // engine adopts a thenable returned from a .then callback and calls its
    // then() a second time, so every request burned two samples — and it fed
    // all three probes the same value, where min and median agree by
    // construction and the estimator was free to be wrong. Now the FASTEST
    // sample is the link's true round trip and the other two are the noise a
    // phone's sleeping radio adds; only a min-based estimator gets these right.
    let sampleIx = 0;
    box.fetch = () => {
        const noise = [900, 0, 40][sampleIx++ % 3];
        box.NOW += fakeRtt + noise;
        return Promise.resolve({ ok: true });
    };
    box.RTT_HOME_MS = RTT_HOME_MS;
    box.RTT_PROBE_KEY = "dash_link_rtt";
    // Read from source, like the threshold. The sandbox only holds the
    // functions grab()bed out of the file, so a module-level constant they use
    // has to be supplied — and a MISSING one does not fail loudly: the
    // ReferenceError is swallowed by _cachedRtt's own try/catch and the cache
    // silently never hits, which is what this file caught when the TTL landed.
    box.RTT_CACHE_MS = Number(/RTT_CACHE_MS\s*=\s*(\d+)/.exec(src)[1]);
    return box;
}

const CODE = [grab("linkClass"), grab("_cachedRtt"),
              // _now is the shared clock guard probeRtt uses (v2.99.0). Pinned
              // to Date.now() here so these cases time nothing real.
              "var _now = function () { return Date.now(); };",
              grab("probeRtt"),
              grab("measuredClass")].join("\n");

async function classify(hostname, rttMs) {
    const box = makeSandbox(hostname, rttMs);
    vm.createContext(box);
    vm.runInContext(CODE + "\nvar __r = measuredClass();", box);
    return await box.__r;
}

const CASES = [
    // hostname,                             rtt,  expect,      why
    ["192.168.1.10",                         3, "home",      "genuinely on the LAN, wired"],
    // CliveS's four real readings, taken from the page footer on his iPhone.
    // The 21 ms case is why the threshold moved from 20 to 50: he was missing
    // "home" on his own wi-fi by ONE millisecond and silently never getting
    // live video. The 116 ms case is a VPN tunnel between two devices in the
    // same building, so it is the FASTEST a remote path can plausibly be.
    ["192.168.1.10",                        21, "home",      "phone on home wi-fi — MEASURED, and a wired-Mac threshold excluded it"],
    ["192.168.1.10",                       116, "vpn",       "phone on home wi-fi through Tailscale — MEASURED"],
    ["192.168.1.10",                       245, "vpn",       "phone on 5G through Tailscale — MEASURED"],
    ["192.168.1.10",                        85, "vpn",       "LAN address over a Tailscale subnet route — THE bug"],
    ["192.168.1.10",                       240, "vpn",       "same, poor mobile signal"],
    ["192.168.1.10",              RTT_HOME_MS, "home",       "exactly at the threshold counts as local"],
    ["192.168.1.10",          RTT_HOME_MS + 1, "vpn",        "one millisecond over is remote"],
    ["10.0.0.5",                                2, "home",      "other private range, local"],
    ["10.0.0.5",                              300, "vpn",       "other private range, tunnelled"],
    ["172.16.0.9",                              4, "home",      "172.16/12 lower bound, local"],
    ["100.68.100.160",                         60, "vpn",       "Tailscale CGNAT address"],
    ["indigo.tail-example.ts.net",       60, "vpn",       "Tailscale MagicDNS name"],
    ["localhost",                               1, "home",      "loopback"],
    ["[::1]",                                   1, "home",      "IPv6 loopback, bracketed as browsers report it"],
    ["[fd7a:115c:a1e0::1]",                     1, "home",      "IPv6 unique-local (a tailnet v6 addr is still not the LAN)"],
    ["myhouse.indigodomo.net",              900, "reflector", "reflector — never streams"],
    ["myhouse.indigodomo.net",                2, "reflector", "a fast probe must NOT promote the reflector"],
    ["172.32.0.1",                               2, "reflector", "just outside 172.16/12"],
    ["100.200.0.1",                              2, "reflector", "just outside the CGNAT range"],
    ["8.8.8.8",                                  2, "reflector", "public address"],
];

let pass = 0, fail = 0;
console.log(`\nthreshold read from source: ${RTT_HOME_MS} ms\n`);
for (const [host, rtt, want, why] of CASES) {
    const got = await classify(host, rtt);
    const ok = got === want;
    ok ? pass++ : fail++;
    console.log(`  ${ok ? "ok  " : "FAIL"} ${host.padEnd(34)} ${String(rtt).padStart(4)}ms -> ` +
                `${got.padEnd(10)} ${ok ? "" : `(want ${want}) `}${why}`);
}

// The probe must be cached for the session — three fetches per page load on a
// slow link is exactly the frugality this whole change is about.
{
    const box = makeSandbox("192.168.1.10", 50);
    vm.createContext(box);
    vm.runInContext(CODE + "\nvar __a = probeRtt();", box);
    await box.__a;
    // Read the STORED value properly rather than string-comparing whatever
    // representation the cache happens to use — it now carries a timestamp
    // alongside the measurement, and an earlier version of this line compared
    // the raw JSON against the returned number and failed for no real reason.
    const first = JSON.parse(box.store["dash_link_rtt"]).ms;
    box.NOW = 0;
    vm.runInContext("var __b = probeRtt();", box);
    const second = await box.__b;
    // NOW unchanged is the real assertion: the fake clock only advances when a
    // fetch happens, so a still clock proves nothing was measured again.
    const ok = Number(second) === Number(first) && box.NOW === 0;
    ok ? pass++ : fail++;
    console.log(`  ${ok ? "ok  " : "FAIL"} cached probe reused within the session ` +
                `(no second measurement)`);
}


// ---- the cached verdict must not outlive a network change --------------
// REPORTED: wi-fi turned off, moved to mobile data, page carried on behaving as
// though it were at home. The probe result was cached for the whole browser
// session, so nothing could ever revise it short of closing the tab.
{
  const uiSrc = fs.readFileSync(SRC, "utf8");
  const camSrc = fs.readFileSync(path.join(HERE, "..", "Dashboards.indigoPlugin",
    "Contents", "Resources", "static", "pages", "cameras.html"), "utf8");

  const ttl = /RTT_CACHE_MS\s*=\s*(\d+)/.exec(uiSrc);
  const okTtl = ttl && Number(ttl[1]) > 0 && Number(ttl[1]) <= 300000;
  okTtl ? pass++ : fail++;
  console.log(`  ${okTtl ? "ok  " : "FAIL"} the cached verdict expires ` +
              `(${ttl ? ttl[1] + " ms" : "NO TTL — it lives for the whole session"})`);

  const stamped = /JSON\.stringify\(\{\s*ms:/.test(uiSrc) && /Date\.now\(\)\s*-\s*v\.at/.test(uiSrc);
  stamped ? pass++ : fail++;
  console.log(`  ${stamped ? "ok  " : "FAIL"} it is stored with a timestamp, ` +
              `so the age can actually be checked`);

  const forget = /function forgetRtt/.test(uiSrc) && /forgetRtt:\s*forgetRtt/.test(uiSrc);
  forget ? pass++ : fail++;
  console.log(`  ${forget ? "ok  " : "FAIL"} a page can drop it deliberately (forgetRtt, exported)`);

  // Coming back to the page is the moment a phone has plausibly moved network.
  // iOS gives no reliable network-change event, so this is the proxy.
  const onResume = /visibilitychange[\s\S]{0,700}forgetRtt\(\)[\s\S]{0,200}measureAndApply\(\)/
                     .test(camSrc);
  onResume ? pass++ : fail++;
  console.log(`  ${onResume ? "ok  " : "FAIL"} cameras.html re-measures when the page comes back`);
}

// ---- link class -> camera policy ---------------------------------------
// Pinned because this behaviour has now been got wrong three times. The rule:
// live MJPEG ONLY at home. Off-LAN a live tile measured 30 s+ behind while the
// stills beside it were 5-8 s behind, because MJPEG queues on a link that
// cannot drain it and never recovers, at ~17 Mbit/s. Worse than a still on both
// counts, so there is no "one live tile" compromise to keep.
{
  const camSrc = fs.readFileSync(path.join(HERE, "..", "Dashboards.indigoPlugin",
    "Contents", "Resources", "static", "pages", "cameras.html"), "utf8");
  const start = camSrc.indexOf("function setPolicy(");
  let depth = 0, end = -1;
  for (let j = camSrc.indexOf("{", start); j < camSrc.length; j++) {
    if (camSrc[j] === "{") depth++;
    else if (camSrc[j] === "}") { depth--; if (depth === 0) { end = j + 1; break; } }
  }
  // RTT_TUNNEL_MS read from source, for the same reason as the other constants:
  // a missing one is not a loud failure, it just quietly changes the answer.
  const box = { hosts: ["a","b","c","d","e","f","g","h","i"], cfg: { livePoolSize: 6 },
                LINK: null, LIVE_POOL_SIZE: null, DEFAULT_LIVE: null,
                DEFAULT_LIVE_SET: null, LIVE_FOLLOWS_FOCUS: null, Set, Math, console,
                RTT_TUNNEL_MS: Number(/RTT_TUNNEL_MS\s*=\s*(\d+)/.exec(camSrc)[1]) };
  vm.createContext(box);
  vm.runInContext(camSrc.slice(start, end), box);
  // THREE BANDS, not two. CliveS runs Tailscale permanently, at home included,
  // and that is correct — turning it off on wi-fi to get live video would leave
  // it off on untrusted wi-fi too. So "home with the tunnel up" (116 ms
  // measured) has to be catered for. Round trip cannot cleanly separate it from
  // 5G with the tunnel up (245 ms measured) — barely 2x — so the middle band
  // runs ONE live tile rather than six: right, and he gets live video at home
  // through the tunnel; wrong, and it costs one stream that the stall watchdog
  // demotes, instead of the six that stalled his phone originally.
  for (const [cls, rtt, wantLive, why] of [
        ["home",      21, 6, "on the LAN, tunnel off"],
        ["vpn",      116, 1, "MEASURED: at home with Tailscale up — one live tile"],
        ["vpn",      150, 1, "top of the tunnel band still counts as near"],
        ["vpn",      151, 0, "one millisecond past it does not"],
        ["vpn",      245, 0, "MEASURED: 5G with Tailscale up — no live tiles"],
        ["vpn",     null, 0, "UNMEASURED must never assume the expensive case"],
        ["reflector", 10, 0, "the reflector cannot carry MJPEG at any speed"],
      ]) {
    vm.runInContext(`setPolicy(${JSON.stringify(cls)}, ${JSON.stringify(rtt)})`, box);
    const got = box.LIVE_POOL_SIZE;
    const ok = got === wantLive;
    ok ? pass++ : fail++;
    console.log(`  ${ok ? "ok  " : "FAIL"} ${cls.padEnd(9)} ${String(rtt).padStart(4)}ms -> ` +
                `${got} live ${ok ? "" : `(want ${wantLive}) `}— ${why}`);
  }
  // With no live tile there is nothing for the focus to carry.
  vm.runInContext('setPolicy("vpn", 245)', box);
  const ok = box.LIVE_FOLLOWS_FOCUS === false;
  ok ? pass++ : fail++;
  console.log(`  ${ok ? "ok  " : "FAIL"} off-LAN has no live slot to follow the focus`);
}

// ---- wi-fi association beats timing ------------------------------------
// The best answer does not come from timing anything. The UniFi controller
// already knows which phones are on which access point, and UniFiHealth
// surfaces that as a device carrying `presence` and `essid` (measured live:
// presence='home', essid='Highsteads_AX'). With a permanently-on VPN, timing
// cannot separate home (116 ms) from 5G (245 ms). Association can, exactly.
{
  const camSrc2 = fs.readFileSync(path.join(HERE, "..", "Dashboards.indigoPlugin",
    "Contents", "Resources", "static", "pages", "cameras.html"), "utf8");
  const code2 = camSrc2.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  const ck = (ok, label, detail = "") => {
    ok ? pass++ : fail++;
    console.log(`  ${ok ? "ok  " : "FAIL"} ${label}${detail ? "   " + detail : ""}`);
  };

  ck(/states\.presence/.test(code2) || /st\.presence/.test(code2),
     "asks Indigo whether this device is present, rather than inferring it");

  // "Is anybody home" must never be served anonymously. /public has no auth,
  // over the reflector as well, so this has to go through the keyed API.
  // EVERY call to the devices API must carry the key — checking that the word
  // "Bearer" appears somewhere is not enough, because the pairing picker also
  // makes one, and dropping the header from the presence fetch alone slipped
  // past an earlier version of this line.
  const devFetches = (code2.match(/fetch\(\s*[`"'][^`"']*v2\/api\/indigo\.devices/g) || []).length;
  const bearers = (code2.match(/Authorization:\s*"Bearer "/g) || []).length;
  ck(devFetches > 0 && bearers >= devFetches,
     "EVERY devices-API call carries the key, never /public",
     `${devFetches} call(s), ${bearers} authorised — presence must not be served anonymously`);

  // A stale "home" is the expensive direction — six live streams on mobile.
  // Assert the COMPARISON, not just that both names appear — they each occur
  // elsewhere (the constant's declaration, the Number() coercion), so a mutant
  // that replaced the whole test with `true` went unnoticed the first time.
  ck(/mins\s*<=\s*PRESENCE_MAX_MIN/.test(code2),
     "requires the sighting to be RECENT",
     "UniFi debounces a client dropping off, so 'home' outlives the fact");

  // Belt and braces: presence alone must not be able to open the full pool.
  ck(/presence\.home[\s\S]{0,160}ms\s*<=\s*RTT_TUNNEL_MS/.test(code2),
     "presence AND timing must agree before the full pool opens",
     "so one stale controller reading cannot cost six streams on mobile data");

  // Unpaired, or no key, must change nothing.
  ck(/if\s*\(!paired\s*\|\|\s*!key\)\s*return Promise\.resolve\(null\)/.test(code2),
     "unpaired browsers fall back to the timing bands, unchanged");

  // Which phone this is differs per device, so it cannot live in shared config.
  ck(/localStorage\.(getItem|setItem)\(PRESENCE_KEY/.test(code2)
     || /localStorage\.getItem\(PRESENCE_KEY/.test(code2),
     "the pairing is per-BROWSER, not in the plugin's shared config");
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
