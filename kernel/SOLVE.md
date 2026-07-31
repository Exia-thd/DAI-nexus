# SOLVE — The Reasoning Loop

Always follow all steps. If the task is a single trivial edit (e.g., a typo fix), steps 2–3 may collapse to one row/one item — but `VERIFY` (step 6) and `AUDIT` (step 7) are never skipped.

## 1. UNDERSTAND (Write this scratchpad before anything else)
- Task in one sentence:
- What must be TRUE at the end (observable, checkable):
- What could I be wrong about (choose from: wrong file? wrong API shape? wrong version? wrong root cause? missing case?):

## 2. GROUND (Assumption sweep)
Verify essential elements (files, signatures, dependencies, CLI tools) using real check commands.
Do not self-attest Y/N. Mechanical checks must be script-produced evidence that you consume.
| Assumption | Check command / script | Script-produced Evidence |
|---|---|---|
| Target file exists | `ls` / View file | ... |
| Function signature | View file `<file:line>` | ... |
| Dependency/version | View file `package.json` | ... |
| Required CLI tool  | `which <tool>` | ... |

Resolve any failures now or mark the step `HARD`.

## 3. DECOMPOSE
Path branches based on task type:

**A. EDIT PATH (Code modifications)**
Plan least-to-most. EVERY item must have all three fields:
`n. ACTION (one concrete action) | TARGET (exact file/symbol) | CHECK (one command whose exit code proves this item done)`

**B. QUESTION PATH (Codebase queries, non-edit)**
`n. QUESTION | SEARCH COMMAND (e.g., rg "pattern" src/) | SYNTHESIS EXPECTATION`

**C. DESIGN PATH (Architecture/Review, non-edit)**
`n. COMPONENT | ANALYSIS SCRIPT/COMMAND | DESIGN CONSTRAINT`

**D. UI DESIGN GATE (Frontend Edits)**
Before any frontend UI implementation, generate a design contract containing:
- User goal and primary action
- Content hierarchy and layout rationale
- Existing design-system audit
- Tokens: color, typography, spacing, radius, elevation, motion
- Component states: default, hover, focus, disabled, loading, empty, error
- Responsive behavior matrix for narrow, medium, and wide viewports
- Accessibility and reduced-motion requirements
- Wireframe, mockup, or written layout specification
*Note: Major screens/redesigns require user approval. Small UI fixes require an inline design contract but may proceed without blocking.*

**Gate**:
Do not self-attest Y/N claims. Mechanical checks must be script-produced evidence that you consume. Execute your plan's checks to verify:
- Edit plans have concrete actions, verified files, and runnable CHECK commands.
- Total items ≤ 10.
If the script-produced evidence shows failures, fix the list. Do not start execution.

### Parallel Orchestration Decision Contract

Before dispatching parallel workers (`skills/_shared/protocols/parallel-dispatch.md`), decide deterministically:
- Small or serial work → **0 workers** (do it yourself).
- Mechanical inventory/search → at most **1 scout**.
- **2–3 workers** only for independent, path-disjoint scopes — each bound by a task contract (`worktree_manager.py contract`), scopes must not overlap.
- Cap workers by scope count and remaining budget; reserve one slot for a fresh-context reviewer when review is requested.
- Security, schema, public-API, concurrency work, or worker disagreement → route to escalation (ESCALATE section), not to more workers.
- No worker may recursively spawn workers.
- **Stop conditions**: duplicate findings, scope already covered, the same blocker twice, budget exhausted, or deadline cap → stop dispatching, consolidate.

## 4. PROGRAM-OF-THOUGHT (PoT) RULE
For any complex logic, calculations, algorithms, or non-trivial implementations:
- Write a quick Program-of-Thought (PoT) scratch script or verification test first.
- Run it to verify the logic and correctness of the assumptions in isolation.
- Use the execution output as ground truth before coding in the main application.

## 5. FREE-FORM THEN JSON RULE
If the task requires JSON or structured output:
- Always think free-form first (write a reasoning block or scratchpad).
- Only output the final clean JSON/structured payload at the very end of the response.

## 6. EXECUTE & VERIFY (One item at a time)
**Note:** The Guardrail protocol applies `before_tool()` on every tool call during execution. Destructive operations are blocked. See `skills/_shared/protocols/guardrail.md`.

For each plan item:
1. Tag as `EASY` or `HARD` per ESCALATE section.
2. If `HARD` → follow the escalation protocol in ESCALATE section.
3. If `EASY` → execute it, then IMMEDIATELY run its CHECK command.
4. **Reasoning checkpoint** (after each CHECK result): Before proceeding, write 1–2 sentences: *What did this result tell me? Does it change my plan?* Do not skip to the next item without this pause.
5. If CHECK fails → resolve the failure before moving to the next item. Never batch items without executing their checks.
6. After finishing all items, emit one `VERIFY` block per changed behavior (see VERIFY section). Machine-written evidence is produced with `python scripts/lite/run_check.py -- <check-cmd>`.
7. **Adversarial review** (for FEATURE/DEBUG tasks with ≥3 changed files): Spawn a reviewer that sees ONLY the diff + original requirements — not your reasoning context. A fresh perspective catches blind spots.

## 7. AUDIT (Requirement Coverage)
Re-read all changed files in full. Build a requirement coverage matrix, scan for contradictions between rules and examples, and check cross-entry consistency. See AUDIT section. GAPS FOUND → fix before delivery.

## 8. STUCK RULE (After 2 failures on the same item)
Stop retrying the same approach. A variant of a failed fix is still the same fix. In order:
1. Write a minimal script/test to isolate and test the assumption, then run it.
2. Search the codebase for a working example of the same pattern.
3. Research external documentation or sources.
4. **Reset context**: If accumulated corrections are polluting reasoning, start fresh — restate the goal from scratch with lessons learned, rather than building on failed attempts.
5. If still stuck → mark the item as `HARD` and escalate.
6. If escalation is unavailable → report the blocker along with all gathered evidence. Never attempt a third time on the same fix.

## 9. TURN-CLOSE — Memory Save (MANDATORY, never skip)

After completing all work for this user turn, persist context so the next turn (or next session) can resume without re-deriving:

1. **Save turn summary** (if `scripts/lite/memory.py` exists):
   ```
   python scripts/lite/memory.py add "REQ: [1-line user goal] | DONE: [what changed/decided] | OPEN: [blockers or none]" --category session
   ```
   If a key decision was made, add a second entry:
   ```
   python scripts/lite/memory.py add "DECISION: [what was decided and why]" --category decisions --importance 8
   ```
2. **Update activeContext.md** — if current work, scope, or blockers changed, overwrite `.dainexus/memory-bank/activeContext.md` (≤300 tokens): Current Status / Next Steps / Open Blockers.
3. **Runtime reclaim** — if this turn started anything long-running, run `python scripts/lite/runtime_lease.py status`, release what you no longer need, and emit VERIFY Template 4. Anything left open must be a deliberate `policy=keep`.
4. **Self-check**: confirm the memory add succeeded. If it failed, log: `⚠ Memory save failed — context may not persist`.
5. **Self-report rule violations**: if you realize you broke a kernel rule (or the user points it out), record it:
   ```
   python scripts/lite/rule_ledger.py add <rule_id> violation "source: self-report|user"
   ```
