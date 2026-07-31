# Guardrail Protocol

> **Purpose:** Pre-authorize every tool call before execution. Blocks destructive operations, warns on sensitive access, enforces scope discipline. The only protocol that can halt execution — the kill switch (kernel Hard Rule 6).

## When to Apply
- **Every tool call** during any skill execution (writes, commands).
- **NOT applied** to read-only operations, **except** sensitive-file reads (Rule 2).

## Configuration

```yaml
# .dainexus.yaml
guardrail:
  enabled: true
  mode: warn            # warn | deny | disabled | dry_run
  escalate_to_user: true
# Recommended: run warn mode for 5+ sessions, review the log, then switch to deny.
```

## Rules

| # | Rule | Trigger patterns (representative) | Action |
|---|---|---|---|
| 1 | Destructive file ops | `rm -rf /`, `rm -rf ~`, `rm -rf ./*` at project root, `git push --force`, `DROP TABLE/DATABASE`, `TRUNCATE` | **DENY** + notify user |
| 2 | Sensitive file access | `*.env*`, `*.key`, `*.pem`, `credentials/*`, `.ssh/*`, `~/.aws/*`, filenames matching `*secret*`/`*token*`/`*password*` | **WARN** on read; **DENY** on write |
| 3 | Remote code execution | `curl … \| sh`, `wget … \| bash`, `eval($(curl …))` | **DENY** + suggest explicit dependency management |
| 4 | Publishing / release | `npm publish`, `docker push`, `git push --tags`, `terraform apply`, production deploys | **ESCALATE** — block + request user approval |
| 5 | Scope enforcement | write outside the task's contracted/stated scope; protected paths (brownfield) | **DENY** modify/delete; ALLOW create-alongside |
| 6 | Dry-run mode | any mutating tool while `mode: dry_run` | Intercept; emit a `.diff` artifact instead of writing |
| 7 | Path traversal | `../` in write paths; absolute paths outside workspace (`/etc/*`, `C:\Windows\*`) | **DENY** |
| 8 | Symlink safety | write target is a symlink resolving outside workspace | **WARN** + confirm |
| 9 | Credential content | writing content matching `sk-…`, `ghp_…`, `AKIA…`, private-key blocks, `password = "…"`, bearer tokens | **DENY** + suggest `.env` |
| 10 | Resource exhaustion | writes >10 MB, fork bombs, `dd if=/dev/zero`, unbounded `while true` | **DENY** |
| 11 | Environment persistence | writes/appends to `~/.bashrc`, `~/.zshrc`, `/etc/profile`, PowerShell `$PROFILE` | **DENY** + suggest project-local config |
| 12 | Network exfiltration | `curl -X POST -d`, `wget --post-data`, `nc -l`, reverse-shell one-liners | **WARN** (legit API calls are common) |
| 13 | Supply chain | `pip install --index-url`, `npm install <url/github>` without lockfile, `cargo install --git` | **WARN** — verify authenticity |

## Decision Matrix (summary)

| Target | Read | Write | Execute | Delete |
|---|---|---|---|---|
| Normal files | ALLOW | ALLOW | ALLOW | WARN |
| Sensitive files | WARN | DENY | — | DENY |
| Protected paths | ALLOW | DENY | — | DENY+ESCALATE |
| Destructive commands | — | — | DENY | — |
| Publishing commands | — | — | ESCALATE | — |

## Mechanical Gate (Execution Policy)

The rule table above is judgment; `scripts/lite/policy_check.py` is enforcement. Before any risky command execution:

```bash
python scripts/lite/policy_check.py check <tool_name> "<args>"
```

Exit 0 = ALLOW · exit 2 = WARN (proceed, tag step HARD) · exit 1 = DENY (blocked — includes fail-closed when `.dainexus/execution-policy.yaml` is missing or malformed). Configuration and editing rules: `kernel/POLICY.md`.

## On DENY
1. Do NOT retry, rephrase, or route around the block (Hard Rule 6).
2. Emit a log line and surface the decision to the user with the reason and a safer alternative.
3. If the task cannot proceed without the blocked operation → report the blocker; the user decides.

## Logging

Append every non-ALLOW decision to `.dainexus/guardrail-log.jsonl`:

```jsonl
{"timestamp":"ISO-8601","decision":"DENY","tool":"run_command","target":"rm -rf ./","rule":"destructive-file-ops","reason":"..."}
```

## Graceful Degradation
- Rule evaluation fails (regex/config error) → security rules (1–4, 7–11) **fail closed** (DENY); non-security custom rules fail open (ALLOW). Never crash the pipeline on a guardrail internal error — log and continue.

## Custom Rules

```yaml
# .dainexus.yaml
guardrail:
  custom_rules:
    - name: no-direct-db-push
      pattern: "prisma db push"
      action: DENY
      reason: "Use migrations"
      suggestion: "npx prisma migrate dev --name <name>"
```
