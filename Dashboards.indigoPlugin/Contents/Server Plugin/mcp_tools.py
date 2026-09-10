#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    mcp_tools.py
# Description: The plugin-provided MCP tools behind Contents/Resources/
#              mcp-manifest.json. An Indigo MCP server that reads provider
#              manifests (mlamoure's Indigo MCP Server from v2026.8.1,
#              Claude Bridge from v2.26.0) lists these tools to the AI under
#              the "dashboards_" prefix and forwards each call to the
#              plugin's hidden mcp_tool_invoke action, which hands it to
#              dispatch() here. Every reply is a JSON-string envelope:
#                {"status": "ok", "result": ...}
#                {"status": "error", "error": {"type", "message", "details"}}
#              and a failure is always in-band, never a raised exception.
#              Imported LAZILY by Plugin.handle_mcp_tool_invoke so nothing in
#              this file can affect normal plugin startup, and importable
#              without `indigo` so the tests can drive it.
# Author:      CliveS & Claude Fable 5.1
# Date:        10-09-2026
# Version:     1.0

import json
import os
import re
import sys

try:
    import indigo
except ImportError:      # unit tests run outside the plugin host
    indigo = None

# The bare tool names, in manifest order. test_mcp_manifest pins the manifest
# and this tuple together so a tool cannot be listed to the AI without a
# handler, or handled without being listed.
TOOLS = (
    "get_status",
    "run_setup_check",
    "list_room_folders",
    "set_room_folders",
    "list_cameras",
    "set_camera",
    "remove_camera",
    "read_log",
)

ERROR_TYPES = ("validation", "not_found", "conflict", "internal")

LOG_LINES_DEFAULT = 60
LOG_LINES_MAX     = 400
LOG_TAIL_BYTES    = 512 * 1024       # more than 400 lines of anything this plugin writes

VENDORS = ("dahua", "hikvision")
STREAMS = ("sub2", "main")
# Same rule as the Settings endpoint: a host is later interpolated into
# go2rtc.yaml and MJPEG proxy URLs, so an IP or plain hostname only.
HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,252}[A-Za-z0-9])?$")


class ToolError(Exception):
    """A failure the AI can act on. `kind` is one of ERROR_TYPES."""

    def __init__(self, kind, message, details=None):
        super().__init__(message)
        self.kind    = kind if kind in ERROR_TYPES else "internal"
        self.message = message
        self.details = details


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def ok(result):
    return json.dumps({"status": "ok", "result": result}, default=str)


def err(kind, message, details=None):
    body = {"type": kind if kind in ERROR_TYPES else "internal", "message": str(message)}
    if details is not None:
        body["details"] = details
    return json.dumps({"status": "error", "error": body}, default=str)


def dispatch(plugin, tool, arguments):
    """Run one tool and return its JSON-string envelope. Never raises."""
    handler = HANDLERS.get(str(tool or ""))
    if handler is None:
        return err("not_found", f"unknown tool {tool!r}",
                   {"tools": list(TOOLS)})
    if not isinstance(arguments, dict):
        return err("validation", "arguments must be a JSON object")
    try:
        return ok(handler(plugin, arguments))
    except ToolError as exc:
        return err(exc.kind, exc.message, exc.details)
    except Exception as exc:          # a handler bug must reach the AI as an error, not a hang
        try:
            plugin.logger.error(f"[MCP] tool {tool} failed: {exc}")
        except Exception:
            pass
        return err("internal", f"{tool} failed: {exc}")


# ---------------------------------------------------------------------------
# Argument helpers — calls do not pass through any ConfigUI validation, so
# every argument is checked here and refused with a message the AI can fix.
# ---------------------------------------------------------------------------

def _arg_str(args, name, required=False, choices=None, max_len=200):
    value = args.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ToolError("validation", f"{name} is required")
        return None
    if not isinstance(value, str):
        raise ToolError("validation", f"{name} must be a string")
    value = value.strip()
    if len(value) > max_len:
        raise ToolError("validation", f"{name} is too long (max {max_len} characters)")
    if choices and value not in choices:
        raise ToolError("validation", f"{name} must be one of {', '.join(choices)}",
                        {"choices": list(choices)})
    return value


def _arg_bool(args, name):
    value = args.get(name)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ToolError("validation", f"{name} must be true or false")
    return value


