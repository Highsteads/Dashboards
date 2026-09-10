#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_mains_meters.py
# Description: Contract tests for the Mains instrument page's pure helpers
#              (v3.7.0) — power factor, reading liveness, calibration offsets,
#              fleet spread and unmetered load. Every one of these guards a
#              mistake that was actually made on this estate on 08-09-2026.
# Author:      CliveS & Claude Opus 5
# Date:        08-09-2026
# Version:     1.0

import pytest
from conftest import bare_plugin


@pytest.fixture(scope="module")
def P():
    return bare_plugin()


# ── power factor ─────────────────────────────────────────────────────────────

def test_a_reported_power_factor_is_used_as_is(P):
    """The Athom plugs report PF directly and it is the better number."""
    assert P._mains_power_factor(9.0, 249.4, 0.04, reported=0.94) == (0.94, "reported")


def test_power_factor_is_derived_when_the_meter_does_not_report_it(P):
    """The live Samsung TV: 253.5 V x 0.218 A = 55.3 VA against 34.6 W."""
    pf, source = P._mains_power_factor(34.6, 253.5, 0.218)
    assert source == "derived"
    assert 0.61 <= pf <= 0.63, pf


def test_watts_are_NEVER_derived_from_volts_times_amps(P):
    """The whole trap. V x A on that television reads 55 VA against a real
    34.6 W — a 60% overstatement. This helper returns a RATIO and nothing
    else, so there is no path by which it can produce a wattage."""
    out = P._mains_power_factor(34.6, 253.5, 0.218)
    assert isinstance(out, tuple) and len(out) == 2
    assert out[0] <= 1.0

def test_a_tiny_load_gives_no_power_factor_rather_than_a_wrong_one(P):
    """At 0.02 A the current channel's own error is most of the number."""
    pf, why = P._mains_power_factor(0.2, 252.0, 0.001)
    assert pf is None and "too small" in why


def test_an_impossible_power_factor_is_refused_not_printed(P):
    """Above unity means the two channels disagree beyond their error budget."""
    pf, why = P._mains_power_factor(300.0, 250.0, 1.0)
    assert pf is None and "disagree" in why


def test_a_missing_reading_gives_no_power_factor(P):
    assert P._mains_power_factor(None, 250.0, 1.0)[0] is None
    assert P._mains_power_factor(100.0, None, 1.0)[0] is None
    assert P._mains_power_factor(100.0, 250.0, "x")[0] is None


def test_a_nonsense_reported_value_falls_through_to_deriving(P):
    """A meter reporting PF 0.0 for a live load (the dead Tasmota does) must
    not be believed over the arithmetic."""
    pf, source = P._mains_power_factor(34.6, 253.5, 0.218, reported=0.0)
    assert source == "derived"


# ── liveness: a value is not a measurement ───────────────────────────────────

def test_a_fresh_reading_is_live(P):
    assert P._mains_liveness(30, owner_running=True)[0] == "live"


def test_an_old_reading_is_stale_and_says_how_old(P):
    state, why = P._mains_liveness(3600, owner_running=True)
    assert state == "stale" and "1 hour" in why


def test_a_stopped_plugin_makes_every_reading_dead_however_fresh(P):
    """The Kitchen Extractor read 291.0 V on 08-09-2026 — impossible, frozen,
    and its plugin has not been installed since July. Without this the page
    would present that as a dangerous over-voltage."""
    state, why = P._mains_liveness(5, owner_running=False)
    assert state == "dead" and "not running" in why


def test_a_device_that_never_reported_is_dead_not_zero(P):
    assert P._mains_liveness(None, owner_running=True)[0] == "dead"


# ── a quiet meter is not a broken one ────────────────────────────────────────

def test_a_report_on_change_meter_that_is_quiet_is_live(P):
    """THE BUG THE FIRST LIVE RUN FOUND. A Z-Wave dimmer reports only when
    something changes, so silence means nothing changed. The page greyed out
    the Kitchen Cupboard Lights as 'stale, 10 days' while they were drawing
    75.9 W in front of everyone. lastSuccessfulComm is not health on Z-Wave."""
    state, why = P._mains_liveness(10 * 86400, owner_running=True, continuous=False)
    assert state == "live" and why == ""


def test_a_polling_meter_that_goes_quiet_is_still_stale(P):
    """The other half — a Shelly answers every 35 seconds, so silence IS a
    fault. Losing this would hide a plug that has dropped off the network."""
    assert P._mains_liveness(3600, owner_running=True, continuous=True)[0] == "stale"


