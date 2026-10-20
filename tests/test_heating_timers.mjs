import fs from "node:fs";
import vm from "node:vm";
import {check, done} from "./lib/check.mjs";
const page = fs.readFileSync(new URL("../Dashboards.indigoPlugin/Contents/Resources/static/pages/heating.html", import.meta.url), "utf8");
const elements = {};
for (const key of ["boost1", "boost2", "summer", "timer-status"]) elements["evo-" + key] = {
 textContent: "", attrs: {}, active: false,
 setAttribute(k,v) { this.attrs[k] = v; },
 classList: {toggle(k,v) { elements["evo-" + key].active = v; }},
};
let clock = 100000;
let reply = {ok:true, serverNow:1000, boostHours:1, boostExpiry:4600, summerExpiry:87400};
const ctx = {Date:{now:()=>clock}, document:{getElementById:id=>elements[id]},
 window:{INDIGO_CONFIG:{heatingControls:true}},
 DashUI:{message:async()=> {if(reply instanceof Error) throw reply; return reply;},poll(){}},
 setInterval(){}, _pad:n=>String(n).padStart(2,"0")};
vm.createContext(ctx);
vm.runInContext(page.slice(page.indexOf("    let _evoToastTimer"), page.indexOf("    async function callEvoAction")),ctx);
await ctx.refreshEvoTimers();
check("one-hour and summer timers can both be active",elements["evo-boost1"].active && elements["evo-summer"].active);
check("other boost stays blue",!elements["evo-boost2"].active);
check("saved boost has countdown",elements["evo-boost1"].textContent.endsWith("1:00:00 left"));
check("24-hour countdown",elements["evo-summer"].textContent.endsWith("24:00:00 left"));
clock+=1000;ctx.renderEvoTimers();
check("ticks each second",elements["evo-boost1"].textContent.endsWith("0:59:59 left"));
reply={ok:true,serverNow:1001,boostHours:2,boostExpiry:8201,summerExpiry:null};await ctx.refreshEvoTimers();
check("switch duration and cancel summer",!elements["evo-boost1"].active && elements["evo-boost2"].active && !elements["evo-summer"].active);
reply={ok:true,serverNow:8201,boostHours:2,boostExpiry:8201,summerExpiry:null};await ctx.refreshEvoTimers();
check("expiry clears red",!elements["evo-boost2"].active);
reply=new Error("offline");await ctx.refreshEvoTimers();
check("failure says unknown",elements["evo-timer-status"].textContent.includes("unavailable"));
reply={ok:true,serverNow:1000,boostHours:1,boostExpiry:4600,summerExpiry:null};await ctx.refreshEvoTimers();
clock+=16000;ctx.renderEvoTimers();
check("stale status loses active claim",!elements["evo-boost1"].active && elements["evo-timer-status"].textContent.includes("unavailable"));
done();
