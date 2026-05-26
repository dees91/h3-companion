#!/usr/bin/env python3
"""Agent-facing MCP advisor helpers for H3 Companion."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

try:
    from tools import battle_estimator_gui, h3_save_parser
except ImportError:  # pragma: no cover - direct script execution fallback.
    import battle_estimator_gui
    import h3_save_parser


@dataclass(frozen=True)
class AdvisorContextMetadata:
    """Small read-only summary for the cached advisor domain snapshot."""

    mode: str
    autosave_dir: str
    save_file: str
    save_name: str
    save_fingerprint: dict[str, Any]
    map_file: str
    map_name: str
    map_fingerprint: dict[str, Any]
    loaded_at: str
    hero_count: int
    neutral_target_count: int
    town_count: int
    portal_count: int

    @classmethod
    def from_domain_snapshot(
        cls,
        domain_snapshot: battle_estimator_gui.DomainSnapshot,
    ) -> "AdvisorContextMetadata":
        state = domain_snapshot.state
        save_file = Path(state["save_file"])
        map_file = Path(state["map_file"])
        return cls(
            mode=state["mode"],
            autosave_dir=state["autosave_dir"],
            save_file=str(save_file),
            save_name=save_file.name,
            save_fingerprint=copy.deepcopy(state["save_fingerprint"]),
            map_file=str(map_file),
            map_name=map_file.name,
            map_fingerprint=copy.deepcopy(state["map_fingerprint"]),
            loaded_at=datetime.now(timezone.utc).isoformat(),
            hero_count=len(state.get("heroes", ())),
            neutral_target_count=len(state.get("neutral_targets", ())),
            town_count=len(state.get("town_targets", ())),
            portal_count=len(state.get("portal_targets", ())),
        )

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy({
            "mode": self.mode,
            "autosave_dir": self.autosave_dir,
            "save_file": self.save_file,
            "save_name": self.save_name,
            "save_fingerprint": self.save_fingerprint,
            "map_file": self.map_file,
            "map_name": self.map_name,
            "map_fingerprint": self.map_fingerprint,
            "loaded_at": self.loaded_at,
            "hero_count": self.hero_count,
            "neutral_target_count": self.neutral_target_count,
            "town_count": self.town_count,
            "portal_count": self.portal_count,
        })


class AdvisorContextService:
    """Read-only loader/cache for advisor domain snapshots."""

    def __init__(
        self,
        *,
        mode: str | None = None,
        game_dir: str | Path | None = None,
        save_file: str | Path | None = None,
        map_file: str | Path | None = None,
        config_path: str | Path = h3_save_parser.CONFIG_PATH,
    ) -> None:
        self.mode = _resolve_context_mode(mode, save_file)
        self.game_dir = Path(game_dir).expanduser() if game_dir is not None else None
        self.save_file = Path(save_file).expanduser() if save_file is not None else None
        self.map_file = Path(map_file).expanduser() if map_file is not None else None
        self.config_path = Path(config_path).expanduser()
        self._lock = RLock()
        self._domain_snapshot: battle_estimator_gui.DomainSnapshot | None = None
        self._metadata: AdvisorContextMetadata | None = None

    def refresh_context(self) -> dict[str, Any]:
        """Rebuild and cache the current domain snapshot, returning metadata."""

        snapshot = battle_estimator_gui.build_domain_snapshot(
            mode=self.mode,
            autosave_dir=self.game_dir,
            save_file=self.save_file,
            map_file=self.map_file,
            config_path=self.config_path,
            removed_neutral_cache=None,
        )
        metadata = AdvisorContextMetadata.from_domain_snapshot(snapshot)
        with self._lock:
            self._domain_snapshot = snapshot
            self._metadata = metadata
        return metadata.as_dict()

    def get_domain_snapshot(
        self,
        *,
        refresh: bool = False,
    ) -> battle_estimator_gui.DomainSnapshot:
        """Return the cached domain snapshot, optionally forcing a rebuild."""

        if refresh:
            self.refresh_context()
        with self._lock:
            snapshot = self._domain_snapshot
        if snapshot is not None:
            return snapshot
        self.refresh_context()
        with self._lock:
            snapshot = self._domain_snapshot
        if snapshot is None:  # pragma: no cover - defensive guard.
            raise RuntimeError("advisor context refresh did not produce a snapshot")
        return snapshot

    def cached_metadata(self) -> dict[str, Any] | None:
        """Return a defensive copy of cached snapshot metadata if loaded."""

        with self._lock:
            metadata = self._metadata
        return metadata.as_dict() if metadata is not None else None


def _resolve_context_mode(mode: str | None, save_file: str | Path | None) -> str:
    if mode is None:
        return (
            battle_estimator_gui.PINNED_MODE
            if save_file is not None
            else battle_estimator_gui.FOLLOW_LATEST_MODE
        )
    if mode == battle_estimator_gui.FOLLOW_LATEST_MODE and save_file is not None:
        raise ValueError("save_file requires pinned mode or mode=None")
    if mode not in {
        battle_estimator_gui.FOLLOW_LATEST_MODE,
        battle_estimator_gui.PINNED_MODE,
    }:
        expected = ", ".join((
            battle_estimator_gui.FOLLOW_LATEST_MODE,
            battle_estimator_gui.PINNED_MODE,
        ))
        raise ValueError(f"invalid mode {mode!r}; expected {expected}")
    return mode