def test_an_error_state_is_dead_whatever_the_age(P):
    """errorState is the Z-Wave health signal, and it outranks a fresh clock."""
    state, why = P._mains_liveness(5, owner_running=True, continuous=False,
                                   error_state="unreachable")
    assert state == "dead" and "unreachable" in why


def test_the_owning_plugins_own_offline_flag_is_believed(P):
    """ShellyDirect maintains deviceOnline itself and knows before the clock."""
    state, why = P._mains_liveness(5, owner_running=True, online=False)
    assert state == "dead" and "not answering" in why


def test_a_stopped_plugin_outranks_every_other_signal(P):
    """Order matters: a plugin that is not running makes deviceOnline and
    errorState meaningless, because nothing is maintaining them."""
    state, why = P._mains_liveness(5, owner_running=False, online=True,
                                   error_state="", continuous=False)
    assert state == "dead" and "not running" in why


def test_a_quiet_meter_with_no_fault_is_never_called_stale(P):
    """Guards the direction that matters: false staleness hides a real fault
    among a crowd of invented ones."""
    for age in (0, 3600, 86400, 200 * 86400):
        assert P._mains_liveness(age, owner_running=True, continuous=False)[0] == "live"


# ── durations in English ─────────────────────────────────────────────────────

@pytest.mark.parametrize("secs,want", [
    (0, "a moment"), (1, "1 second"), (5, "5 seconds"), (60, "60 seconds"), (120, "2 minutes"),
    (60 * 60, "1 hour"), (2 * 3600, "2 hours"), (86400 * 3, "3 days"),
    (86400, "24 hours"),
])
def test_durations_read_the_way_a_person_says_them(P, secs, want):
    assert P._mains_ago(secs) == want


def test_a_duration_is_singular_when_it_is_one(P):
    """Every branch. "1 seconds ago" reached the detail page's hero because
    this test named the hour and the day and never the second."""
    assert P._mains_ago(0) == "a moment"     # not "0 seconds ago"
    assert P._mains_ago(1) == "1 second"
    assert P._mains_ago(60) == "60 seconds"
    assert P._mains_ago(3600) == "1 hour"
    assert P._mains_ago(86400 * 2) == "2 days"


# ── calibration offsets ──────────────────────────────────────────────────────

def test_an_offset_needs_enough_pairs_to_mean_anything(P):
    """Six samples cannot separate a calibration offset from a busy afternoon."""
    assert P._mains_offset_stats([2.0] * 6) is None


def test_an_offset_is_reported_once_there_are_enough(P):
    """The measured Shelly figure: about +2 V against the inverter."""
    stats = P._mains_offset_stats([1.9, 2.0, 2.1] * 40)
    assert stats["pairs"] == 120
    assert stats["mean"] == 2.0 and stats["median"] == 2.0


def test_the_offset_keeps_the_extremes_so_scatter_is_visible(P):
    stats = P._mains_offset_stats([2.0] * 60 + [0.8, 3.5])
    assert stats["min"] == 0.8 and stats["max"] == 3.5


def test_non_numeric_samples_are_ignored_not_counted(P):
    assert P._mains_offset_stats([None, "x"] * 60) is None


# ── fleet spread: the number the page exists to show ─────────────────────────

def test_the_spread_is_the_real_measured_disagreement(P):
    """Athom -1.70 and -0.93, Shelly +1.96 — 3.66 V apart, about 1.5%."""
    s = P._mains_spread({"athom1": -1.70, "athom2": -0.93, "shelly": 1.96})
    assert s["meters"] == 3 and s["low"] == -1.7 and s["high"] == 1.96
    assert s["spread"] == 3.66


def test_one_meter_alone_has_no_spread(P):
    assert P._mains_spread({"only": 1.0}) is None
    assert P._mains_spread({}) is None


# ── unmetered load ───────────────────────────────────────────────────────────

def test_the_residual_is_what_no_meter_can_see(P):
    watts, why = P._mains_unmetered(1200.0, 450.0)
    assert watts == 750.0 and why == ""


def test_a_negative_residual_is_refused_because_it_is_not_a_reading(P):
    """Meters reading higher than the house total means they disagree by more
    than the load, not that the house is generating in the hall."""
    watts, why = P._mains_unmetered(300.0, 500.0)
    assert watts is None and "higher than" in why


