# DAI Nexus

**Một câu yêu cầu → một app được ship, có kiểm chứng.**

DAI Nexus là một hệ điều hành cho AI coding agents: kernel bất biến nạp mỗi phiên, thư viện skill chuyên gia load theo nhu cầu, và một runtime Python thuần cưỡng bức bằng chứng — agent không được phép nói "xong rồi" nếu không có evidence do máy sinh ra.

## Kiến trúc 3 tầng

```
TẦNG 1 — KERNEL (luôn load, <7k token)
  kernel/{ENTRY, SOLVE, VERIFY, ESCALATE, CLARIFY, AUDIT, POLICY}.md
  → 6 Hard Rules · Boot Sequence (kèm Memory Load bắt buộc) · SOLVE loop
  → VERIFY/AUDIT contract · TURN-CLOSE memory save · Execution policy

TẦNG 2 — SKILLS (1 orchestrator + ~86 chuyên gia, load on-demand)
  skills/pipeline/{LITE.md, SKILL.md, phases/}   ← orchestrator chính
  → modes: QUICK | REVIEW | TEST | FEATURE | SHIP | FULL_BUILD
  → FULL_BUILD: DEFINE → BUILD → HARDEN → SHIP với 3 gate user-approve
  skills/<role>/LITE.md — overlay chuyên gia (GROUND/DECOMPOSE slots theo domain)
  → routing lõi: debugger · software-engineer · ui-designer · code-reviewer
                 · qa-engineer · devops
  → pipeline roles: product-manager · solution-architect · security-engineer
                    · frontend-engineer
  → domain: game (unity/unreal/godot/roblox...), data/AI, mobile, growth,
            per-language (go/python/rust)...
  skills/_shared/protocols/ — ~50 protocol dùng chung (guardrail kill switch,
  parallel-dispatch, self-healing, quality-gate, brownfield-safety...)

TẦNG 3 — RUNTIME (Python thuần, zero-dependency, Windows/macOS/Linux)
  scripts/lite/sync-kernel.py       → sinh CLAUDE.md / AGENTS.md / GEMINI.md từ kernel
  scripts/lite/run_check.py         → ghi evidence JSON (machine-written, atomic, redacted)
  scripts/lite/verify_gate.py       → Stop-hook gate: chặn turn nếu thiếu/giả/hết hạn evidence
  scripts/lite/memory.py            → memory SQLite+FTS5: BM25 + RRF fusion, auto-tag, GC
  scripts/lite/escalate.py          → HARD-step escalation qua expert CLI, budget-enforced
  scripts/lite/worktree_manager.py  → parallel dispatch: contract → validate → merge arbiter
  scripts/lite/policy_check.py      → execution policy gate (deny patterns, fail-closed)
  scripts/lite/runtime_lease.py     → runtime lease guard: chống leak dev server/process
  scripts/lite/rule_ledger.py       → ledger tự khai vi phạm rule (JSONL, stats)
  scripts/lite/validate_overlays.py → linter overlay: chặn evidence giả, path chết, bảng hỏng
  mcp/server.py                     → MCP server (stdio) 8 dn_* tools: pipeline state + memory
```

## Quickstart

> Windows không có alias `python`? Thay `python` bằng `py -3` trong mọi lệnh dưới (hook trong `.claude/settings.json` đã dùng `py -3` sẵn).

```bash
# 1. Sinh boot files từ kernel (chạy lại mỗi khi sửa kernel/)
python scripts/lite/sync-kernel.py

# 2. Tự kiểm tra toàn hệ thống (68 checks)
python tests/smoke.py

# 3. Dùng: mở Claude Code (hoặc Cursor/Gemini CLI) tại repo này.
#    CLAUDE.md/AGENTS.md/GEMINI.md được đọc tự động; Stop hook cưỡng bức
#    evidence; MCP server đăng ký sẵn trong .mcp.json.
```

Trong lúc agent làm việc, mọi claim "đã xong" phải kèm evidence:

```bash
python scripts/lite/run_check.py -- <lệnh kiểm chứng, ví dụ: npm test>
```

## Tài liệu

Site tài liệu nằm ở `docs/` — mở `docs/index.html` bằng browser, hoặc:

```bash
python -m http.server 8000 --directory docs
```

Có 8 trang; trong đó [`memory-guide.html`](docs/memory-guide.html) là **trang độc lập** hướng dẫn
bóc riêng module memory (`scripts/lite/memory.py` — một file, chỉ stdlib) đem gắn vào project khác:
cài 60 giây, 4 cách tích hợp (library · CLI · MCP · hook vòng đời agent), điểm cấu hình nào nên sửa,
thứ gì đừng đụng vào, giới hạn đã biết, và đoạn kiểm chứng chạy được sau khi port.

Ngoài ra có `docs/memory-standalone.html` — **bản một-file của đúng trang đó**: không nav, không link
sang trang nào, CSS nhúng sẵn. Không trang nào trong site trỏ tới nó; nó tồn tại để gửi đi một mình
(đính kèm email, dán vào ticket, copy sang máy khác) mà vẫn hiển thị đầy đủ.

Toàn bộ số liệu và code excerpt trong đó được **sinh từ source lúc build** (`docs/build_docs.py`),
nên không thể drift khỏi code. `python docs/build_docs.py --check` sẽ fail nếu trang đã cũ —
smoke suite kiểm tra điều này mỗi lần chạy.

## Chống ảo giác — 4 lớp

> Bằng chứng theo **tỉ lệ rủi ro**: `QUICK` (1–3 action, một check gọn) · `STANDARD` (≤7 action) · `DEEP` (≤10 action, review độc lập).
> Payment/billing/checkout luôn là `DEEP` bất kể số file. Sửa lỗi phải cho thấy **RED rồi mới GREEN** — cùng một lệnh.

1. **Evidence-first**: VERIFY bắt buộc, evidence do `run_check.py` ghi theo schema v2 (tree-sha, timestamp, `output_sha256`) — gõ tay hoặc sửa tay đều bị bắt là FORGED.
2. **Stop-hook gate**: `verify_gate.py` chặn kết thúc turn khi có code đổi mà thiếu/giả/hết hạn evidence, hoặc còn stub TODO/FIXME.
3. **Execution policy fail-closed**: `policy_check.py` chặn lệnh phá hoại theo deny-pattern; file policy hỏng = chặn luôn.
4. **Runtime ledger**: process dài hạn phải có lease; cuối turn `status` phải CLEAN — "tests passed" không chứng minh máy sạch.

## Tools MCP (`.mcp.json` đã đăng ký sẵn)

`dn_start_pipeline` · `dn_get_state` · `dn_advance_phase` (bị chặn nếu gate chưa approve) · `dn_request_gate_approval` · `dn_approve_gate` · `dn_fail_pipeline` · `dn_memory_add` · `dn_memory_search`

## Roadmap

1. **Vector search** — nhánh embedding thứ hai cho RRF fusion (hiện fuse BM25 + importance/recency).
2. **ASIP** — self-improving loop: extract lessons từ failure, evolve skill.
3. **Dashboard** — UI đọc `.dainexus/pipeline-state.json` qua MCP.
4. **Reviewer attestation** — chữ ký Ed25519 cho review độc lập ở tier `DEEP` (hiện review là fresh-context, chưa ký).
5. **Mutation backcheck** — tự động hoá `RED → GREEN → đột biến phải fail → GREEN` để chứng minh test không rỗng.
