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

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"ffprobe failed: {result.stderr}")

        data = json.loads(result.stdout)

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
            )

            # Try to find bit_rate in multiple places
            br = s.get("bit_rate")
            if not br:
                # MKV often puts this in the BPS tag
                br = tags.get("BPS") or tags.get("bit_rate") or tags.get("bitrate")

            if br:
                try:
                    track.bit_rate = int(br)
                except:
                    pass

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
