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

## Manual verification (user request)

Check every implemented command, query, parameter, response format, limit, error
and safety rule against the official Verdi manual. Correct mismatches, missing
behavior and unsupported assumptions; update the simulator and regression tests.
Produce a short report of coverage, corrections, uncertainties and remaining
physical validation. Continue using only simulated hardware for development/tests.

## Compact driver redesign (user request, 2026-09-10)

Review the entire repository and aggressively reduce Python modules, code and
conceptual overhead. Target controller/protocol/simulator/monitor/gui/errors plus
package entry points. Replace fragmented configuration, lifecycle/ownership systems,
wrappers and compatibility layers with direct Python. Keep a small explicit device
API, optional GUI/logging and a simulator using the same controller interface.
Preserve only concretely justified hardware reliability and safety behavior.
Update public imports, tutorials, examples, tests, README and architecture together;
no external compatibility requirement has been identified. Validate externally
meaningful behavior and retain documented protocol/physical-uncertainty distinctions.
This request authorizes software changes only, with no physical access.

## Further pruning (user request, 2026-09-10)

Reduce data structures and strip most remaining module boundaries. Make a clean
API migration and update all documentation, examples and README. Perform another
holistic review, fix findings, prune obsolete code/tests and commit/push the result.
The renewed push request follows the explicit destination question for
github.com/cct1123/coherent-verdi-control, main. Hardware-free limits still apply.

## New-user README (user request, 2026-09-15)

Make the README welcoming and practical for a first-time human user. Illustrate
the optional GUI with a screenshot and use a block diagram where it clarifies
integration. Keep instructions consistent with the current public API and show
the simplest simulator workflow; no hardware interaction is authorized.

Follow-up, 2026-09-15: review the repository and rewrite README as a simple,
visual first-time lab guide: purpose, implementation/validation status, shortest
copy-paste Quick Start, simulator/demo, one basic usage example, real-hardware
setup, key safety/limitations and short troubleshooting. Put developer/architecture
details near the bottom. Verify commands, interfaces, supported models, limits
and validation claims against the repository; do not invent missing information.

Further direction, 2026-09-15: focus the guide more on real-hardware use. Lead
with serial installation, connection configuration, identification, read/control
workflows and a real-controller Python example; retain simulation as an optional
practice/preview workflow. This is documentation work, not hardware authorization.
