# Echo360 Downloader

[![Copier](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/copier-org/copier/refs/heads/master/img/badge/black-badge.json)](https://github.com/copier-org/copier)

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

## Installation

```bash
uv tool install git+https://github.com/MRDGH2821/echo360-downloader.git
playwright install chromium
```

## Usage

### 1. Login (optional)

If you haven't logged in before, `list` and `download` will
automatically open a browser for SSO. Or run the login step explicitly:

```bash
echo360-dl login
```

Session cookies are saved automatically to:

| Platform      | Location                            |
| ------------- | ----------------------------------- |
| Linux / macOS | `~/.local/state/echo360/state.json` |
| Windows       | `%LOCALAPPDATA%\echo360\state.json` |

### 2. List lectures in a course

```bash
echo360-dl list <section-url>
```

### 3. Download lectures

#### From a course section URL

Download all lectures (interactive selection by default):

```bash
echo360-dl download <section-url>
```

Download a specific lecture by number (1-based):

```bash
echo360-dl download < section-url > 5
```

Download all lectures explicitly:

```bash
echo360-dl download < section-url > ALL
```

#### From a direct media URL

Download a single video by its public media link (no login required):

```bash
echo360-dl download https://echo360.net.au/media/ < uuid > /public
```

With a custom output name:

```bash
echo360-dl download https://echo360.net.au/media/ -n "Lecture 5 Notes" < uuid > /public
```

#### Options

| Flag               | Description                                      |
| ------------------ | ------------------------------------------------ |
| `-o, --output-dir` | Root download directory (default: `./downloads`) |
| `--headed`         | Show the browser window (default: headless)      |
| `-n, --name`       | Custom output folder name (media URLs only)      |

### 4. Batch download

Download all courses from a YAML config file:

```bash
# Create config (auto-generated if missing)
echo360-dl batch courses.yaml
```

The YAML file supports a `parallel` setting for concurrent downloads:

```yaml
parallel: 1 # sequential (default)
courses:
  - url: https://echo360.net.au/section/<uuid>
```

Set `parallel: 3` or `parallel: 4` to download multiple streams at once.

Results are written to a **separate status file** (`<config>_status.yaml`, e.g.
`courses_status.yaml`) so your original config stays clean. Re-run the same
command to skip already-completed courses — the status file is read on startup
to determine what's already done.

### 5. Compress oversized videos

If any downloaded videos are too large for submission (e.g. >500 MB), compress them:

```bash
echo360-dl compress downloads/
```

## Output structure

```
downloads/
├── COURSE001 - Example Course/
│   ├── 2026-03-04_15:15 - Go to class .../
│   │   ├── combined.mp4
│   │   ├── screen.mp4
│   │   └── camera.mp4
│   └── ...
├── COURSE002 - Example Course/
│   └── ...
└── COURSE003 - Example Course/
    └── ...
```

Each lecture folder contains up to 3 files:

| File           | Content                            |
| -------------- | ---------------------------------- |
| `combined.mp4` | Muxed camera + screen + room audio |
| `screen.mp4`   | Screen capture only (no audio)     |
| `camera.mp4`   | Presenter camera feed only         |

Direct media URL downloads create a single folder per video:

```
downloads/
└── <video title>/
    └── combined.mp4
```

## Troubleshooting

### Login fails / session expired

Delete the saved session and log in again:

```bash
rm ~/.local/state/echo360/state.json
echo360-dl login
```

### ffmpeg errors / corrupted output

Ensure ffmpeg is up to date. If downloads stall, try with `--headed` to
watch what the browser is doing.

### Downloads are very slow

Echo360 streams use CloudFront-signed URLs that expire after ~24 hours.
If a download is interrupted, re-run the command — it will start fresh
with new signed URLs.

## Licence

See [LICENCE](./LICENCE.txt)
