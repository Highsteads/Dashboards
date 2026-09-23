#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    health_mixin.py
# Description: The System Health page's server side: Mac vitals, storage, services
#              and the device-health census.
#              Split out of plugin.py in v3.32.0; Plugin inherits it.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

try:
    import indigo
except ImportError:
    pass

import os
import re
import shutil
import time

class HealthMixin:
    # -----------------------------------------------------------------------
    # System-health endpoint — Mac vitals + storage + device-health census.
    # Powers system-health.html. Everything is computed server-side in ONE
    # round-trip because a browser can't read host stats (disk/RAM/swap) or
    # the SQL history DB size, and shipping ~190 devices' full JSON over the
    # reflector just to count them would be wasteful. Bearer-authed by IWS.
    # -----------------------------------------------------------------------
    def handleSystemHealth(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/systemHealth/
        Returns {mac, storage, devices}. No request params. Each section is
        computed defensively so one failure degrades to a partial answer."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        # Off the dispatch path (v3.19.0). Measured at 262 ms worst of three on
        # 18-09-2026: subprocess.run for the Mac vitals, os.walk and os.scandir
        # for the storage breakdown. None of it is wrong; none of it belongs on
        # the thread that serves every dashboard in the house.
        state, payload = self._offpath_get(
            "systemhealth", self._system_health_payload, self.SYSTEM_HEALTH_TTL,
            wait=self.SYSTEM_HEALTH_WAIT)
        if state == "fresh":
            return self._evo_reply(payload)
        if state == "failed":
            return self._evo_reply({"ok": False, "error": payload}, status=500)
        return self._evo_reply(
            {"ok": False, "pending": True,
             "error": "system health is still being gathered — try again shortly"},
            status=503)

    def _system_health_payload(self):
        """The four collectors, on an off-path worker. Each section is computed
        defensively so one failure degrades to a partial answer rather than
        losing the page — which is why this never raises and the pool therefore
        never records a failure for it."""
        out = {"ok": True, "now": time.time()}
        for key, fn in (("mac",      self._mac_vitals),
                        ("storage",  self._storage_breakdown),
                        ("devices",  self._device_health),
                        ("services", self._service_health)):
            try:
                out[key] = fn()
            except Exception as exc:
                self.logger.warning(f"[SystemHealth] {key} section failed: {exc}")
                out[key] = {"error": str(exc)}
        return out

    def _service_health(self):
        """This plugin's own background services (v2.33.0) — the page can then
        say whether the camera pipeline is actually alive, not just assumed."""
        go2 = getattr(self, "_go2rtc_proc", None)
        mj  = getattr(self, "_mjpeg_server", None)
        return {
            # Info.plist, which is what Indigo shows (v3.25.0) — the constant can lag it.
            "plugin_version": getattr(self, "pluginVersion", None) or "",
            "go2rtc":         bool(go2 is not None and go2.poll() is None),
            "mjpeg_proxy":    bool(mj is not None),
            "cameras":        len(self.cameras),
        }

    def _mac_vitals(self):
        """Host vitals: disk, RAM (+swap), load, uptime, OS/Python. RAM total
        comes from os.sysconf (authoritative, no subprocess); the breakdown
        from vm_stat. subprocess uses ABSOLUTE binary paths — the plugin-host
        PATH omits /usr/sbin, so a bare 'sysctl' raises FileNotFoundError."""
        import platform
        import subprocess

        def _sh(args):
            try:
                return subprocess.run(args, capture_output=True, text=True,
                                      timeout=5).stdout.strip()
            except Exception:
                return ""

        out = {
            "hostname": platform.node(),
            "macos":    platform.mac_ver()[0] or "",
            "python":   platform.python_version(),
            "arch":     platform.machine(),
            "cores":    os.cpu_count() or 0,
        }
        try:
            out["indigo"] = str(indigo.server.version)
            out["api"]    = str(indigo.server.apiVersion)
        except Exception:
            pass
        try:
            l1, l5, l15 = os.getloadavg()
            out["load"] = [round(l1, 2), round(l5, 2), round(l15, 2)]
        except Exception:
            out["load"] = []
        try:
            du = shutil.disk_usage("/")
            out["disk"] = {
                "total_gb": round(du.total / 1e9, 1),
                "used_gb":  round(du.used / 1e9, 1),
                "free_gb":  round(du.free / 1e9, 1),
                "used_pct": round(du.used / du.total * 100, 1),
            }
        except Exception:
            out["disk"] = {}

        ram = {}
        try:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            vm = _sh(["/usr/bin/vm_stat"])
            m = re.search(r"page size of (\d+) bytes", vm)
            psize = int(m.group(1)) if m else 4096

            def _pg(label):
                mm = re.search(rf"{re.escape(label)}:\s+(\d+)\.", vm)
                return int(mm.group(1)) if mm else 0

            # "Memory Used" as Activity Monitor reports it: app (active) +
            # wired + compressed. Free/inactive/speculative are reclaimable.
            used = (_pg("Pages active") + _pg("Pages wired down")
                    + _pg("Pages occupied by compressor")) * psize
            # RAM in binary GiB (2**30) — the convention the hardware is sold
            # in. The old decimal /1e9 made an 8 GB Mac mini report "8.6 GB
            # total". Disk stays decimal (matches Finder/Apple SSD specs).
            ram = {
                "total_gb": round(total / 2**30, 1),
                "used_gb":  round(used / 2**30, 1),
                "free_gb":  round(max(0, total - used) / 2**30, 1),
                "used_pct": round(used / total * 100, 1) if total else 0,
            }
            sw = _sh(["/usr/sbin/sysctl", "-n", "vm.swapusage"])
            st = re.search(r"total = ([\d.]+)M", sw)
            su = re.search(r"used = ([\d.]+)M", sw)
            if st:
                ram["swap_total_mb"] = round(float(st.group(1)))
            if su:
                ram["swap_used_mb"] = round(float(su.group(1)))
        except Exception:
            pass
        # Memory-pressure verdict. On an 8 GB Mac, heavy swap is the real
        # signal — a high used_pct alone is normal for macOS.
        up = ram.get("used_pct", 0)
        swu = ram.get("swap_used_mb", 0)
        if "used_pct" not in ram:
            # The measurement itself failed (vm_stat/sysctl timed out — which
            # is exactly what a starved Mac does). Unknown, never 'normal'.
            ram["pressure"] = "unknown"
        elif swu >= 1500 or up >= 92:
            ram["pressure"] = "high"
        elif swu >= 400 or up >= 82:
            ram["pressure"] = "elevated"
        else:
            ram["pressure"] = "normal"
        out["ram"] = ram

        out["uptime_text"] = ""
        try:
            up_txt = _sh(["/usr/bin/uptime"])
            mm = re.search(r"\bup\s+(.+?),\s+\d+\s+user", up_txt)
            out["uptime_text"] = mm.group(1).strip() if mm else up_txt
        except Exception:
            pass
        try:
            bt = _sh(["/usr/sbin/sysctl", "-n", "kern.boottime"])
            mm = re.search(r"sec\s*=\s*(\d+)", bt)
            if mm:
                out["boot_epoch"] = int(mm.group(1))
        except Exception:
            pass
        return out

    def _storage_breakdown(self):
        """SQL history DB size (the dominant, actionable chunk of a near-full
        disk) plus the biggest items in the Logs dir. Cached for 5 minutes so
        the 30 s page poll doesn't re-walk the tree every tick."""
        cache = getattr(self, "_storage_cache", None)
        nowm = time.time()
        if cache and (nowm - cache[0]) < 300:
            return cache[1]
        base = indigo.server.getInstallFolderPath()
        logs = os.path.join(base, "Logs")
        sqlp = os.path.join(logs, "indigo_history.sqlite")
        out = {
            "sql_history_gb":   round(os.path.getsize(sqlp) / 1e9, 2) if os.path.exists(sqlp) else 0.0,
            "sql_history_path": sqlp,
            "logs_total_gb":    0.0,
            "top_items":        [],
        }
        items = []
        try:
            with os.scandir(logs) as it:
                for e in it:
                    try:
                        if e.is_file(follow_symlinks=False):
                            sz = e.stat(follow_symlinks=False).st_size
                            is_dir = False
                        else:
                            sz = 0
                            for root, _dirs, files in os.walk(e.path):
                                for f in files:
                                    try:
                                        sz += os.path.getsize(os.path.join(root, f))
                                    except OSError:
                                        pass
                            is_dir = True
                        items.append((e.name, sz, is_dir))
                    except OSError:
                        pass
        except OSError:
            pass
        out["logs_total_gb"] = round(sum(s for _n, s, _d in items) / 1e9, 2)
        items.sort(key=lambda x: -x[1])
        out["top_items"] = [
            {"name": n, "gb": round(s / 1e9, 2), "dir": d}
            for n, s, d in items[:6] if s > 50e6   # only items over ~50 MB
        ]
        self._storage_cache = (nowm, out)
        return out

    @staticmethod
    def _battery_pct(dev):
        """Battery reading for a device, covering the estate's three battery
        idioms: the native batteryLevel property (Z-Wave etc.), the z2m custom
        `battery` state (guarded >0 — mains z2m devices report 0), and the
        boolean `batteryLow` alarm. Returns (pct_or_None, alarm_bool) — the
        same coverage as overview.html's batteryInfo(), which caught a 1%
        sensor the native-only check missed."""
        bl = getattr(dev, "batteryLevel", None)
        if isinstance(bl, (int, float)) and not isinstance(bl, bool):
            return int(bl), False
        try:
            states = dev.states
        except Exception:
            return None, False
        try:
            bf = float(states.get("battery"))
            if bf > 0:
                return int(bf), False
        except (TypeError, ValueError):
            pass
        if str(states.get("batteryLow", "")).strip().lower() in ("true", "on", "yes", "1"):
            return None, True
        return None, False

    def _device_health(self):
        """Per-device alerts + per-plugin census, computed over the live IOM.
        'In error' uses dev.errorState (the reliable liveness signal); 'quiet'
        uses lastChanged age (not a true comms probe — framed as such on the
        page) with a configurable threshold."""
        try:
            stale_hours = int(self.pluginPrefs.get("healthStaleHours", 48) or 48)
        except (TypeError, ValueError):
            stale_hours = 48
        try:
            low_batt_pct = int(self.pluginPrefs.get("healthLowBatteryPct", 20) or 20)
        except (TypeError, ValueError):
            low_batt_pct = 20

        now = indigo.server.getTime()
        in_error, low_batt, stale = [], [], []
        census = {}
        total = enabled = 0
        # len() and iteration disagree: iteration skips unconfigured devices
        # (measured 209 vs 211 here). Publish both so the page can show the gap.
        try:
            known = len(indigo.devices)
        except Exception:
            known = None

        for d in indigo.devices:
            total += 1
            is_on = bool(d.enabled)
            if is_on:
                enabled += 1
            pid = d.pluginId or "(native/built-in)"
            c = census.setdefault(pid, {"count": 0, "enabled": 0})
            c["count"] += 1
            if is_on:
                c["enabled"] += 1

            es = (d.errorState or "").strip()
            if es:
                in_error.append({"id": d.id, "name": d.name, "plugin": pid, "error": es})

            bl, alarm = self._battery_pct(d)
            if alarm or (bl is not None and bl <= low_batt_pct):
                low_batt.append({"id": d.id, "name": d.name, "plugin": pid,
                                 "battery": bl, "alarm": alarm})

            # "Quiet" only means something for BATTERY devices — silence from a
            # battery sensor can be a flat battery or a dropped mesh link. Mains
            # devices, virtuals and timers are legitimately quiet for days, and
            # some carry an unset/epoch lastChanged (a bogus multi-year age), so
            # they are excluded and implausible ages (>1yr) are dropped.
            if is_on and (alarm or bl is not None):
                try:
                    age_h = (now - d.lastChanged).total_seconds() / 3600.0
                    if stale_hours <= age_h <= 24 * 365:
                        stale.append({"id": d.id, "name": d.name, "plugin": pid,
                                      "age_hours": round(age_h, 1), "battery": bl,
                                      "alarm": alarm})
                except Exception:
                    pass

        plugins = []
        for pid, c in census.items():
            disp, running, plugin_enabled = pid, None, None
            try:
                p = indigo.server.getPlugin(pid)
                if p:
                    disp = p.pluginDisplayName or pid
                    # isRunning, NOT isEnabled (v2.95.1): a plugin that is
                    # enabled and has crashed reads True from isEnabled(), so
                    # this page — the one built to say something is down —
                    # showed a dead device-owning plugin as healthy for 20 h
                    # during the ShellyDirect outage of 16-17 Aug. Both are
                    # returned so the page can tell "stopped" (red) from
                    # "disabled on purpose" (grey). NB getPlugin() of an
                    # unknown id does not raise — it reads all-False — so a
                    # built-in pseudo-id keeps None rather than a false red.
                    if p.isInstalled():
                        running = bool(p.isRunning())
                        plugin_enabled = bool(p.isEnabled())
            except Exception:
                pass
            plugins.append({"plugin": pid, "name": disp, "count": c["count"],
                            "enabled": c["enabled"], "running": running,
                            "pluginEnabled": plugin_enabled})

        in_error.sort(key=lambda x: x["name"].lower())
        # None battery = a batteryLow alarm with no % — sort those first (-1).
        low_batt.sort(key=lambda x: x["battery"] if x["battery"] is not None else -1)
        stale.sort(key=lambda x: -x["age_hours"])
        plugins.sort(key=lambda x: (-x["count"], x["name"].lower()))

        return {
            "total":        total,
            "known":        known,
            "enabled":      enabled,
            "disabled":     total - enabled,
            "stale_hours":  stale_hours,
            "low_batt_pct": low_batt_pct,
            "in_error":     in_error[:50],
            "low_battery":  low_batt[:50],
            "stale":        stale[:30],
            "stale_count":  len(stale),
            "by_plugin":    plugins,
        }
