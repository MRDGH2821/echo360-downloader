"""Command-line interface definition."""

from __future__ import annotations

import argparse
from pathlib import Path

from echo360_downloader.utils import default_state_path


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="echo360-dl",
        description="Automated Echo360 lecture downloader",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=default_state_path(),
        help="Path to Playwright storage state file (default: ~/.local/state/echo360/state.json)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # --- login ---
    login_parser = sub.add_parser("login", help="Authenticate with SSO")
    login_parser.add_argument(
        "--headed",
        action="store_true",
        default=True,
        help="Open browser window for interactive login (default: true)",
    )

    # --- list ---
    list_parser = sub.add_parser("list", help="List lectures in a course")
    list_parser.add_argument("section_url", help="Echo360 section URL")

    # --- download ---
    dl_parser = sub.add_parser("download", help="Download lecture(s)")
    dl_parser.add_argument("section_url", help="Echo360 section URL")
    dl_parser.add_argument(
        "target",
        nargs="?",
        default="ALL",
        help='Lecture number, "ALL", or omit for all (default: ALL)',
    )
    dl_parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("downloads"),
        help="Root download directory (default: ./downloads)",
    )
    dl_parser.add_argument(
        "--headed",
        action="store_true",
        default=False,
        help="Run browser in headed mode (default: headless)",
    )

    # --- batch ---
    batch_parser = sub.add_parser("batch", help="Download all courses from a YAML file")
    batch_parser.add_argument(
        "batch_file", type=Path, help="Path to the YAML batch file"
    )
    batch_parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("downloads"),
        help="Root download directory (default: ./downloads)",
    )
    batch_parser.add_argument(
        "--headed",
        action="store_true",
        default=False,
        help="Run browser in headed mode (default: headless)",
    )

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = build_parser()
    return parser.parse_args(argv)
