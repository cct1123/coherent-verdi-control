"""Exercise the actual knob event handlers with an in-memory DOM; no browser or hardware."""

import json
import shutil
import subprocess
from math import ulp
from pathlib import Path

import pytest

from coherent_verdi import SimulatedVerdi
from coherent_verdi.controller import validate_power_w
from coherent_verdi.gui import create_app
from coherent_verdi.monitor import Monitor


def test_knob_edits_use_power_steps_preserve_ceiling_and_accumulate_slow_drags():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to exercise browser event handlers")
    asset = Path(__file__).resolve().parents[1] / "src/coherent_verdi/assets/panel.js"
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const listeners = {};
const edits = [];
const panel = {disabled: false};
class Element {}
const knob = new Element();
knob.dataset = {max: '0.12346'};
knob.closest = selector => selector === '#panel-knob' ? knob
    : selector === 'fieldset' ? panel : null;
knob.getAttribute = () => '0';
knob.getBoundingClientRect = () => ({left: 0, top: 0, width: 100, height: 100});
knob.setPointerCapture = () => {};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
    Element, performance: {now: () => 0},
    localStorage: {getItem: () => null},
    document: {
        documentElement: {style: {setProperty: () => {}}},
        addEventListener: (name, handler) => {listeners[name] = handler;},
    },
    window: {dash_clientside: {set_props: (id, props) => {
        assert.equal(id, 'target-power');
        edits.push(props.value);
    }}},
});
const event = extra => ({target: knob, preventDefault() {}, shiftKey: false, ...extra});
const key = key => listeners.keydown(event({key}));
key('End');
assert.equal(edits.at(-1), 0.12); // Never clamp to a non-step ceiling.
key('Home');
key('ArrowUp');
assert.equal(edits.at(-1), 0.01);
listeners.wheel(event({deltaY: -1}));
assert.equal(edits.at(-1), 0.02); // Rapid edits chain from the last unsent value.
knob.dataset.max = '0.29';
key('End');
assert.equal(edits.at(-1), 0.29); // Binary 0.29 * 100 must not lose a step.
knob.dataset.max = '0.009';
key('End');
assert.equal(edits.at(-1), 0);
knob.dataset.max = '0.5';
key('Home');
const point = degrees => ({clientX: 50 + 40 * Math.cos(degrees * Math.PI / 180),
                          clientY: 50 + 40 * Math.sin(degrees * Math.PI / 180)});
listeners.pointerdown(event({pointerId: 1, ...point(0)}));
for (let degrees = 1; degrees <= 6; degrees++) {
    listeners.pointermove(event(point(degrees)));
}
assert.equal(edits.at(-1), 0.01); // Accumulate sub-step motion across events.
panel.disabled = true;
const before = edits.length;
listeners.pointermove(event(point(60)));
key('ArrowUp');
listeners.wheel(event({deltaY: -1}));
assert.equal(edits.length, before); // A drag cannot keep editing a disabled panel.
assert(edits.every(value => Math.abs(value * 100 - Math.round(value * 100)) < 1e-12));
"""
    subprocess.run([node, "-e", script, str(asset)], check=True, capture_output=True, text=True)


def test_target_label_and_preset_lamps_reject_invalid_values():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to exercise browser presentation callbacks")
    app = create_app(Monitor(SimulatedVerdi()))
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {window: {}};
const {scripts, cases} = JSON.parse(fs.readFileSync(0, 'utf8'));
scripts.forEach(source => vm.runInNewContext(source, context));
const [target, lamps] = Object.values(context.window.dash_clientside._dashprivate_clientside_funcs);
assert.equal(target(0.01, 0.5)[2], 'TARGET 0.01 W');
assert.equal(target(0.1 + 0.2, 0.5)[2], 'TARGET 0.30 W');
assert.equal(target(0.002, 0.5)[2], 'TARGET INVALID');
assert.equal(target(0.125, 0.5)[2], 'TARGET INVALID');
assert.equal(target(0.51, 0.5)[2], 'TARGET INVALID');
assert.equal(target(0, 0)[2], 'TARGET 0.00 W');
assert.equal(lamps(0.125, 0.125, 0.25, 0.5)[0], 'led');
assert.equal(lamps(0.25, 0.25, 0.5, 0.5)[0], 'led on');
assert.equal(lamps(0.25, 0.25, null, 0.12)[0], 'led');
assert.equal(lamps(0.3, 0.1 + 0.2, null, 0.5)[0], 'led on');
assert.equal(lamps(null, 0.25, 0.5, 0.5)[0], 'led unknown');
for (const {value, valid} of cases) {
    assert.equal(target(value, 0.5)[2] !== 'TARGET INVALID', valid, `target ${value}`);
    const setpoint = Math.round(value * 100) / 100;
    assert.equal(lamps(setpoint, value, null, 0.5)[0], valid ? 'led on' : 'led',
                 `preset ${value}`);
}
"""
    cases = []
    for base in (0, 0.01, 0.29, 0.49, 0.5):
        for offset in range(-4, 5):
            value = base + offset * ulp(base)
            try:
                validate_power_w(value, 0.5)
                valid = True
            except ValueError:
                valid = False
            cases.append(dict(value=value, valid=valid))
    subprocess.run(
        [node, "-e", script],
        input=json.dumps(dict(scripts=app._inline_scripts, cases=cases)),
        check=True,
        capture_output=True,
        text=True,
    )
