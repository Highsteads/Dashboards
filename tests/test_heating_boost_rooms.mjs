// The Heating page says, room by room, what a running boost asked for, whether
// Evohome has confirmed it, or why the room was given less (3.70.0).
import fs from "node:fs";
import vm from "node:vm";
import {check, done} from "./lib/check.mjs";
const page = fs.readFileSync(new URL("../Dashboards.indigoPlugin/Contents/Resources/static/pages/heating.html", import.meta.url), "utf8");
const list = {hidden: true, innerHTML: ""};
const elements = {"evo-boost-rooms": list};
for (const key of ["boost1", "boost2", "summer", "timer-status"]) elements["evo-" + key] = {
  textContent: "", setAttribute() {}, classList: {toggle() {}}};
let reply;
let clock = 100000;
const ctx = {Date: Object.assign(function (ms) { return new Date(ms); }, {now: () => clock}), document: {getElementById: id => elements[id]},
  window: {INDIGO_CONFIG: {heatingControls: true}},
  DashUI: {message: async () => reply, poll() {}}, setInterval() {}, _pad: n => String(n).padStart(2, "0"),
  escapeHtml: t => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"),
  // notLive: 3.73.13, a radiator that cannot be heard confirms nothing.
  DashTile: {zone: {setpoint: d => d.setpointHeat, notLive: d => (d.enabled === false ? "disabled" : "")}},
  // Zone 9 (Dining Room) has taken its 12: "set to" is said only when the radiator says so itself.
  _zoneById: new Map([[11, {setpointHeat: 22}], [0, {setpointHeat: 14}], [2, {setpointHeat: 21}], [9, {setpointHeat: 12}]])};
vm.createContext(ctx);
vm.runInContext(page.slice(page.indexOf("    let _evoToastTimer"), page.indexOf("    async function callEvoAction")), ctx);
// Clock times are checked in the machine's own time, as the page shows them.
function words(ms) {
  const d = new Date(ms), h = d.getHours(), m = d.getMinutes();
  if (h === 0 && m === 0) return "midnight";
  if (h === 12 && m === 0) return "noon";
  return (h % 12 || 12) + (m ? ":" + String(m).padStart(2, "0") : "") + (h < 12 ? "am" : "pm");
}
const HOLD_END = 1795615348, BOOST_END = 1795618976;
const rooms = [
  {id: 11, room: "Living Room Front", target: 22, requested: 22, held: ""},
  {id: 0, room: "Living Room Door", target: 22, requested: 22, held: ""},
  {id: 9, room: "Dining Room", target: 22, requested: 12, held: "a window is open"},
  {id: 2, room: "Conservatory", target: 22, requested: 20, held: "it was set by hand", byHand: true, until: HOLD_END},
  {id: 5, room: "Snug", target: 22, requested: 19, held: "it was set by hand", byHand: true, until: null},
  {id: 3, room: "Hall <Kitchen>", target: 22, requested: null, held: ""},
];
reply = {ok: true, serverNow: 1000, boostHours: 1, boostExpiry: BOOST_END, summerExpiry: null, boostRooms: rooms};
await ctx.refreshEvoTimers();
const html = list.innerHTML;
check("list shown while boosting", list.hidden === false);
check("confirmed when the radiator reports the setting, with the end time", html.includes(`class="ok">Living Room Front: set to 22 degrees until ${words(BOOST_END * 1000)}, confirmed by Evohome.`));
check("waiting when the radiator has not", html.includes('class="wait">Living Room Door: 22 degrees sent, waiting for Evohome to confirm.'));
check("a room the boost cannot reach says so and why", html.includes('class="held">Dining Room: not boosted, set to 12 degrees because a window is open.'));
check("a room set by hand shows the radiator's own setting, not the last request", html.includes(`class="held">Conservatory: set to 21 degrees by hand, so the boost leaves it alone until ${words(HOLD_END * 1000)}.`));
check("a hold with no end says so", html.includes('class="held">Snug: set to 19 degrees by hand, so the boost leaves it alone until it is changed.'));
check("no summary unless every room has its boost", !html.includes("All "));
reply = {ok: true, serverNow: 1000, boostHours: 1, boostExpiry: BOOST_END, summerExpiry: null, boostRooms: [
  {id: 11, room: "Living Room Front", target: 22, requested: 22, held: ""},
  {id: 12, room: "Dining Room", target: 22, requested: 22, held: ""}]};
ctx._zoneById.set(12, {setpointHeat: 22});
await ctx.refreshEvoTimers();
check("the answer first when every room has its boost", list.innerHTML.startsWith(`<li class="ok all">All two boosted rooms are set to 22 degrees until ${words(BOOST_END * 1000)}, confirmed by Evohome.</li>`));
reply = {ok: true, serverNow: 1000, boostHours: 1, boostExpiry: BOOST_END, summerExpiry: null, boostRooms: rooms};
await ctx.refreshEvoTimers();
check("not reached yet", html.includes("Hall &lt;Kitchen&gt;: waiting for the heating controller"));
check("no value dumps", !/[|=]\s*\d/.test(html.replace(/class="\w+"/g, "")));
clock += 16000; ctx.renderEvoTimers();
check("hidden when the status goes stale", list.hidden === true);
clock -= 16000;
reply = {ok: true, serverNow: 1000, boostHours: 0, boostExpiry: null, summerExpiry: null, boostRooms: rooms};
await ctx.refreshEvoTimers();
check("hidden once the boost has ended", list.hidden === true && list.innerHTML === "");
reply = undefined;
await ctx.refreshEvoTimers();
check("hidden when status is unknown", list.hidden === true);
done();
