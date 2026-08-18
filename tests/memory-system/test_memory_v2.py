#!/usr/bin/env python3
"""
test_memory_v2.py — Tests for scripts/lite/memory.py core functionality
Specifically: search fix (multi-word), auto-tagging, adaptive ranking
"""

import sys
import os
import re
import subprocess
import tempfile
import unittest
import importlib.util
from pathlib import Path

# Load scripts/lite/memory.py by path (filename has hyphen, can't be imported directly)
# Repo root. The previous name said `scripts` *and* the joins below added
# "scripts/..." again, producing scripts/scripts/lite/memory.py — a path that
# has never existed, so this file failed at import and never ran.
ROOT = Path(__file__).parent.parent.parent
MEMORY_CLI = ROOT / "scripts" / "lite" / "memory.py"
_spec = importlib.util.spec_from_file_location(
    "memory_v2", ROOT / "scripts/lite/memory.py"
)
_memory_module = importlib.util.module_from_spec(_spec)
sys.modules["memory_v2"] = _memory_module
_spec.loader.exec_module(_memory_module)


class TestAutoTagging(unittest.TestCase):
    """Tests for AUTO_TAG_PATTERNS auto-tagging."""

    def test_auth_tag(self):
        from memory_v2 import auto_extract_tags

        text = "JWT authentication middleware with token validation"
        tags = auto_extract_tags(text)
        self.assertIn("auth", tags)
        self.assertIn("testing", tags)

    def test_architecture_tag(self):
        from memory_v2 import auto_extract_tags

        text = "Architecture redesign using microservices pattern"
        tags = auto_extract_tags(text)
        self.assertIn("architecture", tags)

    def test_database_tag(self):
        from memory_v2 import auto_extract_tags

        text = "PostgreSQL database migration with query optimization"
        tags = auto_extract_tags(text)
        self.assertIn("database", tags)

    def test_performance_tag(self):
        from memory_v2 import auto_extract_tags

        text = "Performance optimization with Redis caching"
        tags = auto_extract_tags(text)
        self.assertIn("performance", tags)

    def test_api_tag(self):
        from memory_v2 import auto_extract_tags

        text = "REST API endpoint with GraphQL wrapper"
        tags = auto_extract_tags(text)
        self.assertIn("api", tags)

    def test_security_tag(self):
        from memory_v2 import auto_extract_tags

        text = "SQL injection vulnerability fixed"
        tags = auto_extract_tags(text)
        self.assertIn("security", tags)

    def test_multiple_tags(self):
        from memory_v2 import auto_extract_tags

        text = "JWT auth with PostgreSQL database and Redis cache"
        tags = auto_extract_tags(text)
        self.assertGreaterEqual(len(tags), 3)

    def test_empty_text(self):
        from memory_v2 import auto_extract_tags

        tags = auto_extract_tags("")
        self.assertEqual(tags, [])

    def test_no_match(self):
        from memory_v2 import auto_extract_tags

        tags = auto_extract_tags("This is a random sentence with no keywords")
        self.assertEqual(tags, [])

    def test_case_insensitive(self):
        from memory_v2 import auto_extract_tags

        text = "JWT AUTHENTICATION with DATABASE"
        tags = auto_extract_tags(text)
        self.assertIn("auth", tags)
        self.assertIn("database", tags)


class TestSearchMultiWord(unittest.TestCase):
    """Tests for multi-word search query splitting."""

    def setUp(self):
        import tempfile

        tmpdir = tempfile.mkdtemp()
        os.environ["MEM0_DB_PATH"] = os.path.join(tmpdir, "memory.db")
        _spec = importlib.util.spec_from_file_location(
            "m", ROOT / "scripts/lite/memory.py"
        )
        _m = importlib.util.module_from_spec(_spec)
        sys.modules["memory_v2"] = _m
        _spec.loader.exec_module(_m)
        self.db = _m.MemoryDB(os.path.join(tmpdir, "memory.db"))

    def test_single_word_search(self):
        self.db.add("Testing the memory system", category="general")
        results = self.db.memory_search("memory", limit=5)
        self.assertGreater(len(results), 0)

    def test_multi_word_search_finds_partial(self):
        self.db.add("JWT authentication system", category="security")
        results = self.db.memory_search("JWT authentication", limit=5)
        self.assertGreater(len(results), 0)

    def test_multi_word_search_matches_any_term(self):
        self.db.add("Memory checkpoint system", category="session")
        self.db.add("Cache optimization", category="performance")
        results = self.db.memory_search("memory optimization", limit=5)
        self.assertGreaterEqual(len(results), 1)

    def test_search_with_numbers(self):
        self.db.add("Memory v2 system", category="general")
        results = self.db.memory_search("memory v2", limit=5)
        self.assertGreaterEqual(len(results), 1)

    def test_empty_query_returns_empty(self):
        results = self.db.memory_search("", limit=5)
        self.assertEqual(results, [])

    def test_search_limit_respected(self):
        for i in range(10):
            self.db.add(f"Test observation {i}", category="general")
        results = self.db.memory_search("test observation", limit=3)
        self.assertLessEqual(len(results), 3)

    def test_archived_excluded(self):
        self.db.add("This should be found", category="general")
        obs_id = self.db.add("This should be excluded", category="general")["id"]
        self.db.delete(obs_id)
        results = self.db.memory_search("should", limit=5)
        ids = [r["id"] for r in results]
        self.assertNotIn(obs_id, ids)

    def test_search_ranking(self):
        self.db.add(
            "Memory system architecture decision", category="decisions", importance=10
        )
        self.db.add("Memory system simple note", category="general", importance=3)
        results = self.db.memory_search("memory system", limit=5)
        if len(results) >= 2:
            high_imp = next((r for r in results if r["id"] == 1), None)
            self.assertIsNotNone(high_imp)

    def test_multi_word_search_checks_each_term_against_title_and_content(self):
        self.db.add("Unrelated content", category="general", title="khách hàng")
        results = self.db.memory_search("tiếng khách", limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "khách hàng")


