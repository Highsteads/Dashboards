/* capabilities.js — catalog-driven control selection for Dashboards.
 *
 * Loads the device capability catalog (catalog.json, generated from the live
 * estate by indigo-device-catalog) and decides which control a device should
 * render from its (pluginId, deviceTypeId) PROFILE — capabilities + states +
 * displayStateId — instead of regex-ing the device's class string inline.
 *
 * Today the room view infers control type ad-hoc, e.g.
 *     const isDimmer = /Dimmer/.test(d.class);
 *     ... d.supportsColor === true ...
 * scattered across room.html. This module makes that one
 * declarative source, and unlocks richer decisions (is there power/energy to
 * show? a battery? which state is primary?) that the scattered regex can't.
 *
 * It DEGRADES GRACEFULLY: a device with no catalog profile yet falls back to
 * the same live-device inference the dashboard already uses, so nothing breaks
 * for an uncatalogued device.
 *
 * The catalog is device-TYPE metadata only (no device names / IPs / secrets),
 * so it is safe to serve from the anonymous /public/ namespace.
 */
const Capabilities = (() => {
  let CATALOG = {};
  let loaded = false;

  async function load(url = "catalog.json") {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      CATALOG = await res.json();
      loaded = true;
    } catch (e) {
      console.warn("capabilities: catalog load failed, falling back to live inference", e);
      CATALOG = {};
    }
    return loaded;
  }

  /* The catalog profile for a device, or null if not catalogued.
   * Primary key is (pluginId, deviceTypeId). Falls back to a deviceTypeId scan
   * so it still resolves if the browser device feed omits pluginId (deviceTypeIds
   * are plugin-namespaced — z2mLight, shellyRelay, matterMotionSensor — so a
   * cross-plugin collision is vanishingly unlikely). */
  function profileFor(device) {
    const byType = CATALOG[device.pluginId];
    if (byType && byType[device.deviceTypeId]) return byType[device.deviceTypeId];
    if (device.deviceTypeId) {
      for (const pid in CATALOG) {
        if (pid[0] === "_") continue;                       // skip _meta
        if (CATALOG[pid][device.deviceTypeId]) return CATALOG[pid][device.deviceTypeId];
      }
    }
    return null;
  }

  /* Decide the primary control + secondary annotations for a device.
   * Returns { control, annotations[], displayStateId, fromCatalog }.
   * control ∈ "color" | "dimmer" | "switch" | "sensor" | "readonly".
   */
  function controlFor(device) {
    const p = profileFor(device);
    const caps = (p && p.capabilities) || {};
    const cls = device.class || (p && p.baseClass) || "";
    // State presence drives the power/energy/battery annotations. Derive it from
    // the device's OWN live states (which every Indigo install provides) unioned
    // with the catalog profile's state list when one is present — so this works
    // for anyone with no catalog, and the catalog is a pure refinement.
    const _catStates  = (p && p.states) || [];
    const _liveStates = (device.states && typeof device.states === "object") ? Object.keys(device.states) : [];
    const _stateSet   = new Set([].concat(_catStates, _liveStates));
    const hasState = (s) => _stateSet.has(s);

    // Primary control — prefer the catalog's capability flags, fall back to the
    // live device fields the dashboard already has. Order matters:
    //   thermostat → colour → dimmer → SENSOR → switch.
    // Sensor is tested BEFORE switch so a binary sensor (contact/motion/presence)
    // that carries its state on `onState` renders as a READ-ONLY indicator, not
    // a toggle the user could press. A switch must be a true output device.
    let control = "readonly";
    const isDimmer = /Dimmer/.test(cls) || caps.supportsDimmer === true ||
                     hasState("brightnessLevel") || device.brightness != null;
    const isSensor = /Sensor/.test(cls) || caps.supportsSensorValue === true;
    if (/Thermostat/.test(cls)) control = "thermostat";
    else if (caps.supportsColor === true || device.supportsColor === true) control = "color";
    else if (isDimmer) control = "dimmer";
    else if (isSensor) control = "sensor";
    else if (caps.supportsOnState === true || /Relay/.test(cls) ||
             typeof device.onState === "boolean") control = "switch";

    // Secondary annotations from the profile's state set — what extra a smart
    // card can surface without per-room hardcoding.
    const annotations = [];
    if (hasState("powerWatts") || hasState("curEnergyLevel") || caps.supportsEnergyMeterCurPower)
      annotations.push("power");
    if (hasState("energyKwhToday") || hasState("accumEnergyTotal") || hasState("energyKwhMonth"))
      annotations.push("energy");
    if (hasState("battery") || hasState("batteryLevel")) annotations.push("battery");

    return {
      control,
      annotations,
      displayStateId: (p && p.displayStateId) || device.displayStateId || null,
      fromCatalog: !!p,
    };
  }

  return {
    load, controlFor, profileFor,
    get loaded() { return loaded; },
    get size() {  // total device-type profiles across all plugins
      let n = 0;
      for (const pid in CATALOG) if (pid[0] !== "_") n += Object.keys(CATALOG[pid]).length;
      return n;
    },
  };
})();

if (typeof window !== "undefined") window.Capabilities = Capabilities;               // explicit global for inline scripts
if (typeof module !== "undefined" && module.exports) module.exports = Capabilities;  // node-testable
