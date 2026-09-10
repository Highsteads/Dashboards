#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_mcp_manifest.py
# Description: The plugin-provided MCP tool contract (v3.12.0), checked from
#              the files as shipped. Contents/Resources/mcp-manifest.json must
#              satisfy the provider-manifest v1 rules an MCP server applies
#              (manifest_version 1, provider id = CFBundleIdentifier, tool
#              names ^[a-z][a-z0-9_]{0,40}$ and unique, object inputSchemas,
#              explicit write flags, timeouts in 5-120), Actions.xml must
#              declare the invoke action the manifest names, plugin.py must
#              implement its callback and broadcast on startup, and every
#              manifest tool must have a handler in mcp_tools — and vice versa.
#              A tool listed to the AI without a handler, or handled without
#              being listed, is exactly the drift this file exists to stop.
# Author:      CliveS & Claude Fable 5.1
# Date:        10-09-2026
# Version:     1.0

import ast
import json
import plistlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from conftest import load_plugin_module

ROOT     = Path(__file__).resolve().parents[1]
BUNDLE   = ROOT / "Dashboards.indigoPlugin"
MANIFEST = BUNDLE / "Contents" / "Resources" / "mcp-manifest.json"
ACTIONS  = BUNDLE / "Contents" / "Server Plugin" / "Actions.xml"
PLUGIN   = BUNDLE / "Contents" / "Server Plugin" / "plugin.py"
PLIST    = BUNDLE / "Contents" / "Info.plist"

TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
PREFIX_RE    = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


@pytest.fixture(scope="module")
def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_is_version_1_for_the_bundles_own_plugin_id(manifest):
    assert manifest["manifest_version"] == 1
    bundle_id = plistlib.loads(PLIST.read_bytes())["CFBundleIdentifier"]
    assert manifest["provider"]["plugin_id"] == bundle_id, (
        "a server rejects the whole manifest when provider.plugin_id differs from "
        "the bundle it was found in (spoof guard)")
    assert manifest["provider"]["display_name"]


def test_prefix_is_declared_valid_and_matches_the_derived_default(manifest):
    # The default is the last dot-segment of the plugin id, snake-cased. We
    # declare it explicitly so the exposed names are stable in documentation
    # even if the derivation rule ever changes; the two must agree today.
    prefix = manifest["tool_prefix"]
    assert PREFIX_RE.match(prefix)
    derived = manifest["provider"]["plugin_id"].rsplit(".", 1)[-1].lower()
    assert prefix == derived == "dashboards"
    assert manifest.get("invoke_action_id", "mcp_tool_invoke") == "mcp_tool_invoke"


def test_every_tool_satisfies_the_v1_field_rules(manifest):
    tools = manifest["tools"]
    assert tools, "tools must be a non-empty array"
    names = [t["name"] for t in tools]
    assert len(names) == len(set(names)), "tool names must be unique within the manifest"
    for t in tools:
        assert TOOL_NAME_RE.match(t["name"]), t["name"]
        assert t["description"].strip(), t["name"]
        assert isinstance(t["write"], bool), f"{t['name']}: write must be an explicit bool"
        assert 5 <= t["timeout_seconds"] <= 120, t["name"]
        schema = t["inputSchema"]
        assert schema["type"] == "object", t["name"]
        props = schema.get("properties", {})
        assert set(schema.get("required", [])) <= set(props), (
            f"{t['name']}: required names a property the schema does not declare")


def test_descriptions_say_read_only_or_name_the_side_effect(manifest):
    """The AI decides from the description alone whether a call is safe to
    make without asking. Every read says so; every write names what it saves."""
    for t in manifest["tools"]:
        d = t["description"]
        if t["write"]:
            assert "dashboards_config.json" in d, f"{t['name']}: a write must say what it saves"
        else:
            assert "Read-only" in d, f"{t['name']}: a read must say it is read-only"


def test_manifest_and_mcp_tools_agree_on_the_tool_set(manifest):
    import importlib
    load_plugin_module()          # puts Server Plugin/ on sys.path (idempotent)
    mcp_tools = importlib.import_module("mcp_tools")
    listed  = [t["name"] for t in manifest["tools"]]
    handled = list(mcp_tools.TOOLS)
    assert listed == handled, "manifest order and mcp_tools.TOOLS must be identical"
    assert set(mcp_tools.HANDLERS) == set(handled)
    for name in handled:
        assert callable(mcp_tools.HANDLERS[name])


def test_actions_xml_declares_the_hidden_invoke_action(manifest):
    root = ET.parse(ACTIONS).getroot()
    action_id = manifest.get("invoke_action_id", "mcp_tool_invoke")
    hits = [a for a in root.iter("Action") if a.get("id") == action_id]
    assert len(hits) == 1, f"exactly one <Action id={action_id!r}> expected"
    a = hits[0]
    assert a.get("uiPath") == "hidden", "the invoke action must stay out of the action picker"
    assert a.findtext("CallbackMethod") == "handle_mcp_tool_invoke"


def test_plugin_implements_the_callback_and_broadcasts_on_startup():
    plugin = load_plugin_module()
    assert callable(getattr(plugin.Plugin, "handle_mcp_tool_invoke", None))
    tree = ast.parse(PLUGIN.read_text(encoding="utf-8"))
    startup = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "startup")
    guarded = False
    for node in ast.walk(startup):
        if isinstance(node, ast.Try):
            for call in ast.walk(node):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "broadcastToSubscribers"
                        and call.args and isinstance(call.args[0], ast.Constant)
                        and call.args[0].value == "mcp_tools_updated"):
                    guarded = True
    assert guarded, ('startup() must call indigo.server.broadcastToSubscribers('
                     '"mcp_tools_updated") inside a try, so it can never affect startup')


def test_mcp_tools_is_imported_lazily_not_at_module_level():
    """A fault in the tool module must not be able to stop the plugin starting."""
    tree = ast.parse(PLUGIN.read_text(encoding="utf-8"))
    top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    for n in top_level:
        names = [a.name for a in n.names] + ([n.module] if isinstance(n, ast.ImportFrom) else [])
        assert "mcp_tools" not in names, "mcp_tools must be imported inside the callback only"
    handler = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "handle_mcp_tool_invoke")
    inner = [n for n in ast.walk(handler) if isinstance(n, ast.Import)
             and any(a.name == "mcp_tools" for a in n.names)]
    assert inner, "handle_mcp_tool_invoke must import mcp_tools itself"
