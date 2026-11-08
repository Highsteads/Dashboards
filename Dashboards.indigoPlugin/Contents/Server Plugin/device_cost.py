#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    device_cost.py
# Description: What one plug-metered device costs to run. Pure - no Indigo, no
#              database - so the tests check the arithmetic directly. Used by
#              the Air page (3.63.0) for the purifier's plug, and by the Plugs
#              page (3.69.0) for every plug that measures its own energy.
# Author:      CliveS & Claude Opus 5.5
# Date:        08-11-2026 19:30
# Version:     1.1
#
# 1.1 (08-11-2026): a small step back in a reading is jitter, not a restart
#     (is_restart) - the Air page's "today" was counting the day again at each
#     one. Also meter_for (which state a device counts energy in),
#     counter_slices (a counter that only goes up), daily_kwh, rate_for_day
#     (the cheap rate that was published for a given day) and money_words.
#
# PRICED AT THE CHEAP RATE ONLY (CliveS, 24-10-2026): "we should only be using
# battery which is charged at the low rate, then use the 2-5am Flux amount only
# for the cost". The house runs from a battery filled in Flux's cheap window,
# so every kWh the device uses is priced at that window's rate, whenever it
# was used. The rate is the LOWEST of today's published spans
# (SigenEnergyManager's elec_rates_today_json, Octopus's own UTC spans), so it
# follows Octopus if the price or the hours move.

import json
from datetime import datetime

DAY_MINUTES = 1440


def _local_minute(dt):
    local = dt.astimezone()                      # the host's zone, with its DST
    return local.hour * 60 + local.minute


