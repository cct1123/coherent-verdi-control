/* Front-panel POWER ADJUST knob and DISPLAY CONTRAST trimmer, browser-only.
 * The knob edits the unsent target-power input and never submits a request;
 * SET POWER (or Apply power) is still the explicit write.
 */
(function () {
    const CONTRAST = [0.55, 0.75, 1, 1.3, 1.6];
    let contrast = Number(localStorage.getItem("verdi-lcd-contrast") || 2);
    let drag = null;
    // Dash updates aria-valuenow asynchronously; chain rapid steps from the last value set.
    let pending = null;

    function applyContrast() {
        contrast = Math.min(CONTRAST.length - 1, Math.max(0, contrast | 0));
        document.documentElement.style.setProperty("--lcd-contrast", CONTRAST[contrast]);
    }
    applyContrast();

    function knobAt(target) {
        const knob = target instanceof Element ? target.closest("#panel-knob") : null;
        const panel = knob && knob.closest("fieldset");
        // Follow the panel's server/watchdog lock, like every other write control.
        return knob && panel && !panel.disabled ? knob : null;
    }

    function setTarget(knob, value) {
        const max = Number(knob.dataset.max) || 0;
        let maxSteps = Math.round(max * 100);
        if (maxSteps / 100 > max) maxSteps -= 1;
        const clamped = Math.min(maxSteps, Math.max(0, Math.round(value * 100))) / 100;
        if (window.dash_clientside && window.dash_clientside.set_props) {
            window.dash_clientside.set_props("target-power", {value: clamped});
            pending = {value: clamped, at: performance.now()};
        }
        return clamped;
    }

    function current(knob) {
        if (pending && performance.now() - pending.at < 500) return pending.value;
        return Number(knob.getAttribute("aria-valuenow")) || 0;
    }

    function angle(knob, event) {
        const box = knob.getBoundingClientRect();
        return Math.atan2(event.clientY - box.top - box.height / 2,
                          event.clientX - box.left - box.width / 2) * 180 / Math.PI;
    }

    document.addEventListener("pointerdown", function (event) {
        const knob = knobAt(event.target);
        if (!knob) return;
        knob.setPointerCapture(event.pointerId);
        drag = {knob: knob, angle: angle(knob, event), value: current(knob)};
        event.preventDefault();
    });
    document.addEventListener("pointermove", function (event) {
        if (!drag) return;
        if (!knobAt(drag.knob)) { drag = null; return; }
        const now = angle(drag.knob, event);
        const turn = ((now - drag.angle + 540) % 360) - 180;
        drag.angle = now;
        // 270 degrees of travel spans the full power ceiling, like the scale on the knob.
        const max = Number(drag.knob.dataset.max) || 0;
        // Accumulate small movements before rounding; slow drags must still advance a step.
        drag.value = Math.min(max, Math.max(0, drag.value + turn / 270 * max));
        setTarget(drag.knob, drag.value);
    });
    document.addEventListener("pointerup", function () { drag = null; });
    document.addEventListener("pointercancel", function () { drag = null; });

    document.addEventListener("wheel", function (event) {
        const knob = knobAt(event.target);
        if (!knob) return;
        event.preventDefault();
        const step = event.shiftKey ? 0.1 : 0.01;
        setTarget(knob, current(knob) + (event.deltaY < 0 ? step : -step));
    }, {passive: false});

    document.addEventListener("keydown", function (event) {
        const trimmer = event.target instanceof Element && event.target.closest("#panel-contrast");
        if (trimmer && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            trimmer.click();
            return;
        }
        const knob = knobAt(event.target);
        if (!knob) return;
        const max = Number(knob.dataset.max) || 0;
        const steps = {ArrowUp: 0.01, ArrowRight: 0.01, ArrowDown: -0.01, ArrowLeft: -0.01,
                       PageUp: 0.1, PageDown: -0.1};
        if (event.key in steps) {
            setTarget(knob, current(knob) + steps[event.key] * (event.shiftKey ? 10 : 1));
        } else if (event.key === "Home") {
            setTarget(knob, 0);
        } else if (event.key === "End") {
            setTarget(knob, max);
        } else {
            return;
        }
        event.preventDefault();
    });

    document.addEventListener("click", function (event) {
        const trimmer = event.target instanceof Element && event.target.closest("#panel-contrast");
        if (!trimmer) return;
        contrast = (contrast + 1) % CONTRAST.length;
        localStorage.setItem("verdi-lcd-contrast", String(contrast));
        applyContrast();
    });
}());
