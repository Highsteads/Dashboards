#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_save_config.py
# Description: Contract test for Plugin.handleSaveDashboardsConfig — the settings
#              editor's persist path. Covers validation (vendor allow-list,
#              mainCameras membership, pinRequired coercion), the customLinks
#              scheme allow-list (javascript:/data: rejected), favourite dropping,
#              and the v2.37.0 round-trip that preserves unknown store keys added
#              via the raw-JSON escape hatch.
# Author:      CliveS & Claude Fable 5
# Date:        15-07-2026
# Version:     1.0

import json
from unittest.mock import MagicMock
from conftest import bare_plugin


class FakeAction:
    def __init__(self, body):
        self.props = {"request_body": body}


def make_plugin():
    """A bare Plugin with the persist + refresh side-effects stubbed, capturing
    the cleaned dict handed to _save_config_store."""
    p = bare_plugin()
    captured = {}

    def _save(clean):
        captured["clean"] = clean
        return {"config": clean}          # stands in for the on-disk store
    p._save_config_store = _save
    p._write_config_js = MagicMock()
    p._build_rooms_json = MagicMock()
    p._build_scenes_json = MagicMock()
    p.cfg_store = {}
    return p, captured


def save(p, cfg):
    reply = p.handleSaveDashboardsConfig(FakeAction(json.dumps({"config": cfg})))
    return json.loads(reply["content"]), reply["status"]


