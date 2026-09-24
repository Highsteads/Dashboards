/* Filename:    dashboards-webrtc.js
 * Description: One live WebRTC camera tile, shared by the Cameras page and
 *              the hub's camera strip (v3.45.0).
 *
 *              go2rtc relays each camera's own H.264 untouched. The browser
 *              sends one signalling POST (WHEP-style: the SDP offer as
 *              application/sdp) to the plugin's own port, which forwards it to
 *              go2rtc's loopback API and relays the answer. Media then flows
 *              browser <-> go2rtc :8555 directly. Video only: the cameras' AAC
 *              audio cannot negotiate in WebRTC.
 *
 *              Until 3.45.0 all of this lived inside cameras.html. Moving it
 *              here lets the hub strip play live video at home without a
 *              second copy of the rules that took several releases to get
 *              right: the ICE wait, the per-attempt abort, a torn-down tile
 *              never sending its offer, and the two first-frame triggers.
 *
 *              The page owns the DOM and the policy (when to go live, what to
 *              fall back to, when to retry). This module owns one peer
 *              connection and reports two things: the first real frame
 *              (onLive) and failure (onFail). After stop() it reports nothing.
 *
 *              It also owns the ONE rule for whether live video is worth
 *              trying at all (measure / decide): the throughput to the Indigo
 *              box, measured, against what the tiles need. Not the address:
 *              a phone on Tailscale arrives from a tunnel address at home and
 *              away alike, so the address says nothing about the pipe. Never
 *              over the reflector, whatever the measurement says.
 *
 *              Usage:
 *                const video = DashRTC.makeVideo();
 *                tile.appendChild(video);
 *                const h = DashRTC.start(host, video, {
 *                    url: DashRTC.url(host, window.CAMERA_CONFIG),
 *                    onLive: () => ..., onFail: why => ... });
 *                ...
 *                h.stop();
 *
 *                DashRTC.decide(4, { hosts }).then(v => v.live ? ... : ...);
 * Author:      CliveS & Claude Opus 5.5
 * Date:        24-09-2026
 * Version:     1.0
 */

