# POLICY — Execution Policy

Runtime guardrail configuration for tool execution. The policy lives in
`.dainexus/execution-policy.yaml` and is enforced by
`scripts/lite/policy_check.py`, called from the Guardrail protocol
(`skills/_shared/protocols/guardrail.md`) before a tool call runs.

## Keys

| Key | Default | Meaning |
|---|---|---|
| `mode` | `strict` | `strict` = deny blocks (exit 1) · `permissive` = warn but allow (exit 2) · `audit` = log only (exit 0) |
| `require_verify` | `true` | Every success claim requires a VERIFY block (VERIFY section) |
| `max_escalations` | `3` | Max `escalate.py` calls per user turn before pausing for approval |
| `deny_patterns` | see file | Case-insensitive regex list matched against `"<tool_name> <args>"` |
| `refresh_interval_ticks` | `10` | Guard re-reads the policy file every N tool calls (hot-reload) |

## Gate protocol

1. Before executing a risky tool call, run
   `python scripts/lite/policy_check.py check <tool_name> "<args>"`.
2. Exit `0` → proceed. Exit `2` → proceed, but tag the step **HARD**
   (ESCALATE section). Exit `1` → the tool call is blocked;
   report the matched pattern to the user instead of retrying.
3. Every match is appended to `.dainexus/policy-log.jsonl` (best-effort).
4. If the policy file is missing, unreadable, empty, or malformed, the gate
   blocks execution (**fail-closed**) and reports a policy configuration
   error. Unknown `mode` values also fail closed (treated as `strict`).

## Editing rules

- Scalars must stay one-per-line with no spaces in the value.
- Deny patterns must stay in the `  - "pattern"` form: regex, no double
  quotes inside the pattern, no inline comments on pattern lines.
- Loosening the policy (`strict` → `permissive`/`audit`, or removing a
  deny pattern) is itself a security-sensitive change: Hard Rule 6 and
  the HARD checklist in ESCALATE section apply.
