import os
import subprocess

from .models import MediaFile


class MediaConverter:
    @staticmethod
    def build_ffmpeg_command(media_file: MediaFile, output_path: str) -> list:
        """
        Builds the ffmpeg command to keep only enabled tracks and set languages.
        """
        cmd = ["ffmpeg", "-y", "-i", media_file.path]  # -y to overwrite

        # Metadata indices in the output file
        audio_idx = 0
        subtitle_idx = 0
        video_idx = 0

        for track in media_file.tracks:
            if not track.enabled:
                continue

            # Map by absolute index
            cmd.extend(["-map", f"0:{track.index}"])

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
