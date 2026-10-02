#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_record_tour.py
# Description: tools/record_tour.py: the tour script names real pages, the
#              film is laid out on one clock, each clip starts with what the
#              screen showed, captions are well formed, and the live-video
#              relay forwards the camera handshake and nothing else.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     1.0
import http.server
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/record_tour.py"
spec = importlib.util.spec_from_file_location("record_tour", TOOL)
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)
PAGES = ROOT / "Dashboards.indigoPlugin/Contents/Resources/static/pages"


def test_every_tour_page_exists_and_every_line_is_speakable():
    tour = json.loads((ROOT / "tools/tour.json").read_text(encoding="utf-8"))
    assert tour["segments"]
    for seg in tour["segments"]:
        assert sum(k in seg for k in ("page", "card", "clip")) == 1, "a segment is a page, a card or a clip"
        if "page" in seg:
            page = seg["page"].split("?")[0]
            assert (PAGES / page).is_file(), f"tour.json names a page that does not exist: {page}"
        assert seg["beats"]
        for beat in seg["beats"]:
            said = beat.get("say", "")
            assert said or beat.get("hold"), "a silent beat needs a hold, or it takes no time"
            assert said.isascii(), "the narration is spoken and captioned: keep it ASCII"
            for action in beat.get("do", []):
                assert action[0] in {"scroll", "point", "press", "drag", "zoom", "unzoom",
                                     "wait", "label", "hide", "expect"}, action


def test_the_live_allow_list_names_only_what_the_tour_presses():
    tour = json.loads((ROOT / "tools/tour.json").read_text(encoding="utf-8"))
    assert all(isinstance(i, int) for i in tour["allow"])
    assert tour.get("allow_messages", []) == [], "no plugin message is a tour action"


def test_plan_lays_every_beat_on_one_clock(monkeypatch, tmp_path):
    lengths = iter([2.0, 3.0, 1.5])
    monkeypatch.setattr(rt, "speak", lambda text, path, voice, rate: next(lengths))
    tour = {"segments": [
        {"page": "index.html", "beats": [{"say": "a"}, {"say": "b {x}", "hold": 5}]},
        {"page": "menu.html", "beats": [{"say": "", "hold": 2}, {"say": "c"}]},
    ]}
    segs, total = rt.plan(tour, str(tmp_path), "Daniel", 178, {"x": "y"})
    a, b = segs[0]["beats"]
    assert b["say"] == "b y", "live words are filled in before speaking"
    assert a["start"] == rt.LEAD_IN
    assert b["start"] == rt.LEAD_IN + 2.0 + rt.BEAT_GAP
    assert b["span"] == 5, "a hold longer than the sentence sets the beat"
    assert segs[0]["length"] == b["start"] + 5 + rt.TAIL
    silent, c = segs[1]["beats"]
    assert silent["audio"] is None and silent["span"] == 2
    assert c["start"] == rt.LEAD_IN + 2, "no gap is left after a silent beat"
    assert segs[1]["offset"] == segs[0]["length"]
    assert total == segs[0]["length"] + segs[1]["length"]


def test_the_guard_refuses_every_command_in_a_rehearsal():
    g = rt.Guard(live=False, allow_ids=[5])
    body = json.dumps({"message": "indigo.device.turnOn", "objectId": 5}).encode()
    assert g.check("/v2/api/command", body)[:2] == (True, False)
    assert g.check("/message/com.x.dashboards/applyColour/", b"{}")[:2] == (True, False)
    assert g.check("/message/com.x.dashboards/changedSince/", b"{}") == (False, True, "")
    assert g.check("/v2/api/indigo.devices", b"") == (False, True, "")


def test_a_live_take_lets_through_only_the_listed_ids():
    g = rt.Guard(live=True, allow_ids=[5])
    ok = json.dumps({"message": "indigo.device.turnOn", "objectId": 5}).encode()
    other = json.dumps({"message": "indigo.device.unlock", "objectId": 6}).encode()
    assert g.check("/v2/api/command", ok)[:2] == (True, True)
    assert g.check("/v2/api/command", other)[:2] == (True, False)
    assert g.check("/v2/api/command", b"not json")[:2] == (True, False)
    assert g.check("/message/com.x.dashboards/unknownWrite/", b"{}")[:2] == (True, False), \
        "an unknown plugin message counts as a command, and is refused"


