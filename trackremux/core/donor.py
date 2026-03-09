"""
Donor Audio Track Support
=========================
DonorCache  — instantaneous lookup: files in the same library that are likely alternative
              versions of the same film (matched by normalized title + ±2% duration).
DonorAligner — computes the sync offset between two files using FFmpeg ebur128 loudness
               envelopes and a pure-Python sliding MAE search. No extra dependencies.
"""

import os
import re
import re
import subprocess
from typing import Optional


# ---------------------------------------------------------------------------
# DonorCache
# ---------------------------------------------------------------------------

class DonorCache:
    """
    In-memory registry of all scanned files.
    Populated by the Explorer as files are probed. Zero I/O on lookup.
    """

    def __init__(self):
        # [(file_path, duration), ...]
        self._registry: list[tuple[str, float]] = []

    def register(self, path: str, duration: float) -> None:
        """Called once per file as it is probed during the initial scan."""
        # Avoid duplicates
        if not any(p == path for p, _ in self._registry):
            self._registry.append((path, duration))

    def get_donors(self, path: str, duration: float) -> list[tuple[str, float]]:
        """
        Returns a list of (donor_path, duration_match_pct) for ANY file in the 
        entire library that is within ±1.5% of the given duration.
        The query file itself is excluded.
        """
        result = []
        for candidate_path, candidate_dur in self._registry:
            if candidate_path == path:
                continue
            if duration <= 0 or candidate_dur <= 0:
                continue
                
            # Duration Match
            ratio = candidate_dur / duration
            
            # ±1.5% tolerance (e.g., ~1.3 minutes on a 90 minute movie)
            if 0.985 <= ratio <= 1.015:
                match_pct = (1.0 - abs(1.0 - ratio)) * 100.0
                result.append((candidate_path, round(match_pct, 1)))
        
        # Sort best match first
        result.sort(key=lambda x: -x[1])
        return result


# ---------------------------------------------------------------------------
# DonorAligner
# ---------------------------------------------------------------------------

class DonorAligner:
    """
    Compute the sync offset between two audio tracks using FFmpeg ebur128
    loudness envelopes and a sliding MAE search.
    """

    SAMPLE_HZ = 10       # ebur128 outputs ~10 values/second (100ms windows)
    PROBE_SECS = 120     # how many seconds to analyse
    SEARCH_WINDOW = 15.0 # ± seconds to search

    @staticmethod
    def _extract_envelope(file_path: str, stream_index: int) -> list[float]:
        """
        Extract Momentary Loudness (LUFS) values via FFmpeg ebur128.
        Returns a list of floats at ~10 Hz.  Empty on failure.
        """
        cmd = [
            "ffmpeg",
            "-hide_banner", "-nostats", "-v", "info",
            "-ss", "0",
            "-t", str(DonorAligner.PROBE_SECS),
            "-i", file_path,
            "-map", f"0:{stream_index}",
            "-af", "ebur128",
            "-f", "null",
            "-",
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60
            )
            output = result.stderr  # ebur128 writes to stderr
        except Exception:
            return []

        values = []
        for line in output.splitlines():
            # Lines look like:   [Parsed_ebur128_0 @ ...] t: 0.0999 TARGET:-23 LUFS M:-120.7 S:-120.7 I: -70.0 LUFS
            if "M:" in line and "S:" in line and "LUFS" in line:
                try:
                    m_idx = line.index("M:")
                    # Extract the value right after "M:"
                    # E.g. "M:-120.7" -> "-120.7"
                    val_str = line[m_idx + 2:].split()[0]
                    val = float(val_str)
                    # Clamp -infinity readings (silence) to a fixed floor
                    if val < -70:
                        val = -70.0
                    values.append(val)
                except (ValueError, IndexError):
                    continue
        return values

    @staticmethod
    def _sliding_mae(ref: list[float], query: list[float], hz: int, window: float) -> tuple[float, float]:
        """
        Slide `query` against `ref` in ±window seconds.
        Returns (best_offset_seconds, confidence_0_to_1).
        """
        max_shift = int(window * hz)
        best_offset = 0
        best_mae = float("inf")

        for shift in range(-max_shift, max_shift + 1):
            # Compute overlap indices
            if shift >= 0:
                ref_start, query_start = shift, 0
            else:
                ref_start, query_start = 0, -shift

            ref_seg = ref[ref_start: ref_start + 200]
            query_seg = query[query_start: query_start + len(ref_seg)]

            overlap = min(len(ref_seg), len(query_seg))
            if overlap < 20:
                continue

            mae = sum(abs(ref_seg[i] - query_seg[i]) for i in range(overlap)) / overlap
            if mae < best_mae:
                best_mae = mae
                best_offset = shift

        offset_seconds = best_offset / hz

        # Confidence: lower MAE = higher confidence
        # Typical random MAE is ~10–15 dB; a good match is <3 dB
        confidence = max(0.0, min(1.0, 1.0 - best_mae / 15.0))
        return offset_seconds, confidence

    @classmethod
    def align_best_track(cls, file_a: str, stream_a: int, file_b: str, tracks_b: list, env_a: list[float] = None) -> tuple[float, float]:
        """
        Compute the offset between stream_a in file_a and ALL audio tracks in file_b,
        returning the (offset, confidence) of the best match.
        Optionally accepts a pre-computed `env_a` to speed up bulk scans.
        """
        if env_a is None:
            env_a = cls._extract_envelope(file_a, stream_a)
            
        if not env_a:
            return 0.0, 0.0

        best_offset = 0.0
        best_conf = -1.0
        
        audio_b = [t for t in tracks_b if t.codec_type == "audio"]
        for t_b in audio_b:
            env_b = cls._extract_envelope(file_b, t_b.index)
            if not env_b:
                continue
            off, conf = cls._sliding_mae(env_a, env_b, cls.SAMPLE_HZ, cls.SEARCH_WINDOW)
            if conf > best_conf:
                best_conf = conf
                best_offset = off
                
        if best_conf < 0:
            return 0.0, 0.0
            
        return best_offset, best_conf

