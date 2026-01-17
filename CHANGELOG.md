# Changelog

All notable changes to this project will be documented in this file.

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
