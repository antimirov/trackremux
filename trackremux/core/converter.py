import os
import re
import subprocess

from .models import MediaFile


class MediaConverter:
    # Codec set of DTS variants that we transcode when convert_audio is on
    DTS_CODECS = {"dts", "dts-hd", "truehd"}  # truehd kept for completeness

    @staticmethod
    def build_ffmpeg_command(
        media_file: MediaFile, output_path: str, convert_audio: bool = False
    ) -> list:
        """
        Builds the ffmpeg command to keep only enabled tracks and set languages.
        Handles both internal (same file) and external (separate file) tracks.

        convert_audio: when True, DTS audio tracks are transcoded to AC3 640k
                       instead of being stream-copied.
        """
        # 1. Identify all unique source files
        # The main file is always index 0
        input_files = [media_file.path]

        # Helper to get input index for a path
        def get_input_index(path):
            if path is None or path == media_file.path:
                return 0
            if path not in input_files:
                input_files.append(path)
            return input_files.index(path)

        # 2. Build inputs part of the command
        cmd = ["ffmpeg", "-fflags", "+genpts", "-y"]
        # Pre-scan tracks to add all necessary inputs
        for track in media_file.tracks:
            if track.enabled and track.source_path:
                get_input_index(track.source_path)

        for ip in input_files:
            cmd.extend(["-i", ip])

        # 3. Map tracks
        # Metadata indices in the output file
        audio_idx = 0
        subtitle_idx = 0
        video_idx = 0

        # Track which audio output indices need transcoding
        dts_audio_indices: list = []  # output audio indices that are DTS

        for track in media_file.tracks:
            if not track.enabled:
                continue

            # Determine input index and stream index
            input_idx = get_input_index(track.source_path)

            # Construct map: input_idx:stream_idx
            cmd.extend(["-map", f"{input_idx}:{track.index}"])

            # Set metadata for output stream
            if track.codec_type == "video":
                # Set disposition for attached pictures (cover art)
                if track.is_attached_pic:
                    cmd.extend([f"-disposition:v:{video_idx}", "attached_pic"])
                cmd.extend([f"-metadata:s:v:{video_idx}", f"trackremux_id={track.index}"])
                video_idx += 1
            elif track.codec_type == "audio":
                if track.language:
                    cmd.extend([f"-metadata:s:a:{audio_idx}", f"language={track.language}"])

                # Handling DTS to AC3 conversion metadata
                if convert_audio and track.codec_name.lower() in MediaConverter.DTS_CODECS:
                    dts_audio_indices.append(audio_idx)

                    # Rewrite the title if it contains DTS
                    title = track.tags.get("title", "")
                    if title:
                        # Replace 'DTS' / 'DTS-HD' with 'AC3'
                        new_title = re.sub(r"(?i)\bdts(?:-hd)?\b", "AC3", title)
                        # Replace typical bitrates like '1536 kbps' or '768 kbps' with '640 kbps'
                        new_title = re.sub(
                            r"\b(?:1536|768)\s*kbps\b", "640 kbps", new_title, flags=re.IGNORECASE
                        )

                        cmd.extend([f"-metadata:s:a:{audio_idx}", f"title={new_title}"])

                elif "title" in track.tags:
                    # Pass through original title if not modifying audio
                    cmd.extend([f"-metadata:s:a:{audio_idx}", f"title={track.tags['title']}"])

                cmd.extend([f"-metadata:s:a:{audio_idx}", f"trackremux_id={track.index}"])
                audio_idx += 1
            elif track.codec_type == "subtitle":
                if track.language:
                    cmd.extend([f"-metadata:s:s:{subtitle_idx}", f"language={track.language}"])
                cmd.extend([f"-metadata:s:s:{subtitle_idx}", f"trackremux_id={track.index}"])
                subtitle_idx += 1

        # 4. Codec selection
        # Start with global copy, then override per-stream for DTS tracks
        cmd.extend(["-c", "copy"])
        for a_idx in dts_audio_indices:
            cmd.extend([f"-c:a:{a_idx}", "ac3", f"-b:a:{a_idx}", "640k"])

        cmd.append(output_path)

        return cmd

    @staticmethod
    def estimate_output_size(media_file: MediaFile) -> int:
        """
        Estimates the output file size based on enabled tracks.
        """
        # If we have total size, start with that.
        # Estimate the size of DISABLED tracks and subtract.
        total_size = media_file.size_bytes
        if total_size <= 0:
            # Fallback to bitrate * duration if size unknown
            total_bitrate = sum(t.bit_rate for t in media_file.tracks if t.enabled and t.bit_rate)
            return int((total_bitrate * media_file.duration) / 8)

        disabled_size = 0
        for track in media_file.tracks:
            if not track.enabled:
                if track.bit_rate:
                    disabled_size += int((track.bit_rate * media_file.duration) / 8)
                else:
                    # Fallback for audio tracks with missing bitrate metadata.
                    # Or just assume it's proportional to track count (risky for video).
                    # For now, if no bitrate for disabled track, we can't subtract accurately.
                    pass

        return max(0, total_size - disabled_size)

    @staticmethod
    def convert(
        media_file: MediaFile, output_path: str, convert_audio: bool = False, progress_callback=None
    ):
        """
        Executes the conversion. Returns the process object so it can be managed.
        """
        cmd = MediaConverter.build_ffmpeg_command(
            media_file, output_path, convert_audio=convert_audio
        )
        cmd.insert(1, "-progress")
        cmd.insert(2, "-")

        # Overwrite output if exists
        if os.path.exists(output_path):
            os.remove(output_path)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
        )
        return process
