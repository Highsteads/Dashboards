#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    mains_mixin.py
# Description: The Mains and Meter pages' server side: every 240 V meter in the
#              house, how far each one can be trusted (offsets measured against
#              the Sigenergy inverter's grid voltage over weeks of paired
#              readings), and one meter's full detail. Split out of plugin.py in
#              v3.30.0; Plugin inherits it.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import json
import math
import time
from datetime import datetime, timedelta, timezone

try:
    import indigo
except ImportError:
    pass
try:
    import history_db as _history_db
except ImportError:
    _history_db = None


class MainsMixin:
    # --------------------------------------------------------
    # Mains metering (v3.7.0) — the instrument page.
    #
    # This house measures its 240 V loads with four different families of
    # meter and they DISAGREE. Paired ten-minute means over September 2026,
    # each against the Sigenergy inverter's grid voltage:
    #
    #     Athom (ESPHome) #1   -1.70 V   (-0.68 %)
    #     Athom (ESPHome) #2   -0.93 V   (-0.37 %)
    #     Shelly Plus Plug     +1.96 V   (+0.79 %)
    #
    # a spread of about 3.7 V, or 1.5 %. None of them is calibrated, and the
    # Shelly exposes no trim (97 RPC methods, the only calibration-shaped one
    # is Shelly.FactoryReset). So this page does NOT present a single truth:
    # it shows each meter's measured offset against a stated reference and
    # lets the reader see the disagreement. Reading 252.6 V and acting on it
    # is exactly how a wrong figure nearly reached the DNO on 08-09-2026.
    # --------------------------------------------------------


    # ── one meter, everything known about it (v3.8.0) ────────────────────
    # CliveS could not tell his two Athom plugs apart — both carry their
    # ESPHome discovery name (athom-without-relay-plug-574f8d / -574eeb) and
    # nothing on the census said which was which. The page that answers that
    # question has to show the things that identify a physical plug: its
    # address, its network name, how long it has been up, its lifetime energy,
    # and the shape of its load over the last day.

    # A reading older than this is a LAST KNOWN VALUE, not a measurement.
    # 15 min is comfortably longer than every polling interval in the house
    # (the Shellys land ~35 s apart) and short enough to catch a plug that
    # has gone off the network.
    MAINS_STALE_SECONDS = 900

    # Offsets move with the hardware, not the hour — a long TTL keeps the
    # history sweep rare. Rebuilt in the background, never on a request.
    MAINS_OFFSET_TTL_SECONDS = 6 * 3600

    MAINS_OFFSET_DAYS = 7

    # Below this the pairing is too thin to quote an offset from.
    MAINS_OFFSET_MIN_PAIRS = 50

    @staticmethod
    def _mains_power_factor(watts, volts, amps, reported=None):
        """Power factor, or (None, reason) when it cannot honestly be known.

        NEVER used to derive watts. These meters report REAL power and RMS
        current from separate channels and the gap between them is genuine
        power factor: the Samsung TV measures 253.5 V x 0.218 A = 55.3 VA
        against 34.6 W, i.e. PF 0.62, steady across every sample. Computing
        watts as volts x amps would overstate that television by 60 %.
        """
        if reported is not None:
            try:
                pf = float(reported)
            except (TypeError, ValueError):
                pf = None
            if pf is not None and 0.0 < pf <= 1.05:
                return (round(min(pf, 1.0), 3), "reported")
        try:
            w, v, a = float(watts), float(volts), float(amps)
        except (TypeError, ValueError):
            return (None, "no reading")
        va = v * a
        # A load drawing almost nothing gives a meaningless ratio: at 0.02 A
        # the current channel's own error is most of the number.
        if va <= 5.0 or w <= 0.5:
            return (None, "load too small to judge")
        pf = w / va
        if pf > 1.05:
            # Above unity is impossible; it means the two channels disagree by
            # more than their error budget. Say so rather than printing it.
            return (None, "channels disagree")
        return (round(min(pf, 1.0), 3), "derived")

    @staticmethod
    def _mains_liveness(age_seconds, owner_running, continuous=True,
                        error_state="", online=None, stale_after=None):
        """('live'|'stale'|'dead', reason). A value is not a measurement.

        The Kitchen Extractor reported 291.0 V on 08-09-2026 — impossible, and
        frozen, because its plugin has not been installed since July. A page
        that shows a number without its age would have presented that as a
        dangerous over-voltage. A stopped owning plugin makes every one of its
        devices' readings historical whatever the timestamp says.

        AGE ONLY MEANS SOMETHING FOR A METER THAT POLLS. A Shelly answers every
        ~35 s, so silence is a fault. A Z-Wave dimmer reports ON CHANGE, so
        silence means nothing changed — and the first live run of this page
        greyed out the Kitchen Cupboard Lights as "stale, 10 days" while they
        were drawing 75.9 W in front of everyone. `lastSuccessfulComm` is not
        health on Z-Wave; errorState is. Callers pass continuous=False for a
        report-on-change device, and its freshness is judged by errorState and
        the owning plugin's own online flag instead.
        """
        if owner_running is False:
            return ("dead", "its plugin is not running")
        if online is False:
            return ("dead", "the device is not answering")
        if error_state:
            return ("dead", str(error_state))
        if not continuous:
            # Quiet is the normal state here, and saying otherwise is worse
            # than saying nothing: it hides a real fault among false ones.
            return ("live", "")
        limit = MainsMixin.MAINS_STALE_SECONDS if stale_after is None else stale_after
        # The coercion IS the guard: float(None) raises, so a device that has
        # never reported lands here with everything else that is not a number.
        # An explicit `is None` check above this was dead code — a mutation
        # sweep removed it and the tests never noticed, which is the tell.
        try:
            age = float(age_seconds)
        except (TypeError, ValueError):
            return ("dead", "never reported")
        if age > limit:
            return ("stale", f"last heard {MainsMixin._mains_ago(age)} ago")
        return ("live", "")

    @staticmethod
    def _mains_ago(seconds):
        """A duration the way a person says it."""
        try:
            s = int(float(seconds))
        except (TypeError, ValueError):
            return "an unknown time"
        if s < 1:
            # "last heard 0 seconds ago" is not how anyone says it, and a
            # meter polling every second lands here constantly. Only zero:
            # "1 second ago" is natural, and swallowing it would take away
            # the singular branch two lines below.
            return "a moment"
        if s < 90:
            # "1 seconds ago" reached the detail page's hero. Every other
            # branch here got its singular right and this one was missed,
            # which is what a parametrised test with no n=1 case looks like.
            return f"{s} second" + ("" if s == 1 else "s")
        # Switch to hours AT the hour: "60 minutes ago" is not how anyone
        # says it, and the tests caught exactly that.
        if s < 3600:
            m = round(s / 60.0)
            return f"{m} minute" + ("" if m == 1 else "s")
        if s < 172800:
            h = round(s / 3600.0)
            return f"{h} hour" + ("" if h == 1 else "s")
        d = round(s / 86400.0)
        return f"{d} day" + ("" if d == 1 else "s")

    @staticmethod
    def _mains_offset_stats(deltas):
        """Mean/min/max of one meter's differences from the reference.

        Returns None below MAINS_OFFSET_MIN_PAIRS: a handful of samples cannot
        separate a calibration offset from a busy afternoon, and quoting one
        from six pairs is how a measurement becomes a guess.
        """
        vals = [d for d in deltas if isinstance(d, (int, float))]
        if len(vals) < MainsMixin.MAINS_OFFSET_MIN_PAIRS:
            return None
        vals.sort()
        n = len(vals)
        mid = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
        return {"pairs": n,
                "mean": round(sum(vals) / n, 2),
                "median": round(mid, 2),
                "min": round(vals[0], 2),
                "max": round(vals[-1], 2)}

    @staticmethod
    def _mains_spread(offsets):
        """How far apart the fleet is, which is the number that matters.

        `offsets` is {meter: mean_volts_vs_reference}. The spread is what says
        'no reading here is better than about this much', and it is the whole
        argument for showing raw values rather than a corrected single truth.
        """
        vals = [v for v in offsets.values() if isinstance(v, (int, float))]
        if len(vals) < 2:
            return None
        return {"meters": len(vals), "low": round(min(vals), 2),
                "high": round(max(vals), 2),
                "spread": round(max(vals) - min(vals), 2)}

    @staticmethod
    def _mains_unmetered(house_watts, metered_watts):
        """What the house is drawing that no meter can see.

        Steps in this residual are the unmetered appliances announcing
        themselves — oven, kettle, shower. A NEGATIVE residual is not a
        reading, it is the instruments disagreeing by more than the load, so
        it is returned as None with a reason rather than shown as a number.
        """
        try:
            house = float(house_watts)
            metered = float(metered_watts)
        except (TypeError, ValueError):
            return (None, "no whole-house reading")
        residual = house - metered
        if residual < -50.0:
            return (None, "meters read higher than the house total")
        return (round(max(residual, 0.0), 1), "")

    # Which state each family of meter puts its readings in. Written as an
    # ordered list because the same quantity has a different name in every
    # plugin, and a device is matched on the FIRST name it actually carries.
    MAINS_STATE_NAMES = {
        "watts":  ("powerWatts", "curEnergyLevel", "power"),
        # Read ONLY on a device that already reports a mains-range voltage —
        # see _mains_live. An ESPHome power monitor with no relay puts its real
        # power in the NATIVE sensorValue and carries none of the names above.
        "watts_native": ("sensorValue",),
        "volts":  ("voltage",),
        "amps":   ("currentAmps", "current"),
        "pf":     ("powerFactor",),
        "today":  ("energyKwhToday", "energyToday"),
        "total":  ("accumEnergyTotal", "totalEnergy", "energyKwhMonth"),
    }

    # A z2m battery sensor also carries a `voltage` state — in MILLIVOLTS,
    # around 3000. Requiring a POWER state is what separates a mains meter
    # from a coin cell; this band is the second guard, and it is deliberately
    # wide because the point of the page is to show readings, not hide them.
    MAINS_VOLTS_SANE = (150.0, 300.0)

    # UK statutory is 230 V +10 %/-6 %, i.e. 216.2 to 253.0. Outside this
    # wider band a reading is not a supply problem, it is a broken instrument:
    # the Kitchen Extractor sat at 291.0 V for weeks with its plugin gone.
    MAINS_VOLTS_PLAUSIBLE = (200.0, 270.0)

    @staticmethod
    def _mains_pick(states, names):
        """First of `names` the device actually carries, as a float, else None."""
        for n in names:
            if n in states:
                try:
                    v = float(states[n])
                except (TypeError, ValueError):
                    continue
                return v
        return None

    # A device's own configuration goes to the browser on the detail page, and
    # at least one family keeps a real credential in it — an ESPHome node
    # carries `encryptionKey`. Measured, not guessed. The endpoint is
    # Bearer-authed, but the page it feeds is served from /public, which is
    # anonymous, so nothing that could ever be a secret leaves this process.
    MAINS_SECRET_HINTS = ("password", "passwd", "secret", "token", "credential",
                          "cookie", "authorization", "apikey", "api_key",
                          "privatekey", "private_key")

    @staticmethod
    def _mains_is_secret(key):
        """True for a props key whose VALUE must never reach the browser.

        `endswith("key")` rather than `"key" in ...` on purpose: it catches
        encryptionKey, apiKey and privateKey while leaving the ESPHome
        `entityKeyMap` and the Z-Wave `zwEndpointClassMap` alone, which are
        routing tables and are exactly the sort of detail this page is for.
        """
        k = str(key).lower()
        return k.endswith("key") or any(h in k for h in MainsMixin.MAINS_SECRET_HINTS)

    @staticmethod
    def _mains_jsonable(value):
        """`value` if json can carry it, else its string form.

        Indigo hands plugin props back as its own `indigo.Dict` and
        `indigo.List` types, and `json.dumps` refuses both with "Object of
        type Dict is not JSON serializable" — a 500 from the whole endpoint
        because of one prop. A Z-Wave dimmer carries eight of them
        (zwClassCmdMap, zwAssociationsMap, zwEndpointClassMap and the rest),
        so every Z-Wave meter's detail page failed while all three other
        families were fine. Ask json rather than listing the types: anything
        it cannot take is shown as text, which is all a display table needs.
        """
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _mains_redact(props):
        """A device's props with every credential replaced, order preserved.

        A redacted key is KEPT and marked rather than dropped: "this device
        holds an encryption key and you are not being shown it" is useful,
        and silently omitting the row would read as the device not having one.
        """
        out = {}
        for k in sorted(props or {}, key=lambda x: str(x).lower()):
            out[str(k)] = ("(hidden)" if MainsMixin._mains_is_secret(k)
                           else MainsMixin._mains_jsonable(props[k]))
        return out

    @staticmethod
    def _mains_source(states, names):
        """WHICH of `names` this device actually answers with, or None.

        The detail page charts a meter's history, and every family keeps its
        power somewhere different — powerWatts on a Shelly, curEnergyLevel on
        Z-Wave, power on a z2m relay, the native sensorValue on a relay-less
        Athom. Naming the column is what lets one chart serve all four without
        the page holding a family list of its own.
        """
        for n in names:
            if n in states:
                try:
                    float(states[n])
                except (TypeError, ValueError):
                    continue
                return n
        return None

    @staticmethod
    def _mains_watts(states, volts):
        """This device's real power, or None if it is not a mains meter.

        Lifted out of _mains_live so a test can drive it. Left inline it was
        reachable only by a structural assertion, and it was wrong: both Athom
        freezer plugs were MISSING from the census while appearing in the trust
        panel, which is built from history. The page named seventeen meters and
        listed fifteen, and the voltage map's visible spread read 1.8 V against
        a measured 3.7 V, because the two absentees were the lowest readers in
        the fleet.

        They are relay-less ESPHome power monitors: the real power lands in the
        NATIVE `sensorValue` and none of the usual names exists on them.
        `sensorValue` is generic, so it is read as watts ONLY where the device
        also reports a mains-range voltage — a lux or temperature sensor does
        not. Measured estate-wide 08-09-2026: 17 devices carry sensorValue
        (6 lux, 5 degC, 4 with no unit, 2 watts) and only the two Athoms pass
        the voltage gate.

        NEVER V x A. On the Samsung television that reads 55 VA against a real
        34.6 W, and a page that overstates a load by 60% is worse than one that
        leaves it out.
        """
        watts = MainsMixin._mains_pick(states, MainsMixin.MAINS_STATE_NAMES["watts"])
        if watts is None and volts is not None:
            watts = MainsMixin._mains_pick(states, MainsMixin.MAINS_STATE_NAMES["watts_native"])
        return watts

    # Every family says "I am reachable" in its own words, and one of them says
    # it in a STRING. Measured across all 35 meters here on 08-09-2026:
    #   ShellyDirect       deviceOnline   bool
    #   ESPHomeBridge      connected      bool  (+ status Online/Disconnected)
    #   TasmotaBridge      availability   "Offline"
    #   Zigbee2MQTTBridge  availability   "online"
    #   Indigo Z-Wave      nothing at all — and quiet is normal there anyway
    MAINS_ONLINE_STATES = ("deviceOnline", "connected", "availability",
                           "online", "reachable")

    _MAINS_ONLINE_WORDS = {"online": True, "true": True, "on": True,
                           "connected": True, "available": True, "yes": True, "1": True,
                           "offline": False, "false": False, "off": False,
                           "disconnected": False, "unavailable": False,
                           "no": False, "0": False}

    @staticmethod
    def _mains_online(states):
        """True / False / None — does the device itself say it is reachable?

        Only ShellyDirect's `deviceOnline` was read before, so an ESPHome plug
        that dropped off the wi-fi kept its last reading and the census counted
        it. Live case 08-09-2026: an Athom freezer monitor went `connected =
        False` at 21:06 and the page went on reporting **793.79 W** for it —
        so the metered total was 794 W high and the unmetered residual short by
        the same, which is a far larger error than the 76 W the switched-off
        rule had just removed.

        A STRING IS NEVER COERCED. `bool("Offline")` is True, and "Offline" is
        precisely the value the check exists to catch. An unrecognised word
        returns None rather than a guess: not knowing is not the same as being
        well, and the liveness rule treats the two differently.
        """
        for name in MainsMixin.MAINS_ONLINE_STATES:
            if name not in states:
                continue
            v = states[name]
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return bool(v)
            return MainsMixin._MAINS_ONLINE_WORDS.get(str(v).strip().lower())
        return None

    @staticmethod
    def _mains_reading_is_stale_off(watts, volts, states):
        """True when a power figure is a leftover from when the load was on.

        A meter that reports ON CHANGE may never send the zero. Read from the
        Kitchen Cupboard Lights' own history (Fibaro FGD212, 08-09-2026):
        switched ON at 09:30:47, reported 75.9 W at 09:30:53, switched OFF at
        09:30:57 — and said nothing further. Ten days on, the census was still
        counting 75.9 W for a light that was off, so the metered total was 76 W
        high and the unmetered residual, which is house minus meters, was short
        by exactly the same amount on the page whose whole point is honest
        measurement.

        Restricted to meters that do NOT poll, using the same discriminator as
        the liveness rule. A Shelly re-reads every ~35 s, so when it reports
        off and 0.4 W that 0.4 W was measured moments ago and is real; only a
        silent device can be frozen.

        Two devices estate-wide at the time of writing: this one and the Garage
        Salus Mains Plug at 0.1 W.
        """
        if volts is not None or "onOffState" not in states:
            return False
        try:
            if float(watts) <= 0:
                return False
        except (TypeError, ValueError):
            return False
        return not states["onOffState"]

    @staticmethod
    def _mains_settled_watts(watts, volts, states):
        """(what to count, what the meter last said) for one reading.

        The correction lived inline in _mains_row, where no test could reach
        it, and a mutation that threw the old figure away instead of recording
        it survived the sweep. Keeping it is the difference between a tile
        saying "off" and a tile that has silently lost 75.9 W.
        """
        if MainsMixin._mains_reading_is_stale_off(watts, volts, states):
            return 0.0, round(float(watts), 1)
        return watts, None

    def _mains_owner_running(self, pid, cache):
        """Is the plugin that owns this device actually running?

        NOT installed counts as dead, and that is a deliberate departure from
        the fail-open rule used where a script HARDCODES a plugin id. This id
        is read off a live device, so it cannot be a typo: an uninstalled
        plugin means the device is orphaned and nothing is maintaining its
        states. That is the Kitchen Extractor, frozen at an impossible 291 V
        since TasmotaBridge was removed. Measured 08-09-2026 across every
        plugin owning a device here: all report installed=True, INCLUDING
        Indigo's own Z-Wave core, so this cannot mark a working family dead.
        """
        if pid not in cache:
            try:
                plug = indigo.server.getPlugin(pid)
                cache[pid] = bool(plug.isInstalled() and plug.isRunning())
            except Exception:
                cache[pid] = True
        return cache[pid]

    def _mains_row(self, dev, running, now):
        """One meter's live reading, or None if this device is not a mains
        meter. Lifted out of _mains_live so the per-device detail endpoint
        reads the SAME row the census does — two renderings of one meter that
        disagreed about its state would be the 17-versus-15 fault again."""
        try:
            states = dev.states
        except Exception:
            return None
        volts = self._mains_pick(states, self.MAINS_STATE_NAMES["volts"])
        if volts is not None and not (self.MAINS_VOLTS_SANE[0] <= volts
                                      <= self.MAINS_VOLTS_SANE[1]):
            volts = None                      # a battery sensor's millivolts
        watts = self._mains_watts(states, volts)
        if watts is None:
            return None                       # no power reading: not a meter
        # Believe the switch over a frozen number — see the helpers above.
        watts, last_known_watts = self._mains_settled_watts(watts, volts, states)
        amps = self._mains_pick(states, self.MAINS_STATE_NAMES["amps"])
        pf, pf_source = self._mains_power_factor(
            watts, volts, amps, self._mains_pick(states, self.MAINS_STATE_NAMES["pf"]))

        pid = getattr(dev, "pluginId", "") or ""
        owner_running = self._mains_owner_running(pid, running)
        age = None
        try:
            if dev.lastSuccessfulComm:
                age = (now - dev.lastSuccessfulComm).total_seconds()
        except Exception:
            age = None
        # A meter that reports VOLTAGE is one that polls continuously (Shelly,
        # Athom, Tasmota all do); a Z-Wave dimmer or a Zigbee relay reports
        # only when something changes, so its silence is not a fault and must
        # not be dressed up as one.
        state, why = self._mains_liveness(
            age, owner_running, continuous=(volts is not None),
            error_state=(getattr(dev, "errorState", "") or ""),
            online=self._mains_online(states))

        implausible = (volts is not None
                       and not (self.MAINS_VOLTS_PLAUSIBLE[0] <= volts
                                <= self.MAINS_VOLTS_PLAUSIBLE[1]))
        return {
            "id": dev.id, "name": dev.name, "plugin": pid,
            "type": getattr(dev, "deviceTypeId", ""),
            "enabled": bool(getattr(dev, "enabled", True)),
            "watts": round(watts, 1),
            "volts": None if volts is None else round(volts, 1),
            "amps": None if amps is None else round(amps, 3),
            "pf": pf, "pfSource": pf_source,
            "todayKwh": self._mains_pick(states, self.MAINS_STATE_NAMES["today"]),
            "totalKwh": self._mains_pick(states, self.MAINS_STATE_NAMES["total"]),
            "state": state, "why": why,
            "ageSeconds": None if age is None else int(age),
            "ago": self._mains_ago(age) if age is not None else None,
            "voltsImplausible": implausible,
            "lastKnownWatts": last_known_watts,
            "onState": (None if "onOffState" not in states
                        else bool(states["onOffState"])),
            "sources": {
                "watts": (self._mains_source(states, self.MAINS_STATE_NAMES["watts"])
                          or (self._mains_source(states, self.MAINS_STATE_NAMES["watts_native"])
                              if volts is not None else None)),
                "volts": self._mains_source(states, self.MAINS_STATE_NAMES["volts"]),
                "amps":  self._mains_source(states, self.MAINS_STATE_NAMES["amps"]),
                "pf":    self._mains_source(states, self.MAINS_STATE_NAMES["pf"]),
                # The detail page LABELS the energy rows from these. The
                # "total" list falls back to energyKwhMonth, which is a month
                # and not a lifetime, so a fixed caption called a Shelly's
                # 0.10 kWh month its lifetime total.
                "today": self._mains_source(states, self.MAINS_STATE_NAMES["today"]),
                "total": self._mains_source(states, self.MAINS_STATE_NAMES["total"]),
            },
        }

    def _mains_live(self):
        """Every device that measures a 240 V load, read from live state.

        Cheap by construction — no history, no network — so it can answer a
        request directly. The expensive half (calibration offsets) is built on
        a background thread and merged in by the handler.
        """
        now = datetime.now()
        running = {}
        rows, metered_w = [], 0.0
        for dev in indigo.devices:
            row = self._mains_row(dev, running, now)
            if row is None:
                continue
            if row["state"] == "live":
                metered_w += max(row["watts"], 0.0)
            rows.append(row)
        rows.sort(key=lambda r: (-r["watts"], r["name"]))
        return rows, round(metered_w, 1)

    def _mains_reference(self):
        """The Sigenergy inverter — house power and the voltage every meter is
        compared against. It is not calibrated either; it is the best-specified
        instrument here (it must measure accurately to stay grid-connected) and
        it sits in the middle of the fleet, which is where a median would put
        it. The page says so rather than implying it is truth.

        Found through _sigen_inverter, the one lookup every caller shares, and
        its live readings held to _sigen_states_live (review 24-09-2026): a
        frozen house total made "unmetered" out of a figure hours old. When
        they are not current, houseWatts and volts are None and `stale` says
        why; the id and name stay, because the offsets read the HISTORY, which
        a stopped plugin does not spoil.

        None without SigenEnergyManager (3.48.4): an inverter device can outlive
        its plugin, and a reference nothing maintains would only give the page
        a frozen figure to explain."""
        if not self._sigen_available():
            return None
        dev = self._sigen_inverter()
        if dev is None:
            return None
        live, why = self._sigen_states_live(dev)
        ref = {"id": dev.id, "name": dev.name, "houseWatts": None, "volts": None,
               "stale": None if live else why}
        if live:
            s = dev.states
            ref["houseWatts"] = self._mains_pick(s, ("homePowerWatts",))
            ref["volts"] = self._mains_pick(s, ("gridVoltageV",))
        return ref

    def _mains_bucketed_volts(self, conn, hist, dev_id, column, since_utc):
        """{10-minute bucket: mean volts} for one meter, PK-RANGED.

        Never ts-filtered. indigo_history.sqlite has no index on ts and runs
        journal_mode=delete, so a scan holds a read lock that blocks the SQL
        Logger's writes — that is what wedged IWS for three minutes in July.
        """
        table = f"device_history_{dev_id}"
        lo = self._rowid_for_ts(conn, table, since_utc)
        if lo is None:
            return {}
        out = {}
        for ts, v in conn.execute(
                f"SELECT ts, {column} FROM {table} "
                f"WHERE id >= ? AND {column} IS NOT NULL", (lo,)):
            if v is None:
                continue
            # One blank or text sample must not fail every meter's offset
            # (review 24-09-2026): float() raised out of the whole build.
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(fv):
                continue
            key = str(ts)[:15]          # 'YYYY-MM-DD HH:M' — a 10-minute bucket
            acc = out.setdefault(key, [0.0, 0])
            acc[0] += fv
            acc[1] += 1
        return {k: a[0] / a[1] for k, a in out.items() if a[1]}

    def _mains_offsets(self):
        """Each voltage-capable meter's measured offset against the reference.

        This is the page's whole point. The meters disagree by about 1.5 %, no
        two agree, and nothing here is calibrated — so the honest presentation
        is every meter's own offset plus the fleet spread, not one corrected
        number wearing an authority none of them has.
        """
        ref = self._mains_reference()
        if not ref:
            return {"ok": False, "error": "no inverter to compare against"}
        hist = self._history()
        try:
            conn = hist.connect()
        except _history_db.HistoryUnavailable as exc:
            return {"ok": False, "error": f"history unavailable: {exc}"}
        try:
            since = (datetime.now(timezone.utc).replace(tzinfo=None)
                     - timedelta(days=self.MAINS_OFFSET_DAYS)
                     ).strftime("%Y-%m-%d %H:%M:%S")
            try:
                ref_cols = hist.column_names(conn, ref["id"])
            except Exception:
                ref_cols = []
            ref_col = "gridvoltagev" if "gridvoltagev" in ref_cols else None
            if not ref_col:
                return {"ok": False, "error": "the inverter logs no grid voltage"}
            ref_series = self._mains_bucketed_volts(conn, hist, ref["id"], ref_col, since)
            # The reference is held to the same sane band as each meter
            # (review 24-09-2026). A power cut reads near zero at the inverter
            # while a backed-up meter still reads ~230 V, and that one bucket
            # moved every meter's quoted offset for a week.
            lo_v, hi_v = self.MAINS_VOLTS_SANE
            ref_series = {k: v for k, v in ref_series.items() if lo_v <= v <= hi_v}
            if not ref_series:
                return {"ok": False, "error": "no reference history in the window"}

            offsets, meters = {}, {}
            for dev in indigo.devices:
                if dev.id == ref["id"]:
                    continue
                try:
                    cols = hist.column_names(conn, dev.id)
                except Exception:
                    continue
                if "voltage" not in cols:
                    continue
                series = self._mains_bucketed_volts(conn, hist, dev.id, "voltage", since)
                if not series:
                    continue
                deltas = [series[k] - ref_series[k] for k in series if k in ref_series
                          # A battery sensor's millivolts share the column name.
                          and self.MAINS_VOLTS_SANE[0] <= series[k] <= self.MAINS_VOLTS_SANE[1]]
                stats = self._mains_offset_stats(deltas)
                if stats is None:
                    continue
                stats["percent"] = round(100.0 * stats["mean"]
                                         / (sum(ref_series.values()) / len(ref_series)), 3)
                meters[str(dev.id)] = dict(stats, name=dev.name)
                offsets[str(dev.id)] = stats["mean"]
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return {"ok": True, "generated": time.time(), "days": self.MAINS_OFFSET_DAYS,
                "reference": {"id": ref["id"], "name": ref["name"]},
                "meters": meters, "spread": self._mains_spread(offsets)}

    def _mains_offsets_if_sigen(self):
        """The offsets, or None without SigenEnergyManager (3.48.4). They are
        measured against the inverter, so without it there is nothing to
        build — and a cold cache would otherwise start a week-long history
        sweep only to report that it had no reference."""
        if not self._sigen_available():
            return None
        return self._mains_offsets_cached()

    def _mains_offsets_cached(self):
        """The offsets cache, starting the background build when it is cold.

        BOTH the census and the per-meter page need this, and a page opened
        straight onto a meter — a bookmark, or a tile tapped after a restart —
        must not sit for ever on an empty answer because only the census ever
        kicked the build off. A missing cache is reported as `building`, never
        as "this meter has no offset": those are different facts and rendering
        them the same way is how an absence starts reading as a measurement.
        """
        # On the shared pool (v3.27.0). An expired entry still beats nothing
        # while the rebuild runs: a calibration offset measured six hours ago
        # has not moved since. Failures are remembered for ten minutes.
        return self._offpath_swr(
            "mains-offsets", self._mains_offsets,
            ttl=self.MAINS_OFFSET_TTL_SECONDS, fail_ttl=600,
            placeholder={"ok": True, "building": True, "meters": {}, "spread": None},
            on_fail=lambda d: {"ok": False, "meters": {}, "spread": None,
                               "error": f"offsets unavailable: {d}"})

    def handleMainsMeters(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/mainsMeters/
        Bearer-authed by IWS. Live readings are computed per request (cheap —
        state reads only); the calibration offsets come from a cache rebuilt on
        a background thread, so the page answers instantly from the first load
        and fills the trust panel in when the sweep lands."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        try:
            rows, metered = self._mains_live()
            ref = self._mains_reference()
            unmetered, unmetered_why = self._mains_unmetered(
                (ref or {}).get("houseWatts"), metered)
            offsets = self._mains_offsets_if_sigen()
            return self._evo_reply({
                "ok": True, "generated": time.time(),
                "meters": rows, "meteredWatts": metered,
                "reference": ref,
                "unmeteredWatts": unmetered, "unmeteredWhy": unmetered_why,
                "offsets": offsets,
                "staleAfterSeconds": self.MAINS_STALE_SECONDS,
            })
        except Exception as exc:
            self.logger.error(f"[Mains] query failed: {exc}")
            return self._evo_reply({"ok": False, "error": str(exc)}, status=500)

    @staticmethod
    def _mains_states(states):
        """Every reading a device publishes, with its own display string.

        Indigo keeps the formatted value in a sibling `<name>.ui` state, so the
        units come free and there is no unit table to keep in step with four
        families of meter. The `.ui` rows themselves are folded in rather than
        listed, or every reading appears twice.
        """
        out = []
        for name in sorted(states, key=lambda x: str(x).lower()):
            if str(name).endswith(".ui"):
                continue
            value = states[name]
            display = states.get(f"{name}.ui")
            out.append({"name": str(name),
                        "value": MainsMixin._mains_jsonable(value),
                        "display": None if display is None else str(display)})
        return out

    def _mains_detail(self, dev_id):
        """Everything this process knows about one meter."""
        try:
            dev_id = int(dev_id)
        except (TypeError, ValueError):
            return {"ok": False, "error": "a device id is required"}
        if dev_id not in indigo.devices:
            return {"ok": False, "error": f"there is no device {dev_id}"}
        dev = indigo.devices[dev_id]
        row = self._mains_row(dev, {}, datetime.now())
        if row is None:
            # Deliberately not a 404. The device is real and the page can still
            # say what it is; refusing outright would leave the reader unable
            # to tell a wrong link from a device that stopped reporting power.
            return {"ok": True, "isMeter": False, "meter": None,
                    "identity": self._mains_identity(dev),
                    "states": self._mains_states(dev.states),
                    "props": self._mains_redact(dict(dev.globalProps.get(dev.pluginId, {}))),
                    "offset": None, "reference": None,
                    "why": "this device reports no power, so it is not a mains meter"}

        offsets = self._mains_offsets_if_sigen() or {}
        offset = (offsets.get("meters") or {}).get(str(dev_id))
        ref = self._mains_reference()
        # No `fleet` here any more: the voltage map it fed was removed from this
        # page at CliveS's request, and building it cost a whole extra
        # _mains_live() sweep of 227 devices on every detail request.
        return {"ok": True, "isMeter": True, "generated": time.time(),
                "meter": row,
                "identity": self._mains_identity(dev),
                # globalProps, not pluginProps: read from THIS plugin's host a
                # foreign device's pluginProps comes back empty, which reads
                # exactly like a device with no configuration at all.
                "props": self._mains_redact(dict(dev.globalProps.get(dev.pluginId, {}))),
                "states": self._mains_states(dev.states),
                "offset": offset,
                "offsetDays": offsets.get("days"),
                "offsetBuilding": bool(offsets.get("building")),
                "spread": offsets.get("spread"),
                "reference": ref,
                "staleAfterSeconds": self.MAINS_STALE_SECONDS}

    def _mains_identity(self, dev):
        """The things that tell you WHICH physical plug this is."""
        pid = getattr(dev, "pluginId", "") or ""
        plug_name, plug_ver, running = pid, None, None
        try:
            plug = indigo.server.getPlugin(pid)
            plug_name = plug.pluginDisplayName or pid
            plug_ver = plug.pluginVersion
            running = bool(plug.isInstalled() and plug.isRunning())
        except Exception:
            pass
        folder = ""
        try:
            if dev.folderId:
                folder = indigo.devices.folders[dev.folderId].name
        except Exception:
            folder = ""
        def _iso(v):
            try:
                return v.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return None
        return {
            "id": dev.id, "name": dev.name,
            "description": getattr(dev, "description", "") or "",
            "model": getattr(dev, "model", "") or "",
            "subModel": getattr(dev, "subModel", "") or "",
            "protocol": str(getattr(dev, "protocol", "") or ""),
            "deviceTypeId": getattr(dev, "deviceTypeId", ""),
            "address": getattr(dev, "address", "") or "",
            "folder": folder,
            "enabled": bool(getattr(dev, "enabled", True)),
            "configured": bool(getattr(dev, "configured", True)),
            "errorState": str(getattr(dev, "errorState", "") or ""),
            "lastSuccessfulComm": _iso(getattr(dev, "lastSuccessfulComm", None)),
            "lastChanged": _iso(getattr(dev, "lastChanged", None)),
            "pluginId": pid, "pluginName": plug_name,
            "pluginVersion": plug_ver, "pluginRunning": running,
        }

    def handleMainsMeter(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/mainsMeter/
        Body: {"id": <deviceId>}. Bearer-authed by IWS. Everything known about
        ONE meter — live reading, identity, offset, states and configuration.
        Reads live state only, so it is cheap enough to answer per request; the
        page fetches its own history through the existing historyQuery."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        payload, _reply = self._request_body(action, refuse_reflector=False)
        if _reply:
            return _reply
        try:
            out = self._mains_detail(payload.get("id"))
            return self._evo_reply(out, status=200 if out.get("ok") else 404)
        except Exception as exc:
            self.logger.error(f"[Mains] detail query failed: {exc}")
            return self._evo_reply({"ok": False, "error": str(exc)}, status=500)
