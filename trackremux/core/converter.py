import os
import subprocess

from .models import MediaFile


class MediaConverter:
    @staticmethod
    def build_ffmpeg_command(media_file: MediaFile, output_path: str) -> list:
        """
        Builds the ffmpeg command to keep only enabled tracks and set languages.
        Handles both internal (same file) and external (separate file) tracks.
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
                video_idx += 1
            elif track.codec_type == "audio":
                if track.language:
                    cmd.extend([f"-metadata:s:a:{audio_idx}", f"language={track.language}"])
                audio_idx += 1
            elif track.codec_type == "subtitle":
                if track.language:
                    cmd.extend([f"-metadata:s:s:{subtitle_idx}", f"language={track.language}"])
                subtitle_idx += 1

        # Copy codecs to avoid re-encoding
        cmd.extend(["-c", "copy"])
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
                    # Heuristic: if no bitrate, assume it's an audio track and take some default?
                    # Or just assume it's proportional to track count (risky for video).
                    # For now, if no bitrate for disabled track, we can't subtract accurately.
                    pass

        return max(0, total_size - disabled_size)

    @staticmethod
    def convert(media_file: MediaFile, output_path: str, progress_callback=None):
        """
        Executes the conversion. Returns the process object so it can be managed.
        """
        cmd = MediaConverter.build_ffmpeg_command(media_file, output_path)
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
