#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_log_error_watch_cause_read.py
# Description: Log_Error_Watch 2.2's two changes, through the real main() against a stub Indigo,
#              a fixed clock and a temporary folder. (1) Causes are read back further than
#              alerts: the rows that can explain an error are read from the alert window's start
#              less the longest EXPLAINED_BY window, from the event-log buffer or, where the
#              buffer is short, the dated log files; alerts still come only from the window.
#              (2) A signature a rule has excused, never alerted, that comes back
#              unexplained with fresh occurrences is new news; old occurrences alone page
#              nothing, and the fact that a rule excused it outlives a run that cannot see
#              the cause. An alerted signature keeps the 24-hour re-alert rule. Uses only
#              made-up rules and lines, so it ships beside the script. Works beside
#              Log_Error_Watch.py (a repo's scripts/) or one folder below it (the house's
#              tests/).
# Author:      CliveS & Claude Opus 5.5
# Date:        20-11-2026 00:39 GMT; 20-11-2026 01:12 GMT review round 1: the kept excuse,
#              counts on the file fill, midnight, a rule over two hours, the join's stamp,
#              the files line's level
# Version:     1.0

import builtins
import io
import json
import math
import os
import sys
import types
from datetime import datetime as real_datetime, timedelta

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPT = os.path.join(_HERE, "Log_Error_Watch.py")
if not os.path.exists(_SCRIPT):
    _SCRIPT = os.path.join(os.path.dirname(_HERE), "Log_Error_Watch.py")

T0 = real_datetime(2026, 3, 3, 12, 0, 0)
WINDOW = 600                              # the made-up rule's own window, in seconds
CAUSE = "widget work started"
FAILED = "the widget failed"
RULES = (
    "EXPLAINED_BY = [\n"
    f"    ('Tester', r'^{FAILED}$', 'Tester', r'^{CAUSE}$', {WINDOW}, 'widget work'),\n"
    "]\n")


class Watch:
    """The real script against a stub, with the clock, the buffer and the dated files this test
    says. Nothing is sent: Pushover and email are replaced by recorders."""

    def __init__(self, tmp_path, rules=RULES):
        self.rows = []
        self.buffer_from = None
        self.sends = []
        self.logged = []
        self.levels = []
        self.deliver = True
        self.folder = tmp_path / "Indigo"
        (self.folder / "Logs").mkdir(parents=True)
        stub = types.ModuleType("indigo")
        stub.server = types.SimpleNamespace(
            log=lambda msg, *a, **k: (self.logged.append(str(msg)),
                                      self.levels.append((str(msg), k.get("level")))),
            getEventLogList=self._buffer,
            getInstallFolderPath=lambda: str(self.folder),
            getPlugin=lambda _id: None,
            sendEmailTo=lambda *a, **k: None)
        sys.modules["indigo"] = stub
        builtins._log_error_watch_core_only = True
        try:
            self.w = types.ModuleType("log_error_watch_cause_read")
            self.w.__dict__["indigo"] = stub
            with io.open(_SCRIPT, encoding="utf-8") as fh:
                exec(compile(fh.read(), _SCRIPT, "exec"), self.w.__dict__)
        finally:
            builtins._log_error_watch_core_only = False

        class Meta(type):
            def __instancecheck__(cls, obj):
                return isinstance(obj, real_datetime)

        class Clock(real_datetime, metaclass=Meta):
            fixed = None

            @classmethod
            def now(cls, tz=None):
                return cls.fixed
        self.clock = Clock
        self.w.datetime = Clock
        self.w.send_pushover = lambda title, body, priority=0: (
            self.sends.append(title) or self.deliver)
        self.w.send_email = lambda *a, **k: self.deliver
        self.w.STATE_PATH = str(tmp_path / "state.json")
        rules_path = tmp_path / "local_rules.py"
        rules_path.write_text(rules, encoding="utf-8")
        self.w.LOCAL_RULES_PATH = str(rules_path)
        self.seed()

    def _buffer(self, **_kw):
        return [r for r in self.rows if r["TimeStamp"] <= self.clock.fixed
                and (self.buffer_from is None or r["TimeStamp"] >= self.buffer_from)]

    def seed(self, signatures=None):
        with open(self.w.STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "seeded_at": "2026-01-01 00:00:00",
                       "signatures": signatures or {}}, fh)

    def add(self, minutes, source, message):
        self.rows.append({"TimeStamp": T0 + timedelta(minutes=minutes), "TypeStr": source,
                          "TypeVal": 1 if source.endswith("Error") else 8, "Message": message})
        self.rows.sort(key=lambda r: r["TimeStamp"])

    def write_dated_files(self):
        """Every row, as Indigo writes its dated 'YYYY-MM-DD Events.txt' files."""
        days = {}
        for r in self.rows:
            stamp = r["TimeStamp"].strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            days.setdefault(r["TimeStamp"].strftime("%Y-%m-%d"), []).append(
                f"{stamp}\t{r['TypeStr']}\t{r['Message']}\n")
        for day, lines in days.items():
            (self.folder / "Logs" / f"{day} Events.txt").write_text("".join(lines),
                                                                    encoding="utf-8")

    def run(self, minutes):
        when = T0 + timedelta(minutes=minutes)
        self.clock.fixed = self.clock.fromtimestamp(when.timestamp())
        self.w.main(quiet=True)
        return list(self.sends)

    def signatures(self):
        with open(self.w.STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh)["signatures"]

    def record(self, source, message):
        return self.signatures()[self.w.signature(source, message)]


