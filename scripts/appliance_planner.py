#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    appliance_planner.py
# Description: Works out when to run a deferrable appliance so it costs the least grid
#              import, given the solar forecast, the house load profile and the battery.
# Author:      CliveS & Claude Opus 5
# Date:        09-09-2026
# Version:     1.0
#
# NB deliberately NOT called appliance_scheduler.py. This volume is case-insensitive, so
# that name and the runner's Appliance_Scheduler.py are the SAME FILE, and installing the
# pair silently leaves one copy of the runner where the engine should be. Nothing errors;
# the import just fails later with "partially initialized module".
#
# WHAT THIS IS FOR, AND HOW BIG THE PRIZE ACTUALLY IS
# ---------------------------------------------------
# Measured before writing a line, from 63 real cycles between 06-Jun and 07-Sep-2026:
# the washing machine runs 61 minutes and uses 0.74 kWh (medians; the spread is tight,
# 56-159 min and 0.58-1.03 kWh), and CliveS ALREADY starts it in daylight - 45 of 63
# cycles begin between 09:00 and 12:00, and only one has ever begun at night.
#
# So in summer this has very little to move, and it would be dishonest to pretend
# otherwise: on a 30 kWh day a 0.74 kWh wash at 10am is already running on sunshine.
# Where it earns its keep is:
#   - WINTER, when the useful window narrows to roughly 10:00-14:00 and a 2 kW load
#     started at the wrong hour is straight grid import.
#   - AGILE from October, where the half-hourly spread is wide enough that the same
#     0.74 kWh can cost 4p or 26p depending on when it runs.
#   - DULL DAYS. On 09-Sep the forecast was 29.7 kWh for today and 18.3 for tomorrow.
# and because the same engine takes any deferrable load - a dishwasher, a dryer, the car.
#
# WHAT IT DOES NOT DO
# -------------------
# It does not start anything. The washing machine's Shelly is monitor-only by three
# separate mechanisms (detached button, initial_state on, a device script named
# "Relay Monitor-Only Mode"), and that is deliberate - see the estate note
# reference_washing_machine_monitor_is_off_by_design. A washing machine also has to be
# loaded by a person, so a person is standing in front of it at exactly the moment the
# advice is useful. This tells them when to press start, or what to set a delay timer to.
#
# THE MODEL
# ---------
# For each candidate start time, the cycle's energy is spread across the hours it covers
# and each hour's share is met in this order:
#   1. SOLAR SURPLUS  - forecast generation for that hour minus the house's own measured
#                       load. Free, and it is solar that would otherwise have gone into a
#                       battery that may not need it.
#   2. BATTERY        - down to the resilience reserve the plugin protects. Drawn at face
#                       value on purpose: the round-trip loss was already taken when that
#                       energy was BANKED, in carry_battery_forward, so charging for it
#                       again here would count it twice.
#
# KNOWN LIMIT, stated rather than hidden: nothing after the run is modelled. Emptying the
# battery at 11pm is scored as free even though it may mean buying at 6am. That is fair
# while the pack is large against the load and the sun refills it daily - on 09-Sep it sat
# at 88.6% with 25 kWh spare against a 0.74 kWh wash - and it will need revisiting for
# winter, or for a load big enough to move the SOC. Carrying the trajectory on to the next
# dawn is the obvious next step.
#   3. GRID           - at that half-hour's actual rate.
# The battery is carried FORWARD hour by hour from now, not evaluated row by row: a plan
# that ignores the stock will happily promise the same kilowatt-hour to two different
# hours (see feedback_a_row_wise_model_ignores_the_stock).
#
# Candidates are ranked on GRID IMPORT first and pennies second, because minimising
# import is the stated top KPI here and export is only worth 12p.

from datetime import timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:                       # pragma: no cover - stdlib since 3.9
    ZoneInfo = None

VERSION = "1.0"

SITE_TZ = "Europe/London"
STEP_MINUTES = 30          # candidate start times land on the half hour, like the rates do


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

