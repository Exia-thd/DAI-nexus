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
    print(
        f"  [{'PASS' if ok else 'FAIL'}] {name}"
        + (f" — {detail}" if detail and not ok else "")
    )
    if not ok:
        FAILURES.append(f"{name}: {detail}")


def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, cwd=ROOT, timeout=120, **kw
    )


def test_compile() -> None:
    r = run(PY + ["-m", "compileall", "-q", "scripts/lite", "mcp", "tests"])
    check("all python sources compile", r.returncode == 0, r.stderr[:300])


def test_verify_gate_selftest() -> None:
    r = run(PY + ["scripts/lite/verify_gate.py", "--selftest"])
    check(
        "verify_gate selftest", r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    )


def test_memory() -> None:
    sys.path.insert(0, str(ROOT / "scripts" / "lite"))
    import importlib

    memory = importlib.import_module("memory")
    with tempfile.TemporaryDirectory() as tmp:
        db = memory.MemoryDB(str(Path(tmp) / "m.db"))
        r1 = db.add(
            "jwt auth decision with token=abcdefgh12345678 rotation",
            category="decisions",
            importance=9,
        )
        check("memory add", not r1["duplicate"] and "auth" in r1["tags"])
        r2 = db.add(
            "jwt auth decision with token=abcdefgh12345678 rotation",
            category="decisions",
        )
        check("memory dedup", r2["duplicate"] is True)
        got = db.memory_get(r1["id"])
        check("memory redaction", "[REDACTED]" in got["content"], got["content"][:80])
        hits = db.memory_search("jwt auth", limit=3)
        check("memory FTS+RRF search", len(hits) >= 1 and hits[0]["id"] == r1["id"])
        for i in range(6):
            db.add(f"filler {i}", category="ingested")
        removed = db.gc(max_obs=3)
        kept_types = {m["type"] for m in db.list_all(limit=10)}
        check(
            "memory value-weighted GC",
            removed >= 1 and "decisions" in kept_types,
            f"removed={removed} kept={kept_types}",
        )
    fused = memory.rrf_merge(
        [{"id": 1}, {"id": 2}],
        [{"id": 2}, {"id": 3}],
        k=60,
    )
    check("rrf_merge favors overlap", fused[0]["id"] == 2, str(fused))


def test_escalate_dry_run() -> None:
    r = run(PY + ["scripts/lite/escalate.py", "--dry-run", "smoke test task"])
    check(
        "escalate dry-run",
        r.returncode == 0 and "[DRY RUN]" in r.stdout,
        r.stderr[:200],
    )


def test_mcp_server() -> None:
    session = (
        "\n".join(
            [
                json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
                ),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            ]
        )
        + "\n"
    )
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
        session = (
            "\n".join(
                [
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/call",
                            "params": {
                                "name": "dn_start_pipeline",
                                "arguments": {"goal": "g"},
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "tools/call",
                            "params": {"name": "dn_advance_phase", "arguments": {}},
                        }
                    ),
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 3,
                            "method": "tools/call",
                            "params": {"name": "dn_advance_phase", "arguments": {}},
                        }
                    ),
                ]
            )
            + "\n"
        )
        import os

        env = dict(os.environ, DAINEXUS_ROOT=tmp)
        r = subprocess.run(
            PY + [str(ROOT / "mcp" / "server.py")],
            input=session,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            cwd=ROOT,
        )
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
    check(
        "kernel sync within 7k budget",
        r.returncode == 0 and "EXCEEDED" not in r.stdout,
        r.stdout[-200:],
    )


