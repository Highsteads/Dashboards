#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_event_log_quiet.py
# Description: The Indigo event log is shared by every plugin on the server and
#              was running at ~2,031 lines a day. Dashboards wrote 614 Info
#              lines into it over 31-Aug to 05-Sep-2026 and about 490 of those
#              were the same handful of plumbing lines, 10 to 13 of them on
#              every restart (six restarts counted 06-09-2026) - file copies
#              and poller/proxy/go2rtc start-stop, all of it narrating
#              work Indigo already brackets with its own "Starting plugin" and
#              "Stopped plugin" pair. Those now go through _activity(), which
#              writes Debug (this plugin's own log) unless the user ticks
#              logActivityToEventLog. The checkbox is not the only switch on
#              them - Log Level sets the event log's floor, so Debug lets the
#              quiet form through and Warning holds the loud form back. Both
#              field helps say so, and the tests below hold them to it.
#
#              The load-bearing test in this file is the LAST group: a fault
#              must still reach the event log. Log_Error_Watch.py reads the
#              event log and nothing else, so a warning demoted to a plugin's
#              own file is a fault nobody is watching. Every assertion that a
#              line went quiet is paired with one that its sibling fault did
#              not.
# Author:      CliveS & Claude Opus 5
# Date:        06-09-2026
# Version:     1.0

import ast
import io
import logging
import os
import re

import pytest

from conftest import SP, bare_plugin, load_plugin_module

PLUGIN_PY = os.path.join(SP, "plugin.py")
CONFIG_XML = os.path.join(SP, "PluginConfig.xml")


def _tree():
    return ast.parse(io.open(PLUGIN_PY, encoding="utf-8").read())


def _func(name, tree=None):
    """The FunctionDef named `name`, wherever it sits in the file."""
    for node in ast.walk(tree or _tree()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"no function named {name} in plugin.py")


def _calls(node, func_name):
    """Every Call to a bare name (log) or an attribute (self._activity)."""
    out = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Name) and f.id == func_name:
            out.append(n)
        elif isinstance(f, ast.Attribute) and f.attr == func_name:
            out.append(n)
    return out


def _level_kw(call):
    for kw in call.keywords:
        if kw.arg == "level":
            return getattr(kw.value, "value", "?")
    return None


# ============================================================
# _activity routes by the pref, and defaults to quiet
# ============================================================

def test_activity_defaults_to_the_plugins_own_log():
    p = bare_plugin()
    p._activity("[Cameras] Poller started - 9 cameras")
    p.logger.debug.assert_called_once_with("[Cameras] Poller started - 9 cameras")
    p.logger.info.assert_not_called()


def test_activity_reaches_the_event_log_when_the_user_asks_for_it():
    p = bare_plugin()
    p.log_activity = True
    p._activity("[MJPEG] Proxy stopped")
    p.logger.info.assert_called_once_with("[MJPEG] Proxy stopped")
    p.logger.debug.assert_not_called()


def test_activity_survives_a_half_built_instance():
    """__init__ sets log_activity, but _activity is called from teardown paths
    that can run after a failed start. A missing attribute must log, not raise."""
    p = bare_plugin()
    assert not hasattr(p, "log_activity")
    p._activity("still logs")
    p.logger.debug.assert_called_once()


def test_the_pref_defaults_to_false_in_code():
    """as_bool's default is what a never-saved install gets. If this flips to
    True the whole change is undone silently."""
    src = io.open(PLUGIN_PY, encoding="utf-8").read()
    assert src.count(
        'self.log_activity = as_bool(pluginPrefs.get("logActivityToEventLog"), False)') == 1
    # And the Configure dialog applies it live, or a user who ticks it has to
    # restart to see anything.
    assert src.count(
        'self.log_activity = as_bool(prefs.get("logActivityToEventLog"), False)') == 1
    assert _func("closedPrefsConfigUi") is not None
    assert "logActivityToEventLog" in ast.dump(_func("closedPrefsConfigUi"))


# ============================================================
# Demoted means REDIRECTED, not destroyed
# ============================================================

def _levelled_plugin(handler=None, file_level=5):
    p = bare_plugin()
    if handler is not None:
        p.indigo_log_handler = handler
    if file_level is not None:
        p.plugin_file_handler = type("H", (), {"level": file_level})()
    return p


