/* UI-only watchdog, independent of Dash's server callback dependency graph.
 * Owns only the warning text and CSS class; never issues network/device requests.
 */
(function () {
    let previous = null;
    let receivedAt = null;
    setInterval(function () {
        const root = document.getElementById("dashboard");
        const signal = document.getElementById("server-heartbeat");
        const warning = document.getElementById("connection-warning");
        if (!root || !signal || !warning) return;
        const now = performance.now();
        const heartbeat = signal.textContent;
        if (receivedAt === null || (heartbeat !== "" && heartbeat !== previous)) {
            previous = heartbeat;
            receivedAt = now;
        }
        const stale = now - receivedAt > 10000;
        warning.textContent = stale
            ? "SERVER UPDATE LOST — all displayed values are stale. Check the dashboard server."
            : heartbeat === "" ? "Waiting for the monitoring server…" : "";
        root.classList.toggle("connection-lost", stale);
        // Operate controls and the front-panel replica.
        document.querySelectorAll("fieldset[data-server-disabled]").forEach(function (controls) {
            controls.disabled = stale || controls.getAttribute("data-server-disabled") === "true";
        });
    }, 1000);
}());
