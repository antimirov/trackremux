"""
AppConfig — persistent language profile and preference storage.

File location: ~/.config/trackremux/config.toml (XDG Base Directory compliant).
Falls back gracefully if the file is missing or malformed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .models import MediaFile, Track

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "trackremux",
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.toml")


@dataclass
class AppConfig:
    """Persistent user preferences loaded from TOML config file."""

    keep_langs: List[str] = field(default_factory=list)
    discard_langs: List[str] = field(default_factory=list)
    prefer_ac3_over_hd: bool = False
    discard_commentaries: bool = False
    discard_descriptions: bool = False
    discard_sdh: bool = False

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls) -> "AppConfig":
        """Load config from disk.  Returns empty defaults if not found."""
        if not os.path.exists(CONFIG_PATH):
            return cls()
        try:
            return cls._parse_toml(CONFIG_PATH)
        except Exception:
            return cls()

    def save(self) -> None:
        """Write config to disk (creates parent dirs as needed)."""
        os.makedirs(CONFIG_DIR, exist_ok=True)
        lines = [
            "[preferences]\n",
            f"keep_langs = {_fmt_list(self.keep_langs)}\n",
            f"discard_langs = {_fmt_list(self.discard_langs)}\n",
            f"prefer_ac3_over_hd = {str(self.prefer_ac3_over_hd).lower()}\n",
            f"discard_commentaries = {str(self.discard_commentaries).lower()}\n",
            f"discard_descriptions = {str(self.discard_descriptions).lower()}\n",
            f"discard_sdh = {str(self.discard_sdh).lower()}\n",
        ]
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            fh.writelines(lines)

    @property
    def exists(self) -> bool:
        """True if a config file already lives on disk."""
        return os.path.exists(CONFIG_PATH)

    # ------------------------------------------------------------------ #
    # Profile application                                                  #
    # ------------------------------------------------------------------ #

    def get_target_states(self, media_file: "MediaFile") -> dict[int, bool]:
        """Calculate the desired enabled state for each track based on the profile."""
        states = {}
        for t in media_file.tracks:
            if t.codec_type == "video":
                continue
            
            # 1. Base language decision
            lang = t.language or "und"
            decision = self._should_keep(lang)
            target_enabled = decision if decision is not None else t.enabled
            
            # 2. Rule-based exclusions (Commentary, Description, SDH)
            if self.discard_commentaries and t.is_commentary:
                target_enabled = False
            if self.discard_descriptions and t.is_description:
                target_enabled = False
            if self.discard_sdh and t.codec_type == "subtitle" and t.is_sdh:
                target_enabled = False
                
            states[t.index] = target_enabled

        if self.prefer_ac3_over_hd:
            from collections import defaultdict
            enabled_audio_by_lang = defaultdict(list)
            for t in media_file.tracks:
                if t.codec_type == "audio" and states.get(t.index, t.enabled):
                    lang = t.language or "und"
                    enabled_audio_by_lang[lang].append(t)
            
            from .converter import MediaConverter
            for lang, tracks in enabled_audio_by_lang.items():
                # Only prefer AC3 if there is a *main* (default) AC3 track,
                # not a commentary or other secondary AC3 track.
                has_default_ac3 = any(
                    t.codec_name.lower() == "ac3" and t.is_default for t in tracks
                )
                if has_default_ac3:
                    # Disable HD codecs for this language since we have native main AC3
                    for t in tracks:
                        if t.codec_name.lower() in MediaConverter.HD_CODECS:
                            states[t.index] = False
        return states

    def matches(self, media_file: "MediaFile") -> List["Track"]:
        """
        Returns non-video tracks whose enabled state would *change* if the
        profile were applied. Empty list → profile has nothing to do here.
        """
        candidates = []
        states = self.get_target_states(media_file)
        for t in media_file.tracks:
            if t.index in states and t.enabled != states[t.index]:
                candidates.append(t)
        return candidates

    def apply_to(self, media_file: "MediaFile") -> None:
        """Toggle tracks on/off according to saved preferences."""
        states = self.get_target_states(media_file)
        for t in media_file.tracks:
            if t.index in states:
                t.enabled = states[t.index]

    def _should_keep(self, lang: str) -> Optional[bool]:
        """Return True/False if the lang is covered by a rule, None otherwise."""
        if self.keep_langs and lang in self.keep_langs:
            return True
        if self.discard_langs and lang in self.discard_langs:
            return False
        # If keep list has entries and this lang is NOT in it → discard
        if self.keep_langs:
            return False
        return None

    # ------------------------------------------------------------------ #
    # TOML parsing (stdlib only, no third-party dep required)              #
    # ------------------------------------------------------------------ #

    @classmethod
    def _parse_toml(cls, path: str) -> "AppConfig":
        cfg = cls()
        with open(path, encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#") or line.startswith("["):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if key == "keep_langs":
                    cfg.keep_langs = _parse_string_list(val)
                elif key == "discard_langs":
                    cfg.discard_langs = _parse_string_list(val)
                elif key in ("prefer_ac3_over_hd", "prefer_ac3_over_dts"):
                    cfg.prefer_ac3_over_hd = val.lower() == "true"
                elif key == "discard_commentaries":
                    cfg.discard_commentaries = val.lower() == "true"
                elif key == "discard_descriptions":
                    cfg.discard_descriptions = val.lower() == "true"
                elif key == "discard_sdh":
                    cfg.discard_sdh = val.lower() == "true"
        return cfg


# ------------------------------------------------------------------ #
# Tiny TOML helpers (avoid external dependencies)                     #
# ------------------------------------------------------------------ #


def _parse_string_list(val: str) -> List[str]:
    """Parse a TOML inline array of strings like ["eng", "nld"]."""
    val = val.strip().lstrip("[").rstrip("]")
    result = []
    for part in val.split(","):
        s = part.strip().strip('"').strip("'")
        if s:
            result.append(s)
    return result


def _fmt_list(lst: List[str]) -> str:
    """Format a Python list as a TOML inline array."""
    inner = ", ".join(f'"{s}"' for s in lst)
    return f"[{inner}]"
