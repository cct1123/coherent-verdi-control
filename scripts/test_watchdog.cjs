/* Browser watchdog behavior with virtual time; no browser/network/device access. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
let now = 0;
let timer;
let disconnected = false;
const nodes = {
    dashboard: {classList: {toggle: (name, value) => {
        assert.equal(name, "connection-lost");
        disconnected = value;
    }}},
    "server-heartbeat": {textContent: ""},
    "connection-warning": {textContent: ""}
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,
    "../src/coherent_verdi/assets/watchdog.js"), "utf8"), {
    document: {getElementById: id => nodes[id]},
    performance: {now: () => now},
    setInterval: (callback, interval) => {assert.equal(interval, 1000); timer = callback;}
});
timer();
assert.match(nodes["connection-warning"].textContent, /Waiting/);
nodes["server-heartbeat"].textContent = "0";
now = 1000;
timer();
assert.equal(nodes["connection-warning"].textContent, "");
now = 9000;
timer();
assert.equal(disconnected, false);
now = 12000;
timer();
assert.equal(disconnected, true);
assert.match(nodes["connection-warning"].textContent, /all displayed values are stale/);
// A new received callback recovers without depending on wall-clock/host timestamps.
nodes["server-heartbeat"].textContent = "1";
timer();
assert.equal(disconnected, false);
assert.equal(nodes["connection-warning"].textContent, "");
console.log(`PASS: browser watchdog startup, live receipt, expiry and recovery (virtual clock; Node ${process.version})`);
