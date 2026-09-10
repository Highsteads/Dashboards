#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_camera_thumbs.py
# Description: Contract test for the grid thumbnail — the second, smaller copy
#              of each camera snapshot.
#
#              WHY THIS EXISTS
#              The eight tiles in the camera grid are drawn about 300 px wide on
#              a desktop and less than that on a phone, but were being sent
#              640 px of picture. MEASURED across all nine cameras: 33.2 KB per
#              full picture against 12.3 KB per thumbnail, so a pass over the
#              grid drops from about 300 KB to 111 KB — 70% less, on the link
#              where it matters, for detail nobody can see.
#
#              THE TRAP THIS GUARDS
#              The obvious way to make a second size is to ask go2rtc for it:
#              /api/frame.jpeg takes &width=. That is what the full-size fetch
#              already does, so it reads as the natural extension — and it is
#              wrong. Eighteen frame requests a pass (nine cameras, two widths)
#              made go2rtc answer **HTTP 500**, because each camera was being
#              asked to decode twice in quick succession. Resizing the frame we
#              already hold costs 1.6 ms (measured, steady state) and 0.6% of
#              one core across nine cameras every 2.03 s, and leaves the load on
#              the cameras exactly as it was. So the test asserts that the
#              thumbnail is NOT fetched — anyone "simplifying" `_make_thumb`
#              into a second HTTP call reintroduces a fault that only appears
#              under sustained load.
#
#              The other half is graceful degradation. Pillow is declared in
#              requirements.txt but cannot be guaranteed on someone else's
#              install, and a missing resizer must cost picture QUALITY, never
#              the picture: `_make_thumb` returns None and the pages fall back
#              to the full-size image they always used.
# Author:      CliveS & Claude Opus 5
# Date:        30-07-2026
# Version:     1.0

import ast
import io
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                   "Server Plugin", "plugin.py")
REQS = os.path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                    "Server Plugin", "requirements.txt")


@pytest.fixture(scope="module")
def source():
    with open(SRC, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def tree(source):
    return ast.parse(source)


def _func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in plugin.py")


def _const(source, name):
    m = re.search(rf"^{name}\s*=\s*(\d+)", source, re.M)
    assert m, f"{name} not defined at module level"
    return int(m.group(1))


# ---------------------------------------------------------------- sizing ----

def test_thumb_is_meaningfully_smaller_than_the_full_picture(source):
    """A thumbnail that is nearly full size saves nothing and doubles the
    files written. 320 against 640 is what the 70% measurement was taken at."""
    full = _const(source, "CAMERA_SNAPSHOT_WIDTH")
    thumb = _const(source, "CAMERA_THUMB_WIDTH")
    assert thumb <= full // 2, (
        f"thumb width {thumb} is not at most half the full width {full} — "
        "the saving this exists for disappears"
    )


def test_the_two_sizes_are_different_files(source, tree):
    """They must not collide, or the grid overwrites the focused tile's
    picture with a small one every pass."""
    fnames = []
    for name in ("_cam_jpg_path", "_cam_thumb_path"):
        node = _func(tree, name)
        got = [n.value for n in ast.walk(node)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and "{host}" not in n.value and ".jpg" in n.value]
        # they are f-strings, so pull the literal parts instead
        if not got:
            got = [seg.value for n in ast.walk(node) if isinstance(n, ast.JoinedStr)
                   for seg in n.values if isinstance(seg, ast.Constant)]
        fnames.append("".join(str(g) for g in got))
    assert fnames[0] != fnames[1], "full and thumb resolve to the same filename"
    assert "thumb" in fnames[1], "the thumb path should be recognisable as one"


# --------------------------------------------------- how it is produced ----

def test_thumb_is_resized_locally_and_never_fetched(tree):
    """THE HEADLINE RULE. Asking go2rtc for a second width made it return
    HTTP 500 under load. `_make_thumb` must work from bytes it is handed."""
    node = _func(tree, "_make_thumb")
    calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
    names = set()
    for c in calls:
        f = c.func
        names.add(getattr(f, "id", None) or getattr(f, "attr", None))
    forbidden = {"get", "urlopen", "request", "Request", "post"}
    assert not (names & forbidden), (
        f"_make_thumb makes a network call ({names & forbidden}) — the whole "
        "point is that it resizes a frame already in memory"
    )
    assert "_fetch_one_snapshot" not in names

    src = ast.get_source_segment(open(SRC, encoding="utf-8").read(), node) or ""
    assert "frame.jpeg" not in src, "_make_thumb must not build a go2rtc URL"
    assert "width=" not in src, "_make_thumb must not ask go2rtc for a width"