class Appliance(object):
    """A deferrable load. Figures are MEASURED from its own history, never nameplate."""

    def __init__(self, key, label, duration_minutes, energy_kwh, peak_watts,
                 measured_from="", cycles_measured=0):
        self.key = key
        self.label = label
        self.duration_minutes = int(duration_minutes)
        self.energy_kwh = float(energy_kwh)
        self.peak_watts = float(peak_watts)
        self.measured_from = measured_from
        self.cycles_measured = int(cycles_measured)


# A finished cycle, and what is plainly not one. The history columns have had lifetime meter
# totals written into them at some point - a "3446 kWh wash" - so anything outside these is
# discarded rather than averaged in. Bounds are deliberately wide: they exclude nonsense, not
# unusual cycles (this machine's real spread is 56-159 min and 0.58-1.03 kWh).
CYCLE_BOUNDS = {"minutes": (20.0, 240.0), "kwh": (0.05, 5.0), "peak_watts": (50.0, 3500.0)}
MIN_CYCLES = 5          # below this, say so rather than quote a median of two


def plausible_cycles(values, kind):
    """Keep the values that could be a real cycle. Consecutive repeats are one cycle
    re-reported, so runs are collapsed."""
    low, high = CYCLE_BOUNDS[kind]
    out, last = [], object()
    for v in values:
        if not isinstance(v, (int, float)):
            last = v
            continue
        if v != last and low <= v <= high:
            out.append(float(v))
        last = v
    return out


def median(values):
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def profile_from_cycles(key, label, minutes, kwh, peaks, min_cycles=MIN_CYCLES):
    """An Appliance built from its OWN measured history, or None if there is not enough of it.

    None is the honest answer for a machine that has run twice. Quoting a median of two, or
    a manufacturer's figure, would put a number on the page that nothing supports - and the
    whole point of this page is that its timings come from the machine rather than the manual.
    """
    m = plausible_cycles(minutes, "minutes")
    e = plausible_cycles(kwh, "kwh")
    p = plausible_cycles(peaks, "peak_watts")
    if len(m) < min_cycles or len(e) < min_cycles:
        return None
    return Appliance(
        key=key, label=label,
        duration_minutes=int(round(median(m))),
        energy_kwh=round(median(e), 3),
        peak_watts=round(median(p), 1) if p else 0.0,
        measured_from=f"{min(len(m), len(e))} cycles",
        cycles_measured=min(len(m), len(e)),
    )


def appliance_key(device_name):
    """"Washing Machine Appliance Monitoring" -> "washing_machine".

    The key names the deadline variable, so it has to be stable and it has to be the one the
    existing washing_machine_deadline already uses.
    """
    name = str(device_name or "").strip().lower()
    for tail in (" appliance monitoring", " appliance monitor", " monitoring", " monitor"):
        if name.endswith(tail):
            name = name[: -len(tail)]
            break
    out = []
    for ch in name.strip():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "_":
            out.append("_")
    return "".join(out).strip("_")


def appliance_label(device_name):
    """"Washing Machine Appliance Monitoring" -> "the washing machine"."""
    key = appliance_key(device_name)
    return ("the " + key.replace("_", " ")) if key else "the appliance"


class Battery(object):
    def __init__(self, soc_pct, capacity_kwh, reserve_pct, efficiency,
                 max_charge_kw=None, max_discharge_kw=None):
        self.soc_pct = float(soc_pct)
        self.capacity_kwh = float(capacity_kwh)
        self.reserve_pct = float(reserve_pct)
        self.efficiency = float(efficiency)
        self.max_charge_kw = max_charge_kw
        self.max_discharge_kw = max_discharge_kw

    @property
    def stored_kwh(self):
        return self.capacity_kwh * self.soc_pct / 100.0

    @property
    def reserve_kwh(self):
        return self.capacity_kwh * self.reserve_pct / 100.0

    @property
    def usable_kwh(self):
        return max(0.0, self.stored_kwh - self.reserve_kwh)


