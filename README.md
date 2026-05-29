# Echo360 Downloader

Automated lecture downloading from Echo360 using Playwright and ffmpeg.

## Requirements

- **Python 3.11+**
- **[ffmpeg](https://ffmpeg.org/)** on `PATH`
- A University of Melbourne SSO account with access to Echo360 courses

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

### 1. Login (one-time, interactive)

Opens a headed browser — complete SSO in the browser window:

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

Download a single lecture by index:

```bash
uv run echo360-dl download < section-url > 5
```

Custom output directory:

```bash
uv run echo360-dl download ~/Videos/echo360 < section-url > --output-dir
```

## Output structure

```
downloads/
├── COMP90020 - Distributed Algorithms/
│   ├── March 4, 2026 - .../
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

## Commands

```
echo360-dl login                  # Interactive SSO login
echo360-dl list <url>             # List lectures in a course
echo360-dl download <url> [N]     # Download lecture N (or all)
echo360-dl download <url> --all   # Download all lectures
echo360-dl --help                 # Full help
```

## How it works

1. **Playwright** handles SSO login and session persistence
2. **Network interception** captures HLS `.m3u8` URLs from the video player
3. **ffmpeg** downloads the streams with cookie-based auth
4. Camera video (`s1`) is muxed with room audio (`s0`) since Echo360 serves it as video-only

## Error handling

- If `ffmpeg` is not installed, `echo360-dl download` prints a platform-specific install hint
- Session expiry is detected and a re-login hint is shown
- Stream downloads that time out after 60 minutes are reported individually
