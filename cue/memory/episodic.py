"""Episodic Memory — SQLite-backed episode storage with 90-day TTL."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

from cue.types import EpisodeRecord


class EpisodicMemory:
    """Stores and retrieves past episodes using SQLite."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    app TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    total_steps INTEGER NOT NULL,
                    steps_summary TEXT NOT NULL,
                    failure_patterns TEXT NOT NULL,
                    recovery_strategies TEXT NOT NULL,
                    reflection TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    embedding TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_app ON episodes(app)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodes_created_at ON episodes(created_at)"
            )
            conn.commit()

    async def store(self, record: EpisodeRecord) -> None:
        """Insert or replace an episode record."""
        await asyncio.to_thread(self._store_sync, record)

    def _store_sync(self, record: EpisodeRecord) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO episodes
                (id, task, app, success, total_steps, steps_summary,
                 failure_patterns, recovery_strategies, reflection, created_at, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.task,
                    record.app,
                    int(record.success),
                    record.total_steps,
                    record.steps_summary,
                    json.dumps(record.failure_patterns),
                    json.dumps(record.recovery_strategies),
                    record.reflection,
                    record.created_at,
                    json.dumps(record.embedding) if record.embedding is not None else None,
                ),
            )
            conn.commit()

    async def find_similar(
        self, task: str, app: str, top_k: int = 3
    ) -> list[EpisodeRecord]:
        """Find episodes for the same app, ranked by text similarity."""
        return await asyncio.to_thread(self._find_similar_sync, task, app, top_k)

    def _find_similar_sync(
        self, task: str, app: str, top_k: int
    ) -> list[EpisodeRecord]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM episodes WHERE app = ? ORDER BY created_at DESC LIMIT 50",
                (app,),
            ).fetchall()

        if not rows:
            return []

        scored: list[tuple[float, EpisodeRecord]] = []
        for row in rows:
            record = self._row_to_record(row)
            sim = self._text_similarity(task, record.task)
            scored.append((sim, record))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [rec for _, rec in scored[:top_k]]

    async def cleanup(self, max_age_days: int = 90) -> None:
        """Delete episodes older than max_age_days."""
        await asyncio.to_thread(self._cleanup_sync, max_age_days)

    def _cleanup_sync(self, max_age_days: int) -> None:
        cutoff = time.time() - max_age_days * 86400
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM episodes WHERE created_at < ?", (cutoff,))
            conn.commit()

    def _text_similarity(self, text1: str, text2: str) -> float:
        """Jaccard similarity on word sets."""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union)

    def _row_to_record(self, row: sqlite3.Row) -> EpisodeRecord:
        embedding_raw = row["embedding"]
        embedding = json.loads(embedding_raw) if embedding_raw else None
        return EpisodeRecord(
            id=row["id"],
            task=row["task"],
            app=row["app"],
            success=bool(row["success"]),
            total_steps=row["total_steps"],
            steps_summary=row["steps_summary"],
            failure_patterns=json.loads(row["failure_patterns"]),
            recovery_strategies=json.loads(row["recovery_strategies"]),
            reflection=row["reflection"],
            created_at=row["created_at"],
            embedding=embedding,
        )
