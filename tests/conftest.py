#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    conftest.py
# Description: Shared test harness for the Dashboards plugin — mock-imports
#              plugin.py outside the Indigo host (stubs `indigo` + optional deps)
#              so its pure helpers can be unit-tested. Seed of the plugin's test
#              suite (v2.36.0); Stage 4 of the deep review builds it out.
# Author:      CliveS & Claude Fable 5
# Date:        15-07-2026
# Version:     1.0

import os
import sys
import types
from unittest.mock import MagicMock

SP = os.path.join(os.path.dirname(__file__), "..",
                  "Dashboards.indigoPlugin", "Contents", "Server Plugin")


def load_plugin_module():
    """Import the plugin.py module with `indigo` and optional third-party deps
    stubbed, returning the module object. Safe to call repeatedly."""
    if "plugin" in sys.modules:
        return sys.modules["plugin"]

    ind = types.ModuleType("indigo")

    class _PluginBase:
        # The real PluginBase raises StopThread from INSIDE sleep() once
        # stopConcurrentThread has set the flag — nothing else in the loop
        # ever sees it. Mirrored here (v2.95.1) so runConcurrentThread can be
        # driven under test and a regression that drops the re-raise, or
        # waits on something other than self.sleep(), turns a test red rather
        # than force-killing the host on the next upgrade.
        class StopThread(Exception):
            pass

        def __init__(self, *a, **k):
            self.pluginPrefs = {}
            self.logger = MagicMock()
            self.stopThread = False
            self.stop_thread = False

        def sleep(self, _s):
            if self.stopThread or self.stop_thread:
                raise self.StopThread()

        def stopConcurrentThread(self):
            self.stopThread = True
            self.stop_thread = True
    ind.PluginBase = _PluginBase
    ind.Dict = dict
    ind.List = list
    for attr in ("server", "devices", "variables", "kStateImageSel",
                 "kDeviceAction", "activePlugin", "actionGroup", "trigger"):
        setattr(ind, attr, MagicMock())
    sys.modules["indigo"] = ind

    # Optional third-party libs the plugin imports at module or method level.
    for name in ("requests",):
        sys.modules.setdefault(name, MagicMock())

    # Stub IndigoSecrets BEFORE plugin.py imports it. Without this the suite
    # ran against the developer's REAL credentials and camera list — tests
    # passed locally that would fail anywhere else, and a test that ever
    # exercised a network path would have used live secrets. An empty module
    # exercises exactly what a fresh install sees.
    sys.modules.setdefault("IndigoSecrets", types.ModuleType("IndigoSecrets"))

    sys.path.insert(0, os.path.abspath(SP))
    import plugin  # noqa: E402  (import after stubs by design)
    return plugin


def redirect_pages(pages_dir):
    """Pages kept only to forward an old address (v3.33.0): presence.html,
    history.html and activity.html now open a Timeline view, and so on. They
    carry no header, no page notes and do not count as pages."""
    from pathlib import Path
    return {p.name for p in Path(pages_dir).glob("*.html")
            if 'http-equiv="refresh"' in p.read_text(encoding="utf-8")}


def plugin_source_files():
    """Every module the Plugin class is built from (v3.32.0): plugin.py, the
    *_mixin.py files it inherits, and dash_common.py / dash_util.py. A test
    that reads the plugin's source reads all of them."""
    import glob
    here = os.path.abspath(SP)
    return ([os.path.join(here, "plugin.py")]
            + sorted(glob.glob(os.path.join(here, "*_mixin.py")))
            + [os.path.join(here, "dash_common.py"), os.path.join(here, "dash_util.py")])


def plugin_source():
    """The text of plugin_source_files(), joined — still one valid module."""
    return "\n\n".join(open(f, encoding="utf-8").read() for f in plugin_source_files())


def bare_plugin():
    """A Plugin instance built WITHOUT running __init__ (which reads secrets,
    builds the config store, starts services). Instance methods that only read
    class-level attributes + their arguments (e.g. _classify_device) work on it.
    Attach only what a given method actually touches."""
    plugin = load_plugin_module()
    p = plugin.Plugin.__new__(plugin.Plugin)
    p.logger = MagicMock()
    return p


class _FakeDevBase:
    """Attribute bag standing in for an Indigo device object."""

    def __init__(self, name="", deviceTypeId="", supportsOnState=False,
                 states=None, batteryLevel=None, folderId=0, dev_id=0):
        self.name = name
        self.deviceTypeId = deviceTypeId
        self.supportsOnState = supportsOnState
        self.states = states if states is not None else {}
        self.batteryLevel = batteryLevel
        self.folderId = folderId
        self.id = dev_id


# Cache one dynamically-named subclass per device-class name so that
# dev.__class__.__name__ (which _classify_device reads to tell a DimmerDevice /
# RelayDevice from a plain sensor) reports the right thing.
_FAKE_DEV_CLASSES = {}


def FakeDev(name="", deviceTypeId="", cls="Device", supportsOnState=False,
            states=None, batteryLevel=None, folderId=0, dev_id=0):
    """Build a device stand-in whose class name is `cls` (e.g. 'DimmerDevice',
    'RelayDevice', 'z2mSensor'), carrying only the attributes the tested helpers
    read."""
    klass = _FAKE_DEV_CLASSES.get(cls)
    if klass is None:
        klass = type(cls, (_FakeDevBase,), {})
        _FAKE_DEV_CLASSES[cls] = klass
    return klass(name=name, deviceTypeId=deviceTypeId,
                 supportsOnState=supportsOnState, states=states,
                 batteryLevel=batteryLevel, folderId=folderId, dev_id=dev_id)