class Slot(object):
    """One candidate, fully costed."""

    def __init__(self, start, finish, grid_kwh, cost_p, solar_kwh, battery_kwh):
        self.start = start
        self.finish = finish
        self.grid_kwh = grid_kwh
        self.cost_p = cost_p
        self.solar_kwh = solar_kwh
        self.battery_kwh = battery_kwh

    @property
    def rank(self):
        # Grid import first, pennies second. Rounded so that two plans differing by a
        # hundredth of a kWh are decided on price rather than on floating-point noise.
        return (round(self.grid_kwh, 3), round(self.cost_p, 2), self.start)

    def __repr__(self):
        return (f"<Slot {self.start:%H:%M} grid={self.grid_kwh:.2f}kWh "
                f"cost={self.cost_p:.1f}p solar={self.solar_kwh:.2f}>")


class NoPlan(Exception):
    """Raised with a plain-English reason. Never guess when the inputs are missing."""


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def site_tz():
    if ZoneInfo is None:
        raise NoPlan("This machine has no timezone database, so I cannot work out local "
                     "times reliably. Rather than guess an hour either way, I have stopped.")
    return ZoneInfo(SITE_TZ)


def to_local(dt):
    return dt.astimezone(site_tz())


def hour_shares(start, minutes):
    """How a run beginning at `start` divides across the clock hours it touches.

    Returns [(hour_start, fraction), ...] summing to 1.0. A run crossing midnight, or a
    daylight-saving boundary, is handled by walking real datetimes rather than by
    arithmetic on hour numbers - the wrapping-window trap.
    """
    if minutes <= 0:
        raise ValueError("a run must last longer than zero minutes")
    out = []
    remaining = float(minutes)
    cursor = start
    while remaining > 1e-9:
        hour_start = cursor.replace(minute=0, second=0, microsecond=0)
        next_hour = hour_start + timedelta(hours=1)
        in_this_hour = min(remaining, (next_hour - cursor).total_seconds() / 60.0)
        out.append((hour_start, in_this_hour / minutes))
        remaining -= in_this_hour
        cursor = next_hour
    return out


# ---------------------------------------------------------------------------
# Inputs, each of which refuses to invent a number
# ---------------------------------------------------------------------------

def _utc():
    if ZoneInfo is None:
        raise NoPlan("no timezone database")
    return ZoneInfo("UTC")


def solar_for_hour(solar_hourly, hour_local):
    """Forecast generation for a local hour, or None if the forecast does not cover it.

    The forecast file is keyed in UTC. None means UNKNOWN, and unknown must never be
    read as "no sun" - a forecast that has not arrived is not a forecast of darkness.
    """
    key = hour_local.astimezone(_utc()).strftime("%Y-%m-%dT%H:00:00Z")
    entry = solar_hourly.get(key)
    if entry is None:
        return None
    if isinstance(entry, dict):
        value = entry.get("kwh")
    else:
        value = entry
    return float(value) if isinstance(value, (int, float)) else None


def house_for_hour(house_hourly, hour_local):
    """The house's own measured draw for that hour, excluding the appliance."""
    profile = house_hourly.get("weekend" if hour_local.weekday() >= 5 else "weekday", {})
    value = profile.get(str(hour_local.hour), profile.get(hour_local.hour))
    return float(value) if isinstance(value, (int, float)) else None


def rate_for(rates, when):
    """Pence per kWh in force at `when`, or None if the rate set does not cover it.

    Takes both shapes without being told which: Tracker publishes one long span a day,
    Agile publishes half-hours, and a day is routinely published with 46 of its 48 slots
    rather than all of them. So this asks which span CONTAINS the moment and never counts
    entries or assumes a grid.
    """
    for span in rates:
        if span["start"] <= when < span["end"]:
            return float(span["pence"])
    return None


# ---------------------------------------------------------------------------
# The simulation
# ---------------------------------------------------------------------------

def surplus_for_hour(solar_hourly, house_hourly, hour_local):
    """Solar left over after the house has taken its share. None if either is unknown."""
    solar = solar_for_hour(solar_hourly, hour_local)
    house = house_for_hour(house_hourly, hour_local)
    if solar is None or house is None:
        return None
    return solar - house


