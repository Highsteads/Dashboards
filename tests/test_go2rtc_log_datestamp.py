#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_go2rtc_log_datestamp.py
# Description: go2rtc stamps its log lines with the TIME only and cannot be
#              configured otherwise — MEASURED 13-08-2026 by running go2rtc
#              1.9.14 twice on throwaway configs differing only in a
#              `log: time:` key: both stamped "09:31:35.010", no date either
#              way, because the console writer hardcodes zerolog's TimeFormat.
#              So a log spanning days cannot place a line on a day, which is
#              exactly what went wrong diagnosing the overnight camera outage
#              that morning.
#
#              The FIRST attempt to measure that proved nothing: the yaml was
#              hand-patched in place, but _start_go2rtc regenerates it, so the
#              key was gone before go2rtc read the file. Test a config change in
#              isolation, never against a file the plugin owns and rewrites.
#
#              These pin the marker that replaces it, and in particular the two
#              ways it could fail SILENTLY: the whole body is wrapped in
#              `except Exception: pass` (deliberately — it rides the camera
#              supervision path), so a marker that never writes looks identical
#              to one that had nothing to say. The first cut had exactly that
#              bug: `datetime.datetime.now()` where plugin.py does
#              `from datetime import datetime`, which raises AttributeError
#              straight into the swallow. py_compile passed it.
# Author:      CliveS & Claude Opus 5
# Date:        13-08-2026 10:05 BST
# Version:     1.0

import io

from conftest import bare_plugin


class _Handle(io.BytesIO):
    """Stands in for the append-mode log file the go2rtc child also holds."""
    closed_flag = False

    @property
    def closed(self):                     # BytesIO closes on GC; be explicit
        return self.closed_flag

    def text(self):
        return self.getvalue().decode("utf-8")


def _plugin_with_log():
    p = bare_plugin()
    handle = _Handle()
    p._go2rtc_logfile = handle
    p._go2rtc_log_day = None
    return p, handle


def test_forced_stamp_writes_a_dated_marker():
    """The load-bearing case. If the swallow ate an exception this is empty."""
    p, handle = _plugin_with_log()
    p._stamp_go2rtc_log(force=True)
    out = handle.text()
    assert out, "no marker written at all — the except swallowed something"
    assert "date marker" in out
    # A real date, not a format string or a repr of a bound method.
    import datetime as _dt
    assert _dt.date.today().strftime("%Y-%m-%d") in out
    assert out.endswith("\n")


def test_marker_names_the_weekday():
    """The point is placing a line on a DAY; the weekday makes that readable."""
    import datetime as _dt
    p, handle = _plugin_with_log()
    p._stamp_go2rtc_log(force=True)
    assert _dt.date.today().strftime("%A") in handle.text()


def test_same_day_does_not_repeat():
    """Called every 30s from supervision — one marker a day, not 2,880."""
    p, handle = _plugin_with_log()
    p._stamp_go2rtc_log(force=True)
    first = handle.text()
    for _ in range(50):
        p._stamp_go2rtc_log()
    assert handle.text() == first


def test_date_rollover_writes_a_second_marker():
    p, handle = _plugin_with_log()
    p._stamp_go2rtc_log(force=True)
    p._go2rtc_log_day = "1999-01-01 Friday"      # pretend the day rolled
    p._stamp_go2rtc_log()
    assert handle.text().count("date marker") == 2


def test_no_handle_is_silent_not_fatal():
    """go2rtc never started (no cameras configured) — must not raise."""
    p = bare_plugin()
    p._go2rtc_logfile = None
    p._stamp_go2rtc_log(force=True)          # must not raise


def test_closed_handle_is_silent_not_fatal():
    p, handle = _plugin_with_log()
    handle.closed_flag = True
    p._stamp_go2rtc_log(force=True)
    assert handle.text() == ""


def test_a_broken_handle_cannot_break_supervision():
    """The reason for the blanket except: this runs on the camera supervision
    path, and a logging cosmetic must never cost a go2rtc restart."""
    class _Exploding:
        closed = False

        def write(self, _data):
            raise OSError("disk full")

    p = bare_plugin()
    p._go2rtc_logfile = _Exploding()
    p._go2rtc_log_day = None
    p._stamp_go2rtc_log(force=True)          # must not raise


def test_failed_write_does_not_claim_the_day():
    """If the write blew up, the day must NOT be recorded as stamped — else the
    next roll-over is the only chance and the whole day goes unmarked."""
    class _Exploding:
        closed = False

        def write(self, _data):
            raise OSError("disk full")

    p = bare_plugin()
    p._go2rtc_logfile = _Exploding()
    p._go2rtc_log_day = None
    p._stamp_go2rtc_log(force=True)
    assert getattr(p, "_go2rtc_log_day", None) is None


def test_config_builder_carries_no_time_key():
    """Pins the MEASURED finding. Someone will reasonably assume go2rtc can be
    told to date its own lines; it cannot, and re-adding the key would look
    like a fix while changing nothing."""
    import os
    sp = os.path.join(os.path.dirname(__file__), "..", "Dashboards.indigoPlugin",
                      "Contents", "Server Plugin", "plugin.py")
    src = open(sp, encoding="utf-8").read()
    # The generated block is a list of literal yaml lines.
    assert '"  level: info"' in src, "log block moved — re-point this test"
    assert '"  time:' not in src and "'  time:" not in src, (
        "a `time:` key is back in the generated go2rtc config — it does nothing "
        "(console writer hardcodes 15:04:05.000); see _stamp_go2rtc_log")
