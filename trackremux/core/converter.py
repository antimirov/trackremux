import os
import re
import subprocess

from .models import MediaFile


class MediaConverter:
    # Codec set of high-res audio variants that we transcode when convert_audio is on
    HD_CODECS = {"dts", "dts-hd", "truehd", "pcm_bluray", "pcm_s16le", "pcm_s24le", "pcm_s32le"}

    # Channel-layout name → channel count
    LAYOUT_CHANNELS = {
        "mono": 1, "stereo": 2,
        "2.1": 3, "3.0": 3, "3.0(back)": 3,
        "4.0": 4, "quad": 4, "quad(side)": 4,
        "4.1": 5, "5.0": 5, "5.0(side)": 5,
        "5.1": 6, "5.1(side)": 6,
        "6.0": 6, "6.0(front)": 6, "hexagonal": 6,
        "6.1": 7, "6.1(back)": 7, "6.1(front)": 7,
        "7.0": 7, "7.0(front)": 7,
        "7.1": 8, "7.1(wide)": 8, "7.1(wide-side)": 8, "octagonal": 8,
    }

    @staticmethod
    def get_channel_count(track) -> int:
        """Return channel count for a Track, resolving from layout name if needed."""
        if track.channels:
            return track.channels
        if track.channel_layout:
            c = MediaConverter.LAYOUT_CHANNELS.get(track.channel_layout.lower())
            if c:
                return c
        return 6  # safe default

    @staticmethod
    def get_audio_fallback_chain(track) -> list:
        """
        Returns an ordered list of codec attempt descriptors for this track.
        Each entry is a dict with keys: codec, bitrate, ac, strict_experimental, label.
        The caller should try them in order, falling back on ffmpeg failure.
        """
        channels = MediaConverter.get_channel_count(track)

        if track.is_dts_hd_ma or channels > 6:
            # DTS-HD MA or plain 7.1 DTS: best we can do in MKV is EAC3 5.1.
            # TrueHD would be ideal but ffmpeg's matroska muxer rejects it (EINVAL).
            # EAC3 at 1024k provides higher quality than AC3 at the same channel count.
            return [
                {"codec": "eac3", "bitrate": "1024k", "ac": 6,
                 "strict_experimental": False,
                 "label": "EAC3 5.1"},
                {"codec": "ac3", "bitrate": "640k", "ac": 6,
                 "strict_experimental": False,
                 "label": "AC3 5.1"},
            ]
        elif channels <= 2:
            return [{"codec": "ac3", "bitrate": "192k", "ac": channels,
                     "strict_experimental": False,
                     "label": f"AC3 {track.channel_layout or f'{channels}ch'}"}]
        else:
            ch_out = min(channels, 6)
            return [{"codec": "ac3", "bitrate": "640k", "ac": ch_out,
                     "strict_experimental": False,
                     "label": f"AC3 {track.channel_layout or f'{ch_out}ch'}"}]

    @staticmethod
    def build_ffmpeg_command(
        media_file: MediaFile, output_path: str, convert_audio: bool = False,
        codec_overrides: dict = None
    ) -> list:
        """
        Builds the ffmpeg command to keep only enabled tracks and set languages.

        codec_overrides: maps audio output index → codec attempt dict from
                         get_audio_fallback_chain(), e.g. {0: {"codec": "eac3", ...}}.
                         When None, the first (preferred) entry from the chain is used.
        convert_audio: when True, DTS audio tracks get transcoded per the fallback chain.
        """
        # 1. Identify all unique source files and their offsets.
        # The main file is always index 0 with offset 0.
        # input_files: list of (path, offset_seconds)
        input_files: list[tuple[str, float]] = [(media_file.path, 0.0)]

        # Helper to get or register input index for a path + offset.
        def get_input_index(path, offset: float = 0.0):
            if path is None or path == media_file.path:
                return 0
            # Reuse existing entry if same path (take max offset seen for it).
            for idx, (p, _o) in enumerate(input_files):
                if p == path:
                    # Update offset to max, so a track's offset wins.
                    if abs(offset) > abs(_o):
                        input_files[idx] = (path, offset)
                    return idx
            input_files.append((path, offset))
            return len(input_files) - 1

        # 2. Build inputs part of the command.
        cmd = ["ffmpeg", "-fflags", "+genpts", "-y"]
        # Pre-scan enabled tracks to register all necessary inputs.
        for track in media_file.tracks:
            if track.enabled and track.source_path:
                get_input_index(track.source_path, track.offset_seconds)

        for path, offset in input_files:
            if abs(offset) > 0.001:
                cmd.extend(["-itsoffset", f"{offset:.6f}"])
            cmd.extend(["-i", path])

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
            input_idx = get_input_index(track.source_path, track.offset_seconds)

            # Construct map: input_idx:stream_idx
            cmd.extend(["-map", f"{input_idx}:{track.index}"])

            # Set metadata for output stream
            if track.codec_type == "video":
                # Set disposition for attached pictures (cover art)
                if track.is_attached_pic:
                    cmd.extend([f"-disposition:v:{video_idx}", "attached_pic"])
                tr_id = track.trackremux_id if track.trackremux_id is not None else track.index
                cmd.extend([f"-metadata:s:v:{video_idx}", f"trackremux_id={tr_id}"])
                video_idx += 1
            elif track.codec_type == "audio":
                if track.language:
                    cmd.extend([f"-metadata:s:a:{audio_idx}", f"language={track.language}"])

                # Handling DTS to AC3 conversion metadata
                if convert_audio and track.codec_name.lower() in MediaConverter.HD_CODECS:
                    dts_audio_indices.append((audio_idx, track))


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

                tr_id = track.trackremux_id if track.trackremux_id is not None else track.index
                cmd.extend([f"-metadata:s:a:{audio_idx}", f"trackremux_id={tr_id}"])
                audio_idx += 1
            elif track.codec_type == "subtitle":
                if track.language:
                    cmd.extend([f"-metadata:s:s:{subtitle_idx}", f"language={track.language}"])
                tr_id = track.trackremux_id if track.trackremux_id is not None else track.index
                cmd.extend([f"-metadata:s:s:{subtitle_idx}", f"trackremux_id={tr_id}"])
                subtitle_idx += 1

        # 4. Codec selection
        cmd.extend(["-c", "copy"])
        for a_idx, track in dts_audio_indices:
            # Determine which codec attempt to use
            chain = MediaConverter.get_audio_fallback_chain(track)
            if codec_overrides and a_idx in codec_overrides:
                attempt = codec_overrides[a_idx]
            else:
                attempt = chain[0]  # preferred (first) codec

            codec = attempt["codec"]
            bitrate = attempt.get("bitrate")
            ac = attempt.get("ac")

            cmd.extend([f"-c:a:{a_idx}", codec])
            if bitrate:
                cmd.extend([f"-b:a:{a_idx}", bitrate])
            if ac:
                cmd.extend([f"-ac:a:{a_idx}", str(ac)])
            if attempt.get("strict_experimental"):
                cmd.extend(["-strict", "experimental"])

            # Rewrite track title to reflect new codec
            title = track.tags.get("title", "")
            if title:
                new_title = re.sub(r"(?i)\bdts(?:-hd(?:\s*ma)?)?\b", attempt["label"], title)
                new_title = re.sub(
                    r"\b(?:1536|768)\s*kbps\b", f"{bitrate or ''}", new_title, flags=re.IGNORECASE
                )
                cmd.extend([f"-metadata:s:a:{a_idx}", f"title={new_title}"])

        cmd.append(output_path)

        return cmd



    @staticmethod
    def estimate_output_size(media_file: MediaFile, convert_audio: bool = False) -> int:
        """
        Estimates the output file size based on enabled tracks and audio conversion.
        """
        total_size = media_file.size_bytes
        if total_size <= 0:
            # Fallback to bitrate * duration if size unknown
            total_bitrate = 0
            for t in media_file.tracks:
                if t.enabled:
                    if convert_audio and t.codec_type == "audio" and t.codec_name.lower() in MediaConverter.HD_CODECS:
                        chain = MediaConverter.get_audio_fallback_chain(t)
                        tg_br = chain[0].get("bitrate", "640k")
                        total_bitrate += int(tg_br.replace("k", "000"))
                    elif t.bit_rate:
                        total_bitrate += t.bit_rate
            return int((total_bitrate * media_file.duration) / 8)

        size_diff = 0
        for track in media_file.tracks:
            if not track.enabled:
                if track.bit_rate:
                    size_diff -= int((track.bit_rate * media_file.duration) / 8)
            elif convert_audio and track.codec_type == "audio" and track.codec_name.lower() in MediaConverter.HD_CODECS:
                # Track is kept but transcoded; subtract original size, add target size
                target_chain = MediaConverter.get_audio_fallback_chain(track)
                target_bitrate_str = target_chain[0].get("bitrate", "640k")
                target_bitrate = int(target_bitrate_str.replace("k", "000"))
                
                # If we don't know the original bitrate, we can't accurately subtract it.
                # MKV often strips audio bitrates. A typical DTS-HD MA is ~3000-4000k. standard DTS is 1536k.
                orig_bitrate = track.bit_rate
                if not orig_bitrate:
                    orig_bitrate = 3500000 if track.is_dts_hd_ma else 1536000
                
                size_diff -= int((orig_bitrate * media_file.duration) / 8)
                size_diff += int((target_bitrate * media_file.duration) / 8)

        return max(0, total_size + size_diff)

    @staticmethod
    def convert(
        media_file: MediaFile, output_path: str, convert_audio: bool = False,
        codec_overrides: dict = None, progress_callback=None
    ):
        """
        Executes the conversion. Returns the process object so it can be managed.
        codec_overrides: see build_ffmpeg_command.
        """
        cmd = MediaConverter.build_ffmpeg_command(
            media_file, output_path, convert_audio=convert_audio,
            codec_overrides=codec_overrides
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

