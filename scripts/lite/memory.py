#!/usr/bin/env python3
"""
scripts/lite/memory.py
DAI Nexus Memory — SQLite + FTS5 + RRF fusion.

Storage: .dainexus/memory.db (WAL mode — crash-safe, concurrent reads)

Progressive disclosure:
  Layer 1 (index)  — titles + scores only, ~15 tokens/result
  Layer 2 (search) — FTS5 BM25 fused with importance/recency via RRF, ~60 tokens/result
  Layer 3 (get)    — full observation, ~200 tokens/result

Usage:
    python scripts/lite/memory.py add <text> [--category C] [--title T] [--tags a,b] [--importance 1-10]
    python scripts/lite/memory.py search <query> [--limit N] [--format compact|json]
    python scripts/lite/memory.py index <query> [--limit N]
    python scripts/lite/memory.py get <id>
    python scripts/lite/memory.py list [--category C] [--limit N]
    python scripts/lite/memory.py delete <id>
    python scripts/lite/memory.py stats
    python scripts/lite/memory.py gc [--max-obs N]

Env vars:
    DAINEXUS_PROJECT_ID   project namespace (default: git remote name or cwd name)
    DAINEXUS_MAX_OBS      max observations before GC (default: 200)
    DAINEXUS_NO_REDACT    set to "1" to disable secret redaction (default: on)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

DB_PATH = os.path.join(".dainexus", "memory.db")
MAX_OBS_DEFAULT = 200
RRF_K = 60

REDACT_PATTERNS = [
    r"sk-[a-zA-Z0-9]{20,}",
    r"ghp_[a-zA-Z0-9]{20,}",
    r"key-[a-zA-Z0-9]{20,}",
    r"Bearer\s+[a-zA-Z0-9\-._~+/]+=*",
    r"(?i)password\s*[:=]\s*['\"]?[^\s'\"]{4,}",
    r"(?i)secret\s*[:=]\s*['\"]?[^\s'\"]{4,}",
    r"(?i)token\s*[:=]\s*['\"]?[^\s'\"]{8,}",
    r"postgres://\S+:\S+@",
    r"mysql://\S+:\S+@",
    r"mongodb(\+srv)?://\S+:\S+@",
]

CATEGORY_WEIGHTS = {
    "decisions": 10,
    "architecture": 8,
    "project": 8,
    "blockers": 7,
    "session": 6,
    "tasks": 5,
    "conversation": 4,
    "general": 4,
    "git-activity": 3,
    "ingested": 2,
}

AUTO_TAG_PATTERNS = [
    (
        r"\b(auth|jwt|oauth|token|credential|password|passphrase|secret|api[_-]?key)\b",
        "auth",
    ),
    (
        r"\b(architecture|design|pattern|schema|model|structure|layer|component|module|interface)\b",
        "architecture",
    ),
    (
        r"\b(sql|database|db|postgres|mysql|mongodb|migration|query|index|table)\b",
        "database",
    ),
    (
        r"\b(performance|speed|optimize|cache|benchmark|profiling|latency|throughput)\b",
        "performance",
    ),
    (
        r"\b(api|rest|graphql|webhook|endpoint|http|request|response|integration)\b",
        "api",
    ),
    (
        r"\b(security|vulnerable|exploit|injection|xss|csrf|encryption|hash|encrypt)\b",
        "security",
    ),
    (
        r"\b(test|spec|coverage|unittest|pytest|jest|qa|verification|validation)\b",
        "testing",
    ),
    (
        r"\b(deploy|docker|kubernetes|ci|cd|pipeline|terraform|infrastructure|cloud|aws|gcp)\b",
        "devops",
    ),
    (
        r"\b(memory|checkpoint|retrieval|context|session|conversation|history)\b",
        "memory",
    ),
    (r"\b(plan|scoring|quality|protocol|process|workflow|gate|approval)\b", "process"),
    (
        r"\b(ui|ux|frontend|react|vue|component|style|animation|responsive)\b",
        "frontend",
    ),
    (r"\b(unity|unreal|godot|game|sprite|physics|level|scene)\b", "game"),
    (r"\b(llm|rag|embedding|vector|nlp|model|train|inference)\b", "ai"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_root TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'general',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT DEFAULT '[]',
    importance INTEGER DEFAULT 5 CHECK (importance BETWEEN 1 AND 10),
    access_count INTEGER DEFAULT 0,
    content_hash TEXT NOT NULL,
    source TEXT DEFAULT 'manual',
    pinned INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_at_epoch INTEGER NOT NULL DEFAULT (unixepoch()),
    last_accessed_epoch INTEGER,
    archived INTEGER DEFAULT 0,
    archived_at TEXT,
    UNIQUE(content_hash, project_root)
);

CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(
    title, content, tags,
    content='observations',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS obs_ai AFTER INSERT ON observations BEGIN
    INSERT INTO observations_fts(rowid, title, content, tags)
    VALUES (new.id, new.title, new.content, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS obs_ad AFTER DELETE ON observations BEGIN
    INSERT INTO observations_fts(observations_fts, rowid, title, content, tags)
    VALUES ('delete', old.id, old.title, old.content, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS obs_au AFTER UPDATE OF title, content, tags ON observations BEGIN
    INSERT INTO observations_fts(observations_fts, rowid, title, content, tags)
    VALUES ('delete', old.id, old.title, old.content, old.tags);
    INSERT INTO observations_fts(rowid, title, content, tags)
    VALUES (new.id, new.title, new.content, new.tags);
END;

CREATE INDEX IF NOT EXISTS idx_obs_project ON observations(project_root);
CREATE INDEX IF NOT EXISTS idx_obs_type ON observations(type);
CREATE INDEX IF NOT EXISTS idx_obs_hash ON observations(content_hash, project_root);
CREATE INDEX IF NOT EXISTS idx_obs_epoch ON observations(created_at_epoch DESC);
CREATE INDEX IF NOT EXISTS idx_obs_archived ON observations(archived);
"""


