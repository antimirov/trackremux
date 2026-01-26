# Changelog

All notable changes to this project will be documented in this file.

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