HUB = ("ENERGY \u00b7 NOW INVERTER SOLAR 5.12 kW today 11.3 kWh GRID 13 W Idle HOME 488 W today "
       "9.1 kWh BATTERY 4.65 kW 54.5% \u00b7 19.1 kWh Now Self-consumption Self-sufficient 61%")


def test_the_hub_energy_card_is_read_as_numbers():
    e = rt.read_energy(HUB)
    assert e["solar"] == 5.12 and e["home"] == 0.488 and e["grid"] == 0.013
    assert e["grid_mode"] == "idle" and e["battery"] == 4.65 and e["battery_pct"] == 54.5
    assert e["self_sufficiency"] == 61


def test_energy_words_say_only_what_the_readings_show():
    w = rt.energy_words(rt.read_energy(HUB))["energy_now"]
    assert "far more than the house needs" in w and "charging the battery" in w
    assert "55 percent" in w, "54.5% is said as a person rounds it"
    assert "kilowatt" not in w and "watts" not in w, "figures that move are left to the screen"
    sunset = rt.energy_words({"solar": 0, "home": 0.6, "grid": 0, "grid_mode": "idle",
                              "battery": 0.6, "battery_pct": 70})["energy_now"]
    assert "battery is running the house" in sunset
    export = rt.energy_words({"solar": 6, "home": 0.5, "grid": 5.4, "grid_mode": "exporting",
                              "battery": 0.0, "battery_pct": 100})["energy_now"]
    assert "sold to the grid" in export and "charging" not in export
    assert "flowing" in rt.energy_words({})["energy_now"], "unreadable -> no figures at all"


def test_a_zoom_eases_in_holds_and_eases_out_on_the_page():
    z = [{"t0": 1.0, "t1": 4.0, "cx": 200, "cy": 150, "s": 1.5}]
    assert rt.zoom_at(z, 0.5, 1280, 720) == (1.0, 640, 360)
    s, cx, cy = rt.zoom_at(z, 3.0, 1280, 720)
    assert s == 1.5 and (cx, cy) == (200, 150)
    assert 1.0 < rt.zoom_at(z, 1.3, 1280, 720)[0] < 1.5
    assert rt.zoom_at(z, 4.0 + rt.ZOOM_RAMP + 0.01, 1280, 720)[0] == 1.0
    x0, y0, x1, y1 = rt.crop_box(1.5, 200, 150, 1280, 720)
    assert (x0, y0) == (0, 0), "a zoom near the corner stays on the page"
    assert round(x1 - x0, 6) == round(1280 / 1.5, 6)


def test_every_cut_dips_at_both_ends():
    assert rt.fade_at(0, 10) == 1.0
    assert rt.fade_at(5, 10) == 0.0
    assert rt.fade_at(10, 10) == 1.0


class _FakeCDP:
    def __init__(self):
        self.events = {}


def test_a_clip_starts_with_what_the_screen_already_showed(tmp_path):
    rec = rt.Recorder(_FakeCDP(), str(tmp_path))
    files = {}
    for name, stamp in (("old", 9.0), ("before", 9.5), ("in1", 10.2), ("in2", 11.0), ("next", 12.5)):
        p = tmp_path / f"{name}.jpg"
        p.write_bytes(b"x")
        files[name] = p
        rec.all.append((stamp, str(p)))
    clip = [(round(t, 6), p) for t, p in rec.take(10.0, 12.0)]
    assert clip == [(0.0, str(files["before"])), (0.2, str(files["in1"])), (1.0, str(files["in2"]))]
    assert not files["old"].exists(), "frames nothing will use are deleted"
    assert files["next"].exists() and rec.all == [(12.5, str(files["next"]))]


