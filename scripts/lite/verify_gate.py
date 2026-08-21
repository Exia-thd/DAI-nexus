#!/usr/bin/env python3
"""
scripts/lite/verify_gate.py
Turn-completion gate for DAI Nexus. Cross-platform (no bash needed).

Modes:
    python scripts/lite/verify_gate.py --selftest     # smoke-test the validators
    python scripts/lite/verify_gate.py --hook         # Claude Code Stop-hook mode (reads stdin JSON)
    python scripts/lite/verify_gate.py                # CLI mode (CI, manual)

Gate logic:
  1. Detect changed files via `git status --porcelain` (excluding .dainexus/).
  2. If no *code* files changed (docs/config only) -> gate OPEN.
  3. Otherwise require a fresh, machine-written evidence file under
     .dainexus/verify/ (written by run_check.py) that passes all checks:

  Evidence contract (schema_version "1" or "2"):
    v1: schema_version, turn, command, exit_code, output, timestamp_utc,
        workspace, tree_sha
    v2: the above plus output_sha256 (integrity digest of `output`),
        tier (see evidence_common.EVIDENCE_TIERS), acceptance, negative_paths

  Rejection reasons:
    MISSING   - no evidence file found
    STALE     - timestamp too old
    MISMATCH  - workspace or tree_sha mismatch
    FAILED    - exit_code != 0
    FORGED    - schema wrong, command empty, output generic/templated
    SECRETS   - output contains unredacted secrets
    STUBS     - changed source files contain TODO/FIXME/NotImplementedError
    MISREPORTED - the response's VERIFY blocks do not match the evidence

Exit codes: 0 = gate OPEN. Block = 2 in --hook mode (Claude Code blocking
convention, stderr is fed back to the agent), 1 otherwise.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence_common import EVIDENCE_TIERS  # noqa: E402

# ── configuration ─────────────────────────────────────────────────────────────
STALENESS_SECS = int(os.environ.get("DAINEXUS_STALENESS_SECS", "3600"))  # 1 hour

_FORGED_OUTPUT_PATTERNS = [
    re.compile(r"^\[REDACTED\]$", re.MULTILINE),
    re.compile(r"^<output>$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^placeholder$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^TODO$", re.MULTILINE),
    re.compile(r"^N/A$", re.MULTILINE),
]

_SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{20,}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(r"-----BEGIN(?:\s+[A-Z]+)?\s+PRIVATE KEY-----"),
]

_STUB_PATTERN = re.compile(r"\b(TODO|FIXME|NotImplementedError)\b")

_BINARY_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".whl",
    ".so",
    ".dylib",
    ".exe",
    ".db",
    ".sqlite",
}
_DOC_EXTS = {".md", ".txt", ".json", ".yaml", ".yml", ".ini", ".cfg", ".toml", ".lock"}
_SKIP_PREFIXES = ("scripts/lite/", ".dainexus/", ".claude/", ".git/")


# ── helpers ───────────────────────────────────────────────────────────────────


def _log(label: str, msg: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    print(f"[VERIFY-GATE] {label}: {msg}", file=stream)


def _ok(msg: str) -> None:
    _log("OK", msg)


def _err(msg: str) -> None:
    _log("ERROR", msg, err=True)


def _workspace() -> Path:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            return Path(r.stdout.strip()).resolve()
    except Exception:
        pass
    return Path.cwd().resolve()


def _current_tree_sha(workspace: Path) -> str:
    try:
        in_git = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=workspace,
            capture_output=True,
            timeout=5,
        )
        if in_git.returncode != 0:
            return "NONGIT"

        head = (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            or "NOHEAD"
        )

        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.splitlines()

        dirty = [
            line for line in status if not line[3:].startswith(".dainexus/verify/")
        ]

        if dirty:
            idx = (
                subprocess.run(
                    ["git", "write-tree"],
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout.strip()
                or "NOIDX"
            )
            return f"DIRTY:{head[:12]}:{idx[:12]}"
        return head
    except Exception:
        return "GITERR"


def _changed_files(workspace: Path) -> list[str]:
    """Repo-relative changed paths from git status, excluding gate internals."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except Exception:
        return []
    files: list[str] = []
    for line in out.splitlines():
        path = line[3:].strip()
        if " -> " in path:  # rename: take the new side
            path = path.split(" -> ", 1)[1]
        path = path.strip('"').replace("\\", "/")
        if not path or any(path.startswith(p) for p in _SKIP_PREFIXES):
            continue
        files.append(path)
    return files


