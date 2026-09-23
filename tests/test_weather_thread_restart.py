#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_weather_thread_restart.py
# Description: A Configure save that restarts the weather thread while a fetch
#              is running must not leave two threads polling OpenWeatherMap
#              (v3.25.0). The old thread re-read self._weather_stop each loop,
#              so it adopted the NEW Event and never stopped.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
import threading
import time

from conftest import bare_plugin


def test_a_replaced_stop_event_still_stops_the_old_thread():
    p = bare_plugin()
    p._WEATHER_POLL_SECONDS = 0.01
    in_fetch = threading.Event()
    release = threading.Event()
    fetches = {"n": 0}

    def slow_fetch():
        fetches["n"] += 1
        in_fetch.set()
        release.wait(2)          # an OWM call still in flight

    p._fetch_and_write_weather = slow_fetch
    old_stop = threading.Event()
    p._weather_stop = old_stop
    t = threading.Thread(target=p._weather_thread_main, args=(old_stop,), daemon=True)
    t.start()
    assert in_fetch.wait(2)

    # What closedPrefsConfigUi does: stop (join times out mid-fetch), then
    # swap in a fresh Event for the new thread.
    old_stop.set()
    p._weather_stop = threading.Event()
    release.set()
    t.join(2)
    assert not t.is_alive(), "the old weather thread adopted the new Event and kept polling"
    time.sleep(0.05)
    assert fetches["n"] == 1
