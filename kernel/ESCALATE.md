# EASY / HARD Routing

Tag each task step during SOLVE section planning.

`EASY` and `HARD` describe **risk and uncertainty**, not seniority or task size. Every tier stays accountable for judgment and evidence.

## HARD Signals
Model self-tag is only a hint. A step is **HARD** if ANY of these objective signals apply:
- [ ] Repeated verification failure, or the Stuck rule fired on this step.
- [ ] Independent evidence materially disagrees.
- [ ] Security-sensitive context (auth, secrets, injection surface, permissions).
- [ ] Changes a public interface, schema, or public exports.
- [ ] Concurrency, locking, ordering, migration, or an irreversible release path.
- [ ] **Payment, billing, in-app purchase, receipt validation, entitlements, subscription, or checkout — mandatory HARD regardless of file count.**
- [ ] Guardrail or execution policy (`policy_check.py`) returned DENY/WARN that changes the feasible approach.
- [ ] The step would signal or kill a process that holds no runtime lease, or would reap a `policy=keep` lease.

Otherwise the step is **EASY**. `QUICK` work does not need per-line tagging ceremony.

## Execution Protocol
- **EASY**: Execute the step yourself.
- **HARD**: Run the escalation runner:
  ```bash
  python scripts/lite/escalate.py "<step + minimal context>"
  ```
  It builds a redacted context packet (task + latest verify evidence + git diff) and delegates to the expert CLI configured in `.dainexus.yaml` (`expertMode.activeCli`, default `claude`) in fresh-context non-interactive mode. You must integrate and verify the answer.
  If no expert CLI is available: (1) dispatch a fresh-context subagent if the host supports one, else (2) pause and present the step + evidence + 2–3 options to the user.

## Review After Escalation
1. Treat escalated output as a **proposal, not truth**; verify it against current constraints and project evidence.
2. Cross-validate only when disagreement or risk remains material — do not trigger a second model merely to satisfy a cascade.
3. Integrate only verified output, and run a `VERIFY` check immediately.

## Budget Limit
- **Cost Budget Rules Apply**: Escalations are bound by token and cost budget rules, not a fixed escalation limit.
- If you exceed the budget, you must **pause**. Do not "do your best".
- Security, schema, and public-interface work must pause and explicitly wait for user approval or budget extension if exhausted.