def _code_files(files: list[str]) -> list[str]:
    return [f for f in files if Path(f).suffix.lower() not in _DOC_EXTS | _BINARY_EXTS]


# ── evidence lookup & validation ──────────────────────────────────────────────


def _find_evidence(project_root: Path, turn_env: str) -> Path | None:
    verify_dir = project_root / ".dainexus" / "verify"
    if turn_env:
        p = verify_dir / f"{turn_env}.json"
        return p if p.is_file() else None
    if verify_dir.is_dir():
        files = sorted(
            verify_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True
        )
        return files[0] if files else None
    return None


SUPPORTED_SCHEMAS = {"1", "2"}


def _validate_schema(ev: dict) -> list[str]:
    errors: list[str] = []
    if ev.get("schema_version") not in SUPPORTED_SCHEMAS:
        errors.append(
            f"FORGED: schema_version must be one of "
            f"{sorted(SUPPORTED_SCHEMAS)}, got {ev.get('schema_version')!r}"
        )
    if ev.get("schema_version") == "2":
        tier = ev.get("tier")
        if tier not in EVIDENCE_TIERS:
            errors.append(
                f"FORGED: v2 'tier' must be one of "
                f"{'|'.join(sorted(EVIDENCE_TIERS))}, got {tier!r}"
            )
        if not isinstance(ev.get("negative_paths", []), list):
            errors.append("FORGED: v2 'negative_paths' must be a list")
    if not isinstance(ev.get("command"), list) or not ev["command"]:
        errors.append("FORGED: 'command' must be a non-empty list")
    if not isinstance(ev.get("turn"), str) or not ev["turn"]:
        errors.append("FORGED: 'turn' must be a non-empty string")
    for field in ("timestamp_utc", "workspace", "tree_sha"):
        if not ev.get(field):
            errors.append(f"FORGED: '{field}' is missing or empty")
    return errors


def _validate_output(ev: dict) -> list[str]:
    errors: list[str] = []
    output = ev.get("output", "")
    if not isinstance(output, str) or not output.strip():
        errors.append("FORGED: 'output' is empty — evidence not machine-written")
        return errors
    for pat in _FORGED_OUTPUT_PATTERNS:
        if pat.search(output):
            errors.append(
                f"FORGED: output matches forged-shape pattern {pat.pattern!r}"
            )
    for pat in _SECRET_PATTERNS:
        if pat.search(output):
            errors.append(
                f"SECRETS: evidence output contains unredacted secret matching {pat.pattern!r}"
            )
    # v2 integrity: the writer stored a digest of the output it captured. If the
    # two disagree, the record was edited after the command ran.
    digest = ev.get("output_sha256")
    if ev.get("schema_version") == "2":
        if not digest:
            errors.append("FORGED: v2 evidence is missing 'output_sha256'")
        else:
            actual = hashlib.sha256(output.encode("utf-8")).hexdigest()
            if actual != digest:
                errors.append(
                    f"FORGED: output_sha256 mismatch — stored {digest[:12]}…, "
                    f"actual {actual[:12]}…; the output field was modified after capture"
                )
    return errors