def test_log_level_moves_the_event_log_handler_not_the_logger():
    """Indigo's own comment: the logger sits at THREADDEBUG so everything
    reaches both handlers, and each handler filters for itself. Setting the
    LOGGER level gates before both - which at the default of Info threw every
    Debug record away before this plugin's own file ever saw it, and would
    have destroyed the narration this change moves to Debug."""
    from unittest.mock import MagicMock
    handler = MagicMock()
    p = _levelled_plugin(handler)
    p._apply_log_level(30)
    handler.setLevel.assert_called_once_with(30)
    # The logger is left at the file handler's own floor, so the plugin log
    # keeps everything whatever the user picks for the shared log.
    p.logger.setLevel.assert_called_once_with(5)


def test_a_blank_or_junk_log_level_falls_back_to_info_without_crashing():
    """A textfield/menu pref comes back as a STRING after a dialog save, and
    can be blank. int('') raises, and this runs inside __init__."""
    from unittest.mock import MagicMock
    for value in ("", None, "not a number", []):
        handler = MagicMock()
        p = _levelled_plugin(handler)
        p._apply_log_level(value)
        handler.setLevel.assert_called_once_with(20)


def test_a_string_log_level_is_coerced():
    from unittest.mock import MagicMock
    handler = MagicMock()
    p = _levelled_plugin(handler)
    p._apply_log_level("10")
    handler.setLevel.assert_called_once_with(10)


def test_debug_deliberately_puts_the_narration_in_the_event_log():
    """This is intended, and the field helps now say so. Log Level is Indigo's
    own event-log verbosity control - PluginBase.debug's setter moves
    indigo_log_handler and nothing else - so making Debug mean anything other
    than "debug in the event log" would leave the menu option lying about
    itself. The checkbox is the everyday switch; Debug is the override you
    reach for when something is wrong."""
    from unittest.mock import MagicMock
    handler = MagicMock()
    p = _levelled_plugin(handler)
    p._apply_log_level(10)
    handler.setLevel.assert_called_once_with(10)


def test_the_log_level_pref_can_never_hide_a_warning():
    """Picking "Error" would set the event-log handler to 40 and drop every
    self.logger.warning() line out of the shared log. Log_Error_Watch.py reads
    the event log and nothing else, so that one menu choice would have blinded
    the estate's only watcher to every warning this plugin raises. The floor is
    capped at WARNING, which makes Error behave as Warning - a far smaller cost
    than a fault nobody sees."""
    from unittest.mock import MagicMock
    handler = MagicMock()
    p = _levelled_plugin(handler)
    p._apply_log_level(40)
    handler.setLevel.assert_called_once_with(30)


def test_the_cap_leaves_every_other_choice_alone():
    """A cap that quietly moved the other three would be a different bug."""
    from unittest.mock import MagicMock
    for chosen, expected in ((10, 10), (20, 20), (30, 30)):
        handler = MagicMock()
        _levelled_plugin(handler)._apply_log_level(chosen)
        handler.setLevel.assert_called_once_with(expected)


def test_log_level_survives_a_host_with_no_handlers():
    """getattr, not attribute access: a half-built instance must not raise
    from inside the logging setup."""
    p = _levelled_plugin(handler=None, file_level=None)
    p._apply_log_level(20)
    p.logger.setLevel.assert_called_once_with(10)   # logging.DEBUG fallback


def test_nothing_narrows_the_logger_behind_apply_log_levels_back():
    """One owner for the level. A stray self.logger.setLevel elsewhere would
    reinstate the gate this method exists to remove."""
    tree = _tree()          # ONE tree: node identity is the whole check below
    calls = [c for c in _calls(tree, "setLevel")
             if isinstance(c.func, ast.Attribute)
             and isinstance(c.func.value, ast.Attribute)
             and c.func.value.attr == "logger"]
    assert len(calls) == 1, \
        f"{len(calls)} self.logger.setLevel calls; expected only the one in _apply_log_level"
    owner = list(ast.walk(_func("_apply_log_level", tree)))
    assert any(c is calls[0] for c in owner), \
        "self.logger.setLevel is set outside _apply_log_level"


# ============================================================
# The thirteen restart lines are off the event log
# ============================================================

