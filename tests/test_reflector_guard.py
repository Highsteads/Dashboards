#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_reflector_guard.py
# Description: Every browser-facing handler refuses the reflector when the
#              owner has asked for that, and every handler that reads a body
#              answers a JSON list with a 400 rather than a 500 (v3.25.0).
#              The spring-clean review found 11 of 22 handlers skipping the
#              refusal while the docstring claimed all of them did, and four
#              raising AttributeError on a list body. The handler list comes
#              from Actions.xml, so a new endpoint is covered the day it lands.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
import inspect
import re
from pathlib import Path

import pytest

from conftest import load_plugin_module

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ROOT / "Dashboards.indigoPlugin/Contents/Server Plugin/Actions.xml"

# Not an HTTP endpoint: it answers any IWS request with a 404 before doing
# anything, and is called plugin-to-plugin by an MCP server.
NOT_HTTP = {"handle_mcp_tool_invoke"}


def _callbacks():
    xml = ACTIONS.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"<CallbackMethod>\s*(\w+)\s*</CallbackMethod>", xml)))


class _Action:
    def __init__(self, headers, body="{}"):
        self.props = {"headers": headers, "request_body": body}


def _plugin(block=True):
    mod = load_plugin_module()
    p = mod.Plugin.__new__(mod.Plugin)
    from unittest.mock import MagicMock
    p.logger = MagicMock()
    p.lan_ip = "192.168.1.10"
    p._reflector_host = "myhouse.indigodomo.net"
    p.pluginPrefs = {"reflectorBlock": block}
    seen = []
    p._evo_reply = lambda obj, status=200: seen.append((status, obj)) or {"status": status, "obj": obj}
    return p, seen


REFLECTOR = {"X-Forwarded-For": "51.0.0.1", "User-Agent": "Mozilla/5.0 (iPhone)"}
# As a page sends it: every page POSTs application/json, and the handlers
# that change something refuse anything else (3.46.0, test_csrf_json_only.py).
LAN = {"Host": "192.168.1.10:8176", "User-Agent": "Mozilla/5.0 (iPhone)",
       "Content-Type": "application/json"}


def test_the_handler_list_is_not_vacuous():
    names = _callbacks()
    assert len(names) >= 20, names
    mod = load_plugin_module()
    missing = [n for n in names if not hasattr(mod.Plugin, n)]
    assert not missing, f"Actions.xml names callbacks plugin.py lacks: {missing}"


@pytest.mark.parametrize("name", [n for n in _callbacks() if n not in NOT_HTTP])
def test_every_handler_refuses_the_reflector(name):
    p, seen = _plugin(block=True)
    reply = getattr(p, name)(_Action(REFLECTOR))
    assert reply is not None and reply["status"] == 403, f"{name} answered {reply}"
    assert reply["obj"].get("reason") == "reflector_blocked"


def _body_handlers():
    mod = load_plugin_module()
    return [n for n in _callbacks() if n not in NOT_HTTP
            and "_request_body(" in inspect.getsource(getattr(mod.Plugin, n))]


def test_body_handlers_are_found():
    # Ten of them read a body; if this drops, the parametrised test below is
    # quietly checking fewer handlers than it did.
    assert len(_body_handlers()) >= 10, _body_handlers()


@pytest.mark.parametrize("name", _body_handlers())
def test_a_json_list_body_is_a_400_not_a_500(name):
    p, seen = _plugin(block=False)
    reply = getattr(p, name)(_Action(LAN, body="[1, 2, 3]"))
    assert reply["status"] == 400, f"{name} answered {reply}"
    assert "JSON object" in reply["obj"]["error"]


@pytest.mark.parametrize("name", _body_handlers())
def test_broken_json_is_a_400(name):
    p, seen = _plugin(block=False)
    reply = getattr(p, name)(_Action(LAN, body="{not json"))
    assert reply["status"] == 400 and "bad JSON" in reply["obj"]["error"], f"{name} answered {reply}"