def _validate_staleness(ev: dict) -> list[str]:
    ts_str = ev.get("timestamp_utc", "")
    if not ts_str:
        return ["STALE: timestamp_utc missing"]
    try:
        ev_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        age_secs = (datetime.now(timezone.utc) - ev_time).total_seconds()
        if age_secs < 0:
            return [
                f"FORGED: evidence timestamp is in the future ({age_secs:.0f}s ahead)"
            ]
        if age_secs > STALENESS_SECS:
            return [
                f"STALE: evidence is {age_secs:.0f}s old (limit: {STALENESS_SECS}s)"
            ]
    except ValueError as e:
        return [f"STALE: cannot parse timestamp_utc {ts_str!r}: {e}"]
    return []


def _validate_workspace(ev: dict, current_workspace: Path) -> list[str]:
    ev_ws = ev.get("workspace", "")
    if not ev_ws:
        return ["MISMATCH: workspace field missing in evidence"]
    if Path(ev_ws).resolve() != current_workspace.resolve():
        return [f"MISMATCH: workspace {ev_ws!r} != current {str(current_workspace)!r}"]
    return []


def _validate_tree(ev: dict, current_tree: str) -> list[str]:
    ev_tree = ev.get("tree_sha", "")
    if not ev_tree:
        return ["MISMATCH: tree_sha missing in evidence"]
    if ev_tree == current_tree:
        return []
    # Both DIRTY: compare HEAD part only (index may have evolved)
    if ev_tree.startswith("DIRTY:") and current_tree.startswith("DIRTY:"):
        if ev_tree.split(":")[1] == current_tree.split(":")[1]:
            return []
    if ev_tree.startswith("NONGIT") or current_tree.startswith("NONGIT"):
        return []
    return [
        f"MISMATCH: tree_sha changed since evidence was written. "
        f"Evidence: {ev_tree!r}, Current: {current_tree!r}"
    ]


def _validate_exit_code(ev: dict) -> list[str]:
    ec = ev.get("exit_code")
    if not isinstance(ec, int):
        return ["FAILED: exit_code is not an integer"]
    if ec != 0:
        return [f"FAILED: evidence exit_code={ec} (must be 0)"]
    return []


# ── stub check (never mutates source) ────────────────────────────────────────