@pytest.fixture
def watch(tmp_path):
    return Watch(tmp_path)


def old_row(watch, minutes=-400):
    """A row old enough that the buffer reaches back over the whole cause read."""
    watch.add(minutes, "Application", "an old row, so the buffer reaches back")


# ---- (1) causes are read back further than alerts ------------------------------------------

def test_a_cause_older_than_the_window_but_inside_its_rules_window_explains(watch):
    """The cause is 94 minutes old, past the 90 the watch alerts on, and nine minutes before
    the error: inside the rule's ten. 2.1 never read it, so the error paged."""
    old_row(watch)
    watch.add(-94, "Tester", CAUSE)
    watch.add(-85, "Tester Error", FAILED)
    assert watch.run(0) == []
    rec = watch.record("Tester", FAILED)
    assert rec["explained"] and rec["reason"] == "widget work"


def test_a_cause_beyond_its_rules_window_explains_nothing(watch):
    old_row(watch)
    watch.add(-100.5, "Tester", CAUSE)
    watch.add(-85, "Tester Error", FAILED)
    assert len(watch.run(0)) == 1
    assert not watch.record("Tester", FAILED)["explained"]


def test_an_error_older_than_the_window_is_read_as_a_cause_row_only(watch):
    """The longer read is for causes. An error in it is never news, never stored."""
    old_row(watch)
    watch.add(-100, "Tester Error", FAILED)
    watch.add(-95, "Tester Error", "something else broke")
    assert watch.run(0) == []
    assert watch.signatures() == {}


def test_a_line_just_inside_the_window_is_not_folded_onto_one_just_before_it(watch):
    """The rows before the window are merged apart from the window's own, so a line 1 ms inside
    it stays its own record, as it was when nothing before the window was read."""
    old_row(watch)
    watch.add(-90 - 0.01 / 60, "Tester Error", "a fault just before the window")
    watch.add(-90 + 0.001 / 60, "Tester Error", "a different fault just inside it")
    assert len(watch.run(0)) == 1
    assert list(watch.signatures().values())[0]["message"] == "a different fault just inside it"


def test_the_shipped_restart_rule_reaches_back_past_the_window_too(watch):
    """The web server's 500 four minutes after a plugin restart that is itself 92 minutes old."""
    old_row(watch)
    watch.add(-92, "Application", "Starting plugin Example Plugin 1.0.0 (pid 123)")
    watch.add(-88, "Web Server Error",
              "internal server error for request /public/example/page.js from 192.0.2.10")
    assert watch.run(0) == []


def test_a_buffer_that_reaches_the_window_but_not_the_cause_is_filled_from_the_files(watch):
    """After a server start the buffer reaches back only to the start. The window is whole, so
    the alerts still come from the buffer, and the older causes come from the dated file."""
    watch.add(-94, "Tester", CAUSE)
    watch.add(-91, "Application", "Indigo server started")
    watch.add(-85, "Tester Error", FAILED)
    watch.write_dated_files()
    watch.buffer_from = T0 + timedelta(minutes=-91)
    assert watch.run(0) == []
    rec = watch.record("Tester", FAILED)
    assert rec["explained"]
    assert rec["count"] == 1, "a window row was read from the buffer and the file both"
    assert not [m for m in watch.logged if "did not reach back far enough" in m]