def carry_battery_forward(battery, solar_hourly, house_hourly, from_hour, to_hour):
    """Battery energy available at `to_hour`, having lived through the hours between.

    Surplus charges it, a deficit discharges it, and it is bounded by the pack size and
    the resilience reserve. Carrying the stock forward is the whole point: costing each
    candidate against today's SOC would promise the same kilowatt-hour to every hour of
    the day.
    """
    stored = battery.stored_kwh
    cap = battery.capacity_kwh
    floor = battery.reserve_kwh
    hour = from_hour.replace(minute=0, second=0, microsecond=0)
    # Stop at the START of the hour the run begins in. Walking through that hour would bank
    # its surplus into the battery here AND leave cost_candidate free to claim the same
    # surplus as direct generation - the same kilowatt-hour spent twice. Found by a fixture
    # built to test something else entirely.
    boundary = to_hour.replace(minute=0, second=0, microsecond=0)
    guard = 0
    while hour < boundary and guard < 240:     # a bounded loop, never a while-True
        guard += 1
        margin = surplus_for_hour(solar_hourly, house_hourly, hour)
        if margin is None:
            pass                                # unknown hour changes nothing, by design
        elif margin > 0:
            stored = min(cap, stored + margin * battery.efficiency)
        else:
            stored = max(floor, stored + margin)
        hour += timedelta(hours=1)
    return max(0.0, stored - floor)


def cost_candidate(appliance, start, battery, solar_hourly, house_hourly, rates, now):
    """Cost one candidate start time. Raises NoPlan when an hour cannot be assessed."""
    finish = start + timedelta(minutes=appliance.duration_minutes)
    available = carry_battery_forward(battery, solar_hourly, house_hourly, now, start)

    grid_kwh = solar_kwh = battery_kwh = 0.0
    cost_p = 0.0
    for hour_start, fraction in hour_shares(start, appliance.duration_minutes):
        need = appliance.energy_kwh * fraction
        margin = surplus_for_hour(solar_hourly, house_hourly, hour_start)
        if margin is None:
            raise NoPlan(f"There is no forecast covering {hour_start:%H:%M on %d %B}, so I "
                         f"cannot say what it would cost to run then.")
        # Surplus is an HOUR's worth of energy, so a run present for part of that hour can
        # claim only that part of it. Scale by the share of the HOUR occupied, not by the
        # share of the RUN that falls in it - a 30-minute wash sitting wholly inside one
        # hour is 100% of the run and only half the hour.
        occupancy = min(1.0, fraction * appliance.duration_minutes / 60.0)
        from_solar = max(0.0, min(need, margin * occupancy))
        need -= from_solar
        solar_kwh += from_solar

        from_battery = max(0.0, min(need, available))
        available -= from_battery
        need -= from_battery
        battery_kwh += from_battery

        if need > 0:
            rate = rate_for(rates, hour_start)
            if rate is None:
                raise NoPlan(f"I have no electricity price for {hour_start:%H:%M on %d %B}, "
                             f"so I cannot compare that time with any other.")
            grid_kwh += need
            cost_p += need * rate
    return Slot(start, finish, grid_kwh, cost_p, solar_kwh, battery_kwh)


def candidate_starts(now, deadline, appliance, step_minutes=STEP_MINUTES):
    """Every half hour at which the cycle could begin and still finish by the deadline."""
    run = timedelta(minutes=appliance.duration_minutes)
    latest = deadline - run
    if latest < now:
        raise NoPlan(
            f"{appliance.label.capitalize()} takes about {appliance.duration_minutes} minutes "
            f"and it is already {now:%H:%M}, so it cannot be finished by "
            f"{deadline:%H:%M}. Start it now and it will be done by {(now + run):%H:%M}.")
    # First candidate is the next step boundary at or after now.
    first = now.replace(second=0, microsecond=0)
    over = first.minute % step_minutes
    if over or now.second or now.microsecond:
        first += timedelta(minutes=step_minutes - over)
    out, cursor, guard = [], first, 0
    while cursor <= latest and guard < 200:
        out.append(cursor)
        cursor += timedelta(minutes=step_minutes)
        guard += 1
    if not out:
        out = [now.replace(second=0, microsecond=0)]
    return out


