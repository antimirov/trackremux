# TrackRemux

**TrackRemux** is a powerful Terminal User Interface (TUI) tool designed to help you clean up your video library. It allows you to interactively specify audio and subtitle tracks from your video files and remux them into clean, optimized containers without re-encoding the video stream.

*This whole project was vibe coded on a Friday evening out of necessity while organizing the media library on my NAS.*

![Media Browser](docs/screenshots/02_media_browser.png)

> [!TIP]
> Check out the [CHANGELOG](CHANGELOG.md) to see what's new in the latest version!

## 🚀 Purpose

Modern media often comes with a bloat of unnecessary tracks - commentary audio, multiple languages you don't speak, or dozens of subtitle formats. **TrackRemux** simplifies the process of removing this clutter.

![TrackRemux Demo](demo.gif)

This not only saves significant disk space but also prevents the confusion and inconvenience of managing tracks in media players (like those on Smart TVs or mobile devices) where selecting the right audio or subtitle stream can be cumbersome or even impossible.

Instead of wrestling with complex `ffmpeg` command-line arguments for every single file, TrackRemux provides a visual interface to:
1.  **Scan** directories for video files.
2.  **Select** exactly which tracks you want to keep.
3.  **Remux** the file efficiently (Direct Stream Copy).

## ✨ Features

-   **Interactive TUI**: Built with `curses` for a fast, keyboard-centric workflow.
-   **Batch Processing**: Automatically detects and processes TV shows/series/collections sequentially.
    -   **Smart Detection**: Recognizes series patterns (S01E01, 1x01, Ep01) and groups by season.
    -   **Structural Fingerprinting**: Groups files with identical track structure.
    -   **Unified Editing**: Edit one file, apply changes to all files in the batch.
-   **Rich Meta-data Explorer**:
    -   Displays file sizes, track counts, and audio languages at a glance.
    -   **Visual Status Indicators**: Instantly spot files that have already been converted (Green size) or are currently processing (Dim Yellow).
    -   **Folder Navigation**: Browse nested directory structures (`Enter` to open, `Esc` to go back).
-   **Deep Track Inspection**:
    -   **Track Reordering**: Move tracks up/down with `Shift+Arrow` keys to set their index in the final file.
    -   **External Tracks**: Automatically detects and integrates external audio/subtitle files (even in `Audio/` or `Subs/` subfolders).
    -   **Language Management**: Guesses 30+ languages from filenames (e.g. `dut.srt`) or supports manual setting via the `[L]` key.
    -   **Smart Matching**: Automatically detects existing conversions and restores your previous track selections.
-   **Preview Capabilities**: Listen to audio tracks directly from the TUI (macOS `afplay` integration) to confirm contents before keeping them.
-   **Intelligent Output Management**:
    -   **Three Output Modes**: Choose between `[O]verwrite` (atomic in-place replacement), `[L]ocal` (save `converted_*` to CWD), or `[R]emote` (save `converted_*` next to source files).
    -   **Smart Batch Output**: Batch conversions automatically create a `converted_<directory>/` folder with original filenames preserved, instead of prefixing every file.
    -   **NAS-Safe Atomic Swaps**: Overwrites are safely processed in a hidden `.trackremux_staging/` directory and shifted via instantaneous atomic swaps to avoid media server race conditions, keeping original files safely in `.trackremux_trash/` for recovery.
    -   **Read-Only Detection**: Automatically warns when the source filesystem is read-only, preventing failed Overwrite/Remote saves.
-   **Audio Conditioning (DTS → AC3)**:
    -   Automatically convert incompatible high-bitrate audio formats (DTS, DTS-HD, TrueHD) down to universally compatible `AC3 640k` via a hotkey `[C]` toggle to ensure Direct Play on all devices (e.g. LG WebOS TVs).
    -   Features a dynamic `DTS>AC3` badge directly inside the Explorer file list tracking conditionally encoded native AC3 streams.
    -   Added `[F]` hotkey to explicitly filter media list views exclusively to files with DTS-encoded formats.
-   **Smart Configurations & Profiles**:
    -   Build and utilize default setting profiles (`keep_langs`, `discard_langs`, `ac3` preference overrides).
    -   Interactive profile editor overlay via `[P]` — Enter to edit fields, cursor navigation, Enter to confirm and auto-save, Escape to discard changes.
    -   Profiles can be intelligently evaluated and interactively applied with `[A]` across matches to dramatically accelerate repetitive multi-file adjustments.
-   **Safe Conversion**:
    -   Uses `ffmpeg` for robust processing.
    -   Identifies edited assets automatically tracking changes reliably even across format shifts with its own `.mkv` metadata tag system: `trackremux_id`.
    -   Real-time progress bar and size estimation.