class TestVietnameseMemoryOutput(unittest.TestCase):
    """CLI output must keep Vietnamese text readable, not backslash-u escapes.

    The upstream version reached into module-level cmd_search/cmd_get helpers.
    This build dispatches through argparse and has no such functions, so the
    property is checked where it actually matters: by running the CLI. That also
    survives any future refactor of the internals.
    """

    def _run(self, tmp, *args):
        return subprocess.run(
            [sys.executable, str(MEMORY_CLI), *args],
            cwd=tmp,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )

    def test_search_output_preserves_vietnamese_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".dainexus").mkdir()
            added = self._run(tmp, "add", "ghi chú bằng tiếng Việt có dấu")
            self.assertEqual(added.returncode, 0, added.stderr)
            found = self._run(tmp, "search", "tiếng Việt", "--format", "json")
            self.assertEqual(found.returncode, 0, found.stderr)
            self.assertIn("tiếng Việt", found.stdout)
            self.assertNotIn("\\u", found.stdout)

    def test_get_output_preserves_vietnamese_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".dainexus").mkdir()
            added = self._run(tmp, "add", "quyết định lưu bằng tiếng Việt")
            self.assertEqual(added.returncode, 0, added.stderr)
            # `add` prints a human line, not JSON: `+ added [id=1] (...)`.
            obs_id = re.search(r"id=(\d+)", added.stdout).group(1)
            got = self._run(tmp, "get", str(obs_id))
            self.assertEqual(got.returncode, 0, got.stderr)
            self.assertIn("tiếng Việt", got.stdout)
            self.assertNotIn("\\u", got.stdout)


class TestAddWithImportance(unittest.TestCase):
    """Tests for add() with importance parameter."""

    def setUp(self):
        import tempfile

        tmpdir = tempfile.mkdtemp()
        _spec = importlib.util.spec_from_file_location(
            "m", ROOT / "scripts/lite/memory.py"
        )
        _m = importlib.util.module_from_spec(_spec)
        sys.modules["memory_v2"] = _m
        _spec.loader.exec_module(_m)
        self.db = _m.MemoryDB(os.path.join(tmpdir, "memory.db"))

    def test_add_with_default_importance(self):
        result = self.db.add("Test memory", category="general")
        self.assertIn("id", result)
        self.assertFalse(result.get("duplicate", False))

    def test_add_with_custom_importance(self):
        result = self.db.add("High priority", category="decisions", importance=10)
        self.assertIn("id", result)

    def test_add_importance_stored(self):
        # importance is stored in db (clamping happens in cmd_add, not db.add)
        result = self.db.add("Test", category="general", importance=8)
        self.assertIn("id", result)

    def test_duplicate_returns_existing_id(self):
        text = "Duplicate test"
        r1 = self.db.add(text, category="general")
        r2 = self.db.add(text, category="general")
        self.assertEqual(r1["id"], r2["id"])
        self.assertTrue(r2.get("duplicate", False))


class TestRedaction(unittest.TestCase):
    """Tests for secret redaction."""

    def test_redacts_api_key(self):
        from memory_v2 import redact_secrets

        text = "API key: sk-1234567890abcdefghijklmn"
        redacted = redact_secrets(text)
        self.assertNotIn("sk-1234567890abcdefghijklmn", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_redacts_bearer_token(self):
        from memory_v2 import redact_secrets

        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9"
        redacted = redact_secrets(text)
        self.assertNotIn("Bearer eyJ", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_redacts_password(self):
        from memory_v2 import redact_secrets

        text = "password=supersecret123"
        redacted = redact_secrets(text)
        self.assertNotIn("supersecret123", redacted)

    def test_redacts_postgres_connection(self):
        from memory_v2 import redact_secrets

        text = "postgres://user:password123@localhost/db"
        redacted = redact_secrets(text)
        self.assertNotIn("password123", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_preserves_normal_text(self):
        from memory_v2 import redact_secrets

        text = "This is a normal sentence about authentication"
        redacted = redact_secrets(text)
        self.assertEqual(text, redacted)


class TestGC(unittest.TestCase):
    """Tests for garbage collection."""

    def setUp(self):
        import tempfile

        tmpdir = tempfile.mkdtemp()
        _spec = importlib.util.spec_from_file_location(
            "m", ROOT / "scripts/lite/memory.py"
        )
        _m = importlib.util.module_from_spec(_spec)
        sys.modules["memory_v2"] = _m
        _spec.loader.exec_module(_m)
        self.db = _m.MemoryDB(os.path.join(tmpdir, "gc_test.db"))

    def test_gc_does_nothing_under_limit(self):
        for i in range(5):
            self.db.add(f"Memory {i}", category="general")
        removed = self.db.gc(max_obs=10)
        self.assertEqual(removed, 0)

    def test_gc_removes_over_limit(self):
        for i in range(15):
            self.db.add(f"Memory {i}", category="general")
        removed = self.db.gc(max_obs=5)
        self.assertEqual(removed, 10)


# The graph layer (nodes, edges, procedural circuits) is not part of this
# build: scripts/lite/memory.py is the distilled FTS5+RRF store. The
# upstream TestProceduralCircuits class was removed here rather than left
# asserting against methods MemoryDB does not define.

if __name__ == "__main__":
    unittest.main(verbosity=2)
