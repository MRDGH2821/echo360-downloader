"""Styled TUI output helpers using Rich."""

from __future__ import annotations

from rich.box import MINIMAL, ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table

_console = Console()

# ---------------------------------------------------------------------------
# Exported console
# ---------------------------------------------------------------------------

console = _console


# ---------------------------------------------------------------------------
# Level-based helpers
# ---------------------------------------------------------------------------


def success(msg: str) -> None:
    """Print a green success message with a checkmark."""
    _console.print(f"[bold green]\u2713[/] {msg}")


def error(msg: str) -> None:
    """Print a red error message with a cross."""
    _console.print(f"[bold red]\u2717[/] {msg}")


def warning(msg: str) -> None:
    """Print a yellow warning message."""
    _console.print(f"[bold yellow]\u26a0[/] {msg}")


def info(msg: str) -> None:
    """Print a cyan info message."""
    _console.print(f"[cyan]\u2139[/] {msg}")


def dim(msg: str) -> None:
    """Print a dimmed status line."""
    _console.print(f"[dim]{msg}[/dim]")


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def heading(title: str) -> None:
    """Print a prominent section heading in a blue panel."""
    _console.print()
    _console.print(Panel(f"[bold cyan]{title}[/]", box=ROUNDED, border_style="blue"))


def subheading(title: str) -> None:
    """Print a non-panel sub-heading."""
    _console.print(f"\n[bold blue]\u2501 {title}[/]")


def divider(char: str = "\u2500", count: int = 50) -> None:
    """Print a dimmed horizontal divider."""
    _console.print(f"[dim]{char * count}[/dim]")


def file_size_label(size_bytes: float) -> str:
    """Format a byte count into a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


# ---------------------------------------------------------------------------
# Lecture list table
# ---------------------------------------------------------------------------


def lecture_list_table(
    lectures: list[dict],
    course_name: str,
) -> None:
    """Render the list of lectures as a styled table.

    Each dict in *lectures* is expected to have keys:
        ``date``, ``startTime``, ``ariaLabel``, ``lessonId``
    """
    table = Table(
        title=course_name,
        title_style="bold cyan",
        box=MINIMAL,
        header_style="bold blue",
        border_style="dim",
        show_lines=False,
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Date", style="cyan", width=17)
    table.add_column("Title", style="white")
    table.add_column("Lesson ID", style="dim", overflow="fold")

    for i, lec in enumerate(lectures, 1):
        dt = lec.get("date", "")
        st = lec.get("startTime", "")
        ts = f"{dt}  {st}" if dt and st else dt or "\u2014"
        title = lec.get("ariaLabel") or lec.get("text", "") or "\u2014"
        lesson_id = lec.get("lessonId", "")
        table.add_row(str(i), ts, title, lesson_id)

    _console.print(table)
    _console.print(f"[dim]{len(lectures)} lecture(s) total[/dim]")


# ---------------------------------------------------------------------------
# Progress spinner for downloads
# ---------------------------------------------------------------------------


class DownloadSpinner:
    """Context manager that shows a spinner with status updates while
    an async download runs.

    Usage::

        with DownloadSpinner() as spin:
            spin.update("Downloading combined stream...")
            await download_stream(...)
            spin.ok("Combined stream done!")
    """

    def __init__(self, description: str = "") -> None:
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None),
            TimeRemainingColumn(),
            console=_console,
        )
        self._task: TaskID | None = None
        self._description = description

    def __enter__(self) -> "DownloadSpinner":
        self._progress.start()
        if self._description:
            self._task = self._progress.add_task(self._description, total=None)
        return self

    def __exit__(self, *args: object) -> None:
        self._progress.stop()

    def update(self, description: str) -> None:
        """Update the spinner description (mid-download status)."""
        if self._task is not None:
            self._progress.update(self._task, description=description)
        else:
            self._task = self._progress.add_task(description, total=None)

    def ok(self, description: str) -> None:
        """Replace the spinner with a completed checkmark message."""
        if self._task is not None:
            self._progress.remove_task(self._task)
            self._task = None
        _console.print(f"[bold green]\u2713[/] {description}")

    def fail(self, description: str) -> None:
        """Replace the spinner with a failed cross message."""
        if self._task is not None:
            self._progress.remove_task(self._task)
            self._task = None
        _console.print(f"[bold red]\u2717[/] {description}")