def test_a_small_negative_is_rounded_to_zero_rather_than_refused(P):
    """Instrument noise either side of zero is not a fault worth shouting."""
    watts, why = P._mains_unmetered(300.0, 320.0)
    assert watts == 0.0 and why == ""


def test_no_whole_house_reading_gives_no_residual(P):
    assert P._mains_unmetered(None, 100.0)[0] is None


# ── which reading counts as watts ────────────────────────────────────────────
# The page named seventeen meters in its trust panel and listed fifteen in its
# census, because both relay-less Athom power monitors put their real power in
# the native `sensorValue` and carry none of the usual names. They were also
# the two LOWEST readers, so the voltage map's visible spread read 1.8 V
# against a measured 3.7 V.

ATHOM = {"sensorValue": 9.4, "voltage": 249.68, "current": 0.04,
         "powerFactor": 0.94, "totalEnergy": 87.7}
LUX = {"sensorValue": 412.0}
SHELLY = {"powerWatts": 34.6, "voltage": 253.5, "currentAmps": 0.218}


def test_a_named_power_state_is_preferred(P):
    assert P._mains_watts(SHELLY, 253.5) == 34.6


def test_a_relayless_esphome_monitor_is_read_from_its_native_sensor_value(P):
    """Without this both Athom freezer plugs vanish from the census."""
    assert P._mains_watts(ATHOM, 249.68) == 9.4


def test_sensor_value_is_only_watts_where_there_is_a_mains_voltage(P):
    """A lux sensor reads 412 and must never be shown as 412 W. The voltage
    gate is what separates them: 17 devices here carry sensorValue and only
    the two mains monitors report a mains-range voltage."""
    assert P._mains_watts(LUX, None) is None


def test_a_named_power_state_wins_even_when_sensor_value_is_present(P):
    """Order matters: a device carrying both must not be read off the generic
    one, which on a dimmer is a brightness level."""
    both = dict(SHELLY, sensorValue=99.0)
    assert P._mains_watts(both, 253.5) == 34.6


def test_a_device_with_neither_is_not_a_mains_meter(P):
    assert P._mains_watts({"temperature": 18.4}, None) is None
    assert P._mains_watts({"temperature": 18.4, "voltage": 250.0}, 250.0) is None


def test_watts_are_never_invented_from_volts_and_amps(P):
    """A meter reporting volts and amps but no power gets no wattage at all —
    V x A on a switch-mode supply overstates the load by more than half."""
    assert P._mains_watts({"voltage": 253.5, "currentAmps": 0.218}, 253.5) is None


# ── the detail page's helpers ────────────────────────────────────────────────
# The detail page exists because CliveS could not tell his two Athom plugs
# apart — both carry their ESPHome discovery name and nothing said which was
# which. It therefore shows a device's own configuration, and one family keeps
# a real credential in there.

def test_an_encryption_key_never_reaches_the_browser(P):
    """MEASURED: an esphomeSensor carries `encryptionKey` in its props."""
    out = P._mains_redact({"encryptionKey": "s3cret", "ip": "192.168.1.50"})
    assert out["encryptionKey"] == "(hidden)"
    assert out["ip"] == "192.168.1.50"


def test_a_redacted_key_is_kept_and_marked_not_dropped(P):
    """Dropping the row would read as the device not having one."""
    assert "encryptionKey" in P._mains_redact({"encryptionKey": "x"})


@pytest.mark.parametrize("key", [
    "password", "Passwd", "apiToken", "clientSecret", "apiKey", "api_key",
    "privateKey", "AUTHORIZATION", "sessionCookie", "userCredential",
])
def test_anything_that_could_be_a_credential_is_hidden(P, key):
    assert P._mains_redact({key: "x"})[key] == "(hidden)"


@pytest.mark.parametrize("key", [
    "entityKeyMap", "zwEndpointClassMap", "ip_address", "mac_address",
    "friendly_name", "hostname", "boardModel", "poll_interval",
])
def test_the_identifying_details_are_NOT_hidden(P, key):
    """These are the whole point of the page — `endswith("key")` rather than
    `"key" in ...` is what keeps entityKeyMap visible."""
    assert P._mains_redact({key: "v"})[key] == "v"


def test_redaction_is_ordered_so_the_page_is_stable_between_polls(P):
    out = P._mains_redact({"zeta": 1, "Alpha": 2, "mid": 3})
    assert list(out) == ["Alpha", "mid", "zeta"]