def test_policy_check() -> None:
    r = run(
        PY + ["scripts/lite/policy_check.py", "check", "run_command", "npm", "test"]
    )
    check("policy allows safe command", r.returncode == 0, r.stderr[:200])
    r = run(
        PY + ["scripts/lite/policy_check.py", "check", "run_command", "rm", "-rf", "/"]
    )
    check("policy denies rm -rf (strict)", r.returncode == 1, f"exit={r.returncode}")
    r = run(
        PY
        + [
            "scripts/lite/policy_check.py",
            "check",
            "run_command",
            "git",
            "push",
            "--force",
        ]
    )
    check("policy denies force push", r.returncode == 1, f"exit={r.returncode}")
    import os

    env = dict(os.environ, DAINEXUS_POLICY_FILE="nonexistent-policy.yaml")
    r = subprocess.run(
        PY + ["scripts/lite/policy_check.py", "check", "x", "y"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=30,
        env=env,
    )
    check(
        "policy fails closed when file missing",
        r.returncode == 1,
        f"exit={r.returncode}",
    )
    r = run(PY + ["scripts/lite/policy_check.py", "get", "max_escalations"])
    check("policy get scalar", r.returncode == 0 and r.stdout.strip() == "3", r.stdout)


def test_runtime_lease() -> None:
    # A dead-PID lease must not count as leaked; a live non-keep lease must.
    lease_file = ROOT / ".dainexus" / "leases.json"
    backup = lease_file.read_text(encoding="utf-8") if lease_file.is_file() else None
    try:
        r = run(
            PY
            + [
                "scripts/lite/runtime_lease.py",
                "run",
                "--role",
                "smoketest",
                "--",
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ]
        )
        check(
            "lease run registers", r.returncode == 0 and "OPENED" in r.stdout, r.stdout
        )
        r = run(
            PY
            + [
                "scripts/lite/runtime_lease.py",
                "run",
                "--role",
                "smoketest",
                "--",
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ]
        )
        check("lease reuses live role", "REUSE" in r.stdout, r.stdout)
        r = run(PY + ["scripts/lite/runtime_lease.py", "status"])
        check(
            "lease status detects leak",
            r.returncode == 1 and "LEAKED" in r.stdout,
            r.stdout,
        )
        r = run(PY + ["scripts/lite/runtime_lease.py", "reap"])
        check("lease reap kills non-keep", r.returncode == 0, r.stdout)
        r = run(PY + ["scripts/lite/runtime_lease.py", "status"])
        check(
            "lease clean after reap",
            r.returncode == 0 and "CLEAN" in r.stdout,
            r.stdout,
        )
    finally:
        if backup is not None:
            lease_file.write_text(backup, encoding="utf-8")
        elif lease_file.is_file():
            lease_file.unlink()


def test_routing_targets_exist() -> None:
    """Every skills/... path referenced by kernel + pipeline must exist on disk."""
    import re

    referenced: set[str] = set()
    sources = [
        ROOT / "kernel" / "ENTRY.md",
        ROOT / "skills" / "pipeline" / "SKILL.md",
        ROOT / "skills" / "pipeline" / "LITE.md",
        *(ROOT / "skills" / "pipeline" / "phases").glob("*.md"),
    ]
    for src in sources:
        for m in re.finditer(
            r"`(skills/[A-Za-z0-9_/\-]+\.md)`", src.read_text(encoding="utf-8")
        ):
            referenced.add(m.group(1))
    missing = [p for p in sorted(referenced) if not (ROOT / p).is_file()]
    check(
        f"all {len(referenced)} routed skill paths exist",
        not missing,
        f"missing: {missing}",
    )


def test_skill_overlays_clean() -> None:
    """No file in the repo may reference upstream-origin paths or names."""
    # Assembled from fragments on purpose. A repo-wide rename pass once rewrote
    # this very list, so the guard started checking for the *new* name and
    # reported every file as dirty. Fragments survive that.
    _w = "".join(("wr", "ight"))
    bad_tokens = (
        "forge" + _w,
        "Forge" + _w,
        "FORGE" + _w.upper() + "_",
        "buiphuc" + "minhtam",
        "mem" + "0-cli",
        "mem" + "0-v2",
    )
    skip_parts = {
        ".git",
        ".gitnexus",
        ".dainexus",
        ".worktrees",
        "__pycache__",
        "node_modules",
    }
    stale = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in {
            ".md",
            ".py",
            ".json",
            ".yaml",
            ".yml",
            ".ts",
            ".sh",
            ".html",
            ".css",
        }:
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


def test_standalone_page_is_orphaned() -> None:
    """docs/memory-standalone.html must survive being handed over on its own.

    It is deliberately unreachable from the site: no nav, no outbound links, no
    page pointing at it, and the stylesheet inlined. Any of those creeping back
    silently breaks the one property it exists for.
    """
    import re

    page = ROOT / "docs" / "memory-standalone.html"
    check("standalone page exists", page.is_file())
    if not page.is_file():
        return
    text = page.read_text(encoding="utf-8")

    refs = (
        re.findall(r'(?:src|href)="([^"]+)"', text)
        + re.findall(r"@import[^;]+;", text)
        + re.findall(r"url\((?!data:)([^)]+)\)", text)
    )
    check("standalone page references no external file", not refs, str(refs[:5]))
    check("standalone page has no navigation", 'class="nav"' not in text)
    check(
        "standalone page inlines the stylesheet",
        "<style>" in text and "--accent" in text,
    )

    inbound = [
        p.name
        for p in (ROOT / "docs").glob("*.html")
        if p.name != page.name and "memory-standalone" in p.read_text(encoding="utf-8")
    ]
    check("no sibling page links to the standalone page", not inbound, str(inbound))

    # It is a clone of the guide: the section headings must match, so the two do
    # not silently drift into different documents.
    def heads(html_text: str) -> list[str]:
        return [
            re.sub(r"<[^>]+>", "", h).strip()
            for h in re.findall(r"<h2[^>]*>(.*?)</h2>", html_text, re.DOTALL)
        ]

    guide = (ROOT / "docs" / "memory-guide.html").read_text(encoding="utf-8")
    check(
        "standalone content matches the guide",
        heads(text) == heads(guide),
        f"standalone={heads(text)[:3]} guide={heads(guide)[:3]}",
    )


def test_memory_is_portable() -> None:
    """docs/memory-guide.html promises one file, stdlib only, works standalone.

    If someone adds a third-party import or splits the module, that promise turns
    into a lie for every reader who followed the guide — so it is a test, not a
    comment.
    """
    import ast

    src = (ROOT / "scripts" / "lite" / "memory.py").read_text(encoding="utf-8")
    mods: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
    third_party = sorted(m for m in mods if m not in sys.stdlib_module_names)
    check(
        "memory.py imports stdlib only", not third_party, f"third-party: {third_party}"
    )
    check(
        "memory.py has no local imports (single-file promise)",
        not any(
            isinstance(n, ast.ImportFrom) and n.level > 0
            for n in ast.walk(ast.parse(src))
        ),
    )

    # The guide's own verification snippet, run against a copy in a bare directory.
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "memory.py").write_text(src, encoding="utf-8")
        snippet = (
            "import sys; sys.path.insert(0, %r)\n"
            "from memory import MemoryDB\n"
            "db = MemoryDB(%r)\n"
            "a = db.add('use jwt with token=abcdefgh12345678 rotation',"
            " category='decisions', importance=9)\n"
            "assert not a['duplicate'] and a['tags']\n"
            "assert db.add('use jwt with token=abcdefgh12345678 rotation')['duplicate']\n"
            "assert '[REDACTED]' in db.memory_get(a['id'])['content']\n"
            "assert db.memory_search('jwt')[0]['id'] == a['id']\n"
            "[db.add('filler %%d' %% i, category='ingested') for i in range(6)]\n"
            "db.gc(max_obs=3)\n"
            "assert 'decisions' in {m['type'] for m in db.list_all(limit=10)}\n"
            "print('memory OK')\n"
        ) % (str(d), str(d / "t.db"))
        r = subprocess.run(
            PY + ["-c", snippet], capture_output=True, text=True, cwd=str(d), timeout=60
        )
        check(
            "guide's verification snippet passes on a bare copy",
            r.returncode == 0 and "memory OK" in r.stdout,
            ((r.stdout or "") + (r.stderr or ""))[-250:],
        )