def test_thumb_takes_the_frame_as_an_argument(tree):
    """If it re-read the file it would race the atomic write it was just
    handed the bytes of."""
    node = _func(tree, "_make_thumb")
    args = [a.arg for a in node.args.args]
    assert len(args) >= 2 and args[0] == "self", f"unexpected signature {args}"
    assert any("byte" in a or "jpeg" in a or "data" in a for a in args[1:]), (
        f"_make_thumb should take the frame bytes, got {args[1:]}"
    )
    assert not any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "open"
                   for n in ast.walk(node)), "_make_thumb must not re-read the file"


# ------------------------------------------------------- degrading well ----

def test_missing_pillow_is_survivable(tree):
    """Pillow is declared, not guaranteed. A missing resizer must cost
    quality, never the picture."""
    node = _func(tree, "_make_thumb")
    handlers = [h for n in ast.walk(node) if isinstance(n, ast.Try) for h in n.handlers]
    caught = set()
    for h in handlers:
        if isinstance(h.type, ast.Name):
            caught.add(h.type.id)
        elif isinstance(h.type, ast.Tuple):
            caught.update(e.id for e in h.type.elts if isinstance(e, ast.Name))
    assert "ImportError" in caught, "an absent Pillow must be caught by name"
    assert "Exception" in caught, "a malformed frame must not escape either"

    # Every path returns None rather than raising or returning junk.
    returns = [r for r in ast.walk(node) if isinstance(r, ast.Return)]
    nones = [r for r in returns if isinstance(r.value, ast.Constant) and r.value.value is None]
    assert len(nones) >= 3, (
        "the import failure, the resize failure and the already-small case "
        "should each return None so the caller falls back to the full picture"
    )


def test_import_failure_latches_but_a_bad_frame_does_not(tree, source):
    """A missing Pillow cannot fix itself while the plugin runs, so nine
    failed imports every two seconds is nine log lines a second. A single
    corrupt frame is the opposite — it must not turn the feature off."""
    node = _func(tree, "_make_thumb")
    src = ast.get_source_segment(source, node)
    imp = src.index("except ImportError")
    exc = src.index("except Exception")
    latch = src.index("_thumb_broken = True")
    assert imp < latch < exc, (
        "_thumb_broken should be latched in the ImportError handler only"
    )
    assert "_thumb_broken = True" not in src[exc:], (
        "a single bad frame must not latch thumbnails off for good"
    )


def test_a_resize_failure_cannot_cost_the_full_picture(source, tree):
    """The full-size write must come FIRST and be independent. It is the one
    file that must always be there."""
    node = _func(tree, "_snapshot_worker")
    src = ast.get_source_segment(source, node)
    full = src.index("_cam_jpg_path")
    thumb = src.index("_cam_thumb_path")
    assert full < thumb, "the full-size picture must be written before the thumb"
    assert re.search(r"if\s+thumb\s*:", src), (
        "the thumb write must be guarded — _make_thumb returns None on failure "
        "and _write_atomic would then write the word 'None' to a .jpg"
    )


