---
title: Claude Code and MCP tools
nav_order: 9
---

# Claude Code and MCP tools

The whole dashboard was built and is maintained through conversation with Claude Code — no
hand-editing of HTML or plugin internals required, and none by me. None of this is needed to *run*
the plugin: the pages need Indigo and a browser, nothing else. It is how you extend it, and how you
get help when something is not working. If you have never done any of this, start with
[Start with nothing but Claude](no-coding-needed.md), which walks a complete beginner through it.

Claude Code is included in every paid Claude plan (Pro is the cheapest) and in Anthropic Console
accounts with pre-paid credits. It is not on the free plan. It shares the plan's usage limits.

## What each part adds

| You have | What Claude can do for the dashboards |
|---|---|
| **Claude Code alone** | Download and install the plugin, install ffmpeg, go2rtc and Tailscale, read and edit the pages, read the plugin's log file, and build any page you can describe. It cannot see Indigo: a device is a number you have to look up and tell it |
| **+ an Indigo MCP server** | See your devices, variables, action groups and folders by name, read their states and the event log, run actions, restart plugins. "The kitchen light" is enough; it finds the device. Diagnosis becomes a conversation: "why is the garden camera not streaming" and it goes and looks |
| **+ this plugin's own tools** (automatic, v3.12.0+) | Run the dashboards' setup check as data, list and change your rooms and cameras, read the plugin's log — through the same MCP server, with nothing configured |
| **+ Tailscale** | Everything above from anywhere, and the dashboards themselves on your phone when you are out |

## Building on it

To give a flavour of the kind of thing you can ask:

- *"Add a heating page that shows all my thermostat zones with their current temperature and
  setpoint"*
- *"The garden camera is not showing in the grid — check the go2rtc config and see what is wrong"*
- *"Add a door control tile to the garage room page that pulses relay device 12345 for 2 seconds
  when tapped, and shows open or closed using contact sensor 67890"*
- *"Create a room page for the conservatory showing its lights, the patio contact sensor, and the
  camera on 192.168.1.55"*
- *"Install ffmpeg and go2rtc on my Mac so the camera grid works"*
- *"The weather card on the hub is not updating — have a look at the event log and tell me what is
  going on"*

Claude Code can read the plugin source, check the Indigo event log through whichever Indigo MCP
server you run, edit pages, restart the plugin and verify the result — all in one conversation.
Most changes that would otherwise mean half an hour of hunting through source files take a couple
of minutes.

**Which MCP server?** Any of the Indigo MCP servers gives Claude live access to your server:
[Claude Bridge](https://github.com/Highsteads/ClaudeBridge) (the author's own),
[mlamoure's Indigo MCP Server](https://github.com/mlamoure/indigo-mcp-server), or Simon's
[MCP Lite](https://github.com/simons-plugins). Each README states its own Indigo and Mac
requirements. Loading [Simon's Indigo skills](https://github.com/simons-plugins/indigo-claude-skill)
at the start of a session gives Claude the Indigo SDK reference and worked examples in a form it can
use, and saves a good deal of time and tokens.

## The plugin's own tools

From v3.12.0 the bundle ships `Contents/Resources/mcp-manifest.json`, a plugin-provided tool
manifest. An Indigo MCP server that reads those — mlamoure's Indigo MCP Server from v2026.8.1, Claude
Bridge from v2.26.0 — finds it on its own and lists these tools to Claude, with no configuration on
either side:

| Tool | What it does |
|---|---|
| `dashboards_get_status` | Version, hub URL, where the configuration comes from, room folders and how many exist, the camera pipeline, the history backend, which companion scripts are present, and the feature flags |
| `dashboards_run_setup_check` | The Test Dashboards Setup sweep, returned as data: every check with its verdict and detail |
| `dashboards_list_room_folders` | The folders that become rooms, whether they are the built-in defaults, every folder Indigo has, and any configured name that does not exist |
| `dashboards_set_room_folders` | Replace the room folders. Unknown names are refused and the real ones listed back. Live at once |
| `dashboards_list_cameras` | The saved cameras, the hub strip, whether credentials are set and the streams are running, and whether a restart is pending |
| `dashboards_set_camera` | Add a camera, or change the one with that host. Says whether a restart is needed |
| `dashboards_remove_camera` | Remove a camera, and take it out of the hub strip |
| `dashboards_read_log` | The last lines of the plugin's own log, optionally filtered to a phrase |

So "set my dashboard rooms to Kitchen, Hall and Lounge" or "why is the garden camera not streaming"
is a conversation with no source files in it.

The writes are refused if the MCP server's "allow plugin-provided tools to make changes" setting is
off, and every write goes through the same validation as the Settings page. Reads never return a
credential. Without an MCP server the manifest is inert data and nothing about the plugin changes.

**A note for people writing their own provider.** The manifest follows the provider-manifest v1
contract that mlamoure published with his server. The plugin answers a hidden `mcp_tool_invoke`
action with a JSON-string envelope, imports its tool module lazily so a fault there cannot stop the
plugin starting, and broadcasts `mcp_tools_updated` on startup so a server can rescan. The
implementation is `Server Plugin/mcp_tools.py`; the tests are `tests/test_mcp_manifest.py` and
`tests/test_mcp_tools.py`.
