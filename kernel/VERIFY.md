# VERIFY — Evidence Contract

Completion requires **observed, current** evidence. Prose, checkboxes, test counts recited from memory, and bare "PASS" markers are `UNVERIFIED`.

Machine-written evidence is produced with:
```bash
python scripts/lite/run_check.py -- <your-check-command>
```
This writes an evidence JSON to `.dainexus/verify/` that the completion gate (`scripts/lite/verify_gate.py`) validates. Evidence you type by hand is FORGED by definition.

## Proportional evidence
- `QUICK` — one compact line covering the focused check:
  `CHECK: <command> | EXIT: <code> | RESULT: PASS | FAIL`
  One check may cover tightly coupled acceptance conditions.
- `STANDARD` / `DEEP` — report every material behavior using the templates below.

## Fixes: RED then GREEN
A fix is not proven by a passing test. Run the **same command unchanged** and show:
1. **RED** — the check failing before the fix (proves the check actually detects the bug),
2. **GREEN** — the same check passing after.

A test that was never seen failing is not evidence that it would catch a regression. If you cannot produce RED, say so explicitly and state what that leaves unproven.

## Template 1: Standard Command / Test Check
Use this for unit/integration/E2E test runs, compiler output, or command exit code checks.
```text
CLAIM: <what you claim now works>
COMMAND: <the exact command you ran to check/test>
OUTPUT: <pasted stdout/stderr, last lines>
EXIT CODE: <number>
VERDICT: PASS | FAIL
```

## Template 2: UI / Visual Verification
A green build never proves responsiveness. Report `CLAIM`, the DOM check command and its output, then the inspected basis:
breakpoints/viewports tested · horizontal overflow · wrapping and hierarchy · keyboard/focus · component states (loading, empty, error, disabled) · design-token conformance · screenshots/VRT.
Missing basis or render = `UNVERIFIED`. Verdict caps at `STRUCTURALLY VERIFIED` — aesthetic judgment stays with the user.

## Template 3: Executable Logic Verification
For math, algorithms, state transitions, parsing, or concurrency: report `CLAIM`, script path, run command, output, exit code, verdict.

## Template 4: Runtime Ledger
Use this whenever the task started anything long-running — a dev server, watcher, emulator, container. A leaked process is invisible in every other template: the tests pass, the build is green, and RAM keeps climbing.
```text
RUNTIME LEDGER
OPENED:  <lease_id> role=<..> pid=<..>
CLOSED:  <lease_id>
LEAKED:  none | <lease_id list>
COMMAND: python scripts/lite/runtime_lease.py status
OUTPUT:  <pasted status output>
VERDICT: CLEAN | LEAKED
```
Rules for this block:
- Start long-running processes with `python scripts/lite/runtime_lease.py run --role <role> -- <command>`. It reuses an already-running instance instead of starting a duplicate, and registers a lease so the process can be reclaimed.
- `LEAKED` is only acceptable when the lease is deliberately `policy=keep`; say why.
- A process you started with no lease at all is a `LEAKED` verdict, not an exemption.

## Rules
1. Never report PASS from prose or memory. A success claim without pasted `OUTPUT` and `EXIT CODE` / `DOM OUTPUT` is automatically FALSE.
2. Report `FAIL` immediately; never hide it or narrate it into success.
3. `QUICK` may use one compact evidence line; `STANDARD`/`DEEP` report each material behavior.
4. Prefer deterministic checks (tests, linters, build exit codes). If none proves a material behavior, create one before claiming success.
5. VERIFY proves the code works; AUDIT proves the requirements are covered. Both are required.
6. UI evidence separates structural/tool verification from human aesthetic judgment.
7. If the task started any long-running process, emit Template 4 too. "The tests passed" is not evidence that the machine was left clean.

## Evidence schema
`run_check.py` writes schema **v2**: the v1 fields (`command`, `exit_code`, `output`, `timestamp_utc`, `workspace`, `tree_sha`) plus
`output_sha256` (integrity — a hand-edited `output` no longer matches its digest),
`tier` (`quick|standard|deep`), `acceptance` (what the check is supposed to prove), and
`negative_paths` (failure/rejection cases actually observed, not assumed).
The gate accepts v1 and v2; v2 additionally fails on a digest mismatch.
