"""Shared, repository-scoped Docker Compose commands for local development.

This module has no knowledge of commercial applications. Each repository supplies
its own Compose file and project name through a small scripts/dev.py entry point.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def main(
    root: Path,
    *,
    project: str,
    url: str,
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("up", "down", "status", "logs", "restart", "check"))
    parser.add_argument("--timeout", type=int, default=300, help="Startup timeout in seconds.")
    parser.add_argument("--tail", type=int, default=100, help="Recent log lines per service.")
    parser.add_argument("--follow", action="store_true", help="Follow logs until Ctrl+C.")
    args = parser.parse_args(argv)
    if args.timeout < 1 or args.tail < 0:
        parser.error("--timeout must be positive and --tail must be non-negative")

    root = root.resolve()
    docker = shutil.which("docker")
    if docker is None:
        print("Docker is required. Install Docker with Compose v2 and start its engine.")
        return 1

    env_file = root / ".env"
    if not env_file.exists():
        # Exclusive creation preserves a concurrently created developer configuration.
        try:
            with env_file.open("x", encoding="utf-8") as target:
                target.write((root / ".env.example").read_text(encoding="utf-8"))
        except FileExistsError:
            pass
        print("Created local .env from .env.example; configure credentials before paid work.")

    command = [
        docker,
        "compose",
        "--project-name",
        project,
        "--project-directory",
        str(root),
        "--env-file",
        str(env_file),
        "--file",
        str(root / "compose.dev.yaml"),
    ]
    actions = {
        "up": ["up", "--detach", "--build", "--wait", "--wait-timeout", str(args.timeout)],
        # Keep databases, uploads and telemetry. Destructive volume removal is never implicit.
        "down": ["down", "--remove-orphans", "--timeout", "35"],
        "status": ["ps", "--all"],
        "logs": ["logs", "--tail", str(args.tail), *(["--follow"] if args.follow else [])],
        "restart": ["restart", "--timeout", "35", "api", "worker"],
        # Quiet validation avoids printing interpolated credentials.
        "check": ["config", "--quiet"],
    }
    try:
        result = subprocess.run([*command, *actions[args.command]], cwd=root, check=False)
    except KeyboardInterrupt:
        print("Command interrupted. Use 'status' to inspect and 'down' to stop the stack.")
        return 130
    except OSError as exc:
        print(f"Could not run Docker ({type(exc).__name__}). Check the Docker installation.")
        return 1
    if result.returncode:
        print("Command failed. Check Docker, port conflicts, then run 'status' and 'logs'.")
        return result.returncode
    if args.command == "up":
        print(f"Stack ready: {url}\nUse 'down' when finished; repeated 'up' reuses this stack.")
    return 0
