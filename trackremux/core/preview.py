import os
import subprocess
import tempfile
from typing import Optional


class MediaPreview:
    _current_process = None

    @staticmethod
    def extract_snippet(
        file_path: str, codec_type: str, track_index_in_type: int, start_time: float = 0.0
    ) -> Optional[str]:
        """
        Extracts a 30-second WAV snippet of a specific track starting at start_time.
        Returns the path to the temporary WAV file.
        """
        temp_dir = tempfile.gettempdir()
        output_path = os.path.join(temp_dir, f"preview_track_{track_index_in_type}.wav")

        # Remove old preview if exists
        if os.path.exists(output_path):
            os.remove(output_path)

        # ffmpeg -ss START -i input -map 0:a:N -t 30 -ac 2 -f wav output.wav
        # Using -ss before -i for fast seeking
        type_flag = "a" if codec_type == "audio" else ("v" if codec_type == "video" else "s")
        if type_flag != "a":
            return None  # We only support audio previews for now

        cmd = [
            "ffmpeg",
            "-v",
            "quiet",
            "-y",
            "-ss",
            str(start_time),
            "-i",
            file_path,
            "-map",
            f"0:a:{track_index_in_type}",
            "-t",
            "30",
            "-ac",
            "2",  # Force stereo for better compatibility
            "-f",
            "wav",
            output_path,
        ]

        result = subprocess.run(cmd)
        return output_path if result.returncode == 0 else None

    @staticmethod
    def play_snippet(wav_path: str):
        """
        Plays the WAV file using afplay (Mac) or ffplay -nodisp.
        """
        MediaPreview.stop()

        # Use afplay on Mac for zero-window experience
        cmd = ["afplay", wav_path]

        # Fallback to ffplay -nodisp if afplay is not available
        try:
            MediaPreview._current_process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            # Fallback for non-Mac or missing afplay
            cmd = ["ffplay", "-nodisp", "-autoexit", "-v", "quiet", wav_path]
            MediaPreview._current_process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

    @staticmethod
    def stop():
        if MediaPreview._current_process and MediaPreview._current_process.poll() is None:
            MediaPreview._current_process.terminate()
            MediaPreview._current_process = None