def plan(appliance, now, deadline, battery, solar_hourly, house_hourly, rates):
    """Best start time, and the runners-up. Raises NoPlan with a reason it can say aloud."""
    if deadline <= now:
        raise NoPlan(f"That deadline ({deadline:%H:%M}) has already passed.")
    slots, problems = [], []
    for start in candidate_starts(now, deadline, appliance):
        try:
            slots.append(cost_candidate(appliance, start, battery, solar_hourly,
                                        house_hourly, rates, now))
        except NoPlan as err:
            problems.append(str(err))
    if not slots:
        raise NoPlan(problems[0] if problems else
                     "I could not cost a single start time between now and the deadline.")
    slots.sort(key=lambda s: s.rank)
    return slots[0], slots


# ---------------------------------------------------------------------------
# Saying it in English
# ---------------------------------------------------------------------------

def describe(appliance, best, everything, now, deadline):
    """Plain sentences that explain their own numbers. No value dumps, ASCII only."""
    worst = max(everything, key=lambda s: s.rank)
    saving_p = worst.cost_p - best.cost_p
    covered = best.solar_kwh / appliance.energy_kwh * 100.0 if appliance.energy_kwh else 0.0

    when = ("right now" if best.start <= now + timedelta(minutes=STEP_MINUTES)
            else f"at {_clock(best.start)}")
    lines = [f"Put {appliance.label} on {when} and it should finish about "
             f"{_clock(best.finish)}."]

    if best.grid_kwh <= 0.01:
        lines.append(f"The whole {appliance.energy_kwh:.1f} kWh should come from the sun and "
                     f"the battery, with nothing bought from the grid.")
    elif best.grid_kwh < 0.1:
        # Never print "0.0 kWh ... costing 1p". A quantity shown as zero beside a cost that
        # is not zero reads as a fault in the arithmetic.
        lines.append(f"Nearly all of its {appliance.energy_kwh:.1f} kWh comes from the sun "
                     f"and the battery, with only about {_pence(best.cost_p)} bought in.")
    else:
        lines.append(f"About {best.grid_kwh:.1f} of its {appliance.energy_kwh:.1f} kWh would "
                     f"come off the grid, costing roughly {_pence(best.cost_p)}.")

    if covered >= 5.0:
        lines.append(f"Around {covered:.0f}% of it runs straight off the panels.")

    by_when = f"{_clock(deadline)} {_day_word(deadline, now)}"
    if saving_p >= 1.0 and len(everything) > 1:
        lines.append(f"The worst moment between now and {by_when} is "
                     f"{_clock(worst.start)}, which would cost about {_pence(worst.cost_p)}, "
                     f"so the timing is worth roughly {_pence(saving_p)}.")
    elif len(everything) > 1:
        lines.append(f"It makes very little difference when you run it before "
                     f"{by_when}, so suit yourself.")

    if appliance.cycles_measured:
        lines.append(f"Those figures come from {appliance.cycles_measured} real cycles, "
                     f"not the manual.")
    return " ".join(lines)


def _day_word(when, now):
    """today / tomorrow / the weekday name - derived, never assumed.

    The first live run said "before 4pm today" about a deadline that was the NEXT day.
    A relative word is a claim about the calendar, so it has to come from the calendar.
    """
    days = (when.date() - now.date()).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return when.strftime("%A")


def _clock(dt):
    """Times the way a person says them: 1:45, 4pm, half past nine."""
    hour = dt.hour % 12 or 12
    suffix = "am" if dt.hour < 12 else "pm"
    if dt.minute == 0:
        return f"{hour}{suffix}"
    return f"{hour}:{dt.minute:02d}{suffix}"


def _pence(p):
    if p < 100:
        return f"{p:.0f}p"
    return f"{p / 100.0:.2f} pounds"
