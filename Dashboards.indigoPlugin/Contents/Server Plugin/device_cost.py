#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    device_cost.py
# Description: What one plug-metered device costs to run. Pure - no Indigo, no
#              database - so the tests check the arithmetic directly. Used by
#              the Air page (3.63.0) for the purifier's plug.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-10-2026
# Version:     1.0
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


def kwh_slices(rows):
    """[(epoch, kwh)] used between readings, from [(epoch, energy today)]
    rows in time order. The counter starts again from 0 at local midnight,
    so the first reading on a new day, or one lower than the one before, is
    energy since that restart - which also covers a gap in the readings over
    midnight, where the next day's figure must not be read as one slice."""
    out = []
    prev = None
    prev_day = None
    for epoch, kwh in rows:
        try:
            kwh = float(kwh)
            day = datetime.fromtimestamp(int(epoch)).date()
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        if prev is not None:
            used = kwh if (day != prev_day or kwh < prev) else kwh - prev
            if used > 0:
                out.append((int(epoch), used))
        prev, prev_day = kwh, day
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
