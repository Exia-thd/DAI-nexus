# EASY / HARD Routing

Tag each task step during SOLVE section planning.

## Classification Checklist
Model self-tag is only a hint. A step is **HARD** if ANY of these objective runtime signals or conditions apply:
- [ ] Repeated verification failure (runtime signal).
- [ ] Independent-sample disagreement (runtime signal).
- [ ] Security-sensitive context (auth, secrets, injection surface, permissions).
- [ ] Changes a public interface, schema, or public exports.
- [ ] Concurrency, locking, or asynchronous ordering paths.
- [ ] The Stuck rule fired on this step.
- [ ] Guardrail or execution policy (`policy_check.py`) flagged a DENY or WARN on this step.
- [ ] The step would signal or kill a process that holds no runtime lease, or would reap a `policy=keep` lease.

Otherwise, the step is **EASY**.

## Execution Protocol
- **EASY**: Execute the step yourself.
- **HARD**: Run the escalation runner:
  ```bash
  python scripts/lite/escalate.py "<step + minimal context>"
  ```
  It builds a redacted context packet (task + latest verify evidence + git diff) and delegates to the expert CLI configured in `.dainexus.yaml` (`expertMode.activeCli`, default `claude`) in fresh-context non-interactive mode. You must integrate and verify the answer.
  If no expert CLI is available: (1) dispatch a fresh-context subagent if the host supports one, else (2) pause and present the step + evidence + 2–3 options to the user.

## Agreement-Based Cascade Rules
When a step is escalated (to a subagent or, later, a stronger model):
1. Verify the generated output matches all constraints and local coding patterns.
2. If the escalated output introduces any ambiguity or contradicts other parts of the plan, run another escalation to cross-validate or ask the user for confirmation.
3. Integrate and run a `VERIFY` check immediately. Never merge unverified escalated output.

## Budget Limit
- **Cost Budget Rules Apply**: Escalations are bound by token and cost budget rules, not a fixed escalation limit.
- If you exceed the budget, you must **pause**. Do not "do your best".
- Security, schema, and public-interface work must pause and explicitly wait for user approval or budget extension if exhausted.
