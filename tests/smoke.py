#!/usr/bin/env python3
"""
tests/smoke.py — DAI Nexus self-test suite (no external services, no model calls).

Run:  python tests/smoke.py
Exit: 0 = all pass, 1 = failures (listed on stderr)
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = [sys.executable]
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(f"{name}: {detail}")


def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, cwd=ROOT, timeout=120, **kw)


def test_compile() -> None:
    r = run(PY + ["-m", "compileall", "-q", "scripts/lite", "mcp", "tests"])
    check("all python sources compile", r.returncode == 0, r.stderr[:300])


def test_verify_gate_selftest() -> None:
    r = run(PY + ["scripts/lite/verify_gate.py", "--selftest"])
    check("verify_gate selftest", r.returncode == 0, r.stdout + r.stderr)


def test_memory() -> None:
    sys.path.insert(0, str(ROOT / "scripts" / "lite"))
    import importlib
    memory = importlib.import_module("memory")
    with tempfile.TemporaryDirectory() as tmp:
        db = memory.MemoryDB(str(Path(tmp) / "m.db"))
        r1 = db.add("jwt auth decision with token=abcdefgh12345678 rotation", category="decisions", importance=9)
        check("memory add", not r1["duplicate"] and "auth" in r1["tags"])
        r2 = db.add("jwt auth decision with token=abcdefgh12345678 rotation", category="decisions")
        check("memory dedup", r2["duplicate"] is True)
        got = db.memory_get(r1["id"])
        check("memory redaction", "[REDACTED]" in got["content"], got["content"][:80])
        hits = db.memory_search("jwt auth", limit=3)
        check("memory FTS+RRF search", len(hits) >= 1 and hits[0]["id"] == r1["id"])
        for i in range(6):
            db.add(f"filler {i}", category="ingested")
        removed = db.gc(max_obs=3)
        kept_types = {m["type"] for m in db.list_all(limit=10)}
        check("memory value-weighted GC", removed >= 1 and "decisions" in kept_types,
              f"removed={removed} kept={kept_types}")
    fused = memory.rrf_merge(
        [{"id": 1}, {"id": 2}], [{"id": 2}, {"id": 3}], k=60,
    )
    check("rrf_merge favors overlap", fused[0]["id"] == 2, str(fused))


def test_escalate_dry_run() -> None:
    r = run(PY + ["scripts/lite/escalate.py", "--dry-run", "smoke test task"])
    check("escalate dry-run", r.returncode == 0 and "[DRY RUN]" in r.stdout, r.stderr[:200])


def test_mcp_server() -> None:
    session = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ]) + "\n"
    r = run(PY + ["mcp/server.py"], input=session)
    lines = [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
    ok = (
        len(lines) == 2
        and lines[0]["result"]["serverInfo"]["name"] == "dai-nexus"
        and len(lines[1]["result"]["tools"]) == 8
    )
    check("mcp initialize + tools/list (8 tools)", ok, r.stdout[:200] + r.stderr[:200])


def test_mcp_gate_discipline() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        session = "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "dn_start_pipeline", "arguments": {"goal": "g"}}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "dn_advance_phase", "arguments": {}}}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "dn_advance_phase", "arguments": {}}}),
        ]) + "\n"
        import os
        env = dict(os.environ, DAINEXUS_ROOT=tmp)
        r = subprocess.run(PY + [str(ROOT / "mcp" / "server.py")], input=session,
                           capture_output=True, text=True, timeout=60, env=env, cwd=ROOT)
        lines = [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
        payloads = [json.loads(m["result"]["content"][0]["text"]) for m in lines]
        ok = (
            payloads[0].get("started") is True
            and payloads[1].get("advanced") is True
            and "gate" in payloads[2].get("error", "")
        )
        check("mcp gate discipline blocks unapproved advance", ok, str(payloads))


def test_sync_kernel_budget() -> None:
    r = run(PY + ["scripts/lite/sync-kernel.py"])
    check("kernel sync within 7k budget", r.returncode == 0 and "EXCEEDED" not in r.stdout, r.stdout[-200:])


def test_policy_check() -> None:
    r = run(PY + ["scripts/lite/policy_check.py", "check", "run_command", "npm", "test"])
    check("policy allows safe command", r.returncode == 0, r.stderr[:200])
    r = run(PY + ["scripts/lite/policy_check.py", "check", "run_command", "rm", "-rf", "/"])
    check("policy denies rm -rf (strict)", r.returncode == 1, f"exit={r.returncode}")
    r = run(PY + ["scripts/lite/policy_check.py", "check", "run_command", "git", "push", "--force"])
    check("policy denies force push", r.returncode == 1, f"exit={r.returncode}")
    import os
    env = dict(os.environ, DAINEXUS_POLICY_FILE="nonexistent-policy.yaml")
    r = subprocess.run(PY + ["scripts/lite/policy_check.py", "check", "x", "y"],
                       capture_output=True, text=True, cwd=ROOT, timeout=30, env=env)
    check("policy fails closed when file missing", r.returncode == 1, f"exit={r.returncode}")
    r = run(PY + ["scripts/lite/policy_check.py", "get", "max_escalations"])
    check("policy get scalar", r.returncode == 0 and r.stdout.strip() == "3", r.stdout)


def test_runtime_lease() -> None:
    # A dead-PID lease must not count as leaked; a live non-keep lease must.
    lease_file = ROOT / ".dainexus" / "leases.json"
    backup = lease_file.read_text(encoding="utf-8") if lease_file.is_file() else None
    try:
        r = run(PY + ["scripts/lite/runtime_lease.py", "run", "--role", "smoketest", "--",
                      sys.executable, "-c", "import time; time.sleep(30)"])
        check("lease run registers", r.returncode == 0 and "OPENED" in r.stdout, r.stdout)
        r = run(PY + ["scripts/lite/runtime_lease.py", "run", "--role", "smoketest", "--",
                      sys.executable, "-c", "import time; time.sleep(30)"])
        check("lease reuses live role", "REUSE" in r.stdout, r.stdout)
        r = run(PY + ["scripts/lite/runtime_lease.py", "status"])
        check("lease status detects leak", r.returncode == 1 and "LEAKED" in r.stdout, r.stdout)
        r = run(PY + ["scripts/lite/runtime_lease.py", "reap"])
        check("lease reap kills non-keep", r.returncode == 0, r.stdout)
        r = run(PY + ["scripts/lite/runtime_lease.py", "status"])
        check("lease clean after reap", r.returncode == 0 and "CLEAN" in r.stdout, r.stdout)
    finally:
        if backup is not None:
            lease_file.write_text(backup, encoding="utf-8")
        elif lease_file.is_file():
            lease_file.unlink()


def test_routing_targets_exist() -> None:
    """Every skills/... path referenced by kernel + pipeline must exist on disk."""
    import re
    referenced: set[str] = set()
    sources = [ROOT / "kernel" / "ENTRY.md",
               ROOT / "skills" / "pipeline" / "SKILL.md",
               ROOT / "skills" / "pipeline" / "LITE.md",
               *(ROOT / "skills" / "pipeline" / "phases").glob("*.md")]
    for src in sources:
        for m in re.finditer(r"`(skills/[A-Za-z0-9_/\-]+\.md)`", src.read_text(encoding="utf-8")):
            referenced.add(m.group(1))
    missing = [p for p in sorted(referenced) if not (ROOT / p).is_file()]
    check(f"all {len(referenced)} routed skill paths exist", not missing, f"missing: {missing}")


def test_skill_overlays_clean() -> None:
    """No file in the repo may reference upstream-origin paths or names."""
    bad_tokens = (".forge" + "wright", "forge" + "wright", "Forge" + "wright",
                  "buiphucminhtam", "mem0-cli", "mem0-v2", "FORGE" + "WRIGHT_")
    skip_parts = {".git", ".dainexus", ".worktrees", "__pycache__"}
    stale = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in {".md", ".py", ".json", ".yaml", ".yml", ".ts", ".sh"}:
            continue
        if any(part in skip_parts for part in p.parts) or p.name == "smoke.py":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        lower = text.lower()
        for bad in bad_tokens:
            if bad.lower() in lower:
                stale.append(f"{p.relative_to(ROOT)}: {bad}")
    check("repo free of upstream-origin references", not stale, str(stale[:10]))


def test_overlay_validator() -> None:
    r = run(PY + ["scripts/lite/validate_overlays.py"])
    check("all overlays pass validator (no fake evidence/dead paths)",
          r.returncode == 0, (r.stdout + r.stderr)[-400:])


def test_escalate_timeout_and_lease() -> None:
    """A hung provider must be killed, reported as 124, and leave no lease behind."""
    sys.path.insert(0, str(ROOT / "scripts" / "lite"))
    import importlib
    esc = importlib.import_module("escalate")
    lease_mod = importlib.import_module("runtime_lease")

    check("timeout clamps below 1", esc.provider_timeout_seconds({"providerTimeoutSeconds": 0}) == 1)
    check("timeout clamps above 3600",
          esc.provider_timeout_seconds({"providerTimeoutSeconds": 99999}) == 3600)
    check("timeout falls back on garbage",
          esc.provider_timeout_seconds({"providerTimeoutSeconds": "abc"}) == 120)

    lease_file = ROOT / ".dainexus" / "leases.json"
    backup = lease_file.read_text(encoding="utf-8") if lease_file.is_file() else None
    import os
    cwd = os.getcwd()
    try:
        os.chdir(ROOT)
        before = len(lease_mod.load_leases())
        result = esc.run_provider(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            "", False, dict(os.environ), timeout_seconds=2,
        )
        after = lease_mod.load_leases()
        check("hung provider returns exit 124", result.returncode == 124, str(result.returncode))
        check("timed-out provider leaves no lease", len(after) == before,
              f"before={before} after={len(after)}")
    finally:
        os.chdir(cwd)
        if backup is not None:
            lease_file.write_text(backup, encoding="utf-8")
        elif lease_file.is_file():
            lease_file.unlink()


def test_skill_test_contracts() -> None:
    r = run(PY + ["skills/_test/skill-test-executor.py", "validate"])
    check("skill test contracts valid", r.returncode == 0, (r.stdout + r.stderr)[-400:])
    # The harness must never fabricate output: a silent adapter has to FAIL.
    r = run(PY + ["skills/_test/skill-test-executor.py", "run", "code-reviewer",
                  "--id", "test-basic-review",
                  "--adapter", f'"{sys.executable}" -c "print(\'nothing\')"'])
    check("silent adapter fails instead of faking a pass",
          r.returncode == 1 and "FAIL" in (r.stdout + r.stderr), (r.stdout + r.stderr)[-200:])


def test_rule_ledger() -> None:
    ledger = ROOT / ".dainexus" / "rule-ledger.jsonl"
    backup = ledger.read_text(encoding="utf-8") if ledger.is_file() else None
    try:
        r = run(PY + ["scripts/lite/rule_ledger.py", "add", "hard-rule-1", "violation", "smoke"])
        check("rule ledger add", r.returncode == 0, r.stderr[:200])
        r = run(PY + ["scripts/lite/rule_ledger.py", "stats"])
        check("rule ledger stats", r.returncode == 0 and "hard-rule-1" in r.stdout, r.stdout[:200])
    finally:
        if backup is not None:
            ledger.write_text(backup, encoding="utf-8")
        elif ledger.is_file():
            ledger.unlink()


def main() -> None:
    print("DAI Nexus smoke suite")
    for fn in (test_compile, test_verify_gate_selftest, test_memory,
               test_escalate_dry_run, test_mcp_server, test_mcp_gate_discipline,
               test_sync_kernel_budget, test_policy_check, test_runtime_lease,
               test_routing_targets_exist, test_skill_overlays_clean,
               test_overlay_validator, test_escalate_timeout_and_lease,
               test_skill_test_contracts, test_rule_ledger):
        try:
            fn()
        except Exception as e:
            check(fn.__name__, False, f"crashed: {e}")
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s):", file=sys.stderr)
        for f in FAILURES:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)
    print("\nAll smoke tests passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
