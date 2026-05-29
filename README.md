# Echo360 Downloader

Automated lecture downloading from Echo360 using Playwright and ffmpeg.

## Requirements

- Python 3.11+
- **[ffmpeg](https://ffmpeg.org/)** on `PATH`
- An Echo360 account (primarily designed for University of Melbourne, but should work
  for other instances too — untested)

### Windows

```powershell
# Install ffmpeg (via winget)
winget install ffmpeg

# Or manually: download from https://ffmpeg.org/download.html#build-windows
# and add the bin\ folder to your PATH

# Install uv (if not already installed)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Linux / macOS

```bash
# Debian/Ubuntu
sudo apt install ffmpeg

# macOS
brew install ffmpeg

# Arch
sudo pacman -S ffmpeg
```

## Setup

```bash
uv sync
uv run playwright install chromium
```

## Usage

### 1. Login (optional)

If you haven't logged in before, `list` and `download` will
automatically open a browser for SSO. Or run the login step explicitly:

```bash
uv run echo360-dl login
```

Session cookies are saved automatically to:

| Platform      | Location                            |
| ------------- | ----------------------------------- |
| Linux / macOS | `~/.local/state/echo360/state.json` |
| Windows       | `%LOCALAPPDATA%\echo360\state.json` |

### 2. List lectures in a course

```bash
uv run echo360-dl list <section-url>
```

### 3. Download lectures

Download all lectures:

```bash
uv run echo360-dl download <section-url>
```

Download a single lecture by index (1-based):

```bash
uv run echo360-dl download < section-url > 5
```

Custom output directory:

```bash
uv run echo360-dl download ~/Videos/echo360 < section-url > --output-dir
```

### 4. Batch download (multiple courses)

See [`batch-example.yaml`](batch-example.yaml) in the repo root for a template.

```bash
# Create a YAML file with your course URLs (or copy batch-example.yaml)
echo360-dl batch courses.yaml

# If courses.yaml doesn't exist, a template is created automatically.
```

The YAML file supports a `parallel` setting for concurrent downloads:

```yaml
parallel: 1 # sequential (default)
courses:
  - url: https://echo360.net.au/section/00000000-0000-0000-0000-000000000000
```

Set `parallel: 3` or `parallel: 4` to download multiple streams at once.
After completion the same file is updated with per-lecture status and a
per-course summary — re-run to skip already-downloaded courses.

## Output structure

```
downloads/
├── COMP90020 - Distributed Algorithms/
│   ├── 2026-03-04_15:15 - Go to class .../
│   │   ├── combined.mp4
│   │   ├── camera.mp4   (room audio muxed in)
│   │   └── audio.mp4
│   └── ...
├── SWEN90004 - Modelling Complex Software Systems/
│   └── ...
└── SWEN90016 - Software Processes and Management/
    └── ...
```

Each lecture folder contains up to 3 files:

| File           | Content                                       |
| -------------- | --------------------------------------------- |
| `combined.mp4` | PIP screen + camera + room audio              |
| `camera.mp4`   | Camera only (room audio muxed from s0 stream) |
| `audio.mp4`    | Room audio only                               |

Folders use `YYYY-MM-DD_HH:mm - Title/` format for proper chronological sorting.

## Commands

```
echo360-dl login                  Interactive SSO login
echo360-dl list <url>             List lectures in a course
echo360-dl download <url> [N]     Download lecture N (or all)
echo360-dl batch <file.yaml>      Batch download from YAML course list
echo360-dl --help                 Full help
```

## How it works

1. **Playwright** handles SSO login and session persistence
2. **Network interception** captures HLS `.m3u8` URLs from the video player
3. **ffmpeg** downloads the streams with cookie-based auth
4. Camera video (`s1`) is muxed with room audio (`s0`) since Echo360 serves it as video-only
5. **Batch mode** uses a two-phase approach: capture all M3U8 URLs serially (only one
   video can play at a time), then download all streams in parallel (configurable via
   `parallel` in the YAML)

## Error handling

- If `ffmpeg` is not installed, `echo360-dl download` prints a platform-specific install hint
- Session expiry is detected and a re-login hint is shown
- Stream downloads that time out after 60 minutes are reported individually
- Batch mode skips already-completed courses on re-run and records per-lecture outcomes
