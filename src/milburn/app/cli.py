"""Milburn operator command-line entry point."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from milburn import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the public CLI parser without performing any external effects."""

    parser = argparse.ArgumentParser(
        prog="milburn",
        description="Coordinate long-running Codex agents from a local control plane.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse command-line arguments and return a process exit status."""

    build_parser().parse_args(argv)
    return 0


def run() -> int:
    """Console-script adapter."""

    return main()


if __name__ == "__main__":  # pragma: no cover - exercised by the console script
    raise SystemExit(run())
