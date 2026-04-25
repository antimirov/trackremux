from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class OutputMode(Enum):
    LOCAL = "local"  # Save to CWD as converted_*.mkv (legacy)
    REMOTE = "remote"  # Save converted_* next to the source file
    OVERWRITE = "overwrite"  # Atomic in-place replacement of source


@dataclass
class Track:
    index: int
    codec_name: str
    codec_type: str  # 'video', 'audio', 'subtitle'
    language: Optional[str] = None
    tags: dict = field(default_factory=dict)
    enabled: bool = True

    # Metadata for specific types
    channels: Optional[int] = None  # For audio
    channel_layout: Optional[str] = None  # For audio
    profile: Optional[str] = None  # Codec profile (e.g. 'DTS-HD MA', 'DTS', 'LC')
    pix_fmt: Optional[str] = None  # For video
    color_space: Optional[str] = None  # For video (HDR detection)
    width: Optional[int] = None  # For video
    height: Optional[int] = None  # For video
    bit_rate: Optional[int] = None  # In bits/s
    bit_rate_is_estimated: bool = False  # True when bit_rate was guessed
    nb_frames: Optional[int] = None  # For video
    is_attached_pic: bool = False  # True for cover art/attached pictures
    is_default: bool = False  # True when disposition.default == 1
    is_forced: bool = False  # True when disposition.forced == 1
    is_commentary_disposition: bool = False  # True when disposition.comment == 1
    is_description_disposition: bool = False  # True when disposition.descriptions == 1
    is_sdh_disposition: bool = False  # True when disposition.hearing_impaired == 1
    source_path: Optional[str] = None  # Path to external file (or None for main file)
    offset_seconds: float = 0.0  # Sync offset for donor tracks (applied via -itsoffset)
    trackremux_id: Optional[int] = None  # Unique ID for the output file metadata

    @property
    def is_commentary(self) -> bool:
        """True if the track is a commentary (based on title or disposition)."""
        if self.is_commentary_disposition:
            return True
        title = self.tags.get("title", "").lower()
        # Common commentary keywords
        keywords = ["commentary", "director's", "vfx", "special effects", "behind the scenes"]
        return any(k in title for k in keywords)

    @property
    def is_description(self) -> bool:
        """True if the track is an audio description for the visually impaired."""
        if self.is_description_disposition:
            return True
        title = self.tags.get("title", "").lower()
        keywords = ["description", "descriptive", "visual description", "audio description"]
        return any(k in title for k in keywords)

    @property
    def is_sdh(self) -> bool:
        """True if the track is a subtitle for the deaf and hard of hearing (SDH)."""
        if self.is_sdh_disposition:
            return True
        title = self.tags.get("title", "").lower()
        # Look for SDH markers in the title
        keywords = ["(sdh)", " sdh", "hearing impaired"]
        return any(k in title for k in keywords)

    @property
    def is_dts_hd_ma(self) -> bool:
        """True when the track is DTS-HD Master Audio (not plain DTS)."""
        return (
            self.codec_name.lower() == "dts"
            and bool(self.profile)
            and "DTS-HD MA" in (self.profile or "")
        )

    @property
    def display_language(self) -> str:
        """Returns the language code, with smart inference from title if needed."""
        lang = self.language or "und"
        if lang == "und" and self.tags.get("title"):
            title_lower = self.tags["title"].lower()
            if "русский" in title_lower or "rus" in title_lower:
                return "rus"
            elif "japanese" in title_lower or "jpn" in title_lower:
                return "jpn"
            elif "english" in title_lower or "eng" in title_lower:
                return "eng"
        return lang

    @property
    def display_info(self) -> str:
        if self.codec_type == "video":
            hdr_info = ""
            if self.color_space and "bt2020" in self.color_space:
                hdr_info = ", HDR"
            return f"Format: {self.codec_name.upper()}{hdr_info}, {self.width}x{self.height}"
        elif self.codec_type == "audio":
            lang = self.display_language
            
            # Show DTS-HD MA label when applicable
            codec_label = self.codec_name.upper()
            if self.is_dts_hd_ma:
                codec_label = "DTS-HD MA"
            # Show layout name preferably (e.g. "7.1"), fall back to raw channel count
            if self.channel_layout:
                ch_str = self.channel_layout
                if self.channels and str(self.channels) not in self.channel_layout:
                    ch_str += f" ({self.channels}ch)"
            elif self.channels:
                ch_str = f"{self.channels}ch"
            else:
                ch_str = "unknown"
            
            title_str = ""
            if self.tags.get("title"):
                title_str = f" \"{self.tags['title']}\""
            
            return f"Language: {lang}, Format: {codec_label}, Channels: {ch_str}{title_str}"

        elif self.codec_type == "subtitle":
            lang = self.display_language
            title_str = ""
            if self.tags.get("title"):
                title_str = f" \"{self.tags['title']}\""
            return f"Language: {lang}, Format: {self.codec_name.upper()}{title_str}"
        return f"Format: {self.codec_name}"


@dataclass
class MediaFile:
    path: str
    filename: str
    duration: float = 0.0
    size_bytes: int = 0
    tracks: List[Track] = field(default_factory=list)

    @property
    def video_tracks(self) -> List[Track]:
        return [t for t in self.tracks if t.codec_type == "video"]

    @property
    def audio_tracks(self) -> List[Track]:
        return [t for t in self.tracks if t.codec_type == "audio"]

    @property
    def subtitle_tracks(self) -> List[Track]:
        return [t for t in self.tracks if t.codec_type == "subtitle"]