def test_a_buffer_short_of_the_window_reads_the_files_from_the_cause_read(watch):
    """The buffer does not reach the window at all: everything comes from the files, from the
    start of the cause read, and the one INFO line says so."""
    watch.add(-94, "Tester", CAUSE)
    watch.add(-85, "Tester Error", FAILED)
    watch.add(-60, "Application", "Indigo server started")
    watch.write_dated_files()
    watch.buffer_from = T0 + timedelta(minutes=-60)
    assert watch.run(0) == []
    assert watch.record("Tester", FAILED)["explained"]
    assert watch.record("Tester", FAILED)["count"] == 1
    said = [lvl for m, lvl in watch.levels if "did not reach back far enough" in m]
    assert said == [watch.w.logging.INFO]


def test_files_with_nothing_in_the_window_say_so_at_warning(watch):
    """The buffer is empty and the files hold only a row before the window, a cause: the
    window was not read at all, which is a WARNING, not the INFO of a normal fill. A cause row
    alone must not make it look as if the window came back."""
    watch.add(-94, "Tester", CAUSE)
    watch.write_dated_files()
    watch.buffer_from = T0 + timedelta(minutes=1)
    assert watch.run(0) == []
    said = [lvl for m, lvl in watch.levels if "did not reach back far enough" in m]
    assert said == [watch.w.logging.WARNING]


def test_a_buffer_that_starts_after_midnight_takes_the_new_days_causes_from_its_file(watch):
    """The run at 01:35 alerts from 00:05 and reads causes from 23:55 the day before. The
    buffer starts at 00:03, so the cause at 00:01 is in the new day's file, after the day the
    cause read starts on: the fill must read every day up to the buffer's first row."""
    midnight = 12 * 60                    # T0 is noon
    watch.add(midnight - 20, "Application", "a row the day before")
    watch.add(midnight + 1, "Tester", CAUSE)
    watch.add(midnight + 3, "Application", "the first row the buffer still holds")
    watch.add(midnight + 8, "Tester Error", FAILED)
    watch.write_dated_files()
    assert len(list((watch.folder / "Logs").iterdir())) == 2
    watch.buffer_from = T0 + timedelta(minutes=midnight + 3)
    assert watch.run(midnight + 95) == []
    rec = watch.record("Tester", FAILED)
    assert rec["explained"] and rec["count"] == 1
    assert not [m for m in watch.logged if "did not reach back far enough" in m]


def test_a_row_at_the_buffers_first_stamp_is_not_read_twice(watch):
    """The buffer starts exactly at the window's start, with an error there. The file holds
    the same row; only rows older than the buffer's first come from it."""
    watch.add(-95, "Tester", CAUSE)
    watch.add(-90, "Tester Error", FAILED)
    watch.add(-30, "Application", "a later row")
    watch.write_dated_files()
    watch.buffer_from = T0 + timedelta(minutes=-90)
    assert watch.run(0) == []
    rec = watch.record("Tester", FAILED)
    assert rec["explained"] and rec["count"] == 1


def test_a_rule_longer_than_two_hours_reaches_back_through_main(tmp_path):
    """A made-up three-hour rule: its cause four hours before the run, the error 2 h 40 min
    after it. The read follows the longest rule, not the house's two hours."""
    watch = Watch(tmp_path, rules=RULES.replace(str(WINDOW), str(3 * 3600)))
    old_row(watch)
    watch.add(-240, "Tester", CAUSE)
    watch.add(-80, "Tester Error", FAILED)
    assert watch.run(0) == []
    assert watch.record("Tester", FAILED)["explained"]


def test_with_no_dated_files_a_missing_cause_still_pages(watch):
    """Failing towards a page: a cause that cannot be read excuses nothing."""
    watch.add(-94, "Tester", CAUSE)
    watch.add(-91, "Application", "Indigo server started")
    watch.add(-85, "Tester Error", FAILED)
    watch.buffer_from = T0 + timedelta(minutes=-91)
    assert len(watch.run(0)) == 1


def test_the_cause_read_is_the_longest_rule_window_and_is_bounded(bare):
    assert hasattr(bare, "cause_read_seconds"), "Log_Error_Watch has no cause read"
    reach = bare.cause_read_seconds
    cap = bare.CAUSE_READ_MAX_HOURS * 3600
    rule = ("A", "x", "B", "y", 310, "a rule")
    assert reach([]) == 0
    assert reach([rule, ("A", "x", "B", "y", 7200, "longer")]) == 7200
    for bad in ("7200", -5, float("nan"), float("inf"), None, True):
        assert reach([rule, ("A", "x", "B", "y", bad, "bad")]) == 310, bad
        assert reach([("A", "x", "B", "y", bad, "bad")]) == 0, bad
    assert reach([rule, ("too", "short")]) == 310
    assert reach([("A", "x", "B", "y", 10 ** 12, "typo")]) == cap
    assert 0 < cap and math.isfinite(cap)