def test_claim_correlation() -> None:
    """A VERIFY block must quote its evidence, not paraphrase it.

    Evidence proves a command ran; this proves the *report* about it is faithful.
    Rewording the claim, citing another command, or pasting prose where the
    output digest belongs all have to fail.
    """
    r = run(PY + ["scripts/lite/rule_validator.py", "--selftest"])
    check(
        "rule_validator selftest",
        r.returncode == 0,
        ((r.stdout or "") + (r.stderr or ""))[-200:],
    )

    import importlib

    sys.path.insert(0, str(ROOT / "scripts" / "lite"))
    rv = importlib.import_module("rule_validator")
    ev = {
        "command": ["py", "-3", "tests/smoke.py"],
        "output_sha256": "b" * 64,
        "acceptance_criteria": [{"id": "suite-green", "claim": "the suite passes"}],
    }
    good = (
        f"ACCEPTANCE: suite-green\nCLAIM: the suite passes\n"
        f"COMMAND: py -3 tests/smoke.py\nOUTPUT: sha256:{'b' * 64}\n"
        f"EXIT CODE: 0\nVERDICT: PASS"
    )
    check(
        "faithful block accepted",
        not rv.validate(good, ev),
        str(rv.validate(good, ev))[:150],
    )
    check(
        "reworded claim rejected",
        bool(rv.validate(good.replace("the suite passes", "all good"), ev)),
    )
    check(
        "prose instead of digest rejected",
        bool(rv.validate(good.replace(f"sha256:{'b' * 64}", "everything passed"), ev)),
    )
    check("silence is not an error", not rv.validate("plain prose, no claim made", ev))

    # The gate must refuse a misreported turn even when no code changed.
    import os

    if True:
        payload = json.dumps(
            {"response_content": good.replace("the suite passes", "fabricated claim")}
        )
        # Run the gate in a throwaway directory: asserting on this repo's own
        # working tree makes the result depend on whatever else is uncommitted.
        with tempfile.TemporaryDirectory() as sandbox:
            env = dict(os.environ, DAINEXUS_TURN="__no_such_turn__")
            r = subprocess.run(
                PY + [str(ROOT / "scripts" / "lite" / "verify_gate.py"), "--hook"],
                input=payload,
                capture_output=True,
                text=True,
                cwd=sandbox,
                timeout=60,
                env=env,
            )
            out = (r.stdout or "") + (r.stderr or "")
            check(
                "gate blocks a misreported turn",
                r.returncode != 0 and "MISREPORTED" in out,
                out[-200:],
            )