def test_no_props_is_an_empty_dict_not_a_crash(P):
    assert P._mains_redact(None) == {} and P._mains_redact({}) == {}


def test_the_source_names_the_state_the_meter_actually_answers_with(P):
    """The chart needs the COLUMN, and every family keeps power elsewhere."""
    assert P._mains_source({"powerWatts": 3.0}, ("powerWatts", "power")) == "powerWatts"
    assert P._mains_source({"power": 3.0}, ("powerWatts", "power")) == "power"
    assert P._mains_source({"other": 3.0}, ("powerWatts", "power")) is None


def test_a_present_but_unreadable_state_is_not_offered_as_a_source(P):
    """A charted column that holds text produces an empty graph and no error."""
    assert P._mains_source({"powerWatts": "n/a", "power": 3.0},
                           ("powerWatts", "power")) == "power"


def test_every_reading_carries_the_meters_own_display_string(P):
    """Indigo keeps the formatted value in a sibling `.ui` state, so the units
    come free rather than from a table this page would have to maintain."""
    out = P._mains_states({"voltage": 249.68, "voltage.ui": "249.68 V"})
    assert out == [{"name": "voltage", "value": 249.68, "display": "249.68 V"}]


def test_the_ui_rows_are_folded_in_rather_than_listed(P):
    """Listing them shows every reading twice."""
    names = [r["name"] for r in P._mains_states(
        {"a": 1, "a.ui": "1 W", "b": 2, "b.ui": "2 V"})]
    assert names == ["a", "b"]


def test_a_reading_with_no_display_string_still_appears(P):
    assert P._mains_states({"sysUptime": 4210})[0] == {
        "name": "sysUptime", "value": 4210, "display": None}


def test_readings_are_sorted_case_insensitively_so_the_page_does_not_jump(P):
    names = [r["name"] for r in P._mains_states({"Zeta": 1, "alpha": 2, "Mid": 3})]
    assert names == ["alpha", "Mid", "Zeta"]


# ── Indigo's own container types ─────────────────────────────────────────────
# A Z-Wave dimmer's props carry eight indigo.Dict values, and json.dumps
# refuses them: "Object of type Dict is not JSON serializable". One prop 500'd
# the whole endpoint, so every Z-Wave meter's detail page failed while the
# other three families were fine.

class _IndigoDictLike(dict):
    """Stands in for indigo.Dict: dict-like, and json refuses it."""
    def __repr__(self):
        return "zwClassCmdMap"


class _Unserialisable:
    def __repr__(self):
        return "<indigo.List>"


def test_a_value_json_can_carry_is_left_alone(P):
    for v in ("text", 12, 4.5, True, None, [1, 2], {"a": 1}):
        assert P._mains_jsonable(v) == v


def test_a_value_json_refuses_becomes_its_string_form(P):
    assert P._mains_jsonable(_Unserialisable()) == "<indigo.List>"


def test_a_zwave_props_dict_does_not_take_the_endpoint_down(P):
    """The whole page 500'd on one prop before this."""
    import json
    props = {"zwClassCmdMap": _Unserialisable(), "address": "158"}
    out = P._mains_redact(props)
    json.dumps(out)                      # would raise before the fix
    assert out["zwClassCmdMap"] == "<indigo.List>"
    assert out["address"] == "158"


def test_a_readings_value_is_always_serialisable_too(P):
    import json
    json.dumps(P._mains_states({"zwMap": _Unserialisable(), "watts": 4.0}))


def test_a_hidden_credential_is_still_hidden_when_it_is_not_a_string(P):
    """Redaction must run BEFORE the coercion, or an object-valued secret
    would be stringified into the reply instead of being replaced."""
    assert P._mains_redact({"encryptionKey": _Unserialisable()})["encryptionKey"] == "(hidden)"


# ── a switched-off meter that never sent its zero ────────────────────────────
# Read from the Kitchen Cupboard Lights' own history: ON at 09:30:47, reported
# 75.9 W at 09:30:53, OFF at 09:30:57, silent for the ten days after. The
# census counted 75.9 W of light that was off, so the metered total was high
# and the unmetered residual — house minus meters — was short by the same.