def test_a_rule_window_typed_far_too_long_does_not_stop_the_run(tmp_path):
    watch = Watch(tmp_path, rules=RULES.replace(str(WINDOW), str(10 ** 12)))
    old_row(watch)
    watch.add(-85, "Tester Error", "a fault no rule names")
    assert len(watch.run(0)) == 1


# ---- (2) a once-explained signature that comes back unexplained -------------------------------

def known(explained, alerted_ago_h=None, last_seen_ago_m=50, count=1, since_alert=None):
    """A stored record. since_alert None leaves explained_since_alert out, as a record
    written before 2.2 has it."""
    seen = T0 - timedelta(minutes=last_seen_ago_m)
    record = {"source": "Tester", "message": FAILED, "level": "error", "count": count,
              "first_seen": "2026-03-03 11:00:00",
              "last_seen": seen.strftime("%Y-%m-%d %H:%M:%S"),
              "last_seen_exact": seen.isoformat(), "explained": explained, "reason": "",
              "alerted_at": (None if alerted_ago_h is None else
                             (T0 - timedelta(hours=alerted_ago_h)).strftime("%Y-%m-%d %H:%M:%S")),
              "count_at_alert": None if alerted_ago_h is None else count}
    if since_alert is not None:
        record["explained_since_alert"] = since_alert
    return record


def current(w, minutes_ago):
    rows = [{"TimeStamp": T0 - timedelta(minutes=m), "TypeStr": "Tester Error", "TypeVal": 1,
             "Message": FAILED} for m in sorted(minutes_ago, reverse=True)]
    return w.collapse(w.merge_continuations(rows), None)


@pytest.fixture
def bare(tmp_path):
    return Watch(tmp_path).w


def test_explained_before_and_unexplained_now_with_fresh_lines_is_new(bare):
    cur = current(bare, [50, 10])
    key = next(iter(cur))
    new, unresolved = bare.decide(cur, {key: known(explained=True)}, T0)
    assert [e["kind"] for e in new] == ["new"] and unresolved == []


def test_explained_before_and_only_old_lines_now_sends_nothing(bare):
    """The run that keeps lines the last run explained but has lost their cause."""
    cur = current(bare, [55, 50])
    key = next(iter(cur))
    assert bare.decide(cur, {key: known(explained=True)}, T0) == ([], [])


def test_background_never_explained_and_never_alerted_stays_quiet(bare):
    """What the seed run stored is the house's background, and stays so."""
    cur = current(bare, [50, 10])
    key = next(iter(cur))
    assert bare.decide(cur, {key: known(explained=False)}, T0) == ([], [])


def test_an_excuse_two_runs_back_still_counts_when_fresh_lines_come(bare):
    """The last run read the old lines without their cause and stored explained False, but
    a rule excused the signature before that and it has not been alerted since."""
    cur = current(bare, [50, 10])
    key = next(iter(cur))
    new, _ = bare.decide(cur, {key: known(explained=False, since_alert=True)}, T0)
    assert [e["kind"] for e in new] == ["new"]


def test_the_kept_excuse_is_what_decide_reads(bare):
    """Where a record carries explained_since_alert, decide reads that and not the last
    window's verdict: False there (told since) is quiet even if the last run was explained."""
    cur = current(bare, [50, 10])
    key = next(iter(cur))
    assert bare.decide(cur, {key: known(explained=True, since_alert=False)}, T0) == ([], [])


def test_an_alerted_signature_keeps_the_rules_it_had(bare):
    """An excuse after an alert does not make the next unexplained line news inside the
    re-alert day: the 24-hour rule stands, excused or not. Widened, over one house's logs of
    01-08 to 19-11-2026, it sent a web server 500 at eleven more runs and four fewer."""
    cur = current(bare, [50, 10])
    key = next(iter(cur))
    for since in (None, True):
        assert bare.decide(cur, {key: known(explained=True, alerted_ago_h=2,
                                            since_alert=since)}, T0) == ([], [])
        _, unresolved = bare.decide(cur, {key: known(explained=True, alerted_ago_h=26,
                                                     since_alert=since)}, T0)
        assert [e["kind"] for e in unresolved] == ["again"]


