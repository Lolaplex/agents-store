"""Schema v5: WriteRefusal.reason kebab -> snake, idempotent one-shot."""
from __future__ import annotations

import os
import tempfile
import unittest

from agents_store import connect
from agents_store.db import SCHEMA_VERSION, _migrate_v5
from agents_store.store import Store


class TestRefusalReasonMigrate(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(os.remove, self.path)

    def _seed_kebab_db(self):
        """Fresh DB then rewind to v4 with kebab reason rows (bypass trigger)."""
        conn = connect(self.path)
        # Drop append-only update trigger to plant pre-v5 rows, then rewind.
        conn.execute("DROP TRIGGER IF EXISTS refusal_no_update")
        conn.execute("DELETE FROM refusal")
        conn.executemany(
            "INSERT INTO refusal (wrapper, entity, attr, reason, payload) VALUES (?,?,?,?,?)",
            [
                ("md", "e1", None, "parse-fail", "x"),
                ("ical", "e2", "when", "tz-unsupported", "Z"),
                ("store", "e3", "body", "no-grant", None),
                ("pane", "e4", "html", "no-capability-path", None),
                ("ical", "e5", "title", "out-of-projection", None),
                ("store", "e6", "end", "derived-attr", None),
                ("store", "e7", "x", "mediator-conflict", None),
                # already-snake / unknown: must survive untouched
                ("t", "e8", None, "parse_fail", "already"),
                ("t", "e9", None, "custom-reason", "keep"),
            ],
        )
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS refusal_no_update BEFORE UPDATE ON refusal "
            "BEGIN SELECT RAISE(ABORT, 'refusal is append-only'); END"
        )
        conn.execute("PRAGMA user_version = 4")
        conn.close()

    def test_connect_rewrites_kebab_reasons(self):
        self._seed_kebab_db()
        conn = connect(self.path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertGreaterEqual(SCHEMA_VERSION, 5)
        rows = {
            (r[0], r[1])
            for r in conn.execute("SELECT entity, reason FROM refusal ORDER BY id")
        }
        self.assertEqual(
            rows,
            {
                ("e1", "parse_fail"),
                ("e2", "tz_unsupported"),
                ("e3", "no_grant"),
                ("e4", "no_capability_path"),
                ("e5", "out_of_projection"),
                ("e6", "derived_attr"),
                ("e7", "mediator_conflict"),
                ("e8", "parse_fail"),
                ("e9", "custom-reason"),
            },
        )
        # append-only restored
        with self.assertRaises(Exception):
            conn.execute("UPDATE refusal SET reason = 'x' WHERE entity = 'e1'")

    def test_migrate_is_idempotent(self):
        self._seed_kebab_db()
        conn = connect(self.path)
        self.addCleanup(conn.close)
        before = conn.execute("SELECT id, reason FROM refusal ORDER BY id").fetchall()
        # Force re-entry path: call migrate body again after rewind would no-op
        # because user_version is already 5. Call the function directly after
        # planting a stray kebab with trigger down to prove second pass is safe
        # when version gate is satisfied.
        _migrate_v5(conn)  # early return
        after = conn.execute("SELECT id, reason FROM refusal ORDER BY id").fetchall()
        self.assertEqual(before, after)
        # Explicit second rewrite with version forced back still yields snake.
        conn.execute("DROP TRIGGER IF EXISTS refusal_no_update")
        conn.execute(
            "INSERT INTO refusal (wrapper, entity, attr, reason, payload) "
            "VALUES ('md','e10',NULL,'parse-fail','again')"
        )
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS refusal_no_update BEFORE UPDATE ON refusal "
            "BEGIN SELECT RAISE(ABORT, 'refusal is append-only'); END"
        )
        conn.execute("PRAGMA user_version = 4")
        _migrate_v5(conn)
        self.assertEqual(
            conn.execute(
                "SELECT reason FROM refusal WHERE entity = 'e10'"
            ).fetchone()[0],
            "parse_fail",
        )
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 5)

    def test_new_refusals_use_snake(self):
        conn = connect(self.path)
        self.addCleanup(conn.close)
        store = Store(conn)
        store.record_refusal(
            __import__("agents_store", fromlist=["WriteRefusal"]).WriteRefusal(
                wrapper="md", reason="parse_fail", e="n1"
            )
        )
        self.assertEqual(
            conn.execute("SELECT reason FROM refusal WHERE entity='n1'").fetchone()[0],
            "parse_fail",
        )


if __name__ == "__main__":
    unittest.main()