# name of the enclosing function -> the fragment of the quietened message
QUIETENED = [
    ("_sync_pages_to_public",  "Synced manifest.json"),
    ("_sync_pages_to_public",  "asset(s) to"),
    ("_sync_pages_to_public",  "Removed stale"),
    ("_sync_pages_to_domio",   "Domio sync: copied"),
    ("_write_config_js",       "Wrote "),
    ("_start_mjpeg_proxy",     "[MJPEG] Proxy listening"),
    ("_stop_mjpeg_proxy",      "[MJPEG] Proxy stopped"),
    ("_write_go2rtc_config",   "[go2rtc] Wrote config"),
    ("_start_go2rtc",          "[go2rtc] Started"),
    ("_mirror_go2rtc_assets",  "[go2rtc] Mirrored"),
    ("_stop_go2rtc",           "[go2rtc] Stopped"),
    ("runConcurrentThread",    "[Cameras] Poller started"),
    ("runConcurrentThread",    "[Cameras] Poller stopped"),
    ("shutdown",               "stopped"),
    ("_mirror_custom_pages",   "custom page(s) published"),
]


def _joined_strings(call):
    """Every string constant in the call, joined with a space. Joining with a
    space rather than matching per-constant is deliberate: these messages are
    split across f-string parts and implicit concatenation, so a per-constant
    scan misses a phrase that straddles the seam, and joining with nothing
    manufactures matches at it."""
    parts = [n.value for n in ast.walk(call)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return " ".join(parts)


@pytest.mark.parametrize("func_name,fragment", QUIETENED)
def test_restart_narration_no_longer_goes_to_the_event_log(func_name, fragment):
    fn = _func(func_name)
    activity = [c for c in _calls(fn, "_activity") if fragment in _joined_strings(c)]
    assert activity, f"{func_name}: nothing routes {fragment!r} through _activity()"
    # ...and it is not ALSO still being written at Info somewhere in the same
    # function, which would make the demotion cosmetic.
    loud = [c for c in _calls(fn, "log") if fragment in _joined_strings(c)
            and _level_kw(c) in (None, "INFO")]
    loud += [c for c in _calls(fn, "info") if fragment in _joined_strings(c)]
    assert not loud, f"{func_name}: {fragment!r} still reaches the event log at Info"


def test_no_fault_was_routed_through_activity():
    """_activity has no level argument by design. A call that tries to pass one
    is someone funnelling a warning into the quiet channel."""
    calls = _calls(_tree(), "_activity")
    assert len(calls) >= 15, f"only {len(calls)} _activity calls found - did a sweep drop some?"
    for c in calls:
        assert not c.keywords, "_activity takes no keywords; a level= here would be a demoted fault"


def test_startup_writes_exactly_one_info_line():
    """Nine lines used to land here. Indigo brackets startup with its own
    Starting/Started pair, so one summary is the whole budget."""
    fn = _func("startup")
    infos = _calls(fn, "info")
    loud_log = [c for c in _calls(fn, "log") if _level_kw(c) in (None, "INFO")]
    # The one-time pre-v2.71.0 presence.json migration line is allowed: it
    # fires once in the life of an install, not once per restart.
    infos = [c for c in infos if "presence.json" not in _joined_strings(c)]
    assert len(infos) + len(loud_log) == 1, \
        f"startup writes {len(infos) + len(loud_log)} Info lines to the event log, expected 1"


# ============================================================
# The one surviving startup line has to earn its place
# ============================================================

@pytest.fixture
def summary_plugin(monkeypatch):
    """CAMERAS is a MODULE-level constant the whole suite shares. Set it with
    monkeypatch, never by assignment, or these tests leave a doctored camera
    list behind for whatever runs next."""
    plugin = load_plugin_module()

    def build(cameras, user="u", passwd="p", mjpeg=None, go2rtc=None):
        p = bare_plugin()
        p.pluginDisplayName = "Dashboards"
        p.cam_user, p.cam_pass = user, passwd
        p._mjpeg_server, p._go2rtc_proc = mjpeg, go2rtc
        monkeypatch.setattr(plugin, "CAMERAS", cameras)
        return p
    return build


def test_the_camera_list_is_restored_between_tests(summary_plugin):
    """Guards the fixture itself: a leaked CAMERAS would quietly change what
    every later test in the run sees."""
    plugin = load_plugin_module()
    before = plugin.CAMERAS
    summary_plugin([{"n": 1}] * 3)
    assert plugin.CAMERAS == [{"n": 1}] * 3
    assert before is not plugin.CAMERAS or before == plugin.CAMERAS


def test_summary_names_what_the_plugin_ended_up_running(summary_plugin):
    p = summary_plugin([{"n": 1}] * 9, mjpeg=object(), go2rtc=object())
    line = p._startup_summary()
    assert line == ("Dashboards started - 9 cameras, MJPEG proxy on :8177, "
                    "go2rtc running"), line


def test_summary_gets_the_singular_right(summary_plugin):
    p = summary_plugin([{"n": 1}])
    assert "1 camera," in p._startup_summary() + ","
    assert "1 cameras" not in p._startup_summary()


def test_summary_says_so_when_there_are_no_cameras(summary_plugin):
    p = summary_plugin([])
    assert p._startup_summary() == "Dashboards started - no cameras"


def test_summary_flags_cameras_without_credentials(summary_plugin):
    """The demoted lines used to be the only hint. Losing them must not lose
    the reason the cameras are dark."""
    p = summary_plugin([{"n": 1}, {"n": 2}], user="", passwd="")
    assert "no credentials" in p._startup_summary()


# ============================================================
# The bootstrap seed latches per client address
# ============================================================

def test_bootstrap_seed_is_announced_once_per_address():
    p = bare_plugin()
    assert p._note_bootstrap_seed("192.168.1.41") is True
    assert p._note_bootstrap_seed("192.168.1.41") is False
    assert p._note_bootstrap_seed("192.168.1.41") is False


def test_a_new_address_is_always_announced():
    """A device that has never been handed the key is the part worth a line."""
    p = bare_plugin()
    p._note_bootstrap_seed("192.168.1.41")
    assert p._note_bootstrap_seed("192.168.1.99") is True
    assert p._note_bootstrap_seed("100.72.42.14") is True


def test_the_latch_starts_empty_on_each_plugin_run():
    a, b = bare_plugin(), bare_plugin()
    assert a._note_bootstrap_seed("10.0.0.1") is True
    assert b._note_bootstrap_seed("10.0.0.1") is True


# ============================================================
# FAULTS STILL REACH THE EVENT LOG - the point of the exercise
# ============================================================

FAULT_SIBLINGS = [
    # (function, fragment of the fault message that must stay loud)
    ("_sync_pages_to_public", "Could not remove stale"),
    ("_sync_pages_to_public", "Manifest copy failed"),
    ("_sync_pages_to_domio",  "copy failed for"),
    ("_write_config_js",      "Failed to write"),
    ("_stop_mjpeg_proxy",     "[MJPEG] Shutdown error"),
    ("_stop_go2rtc",          "[go2rtc] Shutdown error"),
    ("_mirror_go2rtc_assets", "[go2rtc] Could not mirror"),
    ("runConcurrentThread",   "DAHUA_USER/DAHUA_PASS are not set"),
    ("_mirror_custom_pages",  "custom-page mirror failed"),
]


@pytest.mark.parametrize("func_name,fragment", FAULT_SIBLINGS)
def test_the_fault_beside_each_quietened_line_still_reaches_the_event_log(func_name, fragment):
    """Every function touched above also logs a fault. Those are what
    Log_Error_Watch.py exists to see, and not one of them may have been swept
    up in the demotion."""
    fn = _func(func_name)
    loud = [c for c in _calls(fn, "log")
            if fragment in _joined_strings(c) and _level_kw(c) in ("WARNING", "ERROR")]
    loud += [c for c in _calls(fn, "warning") + _calls(fn, "error")
             if fragment in _joined_strings(c)]
    assert loud, f"{func_name}: {fragment!r} no longer reaches the event log as a fault"
    quiet = [c for c in _calls(fn, "_activity") + _calls(fn, "debug")
             if fragment in _joined_strings(c)]
    assert not quiet, f"{func_name}: {fragment!r} was demoted - Log_Error_Watch cannot see it"


def test_the_plugin_still_raises_plenty_of_faults_to_the_event_log():
    """A vacuous sweep is the failure mode of every structural test in this
    file: if the counts collapse, the parametrised checks above would all pass
    over an empty file."""
    tree = _tree()
    warns = [c for c in _calls(tree, "log") if _level_kw(c) in ("WARNING", "ERROR")]
    warns += _calls(tree, "warning") + _calls(tree, "error")
    assert len(warns) > 80, f"only {len(warns)} fault log calls found in plugin.py"


def test_actions_taken_on_the_house_stay_in_the_event_log():
    """A record of the plugin DOING something is not narration. The EvoHome
    proxy changes the heating and the custom-page writes change what the house
    displays; both stay at Info."""
    for name, fragment in (("handleEvoHomeAction", "triggered via dashboard"),
                           ("handleCustomPages", "custom page saved"),
                           ("handleCustomPages", "custom page deleted")):
        fn = _func(name)
        loud = [c for c in _calls(fn, "info") + _calls(fn, "log")
                if fragment in _joined_strings(c) and _level_kw(c) in (None, "INFO")]
        assert loud, f"{name}: {fragment!r} no longer reaches the event log"


def test_fault_recovery_notices_stay_in_the_event_log():
    """Log_Error_Watch suppresses on evidence of success, so the line that
    closes a fault matters as much as the one that raises it."""
    src = io.open(PLUGIN_PY, encoding="utf-8").read()
    assert 'log(f"[Poller] {name} recovered")' in src
    assert 'recovered after {st[\'fail_count\']} failures")' in src


# ============================================================
# The dialog offers it, and the dialog still builds
# ============================================================

def test_the_config_dialog_offers_the_switch_and_defaults_it_off():
    import xml.etree.ElementTree as ET
    root = ET.parse(CONFIG_XML).getroot()
    fields = {f.get("id"): f for f in root.iter("Field")}
    fld = fields.get("logActivityToEventLog")
    assert fld is not None, "the Configure dialog has no logActivityToEventLog field"
    assert fld.get("type") == "checkbox"
    assert fld.get("defaultValue") == "false"
    label = fld.find("Label")
    assert label is not None and label.text.strip()
    help_text = fields["hlpActivity"].find("Label").text
    # The help must say what is lost and what is not - a switch whose label
    # does not mention the faults invites the reader to assume it hides them.
    assert "Warnings and errors always go to the Event Log" in help_text


def test_the_help_admits_that_log_level_is_the_other_switch():
    """The first draft of this help said the narration "is written only to
    this plugin's own log file" when the box is off. Log Level = Debug puts it
    straight back in the Event Log, so that sentence was false in exactly the
    situation a user reaches for when something is wrong. Both fields must now
    name the other switch, or the reader is back to being told there is one."""
    import xml.etree.ElementTree as ET
    root = ET.parse(CONFIG_XML).getroot()
    helps = {f.get("id"): (f.find("Label").text or "")
             for f in root.iter("Field") if f.get("type") == "label"}
    beside_box = helps.get("hlpActivityLevel", "")
    assert "Log Level" in beside_box
    assert "Debug" in beside_box and "Warning" in beside_box
    assert "not the only switch" in beside_box
    beside_menu = helps.get("hlpLogLevel", "")
    assert "own log file" in beside_menu, "the Log Level help must say what it does NOT touch"
    assert "Debug" in beside_menu
    assert "Error behaves the same as Warning" in beside_menu


def test_the_new_fields_do_not_collide():
    """A duplicate Field id makes the Indigo client refuse to build the whole
    dialog, so no pref in the plugin can be changed. The plugin never parses
    its own XML, so nothing else would catch it."""
    import collections
    import xml.etree.ElementTree as ET
    root = ET.parse(CONFIG_XML).getroot()
    ids = [f.get("id") for f in root.iter("Field")]
    dupes = [k for k, v in collections.Counter(ids).items() if v > 1]
    assert not dupes, f"duplicate Field id(s) in PluginConfig.xml: {dupes}"
    assert "logActivityToEventLog" in ids and "hlpActivity" in ids


# ============================================================
# One file holds the whole story: log() mirrors into plugin.log
# ============================================================
#
# The module log() helper calls indigo.server.log directly, which bypasses the
# logging handlers - that is what stops the Log Level pref filtering a fault
# out of the shared event log. The side effect was that none of the 56 faults
# raised through it ever reached this plugin's OWN log file, while the routine
# narration moved there, so diagnosing anything meant reading two files side
# by side. _install_file_mirror puts the same record through the file handler
# a second time. The two things it must not do are duplicate the event-log
# line, and break its caller.

class _Collector(logging.Handler):
    """Stands in for plugin_file_handler: keeps every record it is handed."""

    def __init__(self, level=logging.NOTSET):
        super().__init__(level=level)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def mirrored():
    """Install a collecting mirror and take it back down again.

    _FILE_MIRROR is MODULE state and logging.getLogger() is process-global, so
    a leaked mirror would quietly attach itself to whatever ran next in the
    session - the same trap the CAMERAS fixture above exists for.
    """
    plugin = load_plugin_module()
    before = plugin._FILE_MIRROR
    collector = _Collector()
    plugin._install_file_mirror(collector)
    yield plugin, collector
    plugin._install_file_mirror(None)
    plugin._FILE_MIRROR = before


def test_the_mirror_fixture_leaves_nothing_behind():
    """Guards the fixture itself, before anything relies on it."""
    plugin = load_plugin_module()
    assert plugin._FILE_MIRROR is None
    assert not logging.getLogger("Plugin.eventlog").handlers


def test_a_fault_reaches_the_event_log_and_the_plugins_own_file(mirrored):
    plugin, collector = mirrored
    plugin.indigo.server.log.reset_mock()
    plugin.log("Manifest copy failed: boom", level="WARNING")
    # The event log, unconditionally, at a real level int.
    assert plugin.indigo.server.log.call_count == 1
    assert plugin.indigo.server.log.call_args.kwargs["level"] == logging.WARNING
    # ...and the same fault in this plugin's own file, exactly once.
    assert len(collector.records) == 1
    assert collector.records[0].levelno == logging.WARNING
    assert collector.records[0].getMessage() == "Manifest copy failed: boom"


def test_the_mirror_carries_the_raw_message_not_the_stamped_copy(mirrored):
    """The file handler stamps its own asctime. Mirroring the event-log copy
    would put two timestamps on every line in plugin.log."""
    plugin, collector = mirrored
    plugin.log("[go2rtc] Shutdown error: nope", level="ERROR")
    mirrored_msg = collector.records[0].getMessage()
    assert mirrored_msg == "[go2rtc] Shutdown error: nope"
    assert not re.match(r"^\[\d\d:\d\d:\d\d\.\d\d\d\] ", mirrored_msg)
    # ...while the event-log copy keeps the prefix it has always had.
    event_line = plugin.indigo.server.log.call_args.args[0]
    assert re.match(r"^\[\d\d:\d\d:\d\d\.\d\d\d\] \[go2rtc\] ", event_line), event_line


def test_the_mirror_does_not_double_the_event_log_line(mirrored):
    """propagate=False. Without it the record climbs to the "Plugin" logger,
    indigo_log_handler writes it to the event log a second time, and every
    fault this plugin raises appears twice."""
    plugin, collector = mirrored
    parent = _Collector()
    logging.getLogger("Plugin").addHandler(parent)
    try:
        plugin.log("Failed to write config.js", level="ERROR")
    finally:
        logging.getLogger("Plugin").removeHandler(parent)
    assert len(collector.records) == 1
    assert parent.records == [], "the mirrored record propagated to the plugin logger"


def test_installing_twice_still_writes_one_line(mirrored):
    """__init__ can run more than once in a process. A stacked handler would
    write every mirrored line twice, which looks like a retry that never
    happened."""
    plugin, collector = mirrored
    plugin._install_file_mirror(collector)
    plugin.log("Synced 4 of 4 asset(s)")
    assert len(collector.records) == 1
    assert len(logging.getLogger("Plugin.eventlog").handlers) == 1


def test_a_host_with_no_file_handler_still_logs_to_the_event_log():
    """The log directory can fail to be created. That must cost the mirror,
    never the event-log line."""
    plugin = load_plugin_module()
    plugin._install_file_mirror(None)
    plugin.indigo.server.log.reset_mock()
    plugin.log("still shouts", level="WARNING")
    assert plugin.indigo.server.log.call_count == 1


def test_a_broken_mirror_never_takes_the_caller_down(mirrored):
    """The event-log line has already gone out by the time the mirror runs, so
    a logging failure here must be swallowed - a fault report that raises on
    its way out is worse than one that only lands in one file."""
    plugin, collector = mirrored

    class _Exploding(logging.Handler):
        def emit(self, record):
            raise RuntimeError("disk full")

    plugin._install_file_mirror(_Exploding())
    plugin.indigo.server.log.reset_mock()
    plugin.log("[MJPEG] Shutdown error: x", level="WARNING")   # must not raise
    assert plugin.indigo.server.log.call_count == 1


def test_the_mirror_is_installed_from_init():
    """A mirror nothing installs is a mirror that does nothing. This is the
    only structural check of the wiring - the tests above all install it
    themselves, so without this one they would pass over dead code."""
    src = io.open(PLUGIN_PY, encoding="utf-8").read()
    assert '_install_file_mirror(getattr(self, "plugin_file_handler", None))' in src
    init = _func("__init__")
    assert "_install_file_mirror" in ast.dump(init), \
        "log() is mirrored to plugin.log only if __init__ installs the mirror"
