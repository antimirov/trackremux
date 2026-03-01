# TrackRemux Roadmap

**Philosophy:** A "Surgeon's Scalpel" for media libraries. Precise, manual control with CLI speed.  
**Goal:** Optimize media for specific household needs, language preferences, and hardware compatibility without the overhead of heavy automation suites.

---

## ✅ Completed

### Batch Processing (v0.6.0)
Automatic detection and sequential processing of TV series and collections. Smart pattern matching by language tag and codec rather than absolute stream ID.

### Cross-Platform Audio Preview (partial, v0.4.0)
Audio previews use `afplay` on macOS with automatic `ffplay -nodisp` fallback on Linux. Windows PowerShell hooks remain TODO.

---

### Smart Defaults & Profile Editor (v0.7.0)
TUI-native profile editor (`[P]`) with inline field editing — Enter to start editing, cursor-based text navigation, Enter to confirm and auto-save to `~/.config/trackremux/config.toml`, Escape to discard changes. Boolean toggles save instantly on Enter/Space. Smart auto-apply via `[A]` across media series.

### Audio "Conditioning" & DTS Badges (v0.7.0)
Automatic detection and transcoding of DTS/TrueHD to universally compatible AC3 640k on the fly to bypass LG TV/console licensing restraints, without touching video. Integrated Explorer badging (`DTS>AC3`) and filter toggles.

### Intelligent Audio Fallback & Progress Engine (v0.8.0)
Upgraded the conditioning flag to target high-quality EAC3 5.1 (1024kbps) for DTS-HD MA tracks with an automatic retry net falling back to AC3 if muxing combinations fail. Completely overhauled the size estimator to dynamically calculate bitrate-level size reductions live in the TUI, built a cleaner string display `[→ EAC3 5.1]`, and fixed ffmpeg byte-progress unreliability by switching to exact frame-count ETA parsing.

### NAS-Safe Atomic Swaps & Staging (v0.7.0)
Eliminated Plex/Sonarr scanning bottlenecks by performing all active remuxing to a hidden local staging directory `.trackremux_staging/`, executing an instant, atomic file swap upon completion instead of network-heavy IO operations.

### Output Actions & Naming (v0.7.0)
Introduced `OVERWRITE`, `REMOTE` (saves `converted_*` next to source), and `LOCAL` output modes. Batch conversions create a `converted_<dir>/` directory with original filenames preserved.

---

## 🧠 Phase 3: Advanced Telemetry & Extension

### 4. Track Metadata Editing
**Problem:** Many files have missing or wrong track titles and disposition flags.
**Solution:**
- `[T]` key to edit track title metadata (e.g., "Commentary", "Director's Cut").
- `[D]` key to toggle `default` / `forced` disposition flags directly from the TUI.

### 5. Size Savings Summary
**Problem:** After batch processing, there's no summary of space recovered.
**Solution:** After conversion, show a table: `Original → Converted → Saved` per file and total.

### 6. Keyboard Shortcut Help Overlay
**Problem:** New users have no way to discover all shortcuts.
**Solution:** Press `[?]` to show a full-screen keybinding reference card.

---

## 🛠 Phase 3: Architecture & Scale
*Refactoring for maintainability, speed, and potential headless operation.*

### 7. Dry Run / Export Mode
**Feature:** Instead of invoking `ffmpeg`, export a `.sh` batch script containing all the commands.
**Use Case:** Curate the media via the TUI on a local workstation, generate the script, and then execute the script directly on the NAS via SSH to completely eliminate SMB network bottlenecks.

### 8. Headless Automation
**Feature:** Add a `--headless --config path/to/profile.toml` flag.
**Use Case:** When a new file is imported to the server, this automatically strips unwanted audio/subs and conditionally flattens DTS tracks based on your config profile, completely hands-free.

### 9. Modern TUI Migration - low level importance
**Upgrade:** Transition from `curses` to **Textual** (Python).
- **Why:** Provides robust, CSS-like styling, reactive state management, and native support for modal pop-ups for confirmation dialogs.

---

## 🧊 Backlog / Ideas

- **Undo/Restore Original**: `--restore` flag or TUI option to swap `converted_` back to original.
- **Multi-Language Streams**: Support for `mul` / dual-audio tracks (complex mapping).
- **Color Theme Support**: User-defined color pairs via config or `--theme dark/light/solarized`.
- **Plugin System for Encoders**: Custom encoder profiles beyond `copy` (e.g., HEVC re-encode at CRF 20).
- **Integration with *arr stack**: Webhook/API to notify Sonarr/Radarr after processing.
- **Statistics Dashboard**: Track cumulative space saved, files processed, most common languages.
- **Windows Audio Preview**: Native PowerShell media hooks for Windows environments.