def _python_stub_lines(source: str) -> list[tuple[int, str]]:
    """Stub markers in Python, ignoring string literals.

    A tool that *documents* stub markers (a linter, this gate, the docs
    generator) mentions TODO/FIXME inside strings. Flagging those is a false
    positive that trains people to bypass the gate. Real stubs live in comments
    (`# TODO: implement`) or in code (`raise NotImplementedError`), so only
    COMMENT and NAME tokens are inspected.
    """
    import io
    import tokenize

    hits: list[tuple[int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT and _STUB_PATTERN.search(tok.string):
                hits.append((tok.start[0], tok.line.rstrip()))
            elif tok.type == tokenize.NAME and tok.string == "NotImplementedError":
                hits.append((tok.start[0], tok.line.rstrip()))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Unparseable file: fall back to the line scan rather than skipping it.
        return [
            (i, line.rstrip())
            for i, line in enumerate(source.splitlines(), 1)
            if _STUB_PATTERN.search(line)
        ]
    return hits


# Bundlers inline the source of tools that *document* stub markers, so a
# generated bundle reports stubs its authored input never had. Path is the only
# reliable signal — esbuild output carries no `@generated` banner.
_BUILD_DIRS = {"dist", "build", "out", "node_modules", ".next", "coverage"}


def _is_build_output(rel_path: str) -> bool:
    parts = PurePosixPath(rel_path.replace("\\", "/")).parts
    return any(part.lower() in _BUILD_DIRS for part in parts[:-1])


def _check_stubs(workspace: Path, files: list[str]) -> list[str]:
    errors: list[str] = []
    for f in files:
        fp = workspace / f
        if fp.suffix.lower() in _DOC_EXTS | _BINARY_EXTS:
            continue
        if _is_build_output(f):
            continue
        if not fp.is_file():
            continue
        try:
            source = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Build outputs are not authored code. Scanning them for stubs flags any
        # generator that *documents* the markers. The file still counts as a
        # change, so evidence is still required — only this scan is skipped.
        if "@generated" in source[:400]:
            continue
        if fp.suffix.lower() == ".py":
            hits = _python_stub_lines(source)
        else:
            hits = [
                (i, line.rstrip())
                for i, line in enumerate(source.splitlines(), 1)
                if _STUB_PATTERN.search(line)
            ]
        errors.extend(f"  {f}:{idx}: {line}" for idx, line in hits)
    return errors


# ── selftest ──────────────────────────────────────────────────────────────────


def _selftest() -> int:
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    try:
        ev = {
            "schema_version": "1",
            "turn": "selftest_001",
            "command": ["echo", "selftest"],
            "exit_code": 0,
            "output": "selftest\n",
            "output_truncated": False,
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "workspace": str(tmp),
            "tree_sha": "NONGIT:selftest",
        }

        def validate(record: dict) -> list[str]:
            return (
                _validate_schema(record)
                + _validate_output(record)
                + _validate_staleness(record)
                + _validate_workspace(record, tmp)
                + _validate_exit_code(record)
            )

        v2 = dict(
            ev,
            schema_version="2",
            tier="unit",
            acceptance="selftest proves the validators accept a well-formed record",
            negative_paths=[],
            output_sha256=hashlib.sha256(ev["output"].encode("utf-8")).hexdigest(),
        )

        cases = [
            ("v1 record accepted", validate(ev), True),
            ("v2 record accepted", validate(v2), True),
            (
                "empty output + nonzero exit rejected",
                _validate_output(dict(ev, output=""))
                + _validate_exit_code(dict(ev, exit_code=1)),
                False,
            ),
            (
                "v2 with edited output rejected",
                _validate_output(dict(v2, output="doctored\n")),
                False,
            ),
            (
                "v2 missing digest rejected",
                _validate_output({k: v for k, v in v2.items() if k != "output_sha256"}),
                False,
            ),
            ("v2 bad tier rejected", _validate_schema(dict(v2, tier="turbo")), False),
            (
                "unknown schema rejected",
                _validate_schema(dict(ev, schema_version="9")),
                False,
            ),
        ]
        for name, errors, want_clean in cases:
            if want_clean and errors:
                _err(f"selftest FAILED — {name}: {errors}")
                return 1
            if not want_clean and not errors:
                _err(f"selftest FAILED — {name}: expected rejection, got none")
                return 1
        # Stub scan: authored code is scanned, build output is not.
        (tmp / "src").mkdir(parents=True, exist_ok=True)
        (tmp / "src" / "dist").mkdir(parents=True, exist_ok=True)
        stub_line = "const q = 'TODO: implement';\n"
        (tmp / "src" / "authored.ts").write_text(stub_line, encoding="utf-8")
        (tmp / "src" / "dist" / "bundle.js").write_text(stub_line, encoding="utf-8")
        if not _check_stubs(tmp, ["src/authored.ts"]):
            _err("selftest FAILED — stub scan missed authored code")
            return 1
        if _check_stubs(tmp, ["src/dist/bundle.js"]):
            _err("selftest FAILED — stub scan flagged build output")
            return 1
        if _check_stubs(tmp, ["src\\dist\\bundle.js"]):
            _err("selftest FAILED — stub scan flagged build output (backslash path)")
            return 1
        _ok(f"selftest PASSED ({len(cases)} validator cases + 3 stub-scan cases)")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── main ──────────────────────────────────────────────────────────────────────


def _utf8_io() -> None:
    """Windows consoles default to a legacy codepage; non-ASCII output would
    crash the tool instead of printing. Force UTF-8 on our own streams."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _correlate_claims(response_text: str) -> list[str]:
    """Check the response's VERIFY blocks against this turn's evidence.

    A command that ran is only half the proof; the other half is that the report
    about it is faithful. Returns [] when the response makes no claim.
    """
    if not response_text:
        return []
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import rule_validator  # noqa: PLC0415
    except ImportError:
        return []
    evidence, _note = rule_validator.load_evidence(
        os.environ.get("DAINEXUS_TURN") or None
    )
    return rule_validator.validate(response_text, evidence)


def main() -> None:
    _utf8_io()
    hook_mode = "--hook" in sys.argv
    block_code = 2 if hook_mode else 1

    if "--selftest" in sys.argv:
        sys.exit(_selftest())

    # Stop-hook payload (unused fields tolerated; stdin may be empty in CLI mode)
    response_text = ""
    if hook_mode and not sys.stdin.isatty():
        try:
            payload = json.load(sys.stdin)
            if isinstance(payload, dict):
                response_text = str(payload.get("response_content") or "")
        except (json.JSONDecodeError, OSError):
            pass

    workspace = _workspace()
    changed = _changed_files(workspace)
    code_changed = _code_files(changed)

    # Claim correlation runs first and unconditionally: a VERIFY block that
    # misquotes its evidence is a false report whether or not code changed.
    claim_errors = _correlate_claims(response_text)

    if not code_changed and not claim_errors:
        _ok(
            f"No code changes detected ({len(changed)} doc/config file(s) changed) — gate OPEN"
        )
        sys.exit(0)

    if code_changed:
        print(
            f"[VERIFY-GATE] {len(code_changed)} changed code file(s): "
            f"{', '.join(code_changed[:10])}"
        )
    all_errors: list[str] = []
    if claim_errors:
        _err("Response claims do not match the evidence:")
        for e in claim_errors:
            print(f"   - {e}", file=sys.stderr)
        all_errors.append("MISREPORTED")
    if not code_changed:
        # Nothing else to validate; the claim mismatch alone decides the turn.
        _err("Gate BLOCKED. Reasons: MISREPORTED")
        sys.exit(block_code)

    # 1. Stub check
    print("[VERIFY-GATE] 1. Checking for stubs (TODO, FIXME, NotImplementedError)...")
    stub_errs = _check_stubs(workspace, code_changed)
    if stub_errs:
        _err("Code contains stubs:")
        for e in stub_errs:
            print(e, file=sys.stderr)
        all_errors.append("STUBS")
    else:
        _ok("No stubs found")

    # 2. Machine-written evidence validation
    print("[VERIFY-GATE] 2. Validating machine-written evidence...")
    turn_env = os.environ.get("DAINEXUS_TURN", "")
    ev_path = _find_evidence(workspace, turn_env)
    if ev_path is None:
        _err("MISSING: No evidence file under .dainexus/verify/")
        print(
            "   Code changes must be gated by a machine-written evidence file.",
            file=sys.stderr,
        )
        print(
            "   Run: python scripts/lite/run_check.py -- <your-check-cmd>",
            file=sys.stderr,
        )
        all_errors.append("MISSING")
    else:
        print(f"   - Evidence file: {ev_path}")
        try:
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            _err(f"FORGED: cannot parse evidence file: {e}")
            all_errors.append("FORGED")
            ev = {}

        if ev:
            current_tree = _current_tree_sha(workspace)
            for check_fn, label in [
                (lambda: _validate_schema(ev), "schema"),
                (lambda: _validate_output(ev), "output"),
                (lambda: _validate_staleness(ev), "staleness"),
                (lambda: _validate_workspace(ev, workspace), "workspace"),
                (lambda: _validate_tree(ev, current_tree), "tree"),
                (lambda: _validate_exit_code(ev), "exit_code"),
            ]:
                errs = check_fn()
                if errs:
                    _err(f"Evidence {label} check failed:")
                    for e in errs:
                        print(f"   {e}", file=sys.stderr)
                    all_errors.extend(errs)

    # Final decision
    if all_errors:
        _err(
            f"Gate BLOCKED. Reasons: {', '.join(sorted(set(e.split(':')[0] for e in all_errors)))}"
        )
        sys.exit(block_code)
    _ok("All checks passed — gate OPEN")
    sys.exit(0)


if __name__ == "__main__":
    main()
