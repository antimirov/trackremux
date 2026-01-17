from dataclasses import dataclass, field
from typing import List, Optional


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
    pix_fmt: Optional[str] = None  # For video
    color_space: Optional[str] = None  # For video (HDR detection)
    width: Optional[int] = None  # For video
    height: Optional[int] = None  # For video
    bit_rate: Optional[int] = None  # In bits/s
    nb_frames: Optional[int] = None  # For video
    is_attached_pic: bool = False  # True for cover art/attached pictures
    source_path: Optional[str] = None  # Path to external file logic (or None for main file)

    @property
    def display_info(self) -> str:
        if self.codec_type == "video":
            hdr_info = ""
            if self.color_space and "bt2020" in self.color_space:
                hdr_info = ", HDR"
            return f"Format: {self.codec_name.upper()}{hdr_info}, {self.width}x{self.height}"
        elif self.codec_type == "audio":
            lang = self.language or "und"
            channels = f"{self.channels or '?'}.{self.channel_layout or ''}"
            return f"Format: {self.codec_name.upper()}, Language: {lang}, Channels: {channels}"
        elif self.codec_type == "subtitle":
            lang = self.language or "und"
            return f"Format: {self.codec_name.upper()}, Language: {lang}"
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