def test_evidence_schema_v2() -> None:
    """v2 records carry an integrity digest; a doctored output must not survive it."""
    import importlib

    sys.path.insert(0, str(ROOT / "scripts" / "lite"))
    vg = importlib.import_module("verify_gate")

    with tempfile.TemporaryDirectory() as tmp:
        r = run(
            PY
            + [
                "scripts/lite/run_check.py",
                "--turn",
                "smoke_v2",
                "--out",
                tmp,
                "--tier",
                "quick",
                "--acceptance",
                "digest covers output",
                "--negative-path",
                "tampered output rejected",
                "--",
                sys.executable,
                "-c",
                "print('hello v2')",
            ]
        )
        check("run_check writes v2 evidence", r.returncode == 0, r.stderr[-200:])
        ev = json.loads((Path(tmp) / "smoke_v2.json").read_text(encoding="utf-8"))

    check(
        "v2 schema_version",
        ev.get("schema_version") == "2",
        str(ev.get("schema_version")),
    )
    check(
        "v2 carries tier/acceptance/negative_paths",
        ev.get("tier") == "quick"
        and ev.get("acceptance")
        and ev.get("negative_paths") == ["tampered output rejected"],
        str(ev)[:150],
    )
    check(
        "v2 clean record validates",
        not vg._validate_output(ev),
        str(vg._validate_output(ev))[:150],
    )
    check(
        "v2 tampered output is FORGED",
        any(
            "output_sha256 mismatch" in e
            for e in vg._validate_output(dict(ev, output="all green\n"))
        ),
    )
    check(
        "v2 missing digest is FORGED",
        bool(
            vg._validate_output({k: v for k, v in ev.items() if k != "output_sha256"})
        ),
    )
    check("v2 bad tier is FORGED", bool(vg._validate_schema(dict(ev, tier="turbo"))))
    # v1 must still be accepted: old evidence files stay valid.
    v1 = {
        k: v
        for k, v in ev.items()
        if k not in ("output_sha256", "tier", "acceptance", "negative_paths")
    }
    v1["schema_version"] = "1"
    check(
        "v1 evidence still accepted",
        not (vg._validate_schema(v1) + vg._validate_output(v1)),
        str(vg._validate_schema(v1) + vg._validate_output(v1))[:150],
    )