def _arg_int(args, name, default, lo, hi):
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("validation", f"{name} must be a whole number between {lo} and {hi}")
    if not lo <= value <= hi:
        raise ToolError("validation", f"{name} must be between {lo} and {hi}")
    return value


def _arg_str_list(args, name, required=False):
    value = args.get(name)
    if value is None:
        if required:
            raise ToolError("validation", f"{name} is required")
        return None
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise ToolError("validation", f"{name} must be a list of strings")
    return [x.strip() for x in value if x.strip()]


# ---------------------------------------------------------------------------
# Shared readers — one source for each fact, so two tools cannot disagree.
# ---------------------------------------------------------------------------

def _plugin_module(plugin):
    """The module plugin.py loaded as (its module-level CAMERAS and helpers)."""
    return sys.modules[type(plugin).__module__]


def _indigo_folder_names():
    try:
        return sorted({f.name for f in indigo.devices.folders if f.name}, key=str.lower)
    except Exception as exc:
        raise ToolError("internal", f"could not read Indigo's device folders: {exc}")


def _room_folder_view(plugin):
    configured = list(plugin._room_folders())
    store = plugin._load_config_store() or {}
    from_store = isinstance(store.get("roomFolders"), list) and bool(store.get("roomFolders"))
    existing = _indigo_folder_names()
    return {
        "configured":     configured,
        "source":         "settings store" if from_store else "built-in defaults",
        "matching":       [n for n in configured if n in existing],
        "missing":        [n for n in configured if n not in existing],
        "indigoFolders":  existing,
    }


def _saved_cameras(plugin):
    """The camera list as SAVED. Plugin._effective_config() reports the store
    once it is in force (v3.12.0) — the running list, module CAMERAS, only
    changes at restart, so after a save it is stale by design."""
    return [dict(c) for c in (plugin._effective_config().get("cameras") or [])]


def _running_cameras(plugin):
    return [dict(c) for c in _plugin_module(plugin).CAMERAS]


def _editable_config(plugin):
    """The full editor-shaped config to hand to Plugin._apply_config: what is
    SAVED, so two edits in a row compose instead of the second silently
    reverting the first. One owner — the same view the Settings page edits."""
    return plugin._effective_config()


def _apply(plugin, cfg):
    """Persist through the Settings endpoint's own validate + apply path.
    Its IWS-shaped reply is unwrapped; a refusal becomes a validation error
    carrying the endpoint's message, which already names the field."""
    reply = plugin._apply_config(cfg)
    try:
        payload = json.loads(reply.get("content") or "{}")
    except Exception:
        payload = {}
    status = int(reply.get("status") or 500)
    if status != 200 or not payload.get("ok"):
        kind = "validation" if status == 400 else "internal"
        raise ToolError(kind, payload.get("error") or f"save refused (HTTP {status})")
    return payload


def _camera_public(cam):
    """A camera dict as the AI should see it — never a credential."""
    out = {"host": cam.get("host", ""), "name": cam.get("name", ""),
           "vendor": cam.get("vendor", ""), "stream": cam.get("stream") or "sub2"}
    room = cam.get("room")
    if isinstance(room, str):
        out["rooms"] = [room] if room.strip() else []
    elif isinstance(room, (list, tuple)):
        out["rooms"] = [str(r) for r in room if str(r).strip()]
    else:
        out["rooms"] = []
    return out


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def tool_get_status(plugin, args):
    rooms = _room_folder_view(plugin)
    saved = _saved_cameras(plugin)
    mod = _plugin_module(plugin)
    scripts_dir = plugin._scripts_dir()
    present, missing = [], []
    for entry in plugin.COMPANION_SCRIPTS.values():
        name = entry[0]
        (present if os.path.isfile(os.path.join(scripts_dir, name)) else missing).append(name)
    db = plugin._history_db_path()
    go2rtc = getattr(plugin, "_go2rtc_proc", None)
    return {
        "version":       plugin.pluginVersion,
        "dashboardUrl":  plugin._dashboard_url(),
        "configSource":  "settings store (dashboards_config.json)"
                         if getattr(plugin, "cfg_loaded", False)
                         else "IndigoSecrets.py / PluginConfig (legacy, never saved from Settings)",
        "roomFolders": {
            "configured": rooms["configured"],
            "source":     rooms["source"],
            "existInIndigo": len(rooms["matching"]),
            "missing":    rooms["missing"],
        },
        "cameras": {
            "saved":            len(saved),
            "running":          len(mod.CAMERAS),
            "credentialsSet":   bool(getattr(plugin, "cam_user", "") and getattr(plugin, "cam_pass", "")),
            "go2rtcRunning":    go2rtc is not None and go2rtc.poll() is None,
            "mjpegProxyRunning": getattr(plugin, "_mjpeg_server", None) is not None,
        },
        "history": {
            "backend":     str((plugin.pluginPrefs or {}).get("historyBackend") or "sqlite"),
            "sqliteFound": os.path.isfile(db),
        },
        "companionScripts": {"present": present, "missing": missing},
        "pluginLog": _log_path(plugin),
        # Which optional plugins are present (v3.13.0) — the answer to "why is
        # there no Energy page": the pages hide themselves when this is false.
        "features": plugin._feature_flags(),
    }


