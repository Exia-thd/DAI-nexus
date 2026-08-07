#!/usr/bin/env python3
"""
skills/_test/skill-test-executor.py
Skill test-contract validator and adapter runner (pure Python, zero-dependency).

This tool NEVER fabricates skill output. It does exactly two things:

  validate  — check every skills/_test/skills/<skill>/test.yaml contract is
              well-formed: unique kebab-case ids, known validators, parseable
              timeouts, expectations that the declared validators can actually
              consume. Runs in CI, needs no model.
  run       — execute a contract against a REAL adapter command supplied by the
              caller (`--adapter "<cmd>"`); the input is passed on stdin and the
              adapter's real stdout is checked against `expected`. With no
              adapter configured it refuses to run rather than simulate.

Usage:
    python skills/_test/skill-test-executor.py validate [skill ...]
    python skills/_test/skill-test-executor.py run <skill> --adapter "<command>" [--id <test-id>]
    python skills/_test/skill-test-executor.py list

Exit codes: 0 = pass, 1 = failures, 2 = usage/config error.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parent / "skills"
TEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
TIMEOUT_RE = re.compile(r"^(\d+)(ms|s|m)$")

# validator -> the `expected:` key it consumes (None = standalone)
VALIDATORS = {
    "output_contains_all": "contains",
    "output_excludes_none": "not_contains",
    "file_count_matches": "files_created",
    "min_lines_satisfied": "min_lines",
    "severity_counts_match": "severity_count",
    "no_todos": None,
}

# Open family: `min_<thing>_satisfied` consumes `expected.min_<thing>` and asserts
# the adapter reported at least that many of <thing>.
MIN_FAMILY_RE = re.compile(r"^min_([a-z0-9_]+)_satisfied$")


def expected_key_for(validator: str) -> str | None | bool:
    """Return the required `expected` key, None for standalone, False if unknown."""
    if validator in VALIDATORS:
        return VALIDATORS[validator]
    m = MIN_FAMILY_RE.match(validator)
    return f"min_{m.group(1)}" if m else False


# ── minimal YAML subset reader ────────────────────────────────────────────────
# The contracts use a fixed shape (mapping / list-of-mappings / block scalars).
# A constrained reader keeps this tool dependency-free; anything it cannot parse
# is reported as a contract error rather than silently skipped.

def parse_yaml(text: str) -> dict:
    root: dict = {}
    stack: list[tuple[int, object]] = [(-1, root)]
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.split(" #", 1)[0].rstrip() if not raw.strip().startswith("#") else ""
        if not line.strip():
            i += 1
            continue
        indent = len(line) - len(line.lstrip())
        content = line.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1] if stack else root

        if content.startswith("- "):
            item_body = content[2:].strip()
            if not isinstance(parent, list):
                i += 1
                continue
            if ":" in item_body:
                item: dict = {}
                parent.append(item)
                stack.append((indent, item))
                key, _, val = item_body.partition(":")
                _assign(item, key.strip(), val.strip(), lines, i, indent + 2, stack)
            else:
                parent.append(_scalar(item_body))
            i += 1
            continue

        if ":" in content:
            key, _, val = content.partition(":")
            if isinstance(parent, dict):
                i = _assign(parent, key.strip(), val.strip(), lines, i, indent, stack)
        i += 1
    return root


def _assign(container: dict, key: str, val: str, lines: list[str], i: int,
            indent: int, stack: list) -> int:
    if val in ("|", ">", "|-", ">-"):          # block scalar
        block, j = [], i + 1
        while j < len(lines):
            nxt = lines[j]
            if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= indent:
                break
            block.append(nxt[indent + 2:] if len(nxt) > indent + 2 else "")
            j += 1
        container[key] = "\n".join(block).rstrip()
        return j - 1
    if val == "":                                # nested block: dict or list
        nxt = next((ln for ln in lines[i + 1:] if ln.strip()), "")
        child: object = [] if nxt.strip().startswith("- ") else {}
        container[key] = child
        stack.append((indent, child))
        return i
    container[key] = _scalar(val)
    return i


def _scalar(val: str):
    val = val.strip()
    if val.startswith("[") and val.endswith("]"):
        return [_scalar(v) for v in val[1:-1].split(",") if v.strip()]
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        return val[1:-1]
    if val.lower() in ("true", "false"):
        return val.lower() == "true"
    if re.fullmatch(r"-?\d+", val):
        return int(val)
    return val


# ── contract validation ───────────────────────────────────────────────────────

def validate_contract(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = parse_yaml(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"unreadable contract: {e}"]

    if not data.get("skill"):
        errors.append("missing top-level `skill:`")
    skill_dir = path.parent.name
    if data.get("skill") and data["skill"] != skill_dir:
        errors.append(f"`skill: {data['skill']}` does not match directory `{skill_dir}`")
    if not (TEST_ROOT.parent.parent / str(data.get("skill", ""))).is_dir():
        errors.append(f"contract targets a skill that does not exist: {data.get('skill')!r}")

    tests = data.get("tests")
    if not isinstance(tests, list) or not tests:
        return errors + ["`tests:` must be a non-empty list"]

    seen: set[str] = set()
    for idx, test in enumerate(tests, 1):
        if not isinstance(test, dict):
            errors.append(f"test #{idx}: not a mapping")
            continue
        tid = test.get("id", "")
        label = tid or f"#{idx}"
        if not tid:
            errors.append(f"test {label}: missing `id`")
        elif not TEST_ID_RE.match(str(tid)):
            errors.append(f"test {label}: id must be kebab-case")
        elif tid in seen:
            errors.append(f"test {label}: duplicate id")
        seen.add(tid)

        timeout = test.get("timeout")
        if timeout is not None and not TIMEOUT_RE.match(str(timeout)):
            errors.append(f"test {label}: timeout {timeout!r} must look like 500ms / 60s / 5m")

        validators = test.get("validate") or []
        if not isinstance(validators, list) or not validators:
            errors.append(f"test {label}: `validate:` must list at least one validator")
            continue
        expected = test.get("expected") or {}
        for v in validators:
            needs = expected_key_for(v)
            if needs is False:
                errors.append(f"test {label}: unknown validator {v!r} (known: "
                              f"{', '.join(sorted(VALIDATORS))}, min_<thing>_satisfied)")
                continue
            if needs and needs not in expected:
                errors.append(f"test {label}: validator {v!r} needs `expected.{needs}`")
    return errors


# ── adapter execution (real output only) ──────────────────────────────────────

def timeout_seconds(raw: str | None) -> int:
    if not raw:
        return 120
    m = TIMEOUT_RE.match(str(raw))
    if not m:
        return 120
    n, unit = int(m.group(1)), m.group(2)
    return max(1, {"ms": n // 1000, "s": n, "m": n * 60}[unit])


def check_expectations(output: str, expected: dict, validators: list[str]) -> list[str]:
    failures: list[str] = []
    for v in validators:
        if v == "output_contains_all":
            for needle in expected.get("contains", []) or []:
                if str(needle).lower() not in output.lower():
                    failures.append(f"output missing expected content: {needle!r}")
        elif v == "output_excludes_none":
            for needle in expected.get("not_contains", []) or []:
                if str(needle).lower() in output.lower():
                    failures.append(f"output contains forbidden content: {needle!r}")
        elif v == "min_lines_satisfied":
            want = int(expected.get("min_lines", 0) or 0)
            got = len(output.splitlines())
            if got < want:
                failures.append(f"output has {got} lines, expected >= {want}")
        elif v == "no_todos":
            if re.search(r"\b(TODO|FIXME)\b", output):
                failures.append("output contains TODO/FIXME stubs")
        elif v == "severity_counts_match":
            for sev, want in (expected.get("severity_count") or {}).items():
                got = len(re.findall(rf"\b{re.escape(str(sev))}\b", output, re.IGNORECASE))
                if got < int(want):
                    failures.append(f"severity '{sev}': found {got}, expected >= {want}")
        elif v == "file_count_matches":
            want = int(expected.get("files_created", 0) or 0)
            got = len(re.findall(r"^\s*(?:created|wrote)\s+\S+", output, re.IGNORECASE | re.MULTILINE))
            if got != want:
                failures.append(f"files created: found {got}, expected {want}")
        else:
            m = MIN_FAMILY_RE.match(v)
            if not m:
                continue
            thing = m.group(1)
            want = int(expected.get(f"min_{thing}", 0) or 0)
            counts = adapter_counts(output)
            if thing not in counts:
                # Refuse to guess. An unverifiable expectation is a failure, not a pass.
                failures.append(
                    f"cannot verify min_{thing}: adapter emitted no machine-readable "
                    f'count (expected a JSON line like {{"counts": {{"{thing}": N}}}})'
                )
            elif counts[thing] < want:
                failures.append(f"{thing}: adapter reported {counts[thing]}, expected >= {want}")
    return failures


def adapter_counts(output: str) -> dict:
    """Read `{"counts": {...}}` from any JSON line the adapter printed."""
    for line in output.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        counts = data.get("counts")
        if isinstance(counts, dict):
            return {str(k): int(v) for k, v in counts.items() if str(v).lstrip("-").isdigit()}
    return {}


def run_contract(skill: str, adapter: str, only_id: str | None) -> int:
    path = TEST_ROOT / skill / "test.yaml"
    if not path.is_file():
        print(f"[skill-test] no contract for skill {skill!r}", file=sys.stderr)
        return 2
    data = parse_yaml(path.read_text(encoding="utf-8"))
    tests = [t for t in (data.get("tests") or [])
             if isinstance(t, dict) and (not only_id or t.get("id") == only_id)]
    if not tests:
        print(f"[skill-test] no matching tests in {path}", file=sys.stderr)
        return 2

    failed = 0
    for test in tests:
        tid = test.get("id", "?")
        payload = json.dumps({"skill": skill, "input": test.get("input", {})},
                             ensure_ascii=False)
        try:
            proc = subprocess.run(adapter, shell=True, input=payload, capture_output=True,
                                  text=True, timeout=timeout_seconds(test.get("timeout")))
        except subprocess.TimeoutExpired:
            print(f"  [FAIL] {tid}: adapter timed out", file=sys.stderr)
            failed += 1
            continue
        if proc.returncode != 0:
            print(f"  [FAIL] {tid}: adapter exited {proc.returncode}: {proc.stderr.strip()[:200]}",
                  file=sys.stderr)
            failed += 1
            continue
        failures = check_expectations(proc.stdout, test.get("expected") or {},
                                      test.get("validate") or [])
        if failures:
            failed += 1
            print(f"  [FAIL] {tid}", file=sys.stderr)
            for f in failures:
                print(f"      - {f}", file=sys.stderr)
        else:
            print(f"  [PASS] {tid}")
    return 1 if failed else 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Skill test contract validator / adapter runner")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("validate")
    sp.add_argument("skills", nargs="*")
    sp = sub.add_parser("run")
    sp.add_argument("skill")
    sp.add_argument("--adapter", required=True,
                    help="real command that receives {skill,input} JSON on stdin")
    sp.add_argument("--id")
    sub.add_parser("list")
    args = p.parse_args()

    if args.cmd == "list":
        for d in sorted(TEST_ROOT.iterdir()):
            if (d / "test.yaml").is_file():
                print(f"  {d.name}")
        sys.exit(0)

    if args.cmd == "validate":
        targets = ([TEST_ROOT / s / "test.yaml" for s in args.skills] if args.skills
                   else sorted(TEST_ROOT.glob("*/test.yaml")))
        failed = 0
        for path in targets:
            if not path.is_file():
                print(f"[skill-test] FAIL {path}: missing", file=sys.stderr)
                failed += 1
                continue
            errors = validate_contract(path)
            if errors:
                failed += 1
                print(f"[skill-test] FAIL {path.parent.name}", file=sys.stderr)
                for e in errors:
                    print(f"    - {e}", file=sys.stderr)
        if failed:
            print(f"[skill-test] {failed}/{len(targets)} contract(s) invalid", file=sys.stderr)
            sys.exit(1)
        print(f"[skill-test] OK — {len(targets)} contract(s) valid")
        sys.exit(0)

    sys.exit(run_contract(args.skill, args.adapter, args.id))


if __name__ == "__main__":
    main()