# ── helpers ───────────────────────────────────────────────────────────────────


def get_project_id() -> str:
    pid = os.environ.get("DAINEXUS_PROJECT_ID")
    if pid:
        return pid
    try:
        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        return remote.rstrip("/").split("/")[-1].replace(".git", "")
    except Exception:
        return Path.cwd().name


def redact_secrets(text: str) -> str:
    if os.environ.get("DAINEXUS_NO_REDACT") == "1":
        return text
    for pattern in REDACT_PATTERNS:
        text = re.sub(pattern, "[REDACTED]", text)
    return text


def auto_extract_tags(text: str) -> list[str]:
    found = set()
    text_lower = text.lower()
    for pattern, tag in AUTO_TAG_PATTERNS:
        if re.search(pattern, text_lower):
            found.add(tag)
    return sorted(found)


def make_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def fts_query(query: str) -> str:
    """Sanitize free text into an FTS5 OR-query of word tokens."""
    terms = [t for t in re.findall(r"\w{2,}", query)]
    return " OR ".join(f'"{t}"' for t in terms)


def rrf_merge(*ranked_lists: list, k: int = RRF_K) -> list:
    """Reciprocal Rank Fusion: score = sum(1 / (k + rank)) across lists."""
    scores: dict = {}
    metadata: dict = {}
    for rows in ranked_lists:
        for rank, item in enumerate(rows, start=1):
            oid = item.get("id")
            if oid is None:
                continue
            scores[oid] = scores.get(oid, 0.0) + 1.0 / (k + rank)
            metadata.setdefault(oid, item)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [dict(metadata[oid], rrf=round(s, 5)) for oid, s in ranked]


# ── database ──────────────────────────────────────────────────────────────────


class MemoryDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        conn = self._connect()
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    # ── Layer 1: compact index ────────────────────────────────────────────────

    def memory_index(self, query: str, limit: int = 30) -> list[dict]:
        conn = self._connect()
        try:
            base = """
                SELECT id, type, title, importance, access_count, created_at_epoch
                FROM observations WHERE archived = 0
            """
            params: tuple = ()
            if query.strip():
                base += " AND (title LIKE ? OR content LIKE ?)"
                params = (f"%{query}%", f"%{query}%")
            base += """
                ORDER BY (importance * 0.3) + (MIN(access_count, 5) * 0.3) +
                    (CASE WHEN created_at_epoch > unixepoch() - 604800 THEN 0.4 ELSE 0 END) DESC,
                    created_at_epoch DESC
                LIMIT ?
            """
            rows = conn.execute(base, (*params, limit)).fetchall()
            results = []
            for row in rows:
                score = (row["importance"] * 0.3) + (min(row["access_count"], 5) * 0.3)
                results.append(
                    {
                        "id": row["id"],
                        "type": row["type"],
                        "title": row["title"],
                        "score": round(score, 2),
                    }
                )
            return results
        finally:
            conn.close()

    # ── Layer 2: FTS5 BM25 + RRF fusion ──────────────────────────────────────

    def memory_search(self, query: str, limit: int = 5) -> list[dict]:
        """BM25 ranking fused with the importance/recency index via RRF."""
        conn = self._connect()
        try:
            fts_results: list[dict] = []
            q = fts_query(query)
            if q:
                rows = conn.execute(
                    """
                    SELECT o.id, o.type, o.title, o.content,
                           bm25(observations_fts) AS rank
                    FROM observations_fts f
                    JOIN observations o ON o.id = f.rowid
                    WHERE observations_fts MATCH ? AND o.archived = 0
                    ORDER BY rank LIMIT ?
                    """,
                    (q, limit * 3),
                ).fetchall()
                for row in rows:
                    content = row["content"] or ""
                    fts_results.append(
                        {
                            "id": row["id"],
                            "type": row["type"],
                            "title": row["title"],
                            "summary": content[:200]
                            + ("..." if len(content) > 200 else ""),
                            "bm25": round(row["rank"], 3),
                        }
                    )

            index_results = self.memory_index(query, limit=limit * 3)
            fused = rrf_merge(fts_results, index_results)[:limit]

            # Attach summaries for items that came only from the index list
            for item in fused:
                if "summary" not in item:
                    row = conn.execute(
                        "SELECT content FROM observations WHERE id = ?", (item["id"],)
                    ).fetchone()
                    content = (row["content"] if row else "") or ""
                    item["summary"] = content[:200] + (
                        "..." if len(content) > 200 else ""
                    )

            ids = [item["id"] for item in fused]
            if ids:
                conn.execute(
                    f"UPDATE observations SET access_count = access_count + 1, "
                    f"last_accessed_epoch = unixepoch() "
                    f"WHERE id IN ({','.join('?' * len(ids))})",
                    ids,
                )
                conn.commit()
            return fused
        finally:
            conn.close()

    # ── Layer 3: full detail ─────────────────────────────────────────────────

    def memory_get(self, obs_id: int) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM observations WHERE id = ? AND archived = 0", (obs_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def add(
        self,
        text: str,
        category: str = "general",
        source: str = "manual",
        title: str | None = None,
        tags: list[str] | None = None,
        importance: int = 5,
    ) -> dict:
        text = redact_secrets(text)
        content_hash = make_hash(text)
        project_root = get_project_id()
        if tags is None:
            tags = auto_extract_tags(text)
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT id FROM observations WHERE content_hash = ? AND project_root = ?",
                (content_hash, project_root),
            ).fetchone()
            if existing:
                return {"id": existing["id"], "duplicate": True, "tags": tags}

            cursor = conn.execute(
                """
                INSERT INTO observations
                    (project_root, type, title, content, content_hash, source, tags, importance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_root,
                    category,
                    title or text[:100].replace("\n", " "),
                    text,
                    content_hash,
                    source,
                    json.dumps(tags, ensure_ascii=False),
                    max(1, min(10, importance)),
                ),
            )
            conn.commit()
            return {"id": cursor.lastrowid, "duplicate": False, "tags": tags}
        finally:
            conn.close()

    def list_all(self, category: str | None = None, limit: int = 20) -> list[dict]:
        conn = self._connect()
        try:
            sql = "SELECT id, type, title, source, created_at FROM observations WHERE archived = 0"
            params: list = []
            if category:
                sql += " AND type = ?"
                params.append(category)
            sql += " ORDER BY created_at_epoch DESC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def delete(self, obs_id: int) -> bool:
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE observations SET archived = 1, archived_at = datetime('now') WHERE id = ?",
                (obs_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def count(self) -> int:
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM observations WHERE archived = 0"
            ).fetchone()["c"]
        finally:
            conn.close()

    def stats(self) -> dict:
        conn = self._connect()
        try:
            by_type = {
                r["type"]: r["c"]
                for r in conn.execute(
                    "SELECT type, COUNT(*) AS c FROM observations WHERE archived = 0 GROUP BY type"
                )
            }
            size = (
                Path(self.db_path).stat().st_size if Path(self.db_path).exists() else 0
            )
            return {"total": self.count(), "by_type": by_type, "size_bytes": size}
        finally:
            conn.close()

    # ── value-weighted GC ────────────────────────────────────────────────────

    def gc(self, max_obs: int | None = None) -> int:
        """Archive lowest-value observations: category weight 50% + recency 50%. Pinned survive."""
        max_o = max_obs or int(os.environ.get("DAINEXUS_MAX_OBS", MAX_OBS_DEFAULT))
        total = self.count()
        if total <= max_o:
            return 0
        conn = self._connect()
        try:
            weights = json.dumps(CATEGORY_WEIGHTS)
            rows = conn.execute(
                """
                SELECT id FROM observations
                WHERE archived = 0 AND pinned = 0
                ORDER BY (
                    COALESCE(CAST(json_extract(?, '$.' || type) AS REAL), 3.0) / 10.0 * 0.5 +
                    (1.0 - MIN((unixepoch() - created_at_epoch) / 2592000.0, 1.0)) * 0.5
                ) ASC
                LIMIT ?
                """,
                (weights, total - max_o),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE observations SET archived = 1, archived_at = datetime('now') WHERE id = ?",
                    (row["id"],),
                )
            conn.commit()
            return len(rows)
        finally:
            conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────────


def _utf8_io() -> None:
    """Windows consoles default to a legacy codepage; non-ASCII output would
    crash the tool instead of printing. Force UTF-8 on our own streams."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _utf8_io()
    p = argparse.ArgumentParser(description="DAI Nexus memory (SQLite+FTS5)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("add")
    sp.add_argument("text")
    sp.add_argument("--category", default="general")
    sp.add_argument("--title")
    sp.add_argument("--tags")
    sp.add_argument("--importance", type=int, default=5)

    for name in ("search", "index"):
        sp = sub.add_parser(name)
        sp.add_argument("query")
        sp.add_argument("--limit", type=int, default=5 if name == "search" else 30)
        if name == "search":
            sp.add_argument("--format", choices=["compact", "json"], default="compact")

    sp = sub.add_parser("get")
    sp.add_argument("id", type=int)

    sp = sub.add_parser("list")
    sp.add_argument("--category")
    sp.add_argument("--limit", type=int, default=20)

    sp = sub.add_parser("delete")
    sp.add_argument("id", type=int)

    sub.add_parser("stats")

    sp = sub.add_parser("gc")
    sp.add_argument("--max-obs", type=int)

    args = p.parse_args()
    db = MemoryDB()

    if args.cmd == "add":
        tags = args.tags.split(",") if args.tags else None
        entry = db.add(
            args.text,
            category=args.category,
            title=args.title,
            tags=tags,
            importance=args.importance,
        )
        if entry["duplicate"]:
            print(f"= duplicate [id={entry['id']}]")
        else:
            print(
                f"+ added [id={entry['id']}] ({args.category}, tags={','.join(entry['tags']) or '-'})"
            )
    elif args.cmd == "search":
        results = db.memory_search(args.query, limit=args.limit)
        if args.format == "json":
            print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
        elif not results:
            print("No memories found.")
        else:
            for m in results:
                print(
                    f"  [{m['id']}] ({m['type']}, rrf={m['rrf']}) {m['summary'][:160]}"
                )
    elif args.cmd == "index":
        for r in db.memory_index(args.query, limit=args.limit):
            print(f"  [{r['id']}] {r['type']}: {r['title'][:80]} (score={r['score']})")
    elif args.cmd == "get":
        obs = db.memory_get(args.id)
        print(
            json.dumps(obs, indent=2, ensure_ascii=False, default=str)
            if obs
            else f"Not found: {args.id}"
        )
    elif args.cmd == "list":
        for m in db.list_all(category=args.category, limit=args.limit):
            print(f"  [{m['id']}] [{m['type']}] {m['title'][:120]}")
    elif args.cmd == "delete":
        print("deleted" if db.delete(args.id) else f"Not found: {args.id}")
    elif args.cmd == "stats":
        s = db.stats()
        print(json.dumps(s, indent=2, ensure_ascii=False))
    elif args.cmd == "gc":
        removed = db.gc(max_obs=args.max_obs)
        print(f"GC: archived {removed}, kept {db.count()}")


if __name__ == "__main__":
    main()
