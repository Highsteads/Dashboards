#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_server_zone.py
# Description: config.js tells the pages which zone the server's clock is in
#              (3.73.4). Indigo's times carry no zone, and a page read them
#              in the browser's own, so from abroad every age was hours out.
# Author:      CliveS & Claude Fable 5.2
# Date:        26-11-2026
# Version:     1.0

import time

from conftest import bare_plugin, load_plugin_module


def test_the_zone_is_a_name_and_an_offset():
    load_plugin_module()
    plug = bare_plugin()
    name, off = plug._server_zone()
    assert isinstance(name, str)
    assert off == int(time.localtime().tm_gmtoff // 60)
    assert name == "" or "/" in name or name in ("UTC", "GMT")


def test_the_flags_carry_it_so_the_tick_follows_a_clock_change():
    load_plugin_module()
    plug = bare_plugin()
    plug._plugin_present = lambda _id: False
    plug._sigen_available = lambda: False
    plug._companion_scripts_installed = lambda: {}
    plug._catalog_published = lambda: False
    flags = plug._feature_flags()
    assert flags["serverTz"] == plug._server_zone()[0]
    assert flags["serverUtcOffsetMin"] == plug._server_zone()[1]
