#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_trusted_networks.py
# Description: DB-R1 (audit 05-10-2026). The :8177 server hands out the full
#              API key (/bootstrap, when auto-seed is on), the guest token and
#              WebRTC camera set-up. Until 3.60.0 it trusted every private
#              address, so a device on an IoT VLAN or a guest network could ask
#              for the key. It now trusts only loopback, Tailscale, the
#              networks the Indigo Mac itself sits on, and any extra networks
#              the owner names in Configure.
# Author:      CliveS & Claude Opus 5.5
# Date:        05-10-2026
# Version:     1.0

import ast
import inspect
import textwrap

import pytest

from conftest import bare_plugin, load_plugin_module

plugin = load_plugin_module()
import cameras_mixin  # noqa: E402
import dash_common  # noqa: E402


# A macOS `ifconfig -a` excerpt. The addresses are generic examples: the main
# LAN is 192.168.1.0/24, and the Mac also has a Tailscale tunnel and a down
# interface that still carries an address.
IFCONFIG = """\
lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
\tinet6 ::1 prefixlen 128
\tinet6 fe80::1%lo0 prefixlen 64 scopeid 0x1
gif0: flags=8010<POINTOPOINT,MULTICAST> mtu 1280
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet6 fe80::4ae:9fbc:de8:b7f9%en0 prefixlen 64 secured scopeid 0x7
\tinet 192.168.1.10 netmask 0xffffff00 broadcast 192.168.1.255
\tinet6 2001:db8:1:2::10 prefixlen 64 autoconf secured
en9: flags=8822<BROADCAST,SMART,SIMPLEX,MULTICAST> mtu 1500
\tinet 172.20.0.5 netmask 0xffff0000 broadcast 172.20.255.255
utun1: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1280
\tinet 100.70.1.2 --> 100.70.1.2 netmask 0xffffffff
\tinet6 fd7a:115c:a1e0::6e28:da01 prefixlen 48
"""


def _nets(texts):
    return {str(n) for n in texts}


# ── parsing the Mac's own interfaces ────────────────────────────────────────
def test_ifconfig_parse_takes_up_interfaces_only():
    nets = _nets(dash_common.interface_networks(IFCONFIG))
    assert "192.168.1.0/24" in nets
    assert "2001:db8:1:2::/64" in nets
    assert "fe80::/64" in nets
    assert "172.20.0.0/16" not in nets          # en9 is not UP


def test_ifconfig_parse_of_nothing_is_empty():
    assert dash_common.interface_networks("") == []
    assert dash_common.interface_networks("garbage\n\tinet banana netmask 0xzz") == []


def test_dotted_netmask_is_understood():
    text = "en0: flags=8863<UP,RUNNING> mtu 1500\n\tinet 10.9.8.7 netmask 255.255.255.0\n"
    assert _nets(dash_common.interface_networks(text)) == {"10.9.8.0/24"}


# ── the extra-networks setting ─────────────────────────────────────────────
def test_parse_extra_networks():
    nets, bad = dash_common.parse_trusted_subnets(" 192.168.2.0/24, 10.1.2.3/16 ,,")
    assert _nets(nets) == {"192.168.2.0/24", "10.1.0.0/16"}
    assert bad == []


def test_parse_extra_networks_names_the_bad_ones():
    nets, bad = dash_common.parse_trusted_subnets("banana, 192.168.2.0/24, 0.0.0.0/0, ::/0")
    assert _nets(nets) == {"192.168.2.0/24"}
    assert bad == ["banana", "0.0.0.0/0", "::/0"]


def test_blank_setting_is_no_extras():
    for blank in ("", None, "   "):
        assert dash_common.parse_trusted_subnets(blank) == ([], [])


# ── the plugin's trust decision ────────────────────────────────────────────
def _plugin(ifconfig=IFCONFIG, extra=""):
    p = bare_plugin()
    p.trusted_subnets_text = extra
    calls = []

    def _read():
        calls.append(1)
        if isinstance(ifconfig, Exception):
            raise ifconfig
        return ifconfig
    p._read_ifconfig = _read
    p._calls = calls
    return p


