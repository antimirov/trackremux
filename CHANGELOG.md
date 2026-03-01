# Changelog

All notable changes to this project will be documented in this file.

## [0.8.1] - 2026-03-01

### Fixed
- **Explorer Filter Badges**: Resolved a visual bug where the explicit `DTS` badge disappeared from the 'TRACKS / AUDIO SIZE' column when the library was actively filtered by the `[D]` hotkey. DTS and `DTS>AC3` tags now persistently render when filtered.

## [0.8.0] - 2026-03-01

### Added
- **Intelligent Audio Fallback**: Advanced chain conversion. DTS-HD MA tracks now target high-quality EAC3 5.1 (1024kbps) instead of immediately downmixing to AC3. If a conversion fails due to ffmpeg encoder limitations, the system automatically catches the failure and falls back to the next codec in the chain (AC3 5.1) seamlessly.
- **Live Codec UI**: The progress header dynamically reflects the active codec processing attempt, while the completion screen appends a full visual history of fallback paths (e.g., `EAC3 5.1 ✘ (code 234) → AC3 5.1 ✔`).
- **Clean Track Formatting**: Track labels correctly present standard `Language: eng, Format: DTS-HD MA, Channels: 7.1` formatting and append exact transcoding targets cleanly `[→ EAC3 5.1]` to the tail of the string.

### Fixed
- **Accurate Progress & ETA**: Completely overhauled progress tracking during conversion. It now parses exact frame counts instead of arbitrary byte streams, resolving an issue where the progress bar would leap to 99% and ETA would read as 0.00s.
- **Dynamic File Size Estimates**: Fixed fundamentally flawed output size estimations during audio transcoding. The editor UI now accurately calculates file size reductions by dynamically swapping the original codec bitrates with encoded target bitrates, providing a realistic estimate instead of just repeating the original file size.


## [0.7.1] - 2026-02-28

### Fixed
- Fixed issue where the `[A]` Apply Profile hint didn't display correctly when evaluating boolean audio-conditioning logic alongside exact language matches.
- Minor refactors to improve TUI reliability across external track parsing edge cases.

## [0.7.0] - 2026-02-22

### Added
- **💾 Output Modes**: Introduced three save modes via an interactive `[O/L/R]` overlay dialog:
  - `[O]verwrite` — atomic in-place replacement of source files
  - `[L]ocal` — save `converted_*` files to the current working directory
  - `[R]emote` — save `converted_*` files next to the source files
  - Mode selection is remembered per session to avoid repetitive prompts.
- **📁 Smart Batch Output**: Batch conversions (TV seasons, collections) now create a `converted_<directory>/` folder with original filenames preserved inside, instead of prefixing every individual file.
- **🛡️ NAS-Safe Atomic Swaps**: All conversions write to a hidden `.trackremux_staging/` directory first, then atomically swap into place. Original files are safely moved to `.trackremux_trash/` during overwrites. Staging directories are automatically cleaned up after completion.
- **🔊 Audio Conditioning (DTS → AC3)**: Toggle `[C]` to transcode DTS/DTS-HD/TrueHD audio to universally compatible AC3 640k, ensuring Direct Play on devices like LG WebOS TVs without touching video streams.
- **⚡ Smart Default Profiles**: Configurable language preferences (`keep_langs`, `discard_langs`, `prefer_ac3_over_dts`) stored in `~/.config/trackremux/config.toml`. Interactive profile editor via `[P]` with cursor-based inline text editing and instant toggle saves. Auto-apply matching profiles to files with `[A]`.
- **🔍 Track Identity Preservation**: Injects a case-insensitive `trackremux_id` metadata tag into MKV streams for deterministic track re-mapping when reloading converted files, completely bypassing FFmpeg codec obfuscation.
- **🔐 Read-Only FS Detection**: The Save dialog automatically detects read-only source filesystems and warns users before attempting Overwrite or Remote saves.
- **📊 Contextual Save Dialog**: The Save overlay now shows exactly what will be created per mode — full output paths for single files, or directory names with file counts for batch operations.
- **🔍 Filter by DTS**: Added `[D]` hotkey to explicitly filter media list views exclusively to files with DTS-encoded formats.

### Changed
- **Batch Progress UI**: Batch conversions now show a dedicated progress view with file-by-file progress (`1/10`, `2/10`...), per-file progress bar, and a completion summary screen.

## [0.6.0] - 2026-01-26