def test_captions_are_well_formed_webvtt(tmp_path):
    assert rt.vtt_time(3725.5) == "01:02:05.500"
    segs = [{"offset": 10.0, "beats": [{"start": 0.8, "dur": 2.0, "say": "Hello."}]}]
    out = tmp_path / "t.vtt"
    rt.write_vtt(segs, str(out))
    text = out.read_text(encoding="utf-8")
    assert text.startswith("WEBVTT\n")
    assert "00:00:10.800 --> 00:00:12.800\nHello." in text


def _upstream():
    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            seen["path"] = self.path
            seen["origin"] = self.headers.get("Origin")
            seen["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            body = b"v=0 answer 192.168.1.10"
            self.send_response(201)
            self.send_header("Access-Control-Allow-Origin", "http://192.168.1.10:8176")
            self.send_header("Content-Type", "application/sdp")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


def test_the_relay_carries_the_camera_handshake_and_nothing_else():
    up, seen = _upstream()
    san = rt.cs.Sanitiser()
    fake = san.scrub(b"192.168.1.20").decode()        # what the page was given
    relay = rt.serve_signalling(0, f"http://127.0.0.1:{up.server_address[1]}", san,
                                "http://192.168.1.10:8176")
    base = f"http://127.0.0.1:{relay.server_address[1]}"
    try:
        req = urllib.request.Request(f"{base}/webrtc/{fake}", data=b"offer", method="POST",
                                     headers={"Origin": "http://127.0.0.1:8898",
                                              "Content-Type": "application/sdp"})
        with urllib.request.urlopen(req, timeout=5) as res:
            assert res.status == 201
            assert res.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8898"
            assert res.read() == b"v=0 answer 192.168.1.10"
        assert seen["path"] == "/webrtc/192.168.1.20", "the real camera goes upstream"
        assert seen["origin"] == "http://192.168.1.10:8176"
        assert seen["body"] == b"offer"
        try:
            urllib.request.urlopen(f"{base}/bootstrap", timeout=5)
            raise AssertionError("anything but /webrtc/ must be refused")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        relay.shutdown()
        up.shutdown()


def test_live_lines_are_rewritten_inside_their_slots(monkeypatch, tmp_path):
    rates = []

    def fake_speak(text, path, voice, rate):
        rates.append(rate)
        return 9.0 if rate == 178 else 7.5         # too long at the normal pace
    monkeypatch.setattr(rt, "speak", fake_speak)
    seg = {"beats": [{"template": "Now {energy_now}", "say": "Now old", "span": 8.0, "dur": 6.0},
                     {"template": "plain", "say": "plain", "span": 3.0, "dur": 3.0}]}
    notes = rt.respeak(seg, {"energy_now": "new"}, "Daniel", 178, str(tmp_path))
    live, plain = seg["beats"]
    assert live["say"] == "Now new" and live["dur"] == 7.5 and live["span"] == 8.0
    assert rates[0] == 178 and rates[1] > 178, "a line that no longer fits is said faster"
    assert plain["dur"] == 3.0 and len(rates) == 2, "a line with nothing live is left alone"
    assert notes == []


def test_a_house_using_nothing_is_a_page_caught_mid_update():
    w = rt.energy_words({"solar": 2.0, "home": 0.0, "grid": 0, "grid_mode": "idle",
                         "battery": 2.0, "battery_pct": 67})["energy_now"]
    assert "watts" not in w and "kilowatt" not in w


def test_the_energy_figures_are_read_until_they_hold_still():
    import asyncio

    pages = iter([HUB.replace("5.12 kW", "1.97 kW"), HUB, HUB.replace("5.12", "5.20")])

    class FakeCDP:
        async def js(self, expr, timeout=30):
            return next(pages)

    got = asyncio.run(rt.steady_energy(FakeCDP(), tries=5, gap=0))
    assert got["solar"] == 5.2, "the first, stale reading is not trusted on its own"

    class Jumpy:
        n = 0

        async def js(self, expr, timeout=30):
            Jumpy.n += 1
            return HUB.replace("5.12 kW", f"{3 ** Jumpy.n}.0 kW")

    assert asyncio.run(rt.steady_energy(Jumpy(), tries=4, gap=0)) == {}, \
        "figures that never settle give no figures at all"


def test_prepare_refuses_an_id_that_is_not_allowed():
    import pytest
    with pytest.raises(SystemExit):
        rt.prepare("192.0.2.1", 8176, "k", [{"message": "indigo.device.unlock", "objectId": 9}], {5})


def test_the_tour_prepares_only_allowed_ids():
    tour = json.loads((ROOT / "tools/tour.json").read_text(encoding="utf-8"))
    assert all(c["objectId"] in tour["allow"] for c in tour.get("prepare", []))


def test_kokoro_speed_follows_the_say_rate_within_a_sane_range():
    assert rt.kokoro_speed(178) == 1.0
    assert rt.kokoro_speed(1000) == 1.4 and rt.kokoro_speed(10) == 0.7
    assert 1.0 < rt.kokoro_speed(200) < 1.2, "respeak's faster retry really is faster"


def test_the_voice_prefix_picks_the_engine(monkeypatch):
    calls = []
    monkeypatch.setattr(rt.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(rt, "media_duration", lambda p: 1.0)
    rt.speak("hi", "/tmp/x.wav", "kokoro:bm_george", 178)
    rt.speak("hi", "/tmp/y.aiff", "Daniel", 178)
    assert calls[0][-4:] == ["bm_george", "1.0", "/tmp/x.wav", "hi"]
    assert calls[0][0].endswith("python")
    assert calls[1][:3] == ["say", "-v", "Daniel"]


def test_the_camera_watch_goes_upstream_with_the_real_addresses():
    # The plugin keeps fresh stills only for cameras it is told are on screen,
    # and it knows them by their real address; the page only ever held the
    # made-up one. Without this the Garage page's pictures froze in a take.
    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            seen["path"] = self.path
            seen["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            seen["len"] = int(self.headers["Content-Length"])
            reply = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

    up = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    san = rt.cs.Sanitiser()
    fake = san.scrub(b"192.168.1.61").decode()
    guard = rt.Guard(live=False)
    proxy = rt.serve_guarded(0, f"http://127.0.0.1:{up.server_address[1]}", san, threading.Lock(),
                             "k", [], None, guard)
    try:
        body = json.dumps({"hosts": [fake]}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{proxy.server_address[1]}/message/com.x.dashboards/watchCameras/",
            data=body, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as res:
            assert res.status == 200
        assert json.loads(seen["body"]) == {"hosts": ["192.168.1.61"]}
        assert seen["len"] == len(seen["body"]), "Content-Length follows the longer real address"
        assert not guard.log, "watching is a read, not a command"
    finally:
        proxy.shutdown()
        up.shutdown()


def test_a_spliced_clip_meets_its_lines_and_waits_on_its_first_frame():
    beats = [{"start": 5.0, "anchor": 0.5}, {"start": 9.0, "anchor": 4.0}]
    a = rt.clip_anchors(beats, 14.0, 12.0)
    assert a[0] == (0.0, 0.0) and a[1] == (4.5, 0.0), "the footage holds until the first line's action is due"
    assert rt.old_time(a, 4.0) == 0.0
    assert rt.old_time(a, 5.0) == 0.5 and rt.old_time(a, 9.0) == 4.0
    assert 0.5 < rt.old_time(a, 7.0) < 4.0
    assert rt.old_time(a, 14.0) == 12.0 and rt.old_time(a, 99) == 12.0, "clamped at the end"
    early = rt.clip_anchors([{"start": 1.0, "anchor": 3.0}], 8.0, 6.0)
    assert early[0] == (0.0, 2.0), "a line that comes first starts the footage part-way in"
    assert rt.clip_anchors([{"start": 1.0}], 8.0, 6.0) == [(0.0, 0.0), (8.0, 6.0)]


def test_the_tour_clip_anchors_lie_inside_its_footage():
    tour = json.loads((ROOT / "tools/tour.json").read_text(encoding="utf-8"))
    for seg in tour["segments"]:
        if "clip" in seg:
            c = seg["clip"]
            old_len = c["to"] - c["from"] - 2 * rt.FADE
            anchors = [b["anchor"] for b in seg["beats"] if "anchor" in b]
            assert anchors == sorted(anchors) and anchors[0] >= 0 and anchors[-1] < old_len
