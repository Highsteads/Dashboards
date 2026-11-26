#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    open_since.py
# Description: When each window and door was opened, kept by the plugin itself.
#              Indigo keeps one "last changed" time for a whole device and
#              moves it on any state write (a battery report, a bridge
#              refresh), so nothing in Indigo says how long a window has been
#              open. This records the moment a contact sensor's state goes
#              on, and forgets it when it goes off. Pure: no Indigo, so it is
#              tested without one.
# Author:      CliveS & Claude Fable 5.2
# Date:        26-11-2026 12:50
# Version:     1.0

import json
import os

# A record kept across a restart is believed only when the plugin was away
# for less than this. Longer, and a window may have been shut and opened
# again unseen, so the old time would be a wrong answer shown with confidence.
TRUST_GAP_SECONDS = 180
FILE_VERSION = 1


class OpenSince:
    """{device id: epoch it went on}, for the devices it is told to follow."""

    def __init__(self):
        self.since = {}          # int id -> float epoch
        self.dirty = False
        self.reconciled = False  # has the first look at the real states happened

    # ---- changes, as they happen -----------------------------------------
    def note(self, dev_id, was_on, is_on, now):
        """A followed device changed. Only a real change of the on state
        counts: the same state written again is not an opening."""
        dev_id = int(dev_id)
        if is_on is True and was_on is not True:
            self.since[dev_id] = float(now)
            self.dirty = True
        elif is_on is not True and dev_id in self.since:
            del self.since[dev_id]
            self.dirty = True

    # ---- the first look after a start --------------------------------------
    def reconcile(self, states, trusted):
        """Square the kept records with what the devices say now.

        states:  {device id: True / False / None} for every followed device.
        trusted: were the kept records made by a plugin that was running
                 until a moment ago (see TRUST_GAP_SECONDS)?

        A record for a device that is shut, unknown or no longer followed is
        dropped. With no trust every record is dropped: an open window then
        has no time until it next changes, which the pages show as plain
        "Open". A device open now with no record is left without one, for
        the same reason: nobody saw it open."""
        before = dict(self.since)
        if not trusted:
            self.since = {}
        else:
            self.since = {i: t for i, t in self.since.items() if states.get(i) is True}
        if self.since != before:
            self.dirty = True
        self.reconciled = True

    # ---- for the pages -----------------------------------------------------
    def reply(self):
        """{"<id>": epoch} for the change poll. Small: only what is open."""
        return {str(i): round(t, 1) for i, t in self.since.items()}

    # ---- on disk -----------------------------------------------------------
    def load(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except Exception:
            return                       # an unreadable file is no records, not a fault
        if not isinstance(data, dict) or data.get("v") != FILE_VERSION:
            return
        kept = {}
        for k, v in (data.get("since") or {}).items():
            try:
                t = float(v)
                if t > 0 and t == t:
                    kept[int(k)] = t
            except (TypeError, ValueError):
                continue
        self.since = kept

    def save(self, path):
        """Write if anything changed. 0600: it is a record of comings and goings."""
        if not self.dirty:
            return False
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"v": FILE_VERSION, "since": {str(i): t for i, t in self.since.items()}}, f)
        os.replace(tmp, path)
        self.dirty = False
        return True
