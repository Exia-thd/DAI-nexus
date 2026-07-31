#!/usr/bin/env python3
"""
scripts/lite/rule_ledger.py
Rule compliance ledger.

Records every rule violation the agent self-reports (or the user reports).
The ledger is append-only JSONL — the raw material for spotting which rules
get forgotten and hardening them.

Ledger: .dainexus/rule-ledger.jsonl

Usage:
    python scripts/lite/rule_ledger.py add <rule_id> <event> [note]
        event: violation | near-miss | corrected
    python scripts/lite/rule_ledger.py list [--limit N]
    python scripts/lite/rule_ledger.py stats
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

LEDGER = Path(".dainexus") / "rule-ledger.jsonl"
EVENTS = {"violation", "near-miss", "corrected"}


def read_entries() -> list[dict]:
    if not LEDGER.is_file():
        return []
    entries = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def main() -> None:
    p = argparse.ArgumentParser(description="DAI Nexus rule ledger")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("add")
    sp.add_argument("rule_id")
    sp.add_argument("event", choices=sorted(EVENTS))
    sp.add_argument("note", nargs="?", default="")
    sp = sub.add_parser("list")
    sp.add_argument("--limit", type=int, default=20)
    sub.add_parser("stats")
    args = p.parse_args()

    if args.cmd == "add":
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "rule_id": args.rule_id,
            "event": args.event,
            "note": args.note[:300],
        }
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"+ ledger: {args.rule_id} {args.event}")
    elif args.cmd == "list":
        for e in read_entries()[-args.limit:]:
            print(f"  {e['timestamp']}  {e['rule_id']:<20} {e['event']:<10} {e.get('note', '')[:80]}")
    elif args.cmd == "stats":
        entries = read_entries()
        by_rule = Counter(e["rule_id"] for e in entries)
        by_event = Counter(e["event"] for e in entries)
        print(json.dumps({"total": len(entries), "by_rule": dict(by_rule.most_common()),
                          "by_event": dict(by_event)}, indent=2, ensure_ascii=False))
        # Rules violated 3+ times deserve hardening
        repeat = [r for r, c in by_rule.items() if c >= 3]
        if repeat:
            print(f"HARDEN CANDIDATES (>=3 entries): {', '.join(repeat)}", file=sys.stderr)


if __name__ == "__main__":
    main()
