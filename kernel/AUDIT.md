# AUDIT — Proportional Requirement Coverage

Audit against the original objective + current workspace evidence before declaring success. Depth scales with risk and blast radius.

## QUICK
For a local, reversible change: inspect the final diff and affected context, confirm the explicit acceptance condition with current evidence, and check that no unrelated path changed. No matrix, no full-repository reread.

**Exception that always applies:** if the changed file is itself an instruction/rule/config file whose consumer reads the whole document (kernel files, overlays, protocols, policy), read that file **in full** for contradictions even when the edit is one line.

## STANDARD
A concise checklist covering each material requirement, each changed surface, and adjacent regression risk. Expand to the matrix below only when it improves traceability.

## DEEP — full structure
```text
REQUIREMENT COVERAGE MATRIX:
| # | Requirement (from user request) | File(s) changed | Covered? | Evidence |
|---|------|------|------|------|
| 1 | ... | ... | ✅ / ⚠️ / ❌ | ... |

CONTRADICTION SCAN:
| File | Rule/instruction says | Example/template shows | Conflict? |
|---|---|---|---|
| ... | ... | ... | ✅ OK / ❌ CONFLICT |

CROSS-ENTRY CONSISTENCY: (if multiple files serve the same role)
| Concept | File A says | File B says | Aligned? |
|---|---|---|---|
| ... | ... | ... | ✅ / ❌ |

VERDICT: FULL COVERAGE | GAPS FOUND → fix before delivery
```

## Rules
1. `STANDARD`/`DEEP`: re-read changed files IN FULL, not diffs — an agent consumes the whole file. `QUICK`: the diff plus affected context is enough, except for instruction/rule/config files (read in full always).
2. Every numbered requirement from the user's request gets its own row in `DEEP`.
3. If examples/templates contradict rules in the same file → ❌ CONFLICT.
4. GAPS FOUND verdict requires fixing before declaring done.
5. If the task involved tool calls, verify no guardrail DENY events were suppressed or bypassed.
