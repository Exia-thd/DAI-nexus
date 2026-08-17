# Response Correlation Protocol

> **Purpose:** Evidence proves a command ran. This proves the *report about it* is faithful. Enforced by `scripts/lite/rule_validator.py`; the Stop hook rejects a mismatch as `MISREPORTED`.

## When to Apply

Whenever a turn's evidence records `acceptance_criteria` — i.e. the check was run with:

```bash
python scripts/lite/run_check.py --acceptance-id <slug> --claim "<exact behaviour>" -- <command>
```

## Strict block shape

Six fields, `ACCEPTANCE` first. Each field is quoted from the evidence, never paraphrased:

```text
ACCEPTANCE: <lowercase-slug matching an acceptance id in the evidence>
CLAIM: <the exact claim text recorded for that id>
COMMAND: <the exact command from the evidence>
OUTPUT: sha256:<the evidence output_sha256>
EXIT CODE: <code>
VERDICT: PASS | FAIL
```

## Rules

1. The acceptance slug must exist in the turn's evidence.
2. `CLAIM` must repeat the recorded wording character for character. Rewording is a mismatch.
3. `COMMAND` must equal the evidence argv, space-joined.
4. `OUTPUT` must be the digest, not pasted output. Prose where a digest belongs is a mismatch.
5. Every recorded acceptance id must be reported; an unreported criterion is a mismatch.
6. Emitting **no** block is fine — not every turn makes a verification claim.
7. Emitting a **partial** block is the failure: it reads like proof while proving nothing.

## Why the digest

`output_sha256` binds the record to the output actually captured. Editing the `output` field by hand — or inventing a digest — breaks the correlation and is detected rather than merely discouraged.
