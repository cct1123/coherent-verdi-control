# Project definition

## Engineering objective

Build a production-quality Python controller for Coherent Verdi V-2/V-5/V-6
lasers, based on the documented RS-232 interface, suitable for integration into
larger research hardware stacks. Provide a clean Python API, robust
telemetry/diagnostics, simulator/fake hardware, CLI, and an optional Plotly Dash
GUI. The GUI must be a client of the controller library, not the protocol
implementation.

## Requirements / acceptance criteria

- Use the Coherent Verdi operator manual as the authoritative protocol/behavior
  reference. Do not invent undocumented device behavior.
- Provide the controller library, telemetry/diagnostics, fake hardware, CLI, and
  optional Dash GUI described above. Derive measurable software criteria in
  STATE.md and connect them to reproducible evidence.
- Initialize and use the engineering framework from
  https://github.com/cct1123/agentic-engineering-template; preserve useful existing
  work and do not modify upstream.
- Immediately continue the inspect -> gap -> design -> implement -> test ->
  diagnose loop after initialization. Scaffolding alone is not completion.

## Constraints

- This phase is completely **HARDWARE-FREE**. Do not probe or enumerate serial
  ports, connect to serial devices, or access physical laboratory hardware,
  including from tests, examples, initialization, recovery, or cleanup.
- Lack of hardware is not a blocker for software development. Complete meaningful
  independent software work and report physical behavior as UNTESTED.
- The GUI consumes controller/telemetry APIs; it does not implement or separately
  poll the protocol.
- Unknown protocol details remain explicitly unknown; simulator policy must be
  distinguished from documented firmware behavior.
- Follow the template's human review gate before any future hardware interaction.
  The current request authorizes no such interaction.

## Available system

- Working repository: `C:\projects\coherent-verdi-control`.
- Authoritative supplied manual: `verdi.manual_v5.pdf` (Coherent Verdi V-2/V-5/V-6
  Operator's Manual, part 0171-750-00, Rev IB).
- Existing `prompt log.txt` is preserved reference material. Its later-phase
  example prompts are not active user instructions or hardware authorization.
- No implementation existed at initial inspection; `main` initially had no commits.
- Framework source pinned to commit
  `724a7f772069d3357ea66dbc4742d25bd874a33e`; downloaded read-only on 2026-09-09.

## Project-specific context

Initial authorization: the user's task in this session, 2026-09-09. Reversible
software work is authorized; physical validation is outside this phase.

## Beginner tutorials (user request, 2026-09-10)

Provide four simple, representative command-control use cases for a new Verdi
user. For each, implement a small tutorial example, a clear Jupyter notebook and
concise documentation explaining the command sequence, expected behavior and
basic error/safety handling. Structure the examples for later hardware use with
minimal changes. Develop and test every example using the Verdi simulator only.
They must be practical, beginner-friendly starting points; this request does not
authorize hardware discovery, connection or operation.

User clarification, 2026-09-10: implement the tutorials for real-hardware use by
human operators, rather than leaving serial setup as an adaptation exercise.
Provide executable operator entry points and notebook hardware configuration while
retaining simulator defaults and simulator-only development/testing. Preparing
these paths does not authorize the agent to connect to or operate physical hardware.

Further clarification during publication review: tutorial notebooks must not use
hidden scripts. Lay out every demonstration function explicitly in the notebook,
use clear sections and avoid crowded code blocks. Retain the requested review,
pruning, commit and push after satisfying this notebook presentation requirement.

## Simplification (user request, 2026-09-10)

Simplify the codebase aggressively: remove unnecessary scaffolding, abstractions,
wrappers, duplicate utilities, unused modules, placeholder code and dependencies.
Prefer direct functions and small classes; reduce files where reasonable and
simplify configuration/control flow. Preserve required controller features,
safety checks, tests and hardware/simulator separation. Keep public APIs stable
when practical and update tests/documentation. The target is the smallest clean,
maintainable implementation that still fully supports the Verdi controller.
