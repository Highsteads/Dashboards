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
const ctx = {Date: {now: () => clock}, document: {getElementById: id => elements[id]},
  window: {INDIGO_CONFIG: {heatingControls: true}},
  DashUI: {message: async () => reply, poll() {}}, setInterval() {}, _pad: n => String(n).padStart(2, "0"),
  escapeHtml: t => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"),
  DashTile: {zone: {setpoint: d => d.setpointHeat}},
  _zoneById: new Map([[11, {setpointHeat: 22}], [0, {setpointHeat: 14}]])};
vm.createContext(ctx);
vm.runInContext(page.slice(page.indexOf("    let _evoToastTimer"), page.indexOf("    async function callEvoAction")), ctx);
const rooms = [
  {id: 11, room: "Living Room Front", target: 22, requested: 22, held: ""},
  {id: 0, room: "Living Room Door", target: 22, requested: 22, held: ""},
  {id: 9, room: "Dining Room", target: 22, requested: 16, held: "it is already warm from the sun"},
  {id: 3, room: "Hall <Kitchen>", target: 22, requested: null, held: ""},
];
reply = {ok: true, serverNow: 1000, boostHours: 1, boostExpiry: 4600, summerExpiry: null, boostRooms: rooms};
await ctx.refreshEvoTimers();
const html = list.innerHTML;
check("list shown while boosting", list.hidden === false);
check("confirmed when the radiator reports the setting", html.includes('class="ok">Living Room Front: 22 degrees, confirmed by Evohome.'));
check("waiting when the radiator has not", html.includes('class="wait">Living Room Door: 22 degrees sent, waiting for Evohome to confirm.'));
check("held back says why", html.includes('class="held">Dining Room: kept at 16 degrees because it is already warm from the sun.'));
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