def test_still_explained_now_sends_nothing(tmp_path):
    w = Watch(tmp_path)
    w.add(-30, "Tester", CAUSE)
    w.add(-25, "Tester Error", FAILED)
    old_row(w)
    assert w.run(0) == []
    w.add(30, "Tester", CAUSE)
    w.add(35, "Tester Error", FAILED)
    assert w.run(60) == []


def test_a_fault_left_behind_after_its_cause_pages_once(watch):
    """Cause at 0 explains the error at 5; the errors at 30 and 100 have no cause in their ten
    minutes. 2.1 stored the first as explained with no alert, and stayed silent after."""
    old_row(watch)
    watch.add(0, "Tester", CAUSE)
    watch.add(5, "Tester Error", FAILED)
    assert watch.run(10) == []
    watch.add(30, "Tester Error", FAILED)
    assert watch.run(70) == ["Indigo log: one new error from Tester"]
    watch.add(100, "Tester Error", FAILED)
    assert len(watch.run(130)) == 1


def test_old_lines_without_their_cause_and_no_fresh_ones_page_nothing_through_main(watch):
    """The second run sees the same line again, but its buffer starts after the cause and there
    is no dated file to fill it from, so the line reads unexplained. No fresh line: nothing."""
    old_row(watch)
    watch.add(0, "Tester", CAUSE)
    watch.add(2, "Application", "a row between the cause and the error")
    watch.add(5, "Tester Error", FAILED)
    assert watch.run(10) == []
    assert watch.record("Tester", FAILED)["explained"]
    watch.buffer_from = T0 + timedelta(minutes=1)
    assert watch.run(94) == []
    rec = watch.record("Tester", FAILED)
    assert not rec["explained"], "explained is this window's verdict"
    assert rec["explained_since_alert"], "the excuse must outlive a run that lost its cause"


def test_a_fault_left_behind_still_pages_after_a_run_that_lost_its_cause(watch):
    """Explained at 10; at 94 the buffer has lost the cause and sees only the old line, so
    nothing goes; then fresh lines with no cause at 100, 160 and 220. The first of them pages,
    once; the rest are inside the re-alert day."""
    old_row(watch)
    watch.add(0, "Tester", CAUSE)
    watch.add(2, "Application", "a row between the cause and the error")
    watch.add(5, "Tester Error", FAILED)
    assert watch.run(10) == []
    watch.buffer_from = T0 + timedelta(minutes=1)
    assert watch.run(94) == []
    for minutes in (100, 160, 220):
        watch.add(minutes, "Tester Error", FAILED)
    assert [len(watch.run(m)) for m in (154, 214, 274)] == [1, 1, 1]
    assert watch.sends == ["Indigo log: one new error from Tester"]
    assert watch.record("Tester", FAILED)["explained_since_alert"] is False


def test_a_fault_left_behind_still_pages_after_a_run_with_the_rules_file_unreadable(watch):
    """The local rules file fails to load for one run, so that run reads the old line with no
    rule at all and sends nothing. The rules come back; the next fresh line pages."""
    old_row(watch)
    watch.add(0, "Tester", CAUSE)
    watch.add(5, "Tester Error", FAILED)
    assert watch.run(10) == []
    rules_path = watch.w.LOCAL_RULES_PATH
    with open(rules_path, encoding="utf-8") as fh:
        good = fh.read()
    with open(rules_path, "w", encoding="utf-8") as fh:
        fh.write("EXPLAINED_BY = [\n")
    assert watch.run(70) == []
    assert any("could not be read" in m for m in watch.logged)
    assert not watch.record("Tester", FAILED)["explained"]
    with open(rules_path, "w", encoding="utf-8") as fh:
        fh.write(good)
    watch.add(100, "Tester Error", FAILED)
    assert watch.run(130) == ["Indigo log: one new error from Tester"]


def test_a_failed_delivery_keeps_the_excuse_until_one_goes(watch):
    """Pushover and email both fail: the signature is pending and still carries the excuse.
    The next run that still has the line in its window delivers it, and only then is the
    excuse cleared."""
    old_row(watch)
    watch.add(0, "Tester", CAUSE)
    watch.add(5, "Tester Error", FAILED)
    assert watch.run(10) == []
    watch.add(30, "Tester Error", FAILED)
    watch.deliver = False
    assert len(watch.run(70)) == 1
    rec = watch.record("Tester", FAILED)
    assert rec["pending"] and rec["alerted_at"] is None and rec["explained_since_alert"]
    watch.deliver = True
    assert len(watch.run(100)) == 2
    rec = watch.record("Tester", FAILED)
    assert not rec["pending"] and rec["alerted_at"] and rec["explained_since_alert"] is False
