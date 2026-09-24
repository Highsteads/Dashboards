#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_lan_origin.py
# Description: The "at home use this" LAN link (config.js lanURL, the
#              reflector refusal, its log warning and the setup link) was
#              always http://<lan>:8176, whatever INDIGO_URL said, so on an
#              install with a different IWS port or https it was a dead link.
#              The scheme and port now come from api_url; only the host is
#              swapped for the LAN address.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

from conftest import bare_plugin, load_plugin_module

load_plugin_module()


def _origin(api_url, lan="192.168.1.10"):
    p = bare_plugin()
    p.api_url = api_url
    p.lan_ip = lan
    return p._lan_origin()


def test_default_install_is_http_8176():
    assert _origin("http://127.0.0.1:8176") == "http://192.168.1.10:8176"
    assert _origin("") == "http://192.168.1.10:8176"


def test_a_changed_port_is_kept():
    assert _origin("http://127.0.0.1:8200") == "http://192.168.1.10:8200"


def test_https_is_kept():
    assert _origin("https://indigo.example:8443") == "https://192.168.1.10:8443"
    assert _origin("https://indigo.example") == "https://192.168.1.10"


def test_no_lan_address_means_no_origin():
    assert _origin("http://127.0.0.1:8176", lan="") == ""


def test_a_malformed_setting_falls_back_to_the_defaults():
    assert _origin("http://127.0.0.1:notaport") == "http://192.168.1.10:8176"
    assert _origin("ftp://x:21") == "http://192.168.1.10:8176"


def test_the_reflector_refusal_uses_it():
    p = bare_plugin()
    p.api_url = "https://127.0.0.1:8443"
    p.lan_ip = "192.168.1.10"
    p.pluginPrefs = {"reflectorBlock": True}
    p._note_reflector_use = lambda action: True
    seen = {}
    p._evo_reply = lambda obj, status=200: seen.update(obj) or obj
    p._refuse_reflector(object())
    assert seen["lanURL"].startswith("https://192.168.1.10:8443/"), seen


def test_no_builder_hardcodes_the_port():
    from conftest import plugin_source
    src = plugin_source()
    assert 'f"http://{self.lan_ip}:8176' not in src