def tool_run_setup_check(plugin, args):
    checks = []
    for label, passed, detail, optional in plugin._setup_checks():
        verdict = "SKIP" if (optional and not passed) else ("PASS" if passed else "FAIL")
        checks.append({"label": label, "ok": bool(passed), "detail": detail,
                       "optional": bool(optional), "verdict": verdict})
    counted = [c for c in checks if c["verdict"] != "SKIP"]
    failed  = [c["label"] for c in counted if not c["ok"]]
    return {
        "checks":    checks,
        "summary": {
            "counted": len(counted),
            "passed":  len(counted) - len(failed),
            "failed":  failed,
            "skipped": [c["label"] for c in checks if c["verdict"] == "SKIP"],
        },
        "allPassed": not failed,
    }


def tool_list_room_folders(plugin, args):
    return _room_folder_view(plugin)


def tool_set_room_folders(plugin, args):
    folders = _arg_str_list(args, "folders", required=True)
    if not folders:
        raise ToolError("validation", "folders must name at least one Indigo device folder")
    existing = _indigo_folder_names()
    unknown = [n for n in folders if n not in existing]
    if unknown:
        raise ToolError("validation",
                        "these are not Indigo device folders (names are exact, case included): "
                        + ", ".join(unknown),
                        {"unknown": unknown, "available": existing})
    seen, ordered = set(), []
    for n in folders:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    cfg = _editable_config(plugin)
    cfg["roomFolders"] = ordered
    _apply(plugin, cfg)
    view = _room_folder_view(plugin)
    return {"roomFolders": view["configured"], "source": view["source"],
            "roomsBuilt": len(view["matching"]),
            "note": "rooms.json was rebuilt; room pages reflect this on their next load"}


def tool_list_cameras(plugin, args):
    cfg     = _editable_config(plugin)
    saved   = [dict(c) for c in (cfg.get("cameras") or [])]
    running = _running_cameras(plugin)
    mod     = _plugin_module(plugin)
    go2rtc  = getattr(plugin, "_go2rtc_proc", None)
    return {
        "cameras":           [_camera_public(c) for c in saved],
        "mainCameras":       list(cfg.get("mainCameras") or []),
        "swapOutHost":       cfg.get("swapOutHost") or "",
        "credentialsSet":    bool(getattr(plugin, "cam_user", "") and getattr(plugin, "cam_pass", "")),
        "go2rtcRunning":     go2rtc is not None and go2rtc.poll() is None,
        "mjpegProxyRunning": getattr(plugin, "_mjpeg_server", None) is not None,
        "restartPending":    mod._parse_cameras(saved) != mod._parse_cameras(running),
    }


