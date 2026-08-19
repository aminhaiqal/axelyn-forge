import sqlite3
import tempfile
import unittest
from pathlib import Path

from forge.context_store import SQLiteContextStore, sync_context_database
from forge.errors import ContextStoreError


class SQLiteContextStoreTests(unittest.TestCase):
    def test_sync_persists_documents_hashes_and_ordered_chunks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = root / "context"
            context.mkdir()
            (context / "candidate.md").write_text(
                "# Candidate\nCore evidence.\n\n## Backend\nPython evidence.",
                encoding="utf-8",
            )
            (context / "policy.md").write_text(
                "# Policy\nNever invent evidence.",
                encoding="utf-8",
            )
            database = root / "context.sqlite3"

            report = sync_context_database(context, database)
            chunks = SQLiteContextStore(database).load_chunks()

            self.assertEqual(2, report.documents)
            self.assertEqual(3, report.chunks)
            self.assertEqual(2, SQLiteContextStore(database).document_count())
            self.assertEqual(
                [
                    "candidate-md--candidate",
                    "candidate-md--candidate-backend",
                    "policy-md--policy",
                ],
                [chunk.chunk_id for chunk in chunks],
            )
            with sqlite3.connect(database) as connection:
                document = connection.execute(
                    "SELECT content_sha256, content_length FROM context_documents "
                    "WHERE source = 'candidate.md'"
                ).fetchone()
                stored_chunk = connection.execute(
                    "SELECT content_sha256 FROM context_chunks "
                    "WHERE chunk_id = 'candidate-md--candidate-backend'"
                ).fetchone()
            self.assertEqual(64, len(document[0]))
            self.assertGreater(document[1], 0)
            self.assertEqual(64, len(stored_chunk[0]))

    def test_resync_atomically_replaces_stale_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first"
            first.mkdir()
            (first / "one.md").write_text("# One\nFirst.", encoding="utf-8")
            (first / "two.md").write_text("# Two\nSecond.", encoding="utf-8")
            second = root / "second"
            second.mkdir()
            (second / "current.md").write_text("# Current\nCurrent evidence.", encoding="utf-8")
            database = root / "context.sqlite3"

            sync_context_database(first, database)
            sync_context_database(second, database)
            chunks = SQLiteContextStore(database).load_chunks()

            self.assertEqual(1, SQLiteContextStore(database).document_count())
            self.assertEqual(["current-md--current"], [chunk.chunk_id for chunk in chunks])

    def test_missing_database_fails_without_creating_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "missing.sqlite3"
            with self.assertRaisesRegex(ContextStoreError, "does not exist"):
                SQLiteContextStore(database).load_chunks()
            self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
