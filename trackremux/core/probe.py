import json
import os
import subprocess

from .models import MediaFile, Track


class MediaProbe:
    @staticmethod
    def probe(file_path: str) -> MediaFile:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            file_path,
        ]

        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            err_msg = result.stderr.decode("utf-8", errors="replace")
            raise Exception(f"ffprobe failed: {err_msg}")

        try:
            text_data = result.stdout.decode("utf-8")
        except UnicodeDecodeError:
            try:
                # Fallback to KOI8-R for legacy Russian tags
                text_data = result.stdout.decode("koi8-r")
            except UnicodeDecodeError:
                try:
                    # Fallback to CP1251 for legacy Cyrillic tags
                    text_data = result.stdout.decode("cp1251")
                except UnicodeDecodeError:
                    text_data = result.stdout.decode("utf-8", errors="replace")

        data = json.loads(text_data)

        format_data = data.get("format", {})
        streams_data = data.get("streams", [])

        media_file = MediaFile(
            path=file_path,
            filename=os.path.basename(file_path),
            duration=float(format_data.get("duration", 0)),
            size_bytes=int(format_data.get("size", 0)),
        )

        for s in streams_data:
            codec_type = s.get("codec_type", "unknown")
            if codec_type not in ("video", "audio", "subtitle"):
                continue

            tags = s.get("tags", {})
            disposition = s.get("disposition", {})

            track = Track(
                index=int(s.get("index", 0)),
                codec_name=s.get("codec_name", "unknown"),
                codec_type=codec_type,
                language=tags.get("language"),
                tags=tags,
                profile=s.get("profile"),
                channels=s.get("channels"),
                channel_layout=s.get("channel_layout"),
                pix_fmt=s.get("pix_fmt"),
                color_space=s.get("color_space"),
                width=s.get("width"),
                height=s.get("height"),
                bit_rate=None,
                nb_frames=(
                    int(s.get("nb_frames"))
                    if s.get("nb_frames") and str(s.get("nb_frames")).isdigit()
                    else None
                ),
                is_attached_pic=disposition.get("attached_pic", 0) == 1,
                is_default=disposition.get("default", 0) == 1,
            )


            # Try to find bit_rate in multiple places (case-insensitive)
            tags_lower = {k.lower(): v for k, v in tags.items()}
            br = s.get("bit_rate") or tags_lower.get("bps") or tags_lower.get("bit_rate") or tags_lower.get("bitrate")

            if br:
                try:
                    track.bit_rate = int(br)
                except:
                    pass
            
            # Fallback: Estimate bitrate for audio if missing
            if track.codec_type == "audio" and not track.bit_rate:
                est = MediaProbe._estimate_bit_rate(track)
                if est:
                    track.bit_rate = est
                    track.bit_rate_is_estimated = True

            # Fallback for nb_frames if missing in container
            if track.codec_type == "video" and not track.nb_frames:
                fps_str = s.get("avg_frame_rate", "0/1")
                try:
                    num, den = map(int, fps_str.split("/"))
                    if den > 0:
                        fps = num / den
                        track.nb_frames = int(media_file.duration * fps)
                except:
                    pass

            media_file.tracks.append(track)

        return media_file

    @staticmethod
    def _estimate_bit_rate(track: Track) -> Optional[int]:
        """Provide a conservative bitrate estimate for common codecs when missing."""
        if track.codec_type != "audio":
            return None
        
        name = track.codec_name.lower()
        ch = track.channels or 2
        
        if name == "aac":
            # HE-AAC vs LC detection via profile
            if track.profile and "HE-AAC" in track.profile:
                return 48000 * ch if ch <= 2 else 192000 # HE-AAC 5.1 ~192k
            return 64000 * ch # LC-AAC 2ch ~128k, 5.1 ~384k
        elif name == "ac3":
            return 192000 if ch <= 2 else 448000
        elif name == "eac3":
            return 256000 if ch <= 2 else 640000
        elif name == "dts":
            return 768000 if ch <= 2 else 1536000
        elif name == "mp3":
            return int(128000 * (ch / 2))
        elif "pcm" in name:
            # PCM can be calculated if we have sample rate
            # FFmpeg JSON for audio streams often has "sample_rate" at top level
            # but Track model doesn't store it yet, so we check tags as backup.
            return 768000 * ch # Conservative estimate (1ch 48k 16bit)
        elif name == "flac":
            return 350000 * ch # Rough estimate for compressed lossless
        
        return None