def test_stub_check_precision() -> None:
    """Real stubs must be caught; documentation *about* stub markers must not be."""
    sys.path.insert(0, str(ROOT / "scripts" / "lite"))
    import importlib

    vg = importlib.import_module("verify_gate")
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        cases = {
            "real_comment.py": ("def f():\n    # TODO: implement\n    return 1\n", 1),
            "real_raise.py": ("def f():\n    raise NotImplementedError\n", 1),
            "doc_string.py": ('MSG = "we ban TODO and FIXME markers"\n', 0),
            "other.ts": ("// TODO: fix later\n", 1),
        }
        for name, (body, want) in cases.items():
            (d / name).write_text(body, encoding="utf-8")
            got = len(vg._check_stubs(d, [name]))
            check(f"stub check: {name} -> {want}", got == want, f"got {got}")
    # The gate's own tooling documents these markers and must stay clean.
    for f in (
        "docs/build_docs.py",
        "scripts/lite/verify_gate.py",
        "docs/evidence.html",
    ):
        check(f"no false stub positive in {f}", len(vg._check_stubs(ROOT, [f])) == 0)
    # ...but @generated must not become a blanket bypass for authored code.
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        (d / "gen.py").write_text(
            "# @generated\ndef f():\n    # TODO: later\n", encoding="utf-8"
        )
        (d / "hand.py").write_text(
            "def f():\n    # TODO: later\n" + "x = 1\n" * 200 + "# @generated\n",
            encoding="utf-8",
        )
        check("@generated header skips scan", len(vg._check_stubs(d, ["gen.py"])) == 0)
        check(
            "@generated deep in file does NOT skip scan",
            len(vg._check_stubs(d, ["hand.py"])) == 1,
        )


def test_utf8_cli_output() -> None:
    """Every CLI must print non-ASCII without dying on a legacy Windows codepage."""
    r = run(PY + ["scripts/lite/rule_ledger.py", "list"])
    check(
        "rule_ledger prints non-ASCII notes",
        r.returncode == 0,
        ((r.stdout or "") + (r.stderr or ""))[-200:],
    )


def test_docs_fresh() -> None:
    """Docs are generated from source — a stale committed page is a lie about the code."""
    r = run(PY + ["docs/build_docs.py", "--check"])
    check(
        "generated docs match current source",
        r.returncode == 0,
        ((r.stdout or "") + (r.stderr or ""))[-300:],
    )


def test_overlay_validator() -> None:
    r = run(PY + ["scripts/lite/validate_overlays.py"])
    check(
        "all overlays pass validator (no fake evidence/dead paths)",
        r.returncode == 0,
        ((r.stdout or "") + (r.stderr or ""))[-400:],
    )


