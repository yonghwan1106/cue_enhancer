"""Semantic Memory — permanent lesson storage using SQLite."""

from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid
from pathlib import Path

from cue.types import Lesson


class SemanticMemory:
    """Stores and retrieves generalized lessons across episodes."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lessons (
                    id TEXT PRIMARY KEY,
                    app TEXT NOT NULL,
                    situation TEXT NOT NULL,
                    failed_approach TEXT NOT NULL,
                    successful_approach TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    success_count INTEGER NOT NULL,
                    failure_count INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    last_used REAL NOT NULL,
                    task_context TEXT NOT NULL,
                    text TEXT NOT NULL,
                    reinforcement_count INTEGER NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lessons_app ON lessons(app)")
            conn.commit()

    async def recall(
        self, task: str, app: str, top_k: int = 5
    ) -> list[Lesson]:
        """Find lessons for the given app ordered by confidence."""
        return await asyncio.to_thread(self._recall_sync, task, app, top_k)

    def _recall_sync(self, task: str, app: str, top_k: int) -> list[Lesson]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM lessons
                WHERE app = ?
                ORDER BY confidence DESC, last_used DESC
                LIMIT ?
                """,
                (app, top_k),
            ).fetchall()
        lessons = [self._row_to_lesson(row) for row in rows]
        # Update last_used timestamps
        now = time.time()
        ids = [l.id for l in lessons]
        if ids:
            self._update_last_used(ids, now)
        return lessons

    def _update_last_used(self, ids: list[str], now: float) -> None:
        placeholders = ",".join("?" * len(ids))
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                f"UPDATE lessons SET last_used = ? WHERE id IN ({placeholders})",
                [now, *ids],
            )
            conn.commit()

    async def upsert(self, lesson: Lesson) -> None:
        """Insert lesson, or update confidence if same app+situation exists."""
        await asyncio.to_thread(self._upsert_sync, lesson)

    def _upsert_sync(self, lesson: Lesson) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                "SELECT id, confidence, success_count, failure_count, reinforcement_count "
                "FROM lessons WHERE app = ? AND situation = ?",
                (lesson.app, lesson.situation),
            ).fetchone()

            now = time.time()
            if existing:
                new_confidence = min(
                    1.0,
                    existing["confidence"]
                    + (lesson.confidence - existing["confidence"]) * 0.3,
                )
                conn.execute(
                    """
                    UPDATE lessons SET
                        confidence = ?,
                        success_count = success_count + ?,
                        failure_count = failure_count + ?,
                        reinforcement_count = reinforcement_count + 1,
                        last_used = ?,
                        successful_approach = ?,
                        text = ?
                    WHERE id = ?
                    """,
                    (
                        new_confidence,
                        lesson.success_count,
                        lesson.failure_count,
                        now,
                        lesson.successful_approach,
                        lesson.text,
                        existing["id"],
                    ),
                )
            else:
                lesson_id = lesson.id or str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO lessons
                    (id, app, situation, failed_approach, successful_approach,
                     confidence, success_count, failure_count, created_at, last_used,
                     task_context, text, reinforcement_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lesson_id,
                        lesson.app,
                        lesson.situation,
                        lesson.failed_approach,
                        lesson.successful_approach,
                        lesson.confidence,
                        lesson.success_count,
                        lesson.failure_count,
                        lesson.created_at or now,
                        lesson.last_used or now,
                        lesson.task_context,
                        lesson.text,
                        lesson.reinforcement_count,
                    ),
                )
            conn.commit()

    def _row_to_lesson(self, row: sqlite3.Row) -> Lesson:
        return Lesson(
            id=row["id"],
            app=row["app"],
            situation=row["situation"],
            failed_approach=row["failed_approach"],
            successful_approach=row["successful_approach"],
            confidence=row["confidence"],
            success_count=row["success_count"],
            failure_count=row["failure_count"],
            created_at=row["created_at"],
            last_used=row["last_used"],
            task_context=row["task_context"],
            text=row["text"],
            reinforcement_count=row["reinforcement_count"],
        )