## 📸 Visual Walkthrough

### 1. Launch & Directory Scan
Scan any folder to instantly see track counts and sizes.
![Launch](docs/screenshots/01_launch_trackremux.png)

### 2. Intelligent Track Selection
Pick exactly what you need. Audio previews help distinguish between different dubs or commentaries.
![Selecting Tracks](docs/screenshots/03_selecting_tracks.png)

### 3. External Tracks & Language Editing
TrackRemux finds external subtitle/audio files automatically. You can also manually correct missing language tags.
![External Tracks](docs/screenshots/07_external_tracks.png)

### 4. Fast, Lossless Conversion
Watch the progress in real-time as ffmpeg remuxes your file at disk-IO speeds.
![Converting](docs/screenshots/04_converting.png)

### 5. Successful Completion
Final sizes and success messages are displayed directly in the TUI upon completion.
![Result](docs/screenshots/05_result.png)

### 6. Efficient Storage
Remuxing is lossless and fast. You can see the significant size savings in your directory listing without any quality loss.
![Result Difference](docs/screenshots/06_list_files.png)

## 🛠️ Prerequisites

-   **Python 3.10+**
-   **FFmpeg** must be installed and accessible in your system PATH.
    -   macOS: `brew install ffmpeg`

## 📦 Installation & Setup

### Option 1: Install as a Global Tool (Recommended)
The easiest way to use TrackRemux is to install it globally using `uv`:
```bash
uv tool install trackremux
```
Once installed, you can simply run `trackremux` from any directory.

### Option 2: Running from Source
If you prefer to run it directly from the repository:

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/antimirov/trackremux.git
    cd trackremux
    ```

2.  **Run using the wrapper**:
    ```bash
    python3 trackremux.py /path/to/media
    ```

3.  **Run as a module**:
    ```bash
    python3 -m trackremux /path/to/media
    ```

4.  **Using `uv` (for development)**:
    ```bash
    uv sync
    uv run trackremux /path/to/media
    ```

## 🖥️ Usage

You can point TrackRemux to a directory (Explorer Mode) or a specific video file (Editor Mode).

### Explorer Mode (Directory)
Browse and process your entire library:
```bash
trackremux /path/to/your/movies
```

### Single File Mode
Jump straight into the track editor for a specific file:
```bash
trackremux "My Movie.mkv"
```

---

## ⌨️ Keyboard Controls

### File Explorer
| Key | Action |
| :--- | :--- |
| **↑ / ↓** | Navigate file list |
| **PgUp / PgDn** | Scroll pages |
| **Enter** | Open selected file in Editor |
| **B** | Open Batch Selector (when batches detected) |
| **D** | Cycle filter: All → DTS only → DTS>AC3 only |
| **M** | Toggle Mouse Support |
| **R** | Force re-scan current directory |
| **N / S / T / A** | Sort by **N**ame, **S**ize, **T**racks, **A**udio Size |
| **Q / Esc** | Quit Application |
| **Ctrl+C** | Force Quit instantly |

### Track Editor
| Key | Action |
| :--- | :--- |
| **Space** | Toggle Track (Keep/Discard) |
| **Enter** | Preview Track (Audio only) |
| **← / →** | Seek in preview |
| **↑ / ↓** | Navigate Tracks |
| **Shift+↑ / ↓** | Move selected track UP / DOWN |
| **L** | Set Language (manual edit) |
| **C** | Toggle DTS → AC3 audio conditioning |
| **P** | Open Profile editor (keep/discard languages, AC3 preference) |
| **A** | Apply saved profile to current file |
| **S** | Save — opens output mode dialog (`[O]`verwrite / `[L]`ocal / `[R]`emote) |
| **Esc / Q** | Back to Explorer |

## 🗺️ Roadmap

See [ROADMAP.md](ROADMAP.md) for the full feature roadmap. Highlights:

- ✅ **Batch Processing** — Completed in v0.6.0
- ✅ **In-Place Saving** — Overwrite / Local / Remote output modes — Completed in v0.7.0
- ✅ **Audio Conditioning** — Flatten DTS-HD / TrueHD to AC3 for universal playback — Completed in v0.7.0
- ✅ **Smart Defaults** — Auto-select tracks based on language config profiles — Completed in v0.7.0
- ⚡ **Track Metadata** — Edit titles, set default/forced disposition flags
- 🧊 **Dry Run / Export** — Generate `.sh` scripts for remote NAS execution

## 📝 License

MIT License. See [LICENSE](LICENSE) for more details.