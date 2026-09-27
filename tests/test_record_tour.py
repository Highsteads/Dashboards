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


def test_every_tour_page_exists_and_every_beat_speaks():
    tour = json.loads((ROOT / "tools/tour.json").read_text(encoding="utf-8"))
    assert tour["segments"]
    for seg in tour["segments"]:
        page = seg["page"].split("?")[0]
        assert (PAGES / page).is_file(), f"tour.json names a page that does not exist: {page}"
        assert seg["beats"]
        for beat in seg["beats"]:
            assert beat["say"].strip()
            assert beat["say"].isascii(), "the narration is spoken and captioned: keep it ASCII"
            assert isinstance(beat.get("to", ""), (str, int))


def test_plan_lays_every_beat_on_one_clock(monkeypatch, tmp_path):
    lengths = iter([2.0, 3.0, 1.5])
    monkeypatch.setattr(rt, "speak", lambda text, path, voice, rate: next(lengths))
    tour = {"segments": [
        {"page": "index.html", "beats": [{"say": "a"}, {"say": "b", "to": "Energy"}]},
        {"page": "menu.html", "beats": [{"say": "c"}]},
    ]}
    segs, total = rt.plan(tour, str(tmp_path), "Daniel", 178)
    a, b = segs[0]["beats"]
    assert a["start"] == rt.LEAD_IN
    assert b["start"] == rt.LEAD_IN + 2.0 + rt.BEAT_GAP
    assert segs[0]["length"] == b["start"] + 3.0 + rt.TAIL
    assert segs[1]["offset"] == segs[0]["length"]
    assert total == segs[0]["length"] + segs[1]["length"]


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
