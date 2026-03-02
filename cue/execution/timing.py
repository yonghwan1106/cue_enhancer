"""Timing controller: wait for UI to stabilise before executing actions."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable

import numpy as np

from cue.types import StabilityResult

POLL_INTERVAL_MS = 100
STABILITY_THRESHOLD = 0.005
STABILITY_TIMEOUT_MS = 3000
STABLE_FRAMES_REQUIRED = 2


@dataclass
class AppTimingProfile:
    """Learned render-time profile for a specific application."""

    avg_render_time_ms: float = 0.0
    sample_count: int = 0


class TimingController:
    """Polls screenshots until consecutive frames are visually stable.

    Uses mean absolute pixel difference (fast proxy for SSIM) to detect
    when the UI has stopped rendering.
    """

    def __init__(self) -> None:
        # Maps app_name -> learned profile.
        self._profiles: dict[str, AppTimingProfile] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    async def wait_for_stable_ui(
        self,
        screenshot_fn: Callable[[], Awaitable[np.ndarray]],
        timeout_ms: int = STABILITY_TIMEOUT_MS,
        app_name: str | None = None,
    ) -> StabilityResult:
        """Poll *screenshot_fn* until the UI is stable or *timeout_ms* elapses.

        Returns a :class:`StabilityResult` describing the outcome.
        """
        start = time.monotonic()
        deadline = start + timeout_ms / 1000.0
        poll_s = POLL_INTERVAL_MS / 1000.0

        prev_frame: np.ndarray | None = None
        stable_streak = 0
        frames_checked = 0
        last_diff = 0.0

        while time.monotonic() < deadline:
            frame = await screenshot_fn()
            frames_checked += 1

            if prev_frame is not None and prev_frame.shape == frame.shape:
                diff = float(np.mean(np.abs(frame.astype(np.float32) - prev_frame.astype(np.float32))) / 255.0)
                last_diff = diff

                if diff < STABILITY_THRESHOLD:
                    stable_streak += 1
                else:
                    stable_streak = 0

                if stable_streak >= STABLE_FRAMES_REQUIRED:
                    elapsed_ms = (time.monotonic() - start) * 1000.0
                    if app_name:
                        self._update_profile(app_name, elapsed_ms)
                    return StabilityResult(
                        is_stable=True,
                        wait_duration_ms=elapsed_ms,
                        final_diff=last_diff,
                        frames_checked=frames_checked,
                    )
            else:
                # First frame or shape mismatch – reset streak.
                stable_streak = 0

            prev_frame = frame
            await asyncio.sleep(poll_s)

        elapsed_ms = (time.monotonic() - start) * 1000.0
        return StabilityResult(
            is_stable=False,
            wait_duration_ms=elapsed_ms,
            final_diff=last_diff,
            frames_checked=frames_checked,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _update_profile(self, app_name: str, render_time_ms: float) -> None:
        """Update the exponential moving average for *app_name*."""
        if app_name not in self._profiles:
            self._profiles[app_name] = AppTimingProfile(
                avg_render_time_ms=render_time_ms, sample_count=1
            )
            return

        profile = self._profiles[app_name]
        n = profile.sample_count + 1
        alpha = min(0.3, 2.0 / (n + 1))
        profile.avg_render_time_ms = (
            alpha * render_time_ms + (1.0 - alpha) * profile.avg_render_time_ms
        )
        profile.sample_count = n

    def get_profile(self, app_name: str) -> AppTimingProfile | None:
        """Return the learned timing profile for *app_name*, or None."""
        return self._profiles.get(app_name)