def tool_set_camera(plugin, args):
    host   = _arg_str(args, "host", required=True)
    if not HOST_RE.match(host):
        raise ToolError("validation",
                        "host must be an IP address or plain hostname (letters, digits, dots, hyphens)")
    name   = _arg_str(args, "name", max_len=60)
    vendor = _arg_str(args, "vendor", choices=VENDORS)
    stream = _arg_str(args, "stream", choices=STREAMS)
    rooms  = _arg_str_list(args, "rooms")
    main   = _arg_bool(args, "main")

    cfg = _editable_config(plugin)
    cameras = [dict(c) for c in (cfg.get("cameras") or [])]
    idx = next((i for i, c in enumerate(cameras) if c.get("host") == host), None)
    if idx is None:
        missing = [f for f, v in (("name", name), ("vendor", vendor)) if not v]
        if missing:
            raise ToolError("validation",
                            f"no camera has host {host}; adding one needs {' and '.join(missing)}",
                            {"knownHosts": [c.get("host") for c in cameras]})
        cam = {"host": host, "name": name, "vendor": vendor}
        cameras.append(cam)
        action = "added"
    else:
        cam = cameras[idx]
        if name:
            cam["name"] = name
        if vendor:
            cam["vendor"] = vendor
        action = "updated"
    if stream:
        cam["stream"] = stream
    if rooms is not None:
        if rooms:
            cam["room"] = rooms if len(rooms) > 1 else rooms[0]
        else:
            cam.pop("room", None)
    cfg["cameras"] = cameras

    main_list = [h for h in (cfg.get("mainCameras") or [])]
    if main is True and host not in main_list:
        main_list.append(host)
    elif main is False:
        main_list = [h for h in main_list if h != host]
    cfg["mainCameras"] = main_list

    payload = _apply(plugin, cfg)
    return {
        "action":              action,
        "camera":              _camera_public(cam),
        "mainCameras":         main_list,
        "cameraRestartNeeded": bool(payload.get("cameraRestartNeeded")),
        "note": ("restart the Dashboards plugin (Plugins > Dashboards > Reload) for the "
                 "streaming pipeline to pick this up" if payload.get("cameraRestartNeeded")
                 else "saved; nothing about the streams changed"),
    }


def tool_remove_camera(plugin, args):
    host = _arg_str(args, "host", required=True)
    cfg = _editable_config(plugin)
    cameras = [dict(c) for c in (cfg.get("cameras") or [])]
    kept = [c for c in cameras if c.get("host") != host]
    if len(kept) == len(cameras):
        raise ToolError("not_found", f"no camera has host {host}",
                        {"knownHosts": [c.get("host") for c in cameras]})
    cfg["cameras"] = kept
    cfg["mainCameras"] = [h for h in (cfg.get("mainCameras") or []) if h != host]
    if (cfg.get("swapOutHost") or "") == host:
        cfg["swapOutHost"] = ""
    payload = _apply(plugin, cfg)
    return {
        "removed":             host,
        "camerasRemaining":    len(kept),
        "mainCameras":         cfg["mainCameras"],
        "cameraRestartNeeded": bool(payload.get("cameraRestartNeeded")),
    }


def _log_path(plugin):
    try:
        base = indigo.server.getInstallFolderPath()
    except Exception as exc:
        raise ToolError("internal", f"could not resolve the Indigo install folder: {exc}")
    return os.path.join(base, "Logs", plugin.pluginId, "plugin.log")


def _tail_lines(path, limit):
    """The last `limit` lines of a text file without reading all of it."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > LOG_TAIL_BYTES:
            f.seek(size - LOG_TAIL_BYTES)
            data = f.read()
            data = data[data.find(b"\n") + 1:]      # drop the partial first line
        else:
            data = f.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[-limit:], len(lines)


def tool_read_log(plugin, args):
    limit    = _arg_int(args, "lines", LOG_LINES_DEFAULT, 1, LOG_LINES_MAX)
    contains = _arg_str(args, "contains", max_len=120)
    path = _log_path(plugin)
    if not os.path.isfile(path):
        raise ToolError("not_found", f"no plugin log at {path}")
    if contains:
        # Filter over a generous window first, then cut to the requested count.
        window, _ = _tail_lines(path, LOG_LINES_MAX * 10)
        needle = contains.lower()
        matched = [ln for ln in window if needle in ln.lower()]
        lines = matched[-limit:]
        truncated = len(matched) > limit
    else:
        lines, available = _tail_lines(path, limit)
        truncated = available > limit
    return {"path": path, "lines": lines, "count": len(lines),
            "truncated": truncated, "contains": contains or ""}


HANDLERS = {
    "get_status":        tool_get_status,
    "run_setup_check":   tool_run_setup_check,
    "list_room_folders": tool_list_room_folders,
    "set_room_folders":  tool_set_room_folders,
    "list_cameras":      tool_list_cameras,
    "set_camera":        tool_set_camera,
    "remove_camera":     tool_remove_camera,
    "read_log":          tool_read_log,
}