def test_pillow_is_declared_so_indigo_installs_it():
    with open(REQS, encoding="utf-8") as f:
        body = f.read()
    lines = [ln.strip() for ln in body.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    assert any(ln.lower().startswith("pillow") for ln in lines), (
        "Pillow must be in requirements.txt or nobody else's install gets "
        f"thumbnails at all — found {lines}"
    )


# ------------------------------------------------- the pages can find it ----

def test_the_page_is_told_the_thumb_pattern(source):
    """Derived on the page rather than sent, a rename here would silently
    404 every tile."""
    assert '"thumbPattern"' in source, "cam_cfg must publish thumbPattern"
    assert '"imagePattern"' in source, "and still publish the full-size one"


# --------------------------------------------------- it actually resizes ----

@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PIL") is None,
    reason="Pillow not installed in the test environment",
)
def test_resize_produces_a_valid_smaller_jpeg(source):
    """Drives the real arithmetic rather than trusting it: a wide frame and a
    letterboxed one, since the cameras here are not all 16:9 (back_door is
    640x280) and a hardcoded height would quietly squash it."""
    from PIL import Image

    thumb_w = _const(source, "CAMERA_THUMB_WIDTH")
    _const(source, "CAMERA_THUMB_QUALITY")   # the real function owns the quality; only assert it is defined

    # The REAL function, not a re-implementation of its arithmetic (v2.95.4):
    # the old form copied the resize maths into the test and asserted on its
    # own copy, so _make_thumb itself was never exercised here.
    from conftest import bare_plugin
    p = bare_plugin()
    p._thumb_broken = False
    p._thumb_last_log = 0.0

    for size in ((640, 360), (640, 280), (1280, 720)):
        buf = io.BytesIO()
        Image.new("RGB", size, (90, 120, 160)).save(buf, format="JPEG", quality=90)
        original = buf.getvalue()

        small = p._make_thumb(original)
        assert small, f"{size}: _make_thumb returned nothing"

        with Image.open(io.BytesIO(small)) as chk:
            assert chk.format == "JPEG"
            assert chk.width == thumb_w
            # aspect ratio preserved to within a pixel of rounding
            assert abs(chk.height - size[1] * thumb_w / size[0]) <= 1, (
                f"{size} came back {chk.size} — aspect ratio not preserved"
            )
        assert len(small) < len(original), "the thumbnail is not smaller"


def test_an_already_small_frame_is_not_upscaled(source):
    """Someone lowering CAMERA_SNAPSHOT_WIDTH below the thumb width should get
    no thumbnail rather than a blurry enlargement of one."""
    node_src = open(SRC, encoding="utf-8").read()
    tree_ = ast.parse(node_src)
    src = ast.get_source_segment(node_src, _func(tree_, "_make_thumb"))
    assert re.search(r"width\s*<=\s*CAMERA_THUMB_WIDTH", src), (
        "_make_thumb should return None when the frame is already small enough"
    )


# ------------------------------------------------- transient 500s ----------
# go2rtc spawns ffmpeg to rescale each frame and it intermittently exits 69
# (EX_UNAVAILABLE), surfacing here as a bare HTTP 500. MEASURED: 1.5% of
# requests (4 in 270) and **all four recovered on a single retry 250 ms
# later**, none needing a second. Without the retry each failure costs that
# camera a whole 2 s cycle and writes a warning that reads like a broken
# camera. These were the "lots of 500 warnings" in the log.
#
# Ruled out first, so nobody re-litigates it: it is NOT concurrency. Firing
# all nine together produced 0 failures in 135 requests while spreading the
# same nine across the same two seconds produced 2 — so staggering is not the
# answer and burst fetching is not the cause. It is also not the &width=
# parameter: fetching the native frame instead still failed, and tripled the
# bytes (32 KB -> 90 KB).

def test_a_failed_snapshot_is_retried_once(source, tree):
    node = _func(tree, "_fetch_one_snapshot")
    src = ast.get_source_segment(source, node)
    assert src.count("attempt()") >= 2, (
        "a failed snapshot should be tried once more — measured 4/4 recovery"
    )
    assert "CAMERA_RETRY_DELAY" in src, "the retry must pause before trying again"


def test_the_retry_does_not_become_a_loop(source, tree):
    """Nine cameras retrying in a loop every two seconds would turn a wedged
    go2rtc into a much worse one."""
    node = _func(tree, "_fetch_one_snapshot")
    loops = [n for n in ast.walk(node) if isinstance(n, (ast.For, ast.While))]
    assert not loops, "the retry must be a single extra attempt, not a loop"


def test_retry_delay_is_sane(source):
    m = re.search(r"^CAMERA_RETRY_DELAY\s*=\s*([\d.]+)", source, re.M)
    assert m, "CAMERA_RETRY_DELAY not defined"
    delay = float(m.group(1))
    # Long enough for ffmpeg to be respawnable, short enough that the retry
    # still lands inside the same 2 s poll cycle.
    assert 0.1 <= delay <= 0.75, f"{delay}s is outside the useful range"
