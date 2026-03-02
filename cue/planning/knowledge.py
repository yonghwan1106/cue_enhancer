"""App Knowledge Base — loads YAML knowledge files and provides lookup helpers."""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ─── Domain Types ──────────────────────────────────────────────────────────────


@dataclass
class Shortcut:
    """A keyboard shortcut entry."""

    action: str
    keys: str
    reliability: float = 1.0  # 0.0–1.0; lower if OS/version-dependent


@dataclass
class Pitfall:
    """A known pitfall and the preferred alternative."""

    situation: str
    avoid: str
    instead: str


@dataclass
class DirectNavigation:
    """A direct navigation method (faster than menu traversal)."""

    target: str
    method: str  # e.g. "Ctrl+L then type URL", "Name Box then Enter"
    notes: str = ""


@dataclass
class AppKnowledge:
    """All structured knowledge for one application."""

    app_name: str
    shortcuts: list[Shortcut] = field(default_factory=list)
    pitfalls: list[Pitfall] = field(default_factory=list)
    common_tasks: list[dict[str, Any]] = field(default_factory=list)
    navigation: list[DirectNavigation] = field(default_factory=list)


# ─── Knowledge Base ────────────────────────────────────────────────────────────


class AppKnowledgeBase:
    """Loads YAML knowledge files and exposes lookup helpers."""

    def __init__(self) -> None:
        self._store: dict[str, AppKnowledge] = {}  # lower-case app_name -> AppKnowledge

    # ── Loading ───────────────────────────────────────────────────────────────

    def load_all(self, directory: str | Path) -> None:
        """Load every .yaml file found under *directory*."""
        directory = Path(directory)
        if not directory.exists():
            logger.warning("Knowledge directory does not exist: %s", directory)
            return
        for path in directory.glob("*.yaml"):
            self._load_file(path)

    def _load_file(self, path: Path) -> None:
        """Parse a single YAML knowledge file and store it."""
        try:
            with open(path, encoding="utf-8") as fh:
                data: dict[str, Any] = yaml.safe_load(fh) or {}
        except Exception:
            logger.exception("Failed to load knowledge file: %s", path)
            return

        app_name: str = data.get("app_name", path.stem)
        knowledge = AppKnowledge(app_name=app_name)

        for raw in data.get("shortcuts", []):
            knowledge.shortcuts.append(
                Shortcut(
                    action=raw.get("action", ""),
                    keys=raw.get("keys", ""),
                    reliability=float(raw.get("reliability", 1.0)),
                )
            )

        for raw in data.get("pitfalls", []):
            knowledge.pitfalls.append(
                Pitfall(
                    situation=raw.get("situation", ""),
                    avoid=raw.get("avoid", ""),
                    instead=raw.get("instead", ""),
                )
            )

        for raw in data.get("navigation", []):
            knowledge.navigation.append(
                DirectNavigation(
                    target=raw.get("target", ""),
                    method=raw.get("method", ""),
                    notes=raw.get("notes", ""),
                )
            )

        knowledge.common_tasks = data.get("common_tasks", [])

        self._store[app_name.lower()] = knowledge
        logger.debug("Loaded knowledge for: %s (%d shortcuts)", app_name, len(knowledge.shortcuts))

    # ── Lookup Helpers ────────────────────────────────────────────────────────

    def get_knowledge(self, app_name: str) -> AppKnowledge | None:
        """Return knowledge for *app_name*, using fuzzy matching as fallback."""
        key = app_name.lower()

        # Exact match first.
        if key in self._store:
            return self._store[key]

        # Substring match (e.g. "firefox" inside "mozilla firefox").
        for stored_key, knowledge in self._store.items():
            if key in stored_key or stored_key in key:
                return knowledge

        # Fuzzy match via difflib.
        candidates = list(self._store.keys())
        matches = difflib.get_close_matches(key, candidates, n=1, cutoff=0.5)
        if matches:
            return self._store[matches[0]]

        return None

    def find_shortcut(self, app: str, action_description: str) -> Shortcut | None:
        """Return the best matching shortcut for *action_description* in *app*.

        Matches by tokenising the action description and looking for overlap
        with each shortcut's action string.
        """
        knowledge = self.get_knowledge(app)
        if knowledge is None:
            return None

        query_tokens = set(_tokenise(action_description))
        best: Shortcut | None = None
        best_score = 0.0

        for shortcut in knowledge.shortcuts:
            shortcut_tokens = set(_tokenise(shortcut.action))
            overlap = query_tokens & shortcut_tokens
            if not overlap:
                continue
            # Score = Jaccard * reliability weight.
            jaccard = len(overlap) / len(query_tokens | shortcut_tokens)
            score = jaccard * shortcut.reliability
            if score > best_score:
                best_score = score
                best = shortcut

        return best

    def find_direct_navigation(self, app: str, target: str) -> DirectNavigation | None:
        """Return a direct navigation method for reaching *target* in *app*."""
        knowledge = self.get_knowledge(app)
        if knowledge is None:
            return None

        target_lower = target.lower()
        target_tokens = set(_tokenise(target))
        best: DirectNavigation | None = None
        best_score = 0.0

        for nav in knowledge.navigation:
            nav_tokens = set(_tokenise(nav.target))
            if target_lower in nav.target.lower() or nav.target.lower() in target_lower:
                return nav  # Direct substring hit — return immediately.
            overlap = target_tokens & nav_tokens
            if overlap:
                score = len(overlap) / len(target_tokens | nav_tokens)
                if score > best_score:
                    best_score = score
                    best = nav

        return best

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def loaded_apps(self) -> list[str]:
        """Return list of loaded application names."""
        return [k.app_name for k in self._store.values()]


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _tokenise(text: str) -> list[str]:
    """Split text into lowercase word tokens, stripping punctuation."""
    import re
    return re.findall(r"[a-z0-9]+", text.lower())
