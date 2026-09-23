#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# Filename:    make_demo_api.py
# Description: Canned answers for the plugin's own endpoints, so the online
#              demo works with no Indigo server behind it (v3.39.0). In demo
#              mode DashUI.message reads demo-data/api/<name>.json instead of
#              asking the plugin, and sigenApi reads sigenApi-<path>.json.
#
#              Captured from a LIVE server and then cut down, because a demo
#              is published:
#                - every string goes through make_demo_fixtures.scrub (private
#                  IPs, MACs, e-mails, anything whose key names a credential);
#                - the Timeline keeps its lights, heating and energy lanes
#                  only. Presence and doors are a record of when the house is
#                  occupied, and the Nights view is not captured at all;
#                - the power-cut history is emptied, and the energy supplier
#                  account balance (and anything else named like an account
#                  figure) is blanked;
#                - the activity diary and the error log are INVENTED below,
#                  not captured: the real ones name who holds a door code and
#                  quote log lines nobody has read for identifiers.
#              Read the output by hand before committing it, then run
#              ~/bin/published-identifier-scan. tests/test_demo_site.py checks
#              the rules above hold.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
#
# Usage: python3 tools/make_demo_api.py      (on the Indigo server)
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_demo_fixtures import scrub, OUT_DIR, INDIGO_URL, INDIGO_API_KEY  # noqa: E402

API_DIR = os.path.join(OUT_DIR, "api")
BASE = INDIGO_URL + "/message/com.clives.indigoplugin.dashboards/"

CAPTURE = {
    "sigenApi-status":   ("sigenApi", {"path": "status", "query": {}}),
    "sigenApi-history":  ("sigenApi", {"path": "history", "query": {"hours": 48}}),
    "sigenApi-daily":    ("sigenApi", {"path": "daily", "query": {"days": 400}}),
    "sigenApi-calendar": ("sigenApi", {"path": "calendar", "query": {}}),
    "sigenApi-vpp":      ("sigenApi", {"path": "vpp", "query": {}}),
    "sigenApi-years":    ("sigenApi", {"path": "years", "query": {}}),
    "solarStringHours":  ("solarStringHours", {}),
    "carbonAdvisor":     ("carbonAdvisor", {}),
    "laundryPlan":       ("laundryPlan", {}),
    "mainsMeters":       ("mainsMeters", {}),
    "homeInsights":      ("homeInsights", {}),
    "systemHealth":      ("systemHealth", {}),
    "timelineDay":       ("timelineDay", {"date": time.strftime("%Y-%m-%d")}),
}
TIMELINE_LANES_KEPT = {"lights", "heating"}
# Keys whose value is somebody's money or account, blanked wherever they sit.
PRIVATE_KEY_PARTS = ("balance_gbp", "account", "mpan", "mprn", "serial")


def blank_private(obj):
    if isinstance(obj, dict):
        return {k: (None if any(p in k.lower() for p in PRIVATE_KEY_PARTS) else blank_private(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [blank_private(v) for v in obj]
    return obj


def ask(name, body):
    for _ in range(60):
        req = urllib.request.Request(
            BASE + name + "/", data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": "Bearer " + INDIGO_API_KEY, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 503:              # still building, or the proxy's cache is cold
                time.sleep(1.0)
                continue
            raise
    raise RuntimeError(f"{name} never stopped answering pending")


def cut_down(key, data):
    """The rules the docstring lists, applied after scrub()."""
    data = blank_private(data)
    if key == "timelineDay":
        data["lanes"] = [ln for ln in data.get("lanes", []) if ln.get("key") in TIMELINE_LANES_KEPT]
    if key == "sigenApi-status" and isinstance(data.get("power_cut"), dict):
        data["power_cut"]["events"] = []
    return data


def invented(now):
    """The diary, automation list and error log, made up for the demo."""
    def at(h, m):
        t = time.localtime(now)
        return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, h, m, 0, 0, 0, -1))
    diary = [
        {"time": "07:42", "epoch": at(7, 42), "src": "Doors", "msg": "Front door opened", "level": "info", "cat": "door", "count": 1},
        {"time": "07:43", "epoch": at(7, 43), "src": "Doors", "msg": "Front door locked", "level": "info", "cat": "lock", "count": 1},
        {"time": "12:15", "epoch": at(12, 15), "src": "Leak", "msg": "Kitchen leak sensor: dry again after a test", "level": "info", "cat": "safety", "count": 1},
        {"time": "16:05", "epoch": at(16, 5), "src": "Indigo", "msg": "Plugin restarted: Dashboards", "level": "info", "cat": "plugin", "count": 1},
    ]
    return {
        "activityFeed": {
            "ok": True, "now": now, "alerts": [], "diary": diary,
            "automation": {
                "next": [{"name": "Evening lights", "epoch": at(19, 30), "when": "7:30pm", "in_min": 90},
                         {"name": "Night sweep", "epoch": at(23, 0), "when": "11pm", "in_min": 300}],
                "watchers": [{"name": "Garage door left open"}, {"name": "Leak alarm"}],
                "disabled": [{"name": "Holiday lighting", "kind": "schedule"}],
                "codes": [],
                "counts": {"schedules": 18, "schedules_off": 1, "triggers": 42, "triggers_off": 2},
            },
        },
        "logErrors": {
            "ok": True, "now": now, "lastRun": "just now", "seededAt": "",
            "feed": {"generatedLocal": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                     "_writeTs": now, "errors": 0, "warnings": 1,
                     "rows": [{"source": "Z-Wave", "message": "Drive temperature sensor: no reply, will retry",
                               "level": "warning", "count": 2, "muted": False, "recovered": True,
                               "explained": False, "reason": "", "first": "09:10", "last": "09:40"}]},
        },
    }


def main():
    os.makedirs(API_DIR, exist_ok=True)
    for key, (name, body) in CAPTURE.items():
        data = cut_down(key, scrub(ask(name, body)))
        with open(os.path.join(API_DIR, key + ".json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        print(f"{key}: captured")
    for key, data in invented(time.time()).items():
        with open(os.path.join(API_DIR, key + ".json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        print(f"{key}: invented")
    print(f"\nWritten to {API_DIR}. Read them before committing, then run published-identifier-scan.")


if __name__ == "__main__":
    main()