def cheap_rate(rates_json):
    """(pence, start_minute, end_minute) of the cheapest published span, in
    local time of day, or None when nothing usable is published."""
    try:
        spans = json.loads(rates_json) if isinstance(rates_json, str) else list(rates_json or [])
    except (TypeError, ValueError):
        return None
    best = None
    for span in spans:
        try:
            start = datetime.fromisoformat(str(span["valid_from"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(span["valid_to"]).replace("Z", "+00:00"))
            pence = float(span["value_inc_vat"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start or pence < 0:
            continue
        if best is None or pence < best[0]:
            best = (pence, _local_minute(start), _local_minute(end))
    return best


# A reading this much lower than the one before is the counter starting
# again. Anything smaller is jitter: a Shelly's energyKwhToday steps back by
# a few watt-hours about 50 times a day (two reports crossing, measured on
# the dehumidifier plug 08-11-2026), and counting each of those as a restart
# added the whole day again every time - 62 kWh for a plug that used 2.4.
RESTART_FRACTION = 0.5      # the new reading is under half the old one
RESTART_MIN_KWH = 0.01      # and at least 10 Wh lower


def is_restart(prev, kwh):
    """True when a lower reading is the counter starting again, not jitter."""
    return kwh < prev * RESTART_FRACTION and prev - kwh >= RESTART_MIN_KWH


def kwh_slices(rows):
    """[(epoch, kwh)] used between readings, from [(epoch, energy today)]
    rows in time order. The counter starts again from 0 at local midnight,
    so the first reading on a new day, or one well below the one before
    (is_restart), is energy since that restart - which also covers a gap in
    the readings over midnight, where the next day's figure must not be read
    as one slice. A small step back is jitter: it is ignored, and the higher
    reading stays the one to count on from, so the climb back is not counted
    twice."""
    out = []
    prev = None
    prev_day = None
    for epoch, kwh in rows:
        try:
            kwh = float(kwh)
            day = datetime.fromtimestamp(int(epoch)).date()
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        if kwh != kwh or kwh < 0:                 # NaN, or nonsense
            continue
        if prev is None:
            prev, prev_day = kwh, day
            continue
        if day != prev_day or is_restart(prev, kwh):
            used, prev = kwh, kwh
        elif kwh < prev:
            used = 0                              # jitter: keep the higher reading
        else:
            used, prev = kwh - prev, kwh
        prev_day = day
        if used > 0:
            out.append((int(epoch), used))
    return out


def kwh_between(slices, since_epoch, until_epoch=None):
    """kWh used in [since_epoch, until_epoch)."""
    return round(sum(used for epoch, used in slices
                     if epoch >= since_epoch and (until_epoch is None or epoch < until_epoch)), 4)


def cost_pence(kwh, rate):
    """Pence for kWh at the rate, or None when no rate is known."""
    if rate is None or kwh is None:
        return None
    return round(float(kwh) * float(rate), 2)


def clock_words(minute):
    """2am, 4:30pm."""
    h = (int(minute) // 60) % 24
    m = int(minute) % 60
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}{suffix}" if m == 0 else f"{h12}:{m:02d}{suffix}"


def rate_words(cheap):
    """'15.5p a unit, the 2am to 5am rate' - what the page says it used."""
    if not cheap:
        return ""
    pence, a, b = cheap
    return f"{pence:.1f}p a unit, the {clock_words(a)} to {clock_words(b)} rate"


# ---- the Plugs page (1.1) ------------------------------------------------

# How each kind of plug reports its energy. "daily" counts from 0 each local
# midnight (ShellyDirect's energyKwhToday); "lifetime" only goes up, apart
# from a reset (a Zigbee plug's energy, an ESPHome monitor's totalEnergy).
# The column is the SQL Logger's lower-case name for the state.
SHELLY_PLUGIN = "com.clives.indigoplugin.shellydirect"
Z2M_PLUGIN = "com.clives.indigoplugin.z2mbridge"
ESPHOME_PLUGIN = "com.clives.indigoplugin.esphomebridge"


def meter_for(plugin_id, state_keys):
    """(state, column, kind) for a device that measures its own energy, or
    None. state_keys is the device's states, or just their names."""
    keys = set(state_keys or ())
    if plugin_id == SHELLY_PLUGIN and "energyKwhToday" in keys:
        return ("energyKwhToday", "energykwhtoday", "daily")
    if plugin_id == Z2M_PLUGIN and "energy" in keys:
        return ("energy", "energy", "lifetime")
    if plugin_id == ESPHOME_PLUGIN and "totalEnergy" in keys:
        return ("totalEnergy", "totalenergy", "lifetime")
    return None


def counter_slices(rows):
    """[(epoch, kwh)] used between readings of a counter that only goes up.
    A reading well below the one before (is_restart) is a reset, so it counts
    as energy since that reset; a small step back is jitter and is ignored.
    Each slice is dated by the later reading."""
    out = []
    prev = None
    for epoch, kwh in rows:
        try:
            kwh = float(kwh)
            epoch = int(epoch)
        except (TypeError, ValueError, OverflowError):
            continue
        if kwh != kwh or kwh < 0:                 # NaN, or nonsense
            continue
        if prev is None:
            prev = kwh
            continue
        if is_restart(prev, kwh):
            used, prev = kwh, kwh
        elif kwh < prev:
            used = 0
        else:
            used, prev = kwh - prev, kwh
        if used > 0:
            out.append((epoch, used))
    return out


def slices_for(rows, kind):
    """The slices for either kind of counter."""
    return kwh_slices(rows) if kind == "daily" else counter_slices(rows)


def daily_kwh(slices, day_starts):
    """kWh used on each day: day_starts are the local-midnight epochs, oldest
    first, and the last day runs to now. Returns a list the same length."""
    out = []
    for i, start in enumerate(day_starts):
        end = day_starts[i + 1] if i + 1 < len(day_starts) else None
        out.append(kwh_between(slices, start, end))
    return out


def rate_for_day(published, day_start, day_end):
    """The cheap rate published FOR a day, from [(epoch written, rates json)]
    in time order (the SQL Logger's history of elec_rates_today_json). The
    list a day is priced from is the last one written before the day ended;
    one written before the day began belongs to the day before. None when no
    list was written during the day (the rate is then unknown, and the day's
    energy is shown without a price rather than at some other day's rate)."""
    best = None
    for epoch, value in published:
        try:
            epoch = int(epoch)
        except (TypeError, ValueError):
            continue
        if day_start <= epoch < day_end:
            best = value
    return cheap_rate(best) if best is not None else None


def money_words(pence):
    """42p, 4.2p, \u00a32.61 - as a person writes it."""
    if pence is None:
        return ""
    pence = float(pence)
    if pence == 0:
        return "0p"
    if round(pence, 1) < 10:
        return f"{pence:.1f}p"
    if round(pence) < 100:                       # 99.6p reads as \u00a31.00, not 100p
        return f"{round(pence):.0f}p"
    return "\u00a3" + f"{pence / 100:.2f}"
