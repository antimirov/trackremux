import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

from .models import MediaFile


@dataclass
class BatchGroup:
    name: str  # e.g. "Series S01"
    files: List[MediaFile] = field(default_factory=list)
    fingerprint: str = ""

    @property
    def count(self) -> int:
        return len(self.files)


class BatchDetector:
    # Regex patterns to detect series/season info
    # 1. S01E01 style
    # 2. 01x01 style
    # 3. Ep01 style  
    # 4. Anime-style bare episode number (Name 02)
    PATTERNS = [
        re.compile(r"(.*?)[ ._-]+S(\d+)E(\d+)", re.IGNORECASE),  # Name S01E01
        re.compile(r"(.*?)[ ._-]+(\d{1,2})x(\d{1,2})(?!\d)", re.IGNORECASE),  # Name 01x01 (max 2 digits to avoid 1920x1080)
        re.compile(r"(.*?)[ ._-]+Ep?(\d+)", re.IGNORECASE),  # Name Ep01
        # Anime-style: Name 02 (2-digit number followed by space, bracket, 'Dir', 'v', or end)
        re.compile(r"(.*?)[ ._-]+(\d{2})(?:[ ._\[v]|Dir|$)", re.IGNORECASE),  # Name 02
    ]

    @staticmethod
    def get_fingerprint(media: MediaFile) -> str:
        """
        Generates a unique signature for the file's structure.
        Format: "V:1|A:3(eng,jpn,und)|S:2(eng,rus)"
        """
        # Count tracks by type
        v_tracks = media.video_tracks
        a_tracks = media.audio_tracks
        s_tracks = media.subtitle_tracks

        # Language order is preserved for strict mapping. 
        # Changing order would break batch logic for mismatched files.

        a_langs = ",".join([t.language or "und" for t in a_tracks])
        s_langs = ",".join([t.language or "und" for t in s_tracks])

        # Fingerprint consists of track count and language order.

        return f"V:{len(v_tracks)}|A:{len(a_tracks)}({a_langs})|S:{len(s_tracks)}({s_langs})"

    @classmethod
    def detect_groups(cls, files: List[MediaFile]) -> List[BatchGroup]:
        """
        Scans a list of files and returns valid batches.
        A valid batch must:
        1. Have >= 2 files
        2. Share the same structural fingerprint
        3. Match a series regex pattern OR be very similar in naming (TODO?)
           Grouping relies on regex patterns for the batch name.
        """
        if len(files) < 2:
            return []

        # Group by Fingerprint first
        by_fingerprint: Dict[str, List[MediaFile]] = defaultdict(list)
        for f in files:
            fp = cls.get_fingerprint(f)
            by_fingerprint[fp].append(f)

        batches = []

        # Now analyze naming within each fingerprint group
        for fp, group_files in by_fingerprint.items():
            if len(group_files) < 2:
                continue

            # Fallback: group files within the same folder if structure matches.
            # Implication: The Scanner usually passes files from one folder.
            # So if they have same fingerprint in one folder, they are likely a batch.

            # Attempt to find common prefix or regex match.
            series_groups: Dict[str, BatchGroup] = {}
            fallback_group = BatchGroup(name="Misc Batch", fingerprint=fp)

            for f in group_files:
                matched = False
                for pat_idx, pat in enumerate(cls.PATTERNS):
                    m = pat.search(f.filename)
                    if m:
                        # Normalize series name
                        series_name = m.group(1).strip().replace(".", " ").replace("_", " ").title()
                        # Only patterns 0-1 (S01E01, 01x01) have season in group(2)
                        # Pattern 2 (Ep01) and 3 (anime) have episode number in group(2)
                        if len(m.groups()) >= 2 and pat_idx <= 1:
                            # Pattern 0 (S01E01) or Pattern 1 (01x01) - group(2) is season
                            season = m.group(2)
                            try:
                                season_num = int(season)
                                key = f"{series_name} - Season {season_num}"
                            except Exception:
                                key = series_name
                        else:
                            # Pattern 2 (Ep01) or Pattern 3 (anime) - no season, just series name
                            key = series_name

                        if key not in series_groups:
                            series_groups[key] = BatchGroup(name=key, fingerprint=fp)
                        series_groups[key].files.append(f)
                        matched = True
                        break

                if not matched:
                    # Fallback logic for unmatched files.
                    # We might fail regex if it's just "01.mkv"
                    fallback_group.files.append(f)

            # Add valid groups
            for bg in series_groups.values():
                if bg.count >= 2:
                    batches.append(bg)

            # Evaluate remaining files for generic batching if they share a structure.
            # Consider Generic Batch if naming is similar.
            # For now, simplistic approach: if we have >=3 files with SAME structure in one folder, it's a batch.
            if fallback_group.count >= 3:
                # Try to determine common prefix
                fallback_group.name = f"Generic Batch ({fallback_group.count} files)"
                batches.append(fallback_group)

        return batches