def test_valid_config_round_trips(monkeypatch):
    p, cap = make_plugin()
    body, status = save(p, {
        "cameras": [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua"}],
        "mainCameras": ["10.0.0.5"],
        "pinRequired": ["5", "-3", "bad", "12"],
    })
    assert status == 200 and body["ok"] is True
    assert cap["clean"]["pinRequired"] == [5, -3, 12]     # ints, junk dropped


def test_bad_vendor_rejected():
    p, _ = make_plugin()
    body, status = save(p, {"cameras": [{"host": "h", "name": "n", "vendor": "nosuchmake"}]})
    assert status == 400 and body["ok"] is False
    assert "vendor" in body["error"]


def test_maincamera_not_in_cameras_rejected():
    p, _ = make_plugin()
    body, status = save(p, {
        "cameras": [{"host": "h", "name": "n", "vendor": "dahua"}],
        "mainCameras": ["not-a-host"],
    })
    assert status == 400 and "mainCameras" in body["error"]


def test_javascript_link_dropped_http_kept():
    p, cap = make_plugin()
    save(p, {"customLinks": [
        {"title": "Evil", "url": "javascript:alert(1)"},
        {"title": "Data", "url": "data:text/html,x"},
        {"title": "Good", "url": "https://example.com/x"},
        {"title": "Rel",  "url": "/local/page"},
    ]})
    urls = [l["url"] for l in cap["clean"]["customLinks"]]
    assert urls == ["https://example.com/x", "/local/page"]


def test_malformed_favourites_dropped_not_crash():
    p, cap = make_plugin()
    save(p, {"favourites": [
        {"type": "device", "id": "7", "label": "Boiler"},   # id coerces to int
        {"type": "bogus", "id": 1},                          # bad type -> dropped
        {"type": "scene"},                                   # no id -> dropped
        "junk",                                              # non-dict -> dropped
    ]})
    favs = cap["clean"]["favourites"]
    assert favs == [{"type": "device", "id": 7, "label": "Boiler"}]


def test_door_favourite_round_trips():
    """v2.76.0: {type:"door", id, openAction, closeAction} survives the save
    with everything coerced to int, plus optional label and state override."""
    p, cap = make_plugin()
    save(p, {"favourites": [
        {"type": "door", "id": "489580549", "openAction": "1463818396",
         "closeAction": 780532115, "label": "Garage", "state": "doorState"},
    ]})
    assert cap["clean"]["favourites"] == [
        {"type": "door", "id": 489580549, "openAction": 1463818396,
         "closeAction": 780532115, "label": "Garage", "state": "doorState"},
    ]


def test_door_favourite_needs_both_actions():
    """Half a door is a trap — an open action plus at least one of a close
    action or a lock device, or the entry is dropped whole."""
    p, cap = make_plugin()
    save(p, {"favourites": [
        {"type": "door", "id": 1, "openAction": 2},                    # no close, no lock
        {"type": "door", "id": 1, "closeAction": 3},                   # no open
        {"type": "door", "id": 1, "openAction": "x", "closeAction": 3},  # junk
        {"type": "door", "id": 4, "openAction": 5, "closeAction": 6},  # good
    ]})
    assert cap["clean"]["favourites"] == [
        {"type": "door", "id": 4, "openAction": 5, "closeAction": 6},
    ]


def test_lock_style_door_saves_without_close_action():
    """v2.77.0: a lockId satisfies the second half of the rule — the front
    door has an unlock sequence but nothing that closes it. Junk in a
    PRESENT key still drops the entry whole rather than half-saving it."""
    p, cap = make_plugin()
    save(p, {"favourites": [
        {"type": "door", "id": "651379270", "lockId": "1835630858",
         "openAction": 1044686530, "label": "Front Door"},
        {"type": "door", "id": 1, "openAction": 2, "lockId": "junk"},  # dropped
    ]})
    assert cap["clean"]["favourites"] == [
        {"type": "door", "id": 651379270, "openAction": 1044686530,
         "lockId": 1835630858, "label": "Front Door"},
    ]


def test_reading_colour_bands_round_trip():
    """v2.77.0: warnBelow/badBelow ride a reading favourite as floats; a junk
    band is dropped alone (the reading still saves); bands never attach to a
    stateless device favourite."""
    p, cap = make_plugin()
    save(p, {"favourites": [
        {"type": "device", "id": 1453377785, "label": "Qashqai 12V",
         "state": "voltage", "warnBelow": "12.4", "badBelow": 12.0},
        {"type": "device", "id": 2, "state": "temp", "warnBelow": "junk"},
        {"type": "device", "id": 3, "warnBelow": 5},        # no state -> no bands
    ]})
    favs = cap["clean"]["favourites"]
    assert favs[0]["warnBelow"] == 12.4 and favs[0]["badBelow"] == 12.0
    assert favs[1] == {"type": "device", "id": 2, "state": "temp"}
    assert favs[2] == {"type": "device", "id": 3}


def test_door_state_override_is_door_or_device_only():
    """The state key rides on device and door favourites; a scene must not
    grow one (nothing reads it there, and stray keys invite drift)."""
    p, cap = make_plugin()
    save(p, {"favourites": [
        {"type": "scene", "id": 9, "state": "doorState"},
        {"type": "door", "id": 4, "openAction": 5, "closeAction": 6},
    ]})
    favs = cap["clean"]["favourites"]
    assert favs[0] == {"type": "scene", "id": 9}
    assert "state" not in favs[1]           # none supplied -> none invented


def test_unknown_store_keys_preserved():
    """A key added via the settings raw-JSON escape hatch must survive the save
    (v2.37.0 round-trip fix) rather than being whitelisted away."""
    p, cap = make_plugin()
    save(p, {"myExperimentalKey": {"a": 1}, "hiddenScenes": ["99"]})
    assert cap["clean"]["myExperimentalKey"] == {"a": 1}
    assert cap["clean"]["hiddenScenes"] == ["99"]


def test_non_object_config_rejected():
    p, _ = make_plugin()
    reply = p.handleSaveDashboardsConfig(FakeAction(json.dumps({"config": "nope"})))
    body = json.loads(reply["content"])
    assert reply["status"] == 400 and body["ok"] is False


def test_bad_json_body_rejected():
    p, _ = make_plugin()
    reply = p.handleSaveDashboardsConfig(FakeAction("{not json"))
    body = json.loads(reply["content"])
    assert reply["status"] == 400 and "bad JSON" in body["error"]


def test_group_favourite_round_trips():
    """v2.93.0: {type:"group", label, devices:[{id, onLevel?, openLoop?}]} —
    one tile driving several devices. Ids coerce to int, onLevel is a whole
    percent, and openLoop marks a member whose state is a belief rather than a
    reading (the RF fire) so the hub never lets it decide a press."""
    p, cap = make_plugin()
    save(p, {"favourites": [
        {"type": "group", "label": "Living Room", "devices": [
            {"id": "372666822", "onLevel": "100"},
            {"id": 1293995000},
            {"id": 515728864},
            {"id": 614164061, "openLoop": True},
        ]},
    ]})
    assert cap["clean"]["favourites"] == [
        {"type": "group", "label": "Living Room", "devices": [
            {"id": 372666822, "onLevel": 100},
            {"id": 1293995000},
            {"id": 515728864},
            {"id": 614164061, "openLoop": True},
        ]},
    ]


def test_group_favourite_drops_junk_members_and_empty_groups():
    """A member with an unusable id goes alone; a group left with nothing to
    command goes whole — a tile that commands nothing is a trap, not a tile.
    An out-of-range or non-numeric onLevel drops the LEVEL only, leaving a
    member that still switches on."""
    p, cap = make_plugin()
    save(p, {"favourites": [
        {"type": "group", "label": "Mixed", "devices": [
            {"id": "nope"},                       # unusable id -> member dropped
            "junk",                               # not a dict  -> member dropped
            {"id": 5, "onLevel": 0},              # out of range -> level dropped
            {"id": 6, "onLevel": "loud"},         # not a number -> level dropped
            {"id": 7, "onLevel": 55.6},           # rounded to a whole percent
        ]},
        {"type": "group", "label": "Empty", "devices": []},          # dropped whole
        {"type": "group", "label": "All junk", "devices": [{"id": None}]},  # dropped whole
        {"type": "group"},                                            # no devices key
    ]})
    assert cap["clean"]["favourites"] == [
        {"type": "group", "label": "Mixed", "devices": [
            {"id": 5}, {"id": 6}, {"id": 7, "onLevel": 56},
        ]},
    ]


def test_group_favourite_openloop_is_not_a_bare_bool():
    """Indigo re-serialises a checkbox as the STRING "false", and bool("false")
    is True — so openLoop goes through as_bool, never bool()."""
    p, cap = make_plugin()
    save(p, {"favourites": [
        {"type": "group", "devices": [
            {"id": 1, "openLoop": "false"},
            {"id": 2, "openLoop": "true"},
            {"id": 3, "openLoop": ""},
        ]},
    ]})
    assert cap["clean"]["favourites"] == [
        {"type": "group", "devices": [{"id": 1}, {"id": 2, "openLoop": True}, {"id": 3}]},
    ]


# ── v2.96.0 keys: roomFolders, siteName, vehicles ──────────────────────────
# Each rides the unknown-key round trip, but is CLEANED so a bad value cannot
# reach the pages: folder names trimmed and capped, the site name capped at 40,
# a vehicle row without a device id dropped like a malformed favourite.

def _base():
    return {"cameras": [], "mainCameras": [], "roomExtras": {}, "hiddenScenes": []}


def test_room_folders_are_cleaned_and_kept():
    p, cap = make_plugin()
    body, status = save(p, dict(_base(), roomFolders=["  Kitchen ", "", "Living Room", "x" * 80]))
    assert status == 200, body
    assert cap["clean"]["roomFolders"] == ["Kitchen", "Living Room", "x" * 60]


def test_room_folders_must_be_a_list_of_strings():
    p, cap = make_plugin()
    body, status = save(p, dict(_base(), roomFolders="Kitchen"))
    assert status == 400 and "roomFolders" in body["error"]
    body, status = save(p, dict(_base(), roomFolders=[1, 2]))
    assert status == 400


def test_site_name_is_trimmed_and_capped():
    p, cap = make_plugin()
    body, status = save(p, dict(_base(), siteName="  The Old Mill " + "!" * 60))
    assert status == 200
    assert cap["clean"]["siteName"] == ("The Old Mill " + "!" * 60)[:40]


def test_vehicles_keep_good_rows_and_drop_bad_ones():
    p, cap = make_plugin()
    body, status = save(p, dict(_base(), vehicles=[
        {"id": 1453377785, "label": "Car 12V"}, {"label": "no id"}, "junk", {"id": "abc"}]))
    assert status == 200
    assert cap["clean"]["vehicles"] == [{"id": 1453377785, "label": "Car 12V"}]
    body, status = save(p, dict(_base(), vehicles={"id": 1}))
    assert status == 400


# ── Review 24-09-2026 [48]: malformed values are named 400s, never bare 500s ──

def _raw_save(p, raw):
    reply = p.handleSaveDashboardsConfig(FakeAction(raw))
    return json.loads(reply["content"]), reply["status"]


def test_wrongly_typed_camera_settings_are_a_named_400():
    for cfg, word in (({"swapOutHost": 5}, "swapOutHost"),
                      ({"mainCameras": [5]}, "mainCameras"),
                      ({"mainCameras": [["a"]]}, "mainCameras"),
                      ({"mainCameras": "10.0.0.5"}, "mainCameras")):
        p, cap = make_plugin()
        body, status = save(p, cfg)
        assert status == 400 and word in body["error"], (cfg, status, body)
        assert "clean" not in cap


def _group_fav(level):
    return ('{"config": {"favourites": [{"type": "group", "label": "G", '
            '"devices": [{"id": 1, "onLevel": ' + level + '}]}]}}')


def test_an_infinite_on_level_is_dropped_not_a_500():
    p, cap = make_plugin()
    body, status = _raw_save(p, _group_fav("1e999"))
    assert status == 200, body
    assert "onLevel" not in cap["clean"]["favourites"][0]["devices"][0]


def test_a_nan_colour_band_is_dropped_and_the_reply_stays_json():
    p, cap = make_plugin()
    body, status = save(p, {"favourites": [{"type": "device", "id": 7, "state": "temp",
                                            "label": "T", "warnBelow": "nan",
                                            "badBelow": 5}]})
    assert status == 200
    fav = cap["clean"]["favourites"][0]
    assert "warnBelow" not in fav and fav["badBelow"] == 5.0
    json.dumps(cap["clean"], allow_nan=False)


def test_a_non_finite_passthrough_key_is_refused():
    p, cap = make_plugin()
    body, status = _raw_save(p, '{"config": {"arrayKwp": NaN}}')
    assert status == 400 and "not finite" in body["error"]
    assert "clean" not in cap


def test_an_unforeseen_fault_is_answered_as_json():
    p, cap = make_plugin()
    def boom(cfg):
        raise KeyError("surprise")
    p._apply_config_checked = boom
    body, status = save(p, {})
    assert status == 500 and body["ok"] is False and "surprise" in body["error"]


def test_the_store_is_never_written_with_nan(tmp_path):
    import pytest
    p = bare_plugin()
    p._store_unreadable = ""
    p._config_store_path = lambda: str(tmp_path / "dashboards_config.json")
    with pytest.raises(ValueError):
        p._save_config_store({"x": float("nan")})
    assert list(tmp_path.iterdir()) == []


def test_a_swap_out_host_that_matches_no_camera_is_cleared():
    """Lows batch [75]: re-addressing the swap-out camera left swapOutHost
    pointing at nothing, stored without a word. It now means 'the last in the
    list', and a matching host still round-trips."""
    p, cap = make_plugin()
    body, status = save(p, {
        "cameras": [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua"}],
        "swapOutHost": "10.0.0.9",
    })
    assert status == 200 and body["ok"] is True
    assert cap["clean"]["swapOutHost"] == ""
    p, cap = make_plugin()
    save(p, {"cameras": [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua"}],
             "swapOutHost": " 10.0.0.5 "})
    assert cap["clean"]["swapOutHost"] == "10.0.0.5"


def test_unhashable_camera_host_is_a_400_not_a_500():
    """DB-01 (audit 05-10-2026): a camera whose host is a list or an object
    must come back as the validation errors, not crash building the set of
    camera hosts with "unhashable type" (a 500 that hid every other error)."""
    p, _ = make_plugin()
    for bad in (["10.0.0.5"], {"ip": "10.0.0.5"}):
        body, status = save(p, {
            "cameras": [{"host": bad, "name": "Front", "vendor": "dahua"}],
            "mainCameras": ["10.0.0.5"],
        })
        assert status == 400, (bad, status, body)
        assert body["ok"] is False
        assert "camera 1" in body["error"]


# ── 3.68.0: page-link favourites ──────────────────────────────────────────
def test_page_favourites_keep_known_pages_and_drop_links_off_the_site():
    p, cap = make_plugin()
    save(p, {"favourites": [
        {"type": "page", "page": "flow.html", "label": " Sigenergy "},
        {"type": "page", "page": "menu.html?g=rooms"},
        {"type": "page", "page": "javascript:alert(1)"},
        {"type": "page", "page": "https://example.com/x.html"},
        {"type": "page", "page": "//example.com/x.html"},
        {"type": "page", "page": "../secret.html"},
        {"type": "page", "page": "flow.html\" onclick=\"x"},
        {"type": "page", "page": ""},
        {"type": "page"},
        {"type": "page", "page": "a" * 80 + ".html"},
    ]})
    assert cap["clean"]["favourites"] == [
        {"type": "page", "page": "flow.html", "label": "Sigenergy"},
        {"type": "page", "page": "menu.html?g=rooms"},
    ]


# ---- review 26-11-2026 ------------------------------------------------------

FULL_STORE = {
    "actionWatch": {"780532115": {"title": "Garage", "timeoutSec": 30, "zz": 1,
                                  "rules": [{"phase": "done", "text": "Closed", "when": {"state": "closed"}}]}},
    "arrayKwp": 14.25,
    "cameras": [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua", "room": "Hall", "stream": "main"},
                {"host": "10.0.0.6", "name": "Drive", "vendor": "dahua", "room": ["Drive", "Garage"]}],
    "customLinks": [{"title": "MQTT", "url": "http://10.0.0.2:4000/", "desc": "broker", "icon": "bolt"}],
    "favourites": [
        {"type": "door", "id": 7, "label": "Front Door", "lockId": 8, "openAction": 1},
        {"type": "door", "id": 9, "label": "Garage", "openAction": 2, "closeAction": 3},
        {"type": "device", "id": 5, "label": "Qashqai 12V", "state": "voltage", "warnBelow": 12.2, "badBelow": 11.8},
        {"type": "device", "id": 6},
        {"type": "scene", "id": 4, "label": "Movie"},
        {"type": "group", "label": "Lamps", "devices": [{"id": 1, "onLevel": 100}, {"id": 2, "openLoop": True}]},
        {"type": "room", "room": "Living Room"},
        {"type": "page", "page": "savings.html", "label": "Savings"},
    ],
    "hiddenScenes": ["folder:Test", "123"],
    "mainCameras": ["10.0.0.5"],
    "pinRequired": [7, 8],
    "roomExtras": {
        "Garage": {"doors": [{"label": "Garage Door", "deviceId": 9, "openAction": 2, "closeAction": 3}],
                   "include": {"motion": [1], "sensors": [2]}, "hideDeviceIds": [3], "plugs": [4], "zz": {"a": 1}},
        "Living Room": {"mainLight": [1], "openLoop": [2], "tv": [3, 4], "fire": [5],
                        "sortOrder": {"lights": [6]}, "appliances": [{"label": "Washer", "monitorId": 1, "cycleId": 2}]},
    },
    "roomFolders": ["Garage", "Living Room"],
    "savings": {"systemCost": 26470, "installDate": "2026-03-12", "quoteAnnualSaving": 2352,
                "quoteAnnualKwh": 9112, "quotePaybackYears": 12},
    "siteName": "Highsteads",
    "swapOutHost": "10.0.0.6",
    "vehicles": [{"id": 5, "label": "Qashqai"}],
    "futureKey": {"kept": True},
}


def test_an_unchanged_save_keeps_every_stored_key():
    """What the Settings page posts after a load with nothing changed is the
    store itself (proved on the live page 25-11-2026). The server must hand
    back the same store: every known key as it was, every unknown one too,
    and the keys a browser never sees carried over from the running plugin."""
    import copy
    p, cap = make_plugin()
    p.control_pin = "4321"
    p.cfg_store = dict(copy.deepcopy(FULL_STORE), controlPin="4321", stillsToken="ab" * 16,
                       alertRules=[{"id": "r1", "name": "Door"}], alertRulesRev=3, alertsActive=True,
                       alertEmail="", _savedAt=1.0)
    want = dict(copy.deepcopy(p.cfg_store))
    want.pop("_savedAt")
    sent = dict(copy.deepcopy(FULL_STORE), controlPin="")          # blank keeps the PIN
    body, status = save(p, sent)
    assert status == 200 and body["ok"] is True, body
    kept = dict(cap["clean"])
    assert kept == want
    assert json.dumps(kept, sort_keys=True) == json.dumps(want, sort_keys=True)      # types too


def test_a_swap_out_left_at_its_default_needs_no_restart():
    """Blank means the last camera, which is what the running plugin holds;
    comparing "" with that host said "restart needed" on every save."""
    p, _ = make_plugin()
    cams = [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua", "room": "", "stream": "sub2"},
            {"host": "10.0.0.6", "name": "Drive", "vendor": "dahua", "room": "", "stream": "sub2"}]
    p.cameras = cams
    p.swap_out_host = "10.0.0.6"                 # what __init__ makes of a blank setting
    body, status = save(p, {"cameras": [dict(c) for c in cams], "swapOutHost": ""})
    assert status == 200 and body["cameraRestartNeeded"] is False
    body, _ = save(p, {"cameras": [dict(c) for c in cams], "swapOutHost": "10.0.0.5"})
    assert body["cameraRestartNeeded"] is True


def test_a_save_whose_page_rebuild_failed_says_so():
    """The store is written, then config.js, rooms.json and scenes.json are
    rebuilt. One of those failing used to be a log line only, and the reply
    still let the page say 'live on the pages now'."""
    p, _ = make_plugin()

    def boom():
        raise OSError("disk full")
    p._build_rooms_json = boom
    body, status = save(p, {"cameras": []})
    assert status == 200 and body["ok"] is True
    assert body["refreshed"] is False and "rooms" in body["refreshError"] and "disk full" in body["refreshError"]
    assert p._write_config_js.called and p._build_scenes_json.called      # the others still ran

    p2, _ = make_plugin()
    body, _ = save(p2, {"cameras": []})
    assert body["refreshed"] is True and "refreshError" not in body