def test_escalate_timeout_and_lease() -> None:
    """A hung provider must be killed, reported as 124, and leave no lease behind."""
    sys.path.insert(0, str(ROOT / "scripts" / "lite"))
    import importlib

    esc = importlib.import_module("escalate")
    lease_mod = importlib.import_module("runtime_lease")

    check(
        "timeout clamps below 1",
        esc.provider_timeout_seconds({"providerTimeoutSeconds": 0}) == 1,
    )
    check(
        "timeout clamps above 3600",
        esc.provider_timeout_seconds({"providerTimeoutSeconds": 99999}) == 3600,
    )
    check(
        "timeout falls back on garbage",
        esc.provider_timeout_seconds({"providerTimeoutSeconds": "abc"}) == 120,
    )

    lease_file = ROOT / ".dainexus" / "leases.json"
    backup = lease_file.read_text(encoding="utf-8") if lease_file.is_file() else None
    import os

    cwd = os.getcwd()
    try:
        os.chdir(ROOT)
        before = len(lease_mod.load_leases())
        result = esc.run_provider(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            "",
            False,
            dict(os.environ),
            timeout_seconds=2,
        )
        after = lease_mod.load_leases()
        check(
            "hung provider returns exit 124",
            result.returncode == 124,
            str(result.returncode),
        )
        check(
            "timed-out provider leaves no lease",
            len(after) == before,
            f"before={before} after={len(after)}",
        )
    finally:
        os.chdir(cwd)
        if backup is not None:
            lease_file.write_text(backup, encoding="utf-8")
        elif lease_file.is_file():
            lease_file.unlink()


def test_skill_test_contracts() -> None:
    r = run(
        PY
        + [
            "skills/_test/skill-test-executor.py",
            "--all",
            "--contract-only",
            "--no-color",
        ]
    )
    check(
        "skill test contracts valid",
        r.returncode == 0,
        ((r.stdout or "") + (r.stderr or ""))[-400:],
    )
    # The harness must never fabricate output: a silent adapter has to FAIL.
    r = run(
        PY
        + [
            "skills/_test/skill-test-executor.py",
            "code-reviewer",
            "test-basic-review",
            "--no-color",
            "--adapter-command",
            f'"{sys.executable}" -c "print(\'nothing\')"',
        ]
    )
    check(
        "silent adapter fails instead of faking a pass",
        r.returncode == 1 and "FAIL" in ((r.stdout or "") + (r.stderr or "")),
        ((r.stdout or "") + (r.stderr or ""))[-200:],
    )


def test_rule_ledger() -> None:
    ledger = ROOT / ".dainexus" / "rule-ledger.jsonl"
    backup = ledger.read_text(encoding="utf-8") if ledger.is_file() else None
    try:
        r = run(
            PY
            + [
                "scripts/lite/rule_ledger.py",
                "add",
                "hard-rule-1",
                "violation",
                "smoke",
            ]
        )
        check("rule ledger add", r.returncode == 0, r.stderr[:200])
        r = run(PY + ["scripts/lite/rule_ledger.py", "stats"])
        check(
            "rule ledger stats",
            r.returncode == 0 and "hard-rule-1" in r.stdout,
            r.stdout[:200],
        )
    finally:
        if backup is not None:
            ledger.write_text(backup, encoding="utf-8")
        elif ledger.is_file():
            ledger.unlink()


def main() -> None:
    print("DAI Nexus smoke suite")
    for fn in (
        test_compile,
        test_verify_gate_selftest,
        test_memory,
        test_escalate_dry_run,
        test_mcp_server,
        test_mcp_gate_discipline,
        test_sync_kernel_budget,
        test_policy_check,
        test_runtime_lease,
        test_routing_targets_exist,
        test_skill_overlays_clean,
        test_overlay_validator,
        test_docs_fresh,
        test_evidence_schema_v2,
        test_claim_correlation,
        test_memory_is_portable,
        test_standalone_page_is_orphaned,
        test_stub_check_precision,
        test_utf8_cli_output,
        test_escalate_timeout_and_lease,
        test_skill_test_contracts,
        test_rule_ledger,
    ):
        try:
            fn()
        except Exception as e:
            import traceback

            # Show where it broke: "crashed: <message>" alone sends you hunting.
            check(
                fn.__name__,
                False,
                f"crashed: {e}\n{traceback.format_exc()[-600:]}",
            )
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s):", file=sys.stderr)
        for f in FAILURES:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)
    print("\nAll smoke tests passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