### Added
- **🎯 Batch Processing**: Automatic detection and sequential processing of TV series and collections
  - **Smart Category Detection**: Recognizes series patterns (`S01E01`, `01x01`, `Ep01`) and groups by season.
  - **Anime-Style Support**: Smart detection of bare episode numbers (e.g., `Name 02`) with grouping logic that preserves the series context without creating redundant single-file seasons.
  - **Structural Fingerprinting**: Ensures all files in a batch share identical track configurations (video/audio/subtitle counts and languages).
  - **Batch Selector UI**: Review and select detected groups by pressing `[B]` in the Explorer view.
  - **Unified Conversion**: Edit one representative file and apply selections to the entire batch with per-file progress tracking.
- **🖱️ Comprehensive Mouse Interaction**:
  - **Fully Clickable Footer**: All footer actions across Explorer and Editor now respond to single mouse clicks.
  - **Smart Seek Controls**: Individual clickable `[←/→]` buttons in the editor for precise audio seeking.
  - **Track Reordering**: Clickable `[Shift+↑/↓]` icons in the footer to reorder tracks via mouse.
  - **Double-Click Support**: Files and directories now respond immediately to double-click without requiring prior selection.
- **📄 Version Flag**: Added `-v` / `--version` support pulling name, version, and description directly from package metadata.

### Changed
- **UI Architecture**:
  - **Split Footer Layout**: Sort controls are now left-aligned and actions right-aligned to prevent UI shifting during navigation.
  - **Simplified Navigation**: Removed the redundant header `[X]` button; all back/quit navigation is now consolidated in the footer.
- **Mouse Detection**: Switched to dynamic, position-based click detection for improved reliability across different terminal sizes.

### Fixed
- **Seek Backward**: Restored the missing `LEFT` arrow key handler in the audio preview.
- **Code Quality**: Removed all conversational/AI-generated comments for professional consistency.
- **Linting**: Resolved all `flake8` warnings regarding whitespace and indentation.

## [0.5.0] - 2026-01-25

### Added
- **Global Background Scanner**: Scanning no longer stops when navigating between folders. It runs persistently in the background.
- **Smart Prioritization**: The scanner now detects which files are visible on screen and bumps them to the front of the queue. Scrolling to "Z..." instantly scans "Z..." files.
- **Asynchronous Loading**: Large directories now open instantly with a "Loading..." spinner, eliminating startup freeze.
- **Rescan Hotkey**: Press `[R]` to force a re-scan of the current directory (bypassing cache).
- **Graceful Exit**: Added global `Ctrl+C` support to force-quit the application safely from any screen.
- **Dynamic Footer**: Context-aware footer labels (`Back` vs `Quit`).

### Fixed
- **Performance**: Fixed massive rendering lag on network drives by caching directory checks.
- **Startup**: Fixed 5+ second hang when opening large directories.
- **Consistency**: Unified `ESC`/`Q` behavior across the entire app.

## [0.4.0] - 2026-01-18

### Added
- **External Track Support**: Automatically detects audio (.ac3, .mka, etc.) and subtitle (.srt, .ass, etc.) files.
- **Recursive Scanning**: Scans `Audio/`, `Subs/` and other subdirectories (depth 2) for component files.
- **Language Detection**: Guesses track language from filenames (e.g., `movie.nld.ac3` -> Dutch) and directory names (`Subs/Eng/file.srt`). Support added for 30+ languages including Chinese, Arabic, Swahili, and more.
- **Manual Language Editing**: Select any track and press `[L]` to manually set its language code (e.g., `und` -> `eng`).
- **Robust Conversion**: 
    - Automatically forces **MKV** output for maximum compatibility.
    - Fixes "Invalid timestamp" errors for AVI source files using `-fflags +genpts`.
- **UI Enhancements**:
    - **Smart Filenames**: Truncates long filenames and removes redundant prefixes (e.g., matching movie name) for cleaner display in the list.
    - **Directory Navigation**: `FileExplorer` now supports navigating nested directories.
- **Track Reordering**: Move tracks up/down using `Shift+Up`/`Shift+Down`.
- **Mouse Support**: Complete mouse interaction for all lists and buttons.

### Changed
- **Default Selection**: External tracks are disabled by default to keep the workflow fast.
- **Navigation**: Standardized `[ESC]` / `[Q]` for Back/Quit across all views.

## [0.3.1] - 2026-01-17

### Changed
- **Entry Point**: Enabled module execution and running as uv tool.

## [0.3.0] - 2026-01-17

### Fixed
- Fixed GitHub URLs in `pyproject.toml`.

## [0.2.0] - 2026-01-17

### Trying to publish to PyPI

## [0.1.0] - 2026-01-17

- Initial release with TUI, track toggling, and basic FFmpeg conversion.