ON_CHANGE_OFF = {"curEnergyLevel": 75.9, "onOffState": False, "brightnessLevel": 0}
ON_CHANGE_ON  = {"curEnergyLevel": 75.9, "onOffState": True, "brightnessLevel": 100}
POLLING_OFF   = {"powerWatts": 0.4, "voltage": 252.0, "onOffState": False}


def test_a_switched_off_on_change_meter_is_not_still_drawing(P):
    assert P._mains_reading_is_stale_off(75.9, None, ON_CHANGE_OFF) is True


def test_a_switched_on_meter_is_believed(P):
    assert P._mains_reading_is_stale_off(75.9, None, ON_CHANGE_ON) is False


def test_a_POLLING_meter_that_is_off_is_believed(P):
    """A Shelly re-reads every ~35 s, so its 0.4 W was measured moments ago
    and is real standby. Only a silent device can be frozen."""
    assert P._mains_reading_is_stale_off(0.4, 252.0, POLLING_OFF) is False


def test_a_meter_with_no_on_off_state_is_left_alone(P):
    """Most meters have no switch to disagree with."""
    assert P._mains_reading_is_stale_off(75.9, None, {"curEnergyLevel": 75.9}) is False


def test_a_meter_already_reading_zero_needs_no_correction(P):
    assert P._mains_reading_is_stale_off(0.0, None, {"onOffState": False}) is False
    assert P._mains_reading_is_stale_off(-3.0, None, {"onOffState": False}) is False


def test_an_unreadable_wattage_is_not_corrected(P):
    assert P._mains_reading_is_stale_off(None, None, {"onOffState": False}) is False
    assert P._mains_reading_is_stale_off("x", None, {"onOffState": False}) is False


def test_the_reading_that_was_dropped_is_kept_so_the_page_can_say_so(P):
    """Zeroing it silently loses 75.9 W; a tile has to be able to say
    "switched off, last drew 75.9 W" or the number just vanishes."""
    assert P._mains_settled_watts(75.9, None, ON_CHANGE_OFF) == (0.0, 75.9)


def test_a_good_reading_passes_through_untouched_with_nothing_to_report(P):
    assert P._mains_settled_watts(75.9, None, ON_CHANGE_ON) == (75.9, None)
    assert P._mains_settled_watts(0.4, 252.0, POLLING_OFF) == (0.4, None)


# ── "am I reachable" is said four different ways ─────────────────────────────
# Only ShellyDirect's deviceOnline was read, so an Athom that dropped off the
# wi-fi at 21:06 kept its last reading and the census went on counting 793.79 W
# for it — a bigger error than the 76 W the switched-off rule had just removed.

def test_shellys_boolean_flag_is_read(P):
    assert P._mains_online({"deviceOnline": True}) is True
    assert P._mains_online({"deviceOnline": False}) is False


def test_esphomes_connected_flag_is_read(P):
    assert P._mains_online({"connected": True, "status": "Online"}) is True
    assert P._mains_online({"connected": False, "status": "Disconnected"}) is False


def test_tasmotas_capitalised_string_is_read(P):
    """bool("Offline") is True, which is exactly the value that matters."""
    assert P._mains_online({"availability": "Offline"}) is False
    assert P._mains_online({"availability": "Online"}) is True


def test_zigbees_lowercase_string_is_read(P):
    """Two plugins use the same state name with different casing."""
    assert P._mains_online({"availability": "online"}) is True
    assert P._mains_online({"availability": "offline"}) is False


def test_a_zwave_device_says_nothing_and_that_is_not_a_fault(P):
    """Quiet is normal on Z-Wave, and None lets the liveness rule decide."""
    assert P._mains_online({"curEnergyLevel": 75.9, "onOffState": True}) is None


def test_a_word_we_do_not_recognise_is_not_read_as_healthy(P):
    """Not knowing is not the same as being well."""
    assert P._mains_online({"availability": "reconfiguring"}) is None


def test_the_first_flag_the_device_carries_wins(P):
    assert P._mains_online({"deviceOnline": False, "availability": "online"}) is False


def test_a_numeric_flag_is_still_understood(P):
    assert P._mains_online({"connected": 1}) is True
    assert P._mains_online({"connected": 0}) is False


def test_a_disconnected_meter_is_dead_however_fresh_its_timestamp(P):
    """The Athom's lastSuccessfulComm was 30 seconds old while its own
    connected flag said False and its reading had been frozen for minutes."""
    assert P._mains_liveness(30, owner_running=True, continuous=True,
                             online=False) == ("dead", "the device is not answering")