TRUSTED = [
    "127.0.0.1",
    "::1",
    "192.168.1.25",                   # the Mac's own LAN
    "::ffff:192.168.1.25",            # the same, IPv4-mapped
    "100.101.102.103",                # Tailscale
    "fd7a:115c:a1e0::1234",           # Tailscale IPv6
    "2001:db8:1:2::99",               # the LAN's IPv6 prefix
]
REFUSED = [
    "192.168.2.7",                   # another private subnet (an IoT VLAN)
    "10.0.0.5",
    "172.20.0.9",                     # only on a DOWN interface
    "8.8.8.8",
    "100.63.255.255",                 # just outside Tailscale's range
    "not-an-address",
    "",
]


@pytest.mark.parametrize("ip", TRUSTED)
def test_trusted_sources(ip):
    assert _plugin()._client_trusted(ip) is True, ip


@pytest.mark.parametrize("ip", REFUSED)
def test_refused_sources(ip):
    assert _plugin()._client_trusted(ip) is False, ip


def test_extra_networks_are_trusted():
    p = _plugin(extra="192.168.2.0/24")
    assert p._client_trusted("192.168.2.7") is True
    assert p._client_trusted("10.0.0.5") is False


def test_networks_are_cached_not_read_per_request():
    p = _plugin()
    for _ in range(20):
        p._client_trusted("192.168.1.25")
    assert len(p._calls) == 1


def test_changing_the_setting_takes_effect_at_once():
    p = _plugin()
    assert p._client_trusted("192.168.2.7") is False
    p._set_trusted_subnets("192.168.2.0/24")
    assert p._client_trusted("192.168.2.7") is True


def test_failure_falls_back_to_loopback_and_tailscale_and_warns_once():
    p = _plugin(ifconfig=OSError("no ifconfig"))
    assert p._client_trusted("127.0.0.1") is True
    assert p._client_trusted("100.101.102.103") is True
    assert p._client_trusted("192.168.1.25") is False
    p._trusted_nets_cache = None                 # force a second derivation
    assert p._client_trusted("192.168.1.25") is False
    warnings = [c for c in p.logger.warning.call_args_list]
    assert len(warnings) == 1, warnings
    text = warnings[0].args[0]
    assert "Extra trusted networks" in text


def test_no_lan_address_found_also_falls_back():
    only_loopback = IFCONFIG.split("gif0")[0]
    p = _plugin(ifconfig=only_loopback, extra="192.168.2.0/24")
    assert p._client_trusted("192.168.1.25") is False
    assert p._client_trusted("192.168.2.7") is True      # extras still apply
    assert p.logger.warning.call_count == 1


# ── Configure validation ───────────────────────────────────────────────────
def test_validate_prefs_accepts_blank_and_good():
    p = bare_plugin()
    for good in ("", "192.168.2.0/24", "192.168.2.0/24, 10.1.0.0/16"):
        ok, values = p.validatePrefsConfigUi({"trustedSubnets": good})[:2]
        assert ok is True, good


def test_validate_prefs_refuses_bad_entries():
    p = bare_plugin()
    for bad in ("banana", "192.168.2.0/24, 0.0.0.0/0", "300.1.1.1/24"):
        res = p.validatePrefsConfigUi({"trustedSubnets": bad})
        assert res[0] is False, bad
        assert "trustedSubnets" in res[2]


def test_setting_is_in_plugin_config():
    import xml.etree.ElementTree as ET
    import os
    from conftest import SP
    root = ET.parse(os.path.join(SP, "PluginConfig.xml")).getroot()
    field = [f for f in root.iter("Field") if f.get("id") == "trustedSubnets"]
    assert field and field[0].get("type") == "textfield"
    assert (field[0].get("defaultValue") or "") == ""


# ── the proxy uses the narrow test everywhere ──────────────────────────────
def _start_proxy_source():
    return textwrap.dedent(inspect.getsource(cameras_mixin.CamerasMixin._start_proxy))


def test_no_route_uses_the_wide_private_test():
    src = _start_proxy_source()
    assert "is_private" not in src
    assert "_client_is_private" not in src


def test_every_credential_route_checks_the_source():
    src = _start_proxy_source()
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_client_is_trusted"]
    # /webrtc POST, /guest-bootstrap, /guest/*, /bootstrap
    assert len(calls) == 4


def test_handler_delegates_to_the_plugin_decision():
    src = _start_proxy_source()
    tree = ast.parse(src)
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "_client_is_trusted"]
    assert fn, "_client_is_trusted not defined on the handler"
    inner = ast.unparse(fn[0])
    assert "plugin_self._client_trusted" in inner
    assert "client_address" in inner
