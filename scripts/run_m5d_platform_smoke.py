from __future__ import annotations

import argparse
import os
import subprocess
import sys


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="M5-D thin wrapper over the existing M2 MediaCrawler real-smoke harness"
    )
    parser.add_argument("--platform", choices=("bilibili", "zhihu"), required=True)
    parser.add_argument("--connector-instance", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--limit", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--confirm-real-network", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if os.environ.get("CI"):
        print("BLOCK: real platform smoke is forbidden in CI")
        raise SystemExit(2)
    if not args.confirm_real_network:
        print("BLOCK: add --confirm-real-network only after M5-D preflight has no BLOCK")
        raise SystemExit(2)
    command = [
        sys.executable,
        "-m",
        "scripts.mediacrawler_smoke",
        "--execute",
        "--platform",
        args.platform,
        "--connector-instance-id",
        args.connector_instance,
        "--source-id",
        args.source,
        "--account-id",
        args.account,
        "--mode",
        "search",
        "--requested-limit",
        str(args.limit),
        "--actor",
        args.actor,
        "--confirm",
        "M2D_REAL_SMOKE",
    ]
    completed = subprocess.run(command, check=False)  # noqa: S603 - fixed argv, no shell
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