(function (root) {
  'use strict';

  var ICE_MS    = 5000;   // no connection by then -> fail
  var FRAME_MS  = 8000;   // connected but no frame by then -> fail
  var DISC_MS   = 5000;   // how long "disconnected" may last before it counts
  var GATHER_MS = 1000;   // host-only candidates gather in milliseconds; cap the wait
  var POOR_FPS   = 2;     // a live tile slower than this is worse than a still
  var POOR_LOOKS = 3;     // ...for this many looks running

  /* Frames the <video> has decoded so far, or null where the browser cannot
     say. Only the difference between two looks is used. */
  function frameCount(video) {
    try {
      if (video.getVideoPlaybackQuality) return video.getVideoPlaybackQuality().totalVideoFrames;
      if (typeof video.webkitDecodedFrameCount === 'number') return video.webkitDecodedFrameCount;
    } catch (e) {}
    return null;
  }

  /* Ask the <video> to play, and swallow the refusal. autoplay alone is not
     enough: headless Chrome leaves a MediaStream video paused, and WebKit
     may not autoplay one it cannot see, and the hub keeps its video at
     opacity 0 until the first frame. A paused video still shows its first
     frame, so it reads as live while the clock never moves (24-09-2026:
     every hub tile failed as "video stalled" 3.5 s after going live). */
  function playVideo(video, onRefused) {
    var refused = function (e) {
      video._playRefused = (e && e.name) || 'refused';
      if (onRefused) onRefused(video._playRefused);
    };
    try {
      var p = video.play();
      // Remembered, not thrown: a refusal (iOS refuses even a muted inline
      // video until the page has been touched) is named in the failure message.
      if (p && p.then) p.then(function () { video._playRefused = null; }, refused);
    } catch (e) { refused(e); }
  }

  /* Streams the browser would not start by itself (NotAllowedError). On
     CliveS's iPhone, 24-09-2026: 847 KB received and 77 frames decoded but
     nothing shown, with Low Power Mode OFF and the video fully visible on the
     Cameras page, so it is iOS wanting a touch first, not only its Low Power
     rule. They stay connected, and the next tap, click or key press anywhere
     on the page starts them: a play() made inside a user gesture is one the
     browser allows (confirmed on the phone). */
  var _blocked = [];
  function blockedCount() {
    _blocked = _blocked.filter(function (h) { return !h.stopped && h.blocked; });
    return _blocked.length;
  }
  function unblockAll() {
    var waiting = _blocked.filter(function (h) { return !h.stopped && h.blocked; });
    _blocked = [];
    waiting.forEach(function (h) {
      try {
        var p = h.video.play();   // synchronously, inside the gesture
        var ok = function () { h.blocked = false; h.video._playRefused = null; };
        if (p && p.then) p.then(ok, function () { if (!h.stopped) _blocked.push(h); });
        else ok();
      } catch (e) { if (!h.stopped) _blocked.push(h); }
    });
  }
  (function listenForGesture() {
    var doc = root && root.document;
    if (!doc || !doc.addEventListener) return;
    ['touchend', 'click', 'keydown'].forEach(function (ev) {
      doc.addEventListener(ev, function () { if (_blocked.length) unblockAll(); },
                           { capture: true, passive: true });
    });
  })();

  /* Why no frame came, for the failure message: whether the browser refused
     to play, whether any video arrived and whether any was decoded, and in
     which codec. Resolves a short text, or "" when the stats cannot say. */
  function noFrameDetail(pc, video) {
    var parts = [];
    if (video && video._playRefused) parts.push('playback refused: ' + video._playRefused);
    else if (video && video.paused) parts.push('paused');
    if (!pc || !pc.getStats) return Promise.resolve(parts.join(', '));
    var timeout = new Promise(function (r) { setTimeout(function () { r(null); }, 1000); });
    return Promise.race([pc.getStats().catch(function () { return null; }), timeout]).then(function (report) {
      if (!report || !report.forEach) return parts.join(', ');
      var inbound = null, codecs = {};
      report.forEach(function (r) {
        if (r.type === 'inbound-rtp' && (r.kind === 'video' || r.mediaType === 'video')) inbound = r;
        if (r.type === 'codec') codecs[r.id] = r.mimeType;
      });
      if (inbound) {
        var kb = Math.round((inbound.bytesReceived || 0) / 1024);
        parts.push(kb >= 1024 ? (Math.round(kb / 102.4) / 10) + ' MB received' : kb + ' KB received');
        parts.push((inbound.framesDecoded || 0) + ' decoded');
        var mime = codecs[inbound.codecId];
        if (mime) parts.push(String(mime).replace(/^video\//, ''));
      } else {
        parts.push('no video received');
      }
      return parts.join(', ');
    });
  }

  function supported() {
    return !!root && ('RTCPeerConnection' in root);
  }

  /* The signalling address. The page is served by IWS on one port; the
     plugin's proxy that forwards the offer listens on its own (proxyPort,
     8177 by default), same host, same scheme. The path comes from config.js
     (webrtcPath, "/webrtc/{host}"). No Authorization header is sent: the
     proxy judges the request by its source address and Host header, and its
     CORS preflight allows Content-Type only, so any other header would make
     Safari's preflight fail and the offer would never be sent. */
  function url(host, cfg) {
    cfg = cfg || {};
    var loc = root.location || {};
    var port = cfg.proxyPort || 8177;
    var path = (cfg.webrtcPath || '/webrtc/{host}').replace('{host}', host);
    return loc.protocol + '//' + loc.hostname + ':' + port + path;
  }

  /* A <video> ready for a live tile: muted and inline, which iOS requires
     before it will autoplay, and without taking over the screen. */
  function makeVideo() {
    var video = root.document.createElement('video');
    video.muted    = true;
    video.defaultMuted = true;
    video.autoplay = true;
    // The attributes as well as the properties: iOS judges autoplay partly
    // on the markup, and an older WebKit only knows the prefixed inline one.
    video.setAttribute('muted', '');
    video.setAttribute('autoplay', '');
    video.setAttribute('playsinline', '');
    video.setAttribute('webkit-playsinline', '');
    return video;
  }

  /* Start one live stream into `video`. Returns a handle:
       handle.pc        the RTCPeerConnection (for getStats)
       handle.stop()    close everything; idempotent; no callback after it
       handle.stopped   true once stopped or failed
       handle.gotFrame  true once the first frame has arrived
       handle.ctrl      the AbortController of the signalling POST while it
                        is in flight, else null
     opts: { url, onLive(), onFail(why), iceMs, frameMs, fetch, stallMs }

     stallMs (optional): once playing, look at the video clock this often and
     fail with "video stalled" when it has not moved for two looks running.
     go2rtc's own counters only see the camera side, which keeps flowing while
     the leg to the browser stalls, so the picture is the only honest judge.
     The Cameras page leaves it out: its own watchdog ties a stall to its
     retry ladder. The hub strip passes it. */
  function start(host, video, opts) {
    opts = opts || {};
    var iceMs   = opts.iceMs   || ICE_MS;
    var frameMs = opts.frameMs || FRAME_MS;
    var doFetch = opts.fetch || function (u, o) { return root.fetch(u, o); };
    var target  = opts.url || url(host, root.CAMERA_CONFIG);

    var h = { host: host, video: video, pc: null, ctrl: null,
              stopped: false, gotFrame: false, stop: stop };
    var stallMs = opts.stallMs || 0;
    var iceTimer = null, frameTimer = null, discTimer = null, stallTimer = null;

    function clearTimers() {
      if (iceTimer)   { clearTimeout(iceTimer);   iceTimer   = null; }
      if (frameTimer) { clearTimeout(frameTimer); frameTimer = null; }
      if (discTimer)  { clearTimeout(discTimer);  discTimer  = null; }
      if (stallTimer) { clearInterval(stallTimer); stallTimer = null; }
    }
    function teardown() {
      h.stopped = true;
      h.blocked = false;
      clearTimers();
      if (h.ctrl) { try { h.ctrl.abort(); } catch (e) {} h.ctrl = null; }
      if (h.pc) { try { h.pc.close(); } catch (e) {} }
      if (video) { try { video.srcObject = null; } catch (e) {} }
    }
    function stop() {
      if (h.stopped) return;
      teardown();
    }
    // Once only, and never after stop(): a stopped tile's late callbacks are
    // exactly what used to open a second stream behind the page's back.
    function fail(why) {
      if (h.stopped) return;
      teardown();
      if (opts.onFail) opts.onFail(why);
    }

    // A refusal to play is not a failure: the stream is fine, it only needs
    // a tap. Stop the no-frame clock, remember the stream for the next
    // gesture, and tell the page so it can say "tap to start".
    var onRefused = function (name) {
      if (h.stopped || h.blocked || name !== 'NotAllowedError') return;
      h.blocked = true;
      if (frameTimer) { clearTimeout(frameTimer); frameTimer = null; }
      _blocked.push(h);
      if (opts.onBlocked) opts.onBlocked();
    };

    var pc = new root.RTCPeerConnection({ iceServers: [] });
    h.pc = pc;
    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.addEventListener('track', function (e) {
      if (h.stopped) return;
      video.srcObject = e.streams[0] || new root.MediaStream([e.track]);
      playVideo(video, onRefused);
    });
    // And again once there is something to play: WebKit can refuse a play()
    // asked for before the stream has any data, then never try by itself.
    ['loadedmetadata', 'canplay'].forEach(function (ev) {
      if (video && video.addEventListener) {
        video.addEventListener(ev, function () { if (!h.stopped && !h.blocked && video.paused) playVideo(video, onRefused); });
      }
    });
    pc.addEventListener('connectionstatechange', function () {
      if (h.stopped) return;
      if (pc.connectionState === 'failed') { fail('connection failed'); return; }
      if (pc.connectionState === 'disconnected') {
        // Transient by definition (a consent-freshness lapse on a mobile link
        // usually returns to connected within seconds); acting on it at once
        // cost a 60 s backoff for nothing.
        clearTimeout(discTimer);
        discTimer = setTimeout(function () {
          if (!h.stopped && pc.connectionState === 'disconnected') fail('connection disconnected');
        }, DISC_MS);
      } else if (pc.connectionState === 'connected') {
        clearTimeout(discTimer);
      }
    });
    iceTimer = setTimeout(function () {
      if (!h.stopped && pc.connectionState !== 'connected') {
        fail('no connection in ' + (iceMs / 1000) + 's');
      }
    }, iceMs);
    frameTimer = setTimeout(function () {
      if (h.stopped || h.gotFrame) return;
      noFrameDetail(pc, video).then(function (detail) {
        if (!h.stopped && !h.gotFrame) {
          fail('no frame in ' + (frameMs / 1000) + 's' + (detail ? ' (' + detail + ')' : ''));
        }
      });
    }, frameMs);

    var firstFrame = function () {
      if (h.stopped) return;
      if (h.gotFrame) return;              // two triggers race; first wins
      h.gotFrame = true;
      if (stallMs) {
        // Two ways a live tile can be worse than a still. The picture stops,
        // or it crawls (under POOR_FPS frames a second for POOR_LOOKS looks
        // running, a picture drifting further and further behind).
        //
        // "Stopped" means NO sign of progress at all: not the media clock,
        // not a painted frame (requestVideoFrameCallback), not the decoder's
        // frame counter. Any one of them moving is enough. Safari's engine
        // does not keep every one of these for a live stream, and a check
        // that trusted only the clock and the counter failed every hub tile
        // on every one of CliveS's devices (24-09-2026) while Chrome played.
        //
        // "Crawling" is judged only on the decoder's counter, and only once
        // that counter has been SEEN to count: a browser that never counts a
        // live stream's frames reads 0 for ever, which is not a crawl. Painted
        // frames are not used for the rate, because a tile scrolled out of
        // view is not painted and would read as crawling.
        var lastTime = video.currentTime || 0, misses = 0, slow = 0;
        var lastFrames = frameCount(video), countsFrames = false;
        var painted = 0, lastPainted = 0;
        var onPaint = function () {
          if (h.stopped) return;
          painted++;
          if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(onPaint);
        };
        if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(onPaint);
        stallTimer = setInterval(function () {
          if (h.stopped) return;
          if (video.paused) {
            if (h.blocked) return;          // waiting for a tap, not stalled
            // Not a stall: nothing asked it to play, or the browser refused.
            // Ask again, and give up only if it still will not after two looks.
            playVideo(video, onRefused);
            if (++misses >= 2) { fail('video would not play'); return; }
            return;
          }
          var now = video.currentTime || 0;
          var frames = frameCount(video);
          var framesMoved = frames != null && lastFrames != null && frames > lastFrames;
          if (framesMoved) countsFrames = true;
          if (now > lastTime || painted > lastPainted || framesMoved) misses = 0;
          else if (++misses >= 2) { fail('video stalled'); return; }
          if (countsFrames && frames != null && lastFrames != null) {
            var fps = (frames - lastFrames) / (stallMs / 1000);
            if (fps < POOR_FPS) { if (++slow >= POOR_LOOKS) { fail('video too slow'); return; } }
            else slow = 0;
          }
          lastTime = Math.max(lastTime, now);
          lastFrames = frames;
          lastPainted = painted;
        }, stallMs);
      }
      if (opts.onLive) opts.onLive();
    };
    // TWO triggers for "the first frame is here", because they cover
    // different truths: requestVideoFrameCallback fires on a COMPOSITED
    // frame, the visual moment, but a hidden or occluded page composites
    // nothing, so on it a healthy stream would sit "connecting" until the
    // no-frame timer wrongly killed it. timeupdate fires whenever the MEDIA
    // CLOCK advances, visible or not. First one wins.
    if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(firstFrame);
    video.addEventListener('timeupdate', function () {
      if (video.currentTime > 0) firstFrame();
    });

    (async function () {
      var offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await new Promise(function (r) {
        if (pc.iceGatheringState === 'complete') return r();
        pc.addEventListener('icegatheringstatechange', function () {
          if (pc.iceGatheringState === 'complete') r();
        });
        setTimeout(r, GATHER_MS);
      });
      // Stopped during the ICE wait (a quick tile change, the tab going to
      // the background): there was no request to abort then, so without this
      // the offer still went out and opened a go2rtc session nobody would
      // ever read.
      if (h.stopped || pc.signalingState === 'closed') return;
      // This attempt's own controller, so stop() can cancel the POST.
      var ctrl = new AbortController();
      h.ctrl = ctrl;
      var r;
      try {
        r = await doFetch(target, {
          method: 'POST',
          headers: { 'Content-Type': 'application/sdp' },
          body: pc.localDescription.sdp,   // the gathered description, not the bare offer
          signal: ctrl.signal,
        });
      } finally {
        if (h.ctrl === ctrl) h.ctrl = null;
      }
      if (h.stopped || pc.signalingState === 'closed') return;
      if (!r.ok) throw new Error('signalling ' + r.status);
      await pc.setRemoteDescription({ type: 'answer', sdp: await r.text() });
    })().catch(function (e) { fail(e && e.message ? e.message : 'negotiation failed'); });

    return h;
  }

  /* ── Is the connection fast enough for live video? ─────────────────
     The ONE rule, shared by the hub strip and the Cameras page (v3.45.0).

     It used to be the address. A LAN address meant live, a Tailscale
     address meant one live tile at most, and the hub strip showed stills
     everywhere. But CliveS runs Tailscale all the time, at home too, so his
     phone arrives from a tunnel address on the sofa and on 5G alike: the
     address says how the packets are wrapped, not how many of them fit.

     So measure the pipe. Download the full-size camera stills (already on
     the server, a few tens of KB each, never compressed on the way) several
     at once, the way the video tiles will share the link: one round to open
     the connections and let them grow, then two timed rounds, and keep the
     better. Each round's time includes one round trip of asking before the
     first byte comes back, which is latency rather than bandwidth, so that
     is taken off (never more than MAX_RTT_SHARE of the round).

     Live is allowed when the measured rate carries the tiles wanted at
     PER_STREAM_MBPS each with HEADROOM to spare:

       PER_STREAM_MBPS 1.4  measured: about 1 MB/s for six live tiles, which
                            is 8 Mbit/s, or 1.33 each, rounded up
       HEADROOM        2    a link is never as steady as its best moment,
                            and the rest of the page needs some of it too

     So four hub tiles need 11.2 Mbit/s, six Cameras-page tiles 16.8.

     NEVER over the reflector. Indigo's servers carry every byte and the
     reflector has a data quota, and neither video port is fronted by it in
     any case. That rule is checked before anything is measured, and again
     every time a verdict is read, so a cached fast reading can never open a
     stream on a page that has since been seen arriving through it.

     The reading is cached for VERDICT_TTL_MS in this browser (localStorage,
     every access wrapped), so moving between pages does not re-measure. A
     page asks again when it becomes visible, and forget() drops it at once
     when the network changes (watchConnection). A failed measurement is not
     cached: the next ask tries again. */
  var PER_STREAM_MBPS = 1.4;
  var HEADROOM        = 2;
  var VERDICT_TTL_MS  = 180000;   // three minutes
  var VERDICT_KEY     = 'dash_live_bw';
  var BW_SAMPLE_MAX   = 6;        // stills per round: the browser's connection cap
  var BW_FETCH_MS     = 8000;     // one round slower than this counts as a failure
  var MAX_RTT_SHARE   = 0.75;     // never take more than this much of a round off as latency

  function ui() { return root.DashUI || null; }
  function nowMs() {
    return (root.performance && root.performance.now) ? root.performance.now() : Date.now();
  }
  /* Mbit/s that `tiles` live streams need, headroom included. */
  function needMbps(tiles) { return tiles * PER_STREAM_MBPS * HEADROOM; }
  /* How many live streams a measured rate carries, headroom included. */
  function tilesCarried(mbps) {
    if (!(mbps > 0)) return 0;
    return Math.floor(mbps / (PER_STREAM_MBPS * HEADROOM) + 1e-9);
  }
  /* The rules that need no measuring. '' when live may be tried, else why not. */
  function blocked(opts) {
    opts = opts || {};
    var u = opts.ui || ui();
    if (!u || !u.linkClass) return 'no link check';
    if (u.linkClass() === 'reflector') return 'reflector';
    if (u.isDemo && u.isDemo()) return 'demo';
    if (!('RTCPeerConnection' in (opts.win || root))) return 'no webrtc';
    return '';
  }

  function _store(opts) {
    if (opts && opts.storage) return opts.storage;
    try { return root.localStorage || null; } catch (e) { return null; }
  }
  function _origin() {
    var loc = root.location || {};
    return String(loc.protocol || '') + '//' + String(loc.host || '');
  }
  function cached(opts) {
    try {
      var st = _store(opts); if (!st) return null;
      var v = JSON.parse(st.getItem(VERDICT_KEY) || 'null');
      var now = opts && opts.now ? opts.now() : Date.now();
      if (!v || typeof v.mbps !== 'number' || typeof v.at !== 'number') return null;
      if (v.origin !== _origin()) return null;
      if (now - v.at > VERDICT_TTL_MS || now < v.at) return null;
      return v;
    } catch (e) { return null; }
  }
  function _remember(v, opts) {
    try { var st = _store(opts); if (st) st.setItem(VERDICT_KEY, JSON.stringify(v)); } catch (e) {}
  }
  /* Drop the cached reading, so the next measure() really measures. */
  function forget(opts) {
    try { var st = _store(opts); if (st) st.removeItem(VERDICT_KEY); } catch (e) {}
  }

  /* One timed round: every url at once, each with a fresh address so no
     cache can answer it (If-Modified-Since would get a 53-byte 304, which
     measures nothing). Resolves {bytes, ms}; rejects if any fetch fails. */
  function _round(urls, opts) {
    var doFetch = opts.fetch || function (u, o) { return root.fetch(u, o); };
    var clock = opts.clock || nowMs;
    var ctrl = root.AbortController ? new root.AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, BW_FETCH_MS) : null;
    var t0 = clock();
    return Promise.all(urls.map(function (u, i) {
      var fresh = u + (u.indexOf('?') < 0 ? '?' : '&') + 'bw=' + Date.now() + '-' + i + '-' + Math.random();
      return Promise.resolve(doFetch(fresh, { cache: 'no-store', signal: ctrl ? ctrl.signal : undefined }))
        .then(function (r) {
          if (!r || !r.ok) throw new Error('HTTP ' + (r && r.status));
          return r.blob();
        })
        .then(function (b) { return (b && b.size) || 0; });
    })).then(function (sizes) {
      if (timer) clearTimeout(timer);
      var bytes = 0;
      sizes.forEach(function (n) { bytes += n; });
      return { bytes: bytes, ms: Math.max(clock() - t0, 0.001) };
    }, function (e) { if (timer) clearTimeout(timer); throw e; });
  }
  /* Mbit/s from one round, the asking round trip taken off. */
  function rateOf(round, rttMs) {
    if (!round || !(round.bytes > 0)) return 0;
    var lat = (typeof rttMs === 'number' && rttMs > 0) ? rttMs : 0;
    var ms = Math.max(round.ms - lat, round.ms * (1 - MAX_RTT_SHARE));
    return (round.bytes * 8) / (ms * 1000);
  }
  /* Warm-up, then the better of two timed rounds. Resolves Mbit/s. */
  function throughput(urls, rttMs, opts) {
    opts = opts || {};
    var best = 0;
    return _round(urls, opts)
      .then(function () { return _round(urls, opts); })
      .then(function (a) { best = Math.max(best, rateOf(a, rttMs)); return _round(urls, opts); })
      .then(function (b) { best = Math.max(best, rateOf(b, rttMs)); return best; });
  }

  /* Measure (or reuse a fresh reading). opts: { hosts, force, ui, fetch,
     storage, now, clock, win }. Resolves {mbps, rttMs, at, cached} or null
     when it must not or could not measure (the reflector, the demo, no
     WebRTC, no stills to time, a failed download). Single flight: pages that
     ask together share one measurement. */
  var _inflight = null;
  function measure(opts) {
    opts = opts || {};
    if (blocked(opts)) return Promise.resolve(null);
    if (!opts.force) {
      var c = cached(opts);
      if (c) return Promise.resolve({ mbps: c.mbps, rttMs: c.rttMs, at: c.at, cached: true });
    }
    if (_inflight) return _inflight;
    var u = opts.ui || ui();
    var hosts = (opts.hosts || []).slice(0, BW_SAMPLE_MAX);
    if (!hosts.length || !u.cameraStills || !u.stillUrl) return Promise.resolve(null);
    var rttMs = null;
    var p = Promise.all([
      u.cameraStills(),
      u.probeRtt ? u.probeRtt().catch(function () { return null; }) : Promise.resolve(null),
    ]).then(function (got) {
      var pats = got[0];
      rttMs = (typeof got[1] === 'number' && got[1] < 9999) ? got[1] : null;
      if (!pats || !pats.imagePattern) return null;
      // A reflector verdict may have arrived while the stills were asked for.
      if (blocked(opts)) return null;
      var urls = hosts.map(function (h) { return u.stillUrl(pats.imagePattern, h); });
      return throughput(urls, rttMs, opts).then(function (mbps) {
        var v = { mbps: Math.round(mbps * 10) / 10, rttMs: rttMs == null ? null : Math.round(rttMs),
                  at: opts.now ? opts.now() : Date.now(), origin: _origin() };
        _remember(v, opts);
        return { mbps: v.mbps, rttMs: v.rttMs, at: v.at, cached: false };
      });
    }).catch(function () { return null; });
    _inflight = p;
    p.then(function () { if (_inflight === p) _inflight = null; });
    return p;
  }

  /* The verdict for `wanted` live tiles. Resolves
       { live, tiles, mbps, rttMs, needMbps, why }
     live is true only when the measured rate carries every tile wanted.
     tiles is how many it would carry (0 when blocked or unmeasured). The
     reflector rule is applied AFTER the measurement as well as before. */
  function decide(wanted, opts) {
    opts = opts || {};
    var need = needMbps(wanted);
    var no = function (why, m) {
      return { live: false, tiles: 0, mbps: m ? m.mbps : null, rttMs: m ? m.rttMs : null,
               needMbps: need, why: why };
    };
    var why = blocked(opts);
    if (why) return Promise.resolve(no(why));
    return measure(opts).then(function (m) {
      var late = blocked(opts);
      if (late) return no(late, m);
      if (!m) return no('not measured');
      var tiles = tilesCarried(m.mbps);
      var live = wanted > 0 && tiles >= wanted;
      return { live: live, tiles: tiles, mbps: m.mbps, rttMs: m.rttMs, needMbps: need,
               why: live ? 'fast enough' : 'too slow' };
    });
  }

  /* Call cb when the browser says the network changed, after dropping the
     cached reading. Where navigator.connection does not exist (Safari) this
     does nothing, and coming back to the page is the cue instead. Returns a
     function that stops listening. */
  function watchConnection(cb, opts) {
    opts = opts || {};
    var nav = opts.navigator || root.navigator;
    var conn = nav && nav.connection;
    if (!conn || !conn.addEventListener) return function () {};
    var h = function () { forget(opts); cb(); };
    conn.addEventListener('change', h);
    return function () { try { conn.removeEventListener('change', h); } catch (e) {} };
  }

  var API = {
    supported: supported,
    url: url,
    makeVideo: makeVideo,
    start: start,
    playVideo: playVideo,
    unblockAll: unblockAll,
    blockedCount: blockedCount,
    noFrameDetail: noFrameDetail,
    ICE_MS: ICE_MS,
    FRAME_MS: FRAME_MS,
    POOR_FPS: POOR_FPS,
    // the bandwidth decision
    measure: measure,
    decide: decide,
    forget: forget,
    cached: cached,
    blocked: blocked,
    needMbps: needMbps,
    tilesCarried: tilesCarried,
    rateOf: rateOf,
    throughput: throughput,
    watchConnection: watchConnection,
    PER_STREAM_MBPS: PER_STREAM_MBPS,
    HEADROOM: HEADROOM,
    VERDICT_TTL_MS: VERDICT_TTL_MS,
    VERDICT_KEY: VERDICT_KEY,
  };
  root.DashRTC = API;
  if (typeof globalThis !== 'undefined') globalThis.DashRTC = API;
})(typeof window !== 'undefined' ? window : globalThis);
