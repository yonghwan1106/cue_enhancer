"""Latency Optimizer — TTL-based result cache to skip redundant grounding calls."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass
class CacheEntry:
    """Single cached result with its creation timestamp."""

    result: Any
    timestamp: float


class LatencyOptimizer:
    """Cache async computations with a configurable TTL.

    Usage::

        optimizer = LatencyOptimizer(cache_ttl=2.0)
        result = await optimizer.get_or_compute("key", compute_fn)
    """

    def __init__(self, cache_ttl: float = 2.0) -> None:
        self._ttl = cache_ttl
        self._cache: dict[str, CacheEntry] = {}
        self._hits = 0
        self._misses = 0

    async def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Return a cached result if still fresh, else compute and cache it."""
        self._cleanup()

        entry = self._cache.get(key)
        if entry is not None and (time.monotonic() - entry.timestamp) < self._ttl:
            self._hits += 1
            return entry.result

        self._misses += 1
        result = await compute_fn()
        self._cache[key] = CacheEntry(result=result, timestamp=time.monotonic())
        return result

    def _cleanup(self) -> None:
        """Remove all entries whose TTL has expired."""
        now = time.monotonic()
        expired = [k for k, v in self._cache.items() if now - v.timestamp >= self._ttl]
        for k in expired:
            del self._cache[k]

    @property
    def hit_rate(self) -> float:
        """Fraction of requests served from cache (0.0–1.0)."""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def invalidate(self) -> None:
        """Clear the entire cache and reset statistics."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
