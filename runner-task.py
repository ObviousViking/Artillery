#!/usr/bin/env python3
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def read_command_file(task_path: Path) -> str:
    command_path = task_path / "command.txt"
    if not command_path.is_file():
        raise FileNotFoundError(f"command.txt not found in {task_path}")
    return command_path.read_text(encoding="utf-8").strip()


def update_last_run(task_path: Path) -> None:
    timestamp_path = task_path / "last_run.txt"
    timestamp_path.write_text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")


def resolve_task_path(arg: str) -> Path:
    candidate = Path(arg)
    if candidate.is_dir():
        return candidate
    task_path = Path("/tasks") / arg
    if task_path.is_dir():
        return task_path
    raise FileNotFoundError(f"Task folder not found: {arg}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: runner-task.py <task_path_or_name>", file=sys.stderr)
        sys.exit(1)

    task_path = resolve_task_path(sys.argv[1])
    task_name = task_path.name

    lockfile = task_path / "lockfile"
    if lockfile.exists():
        print(f"Task already running: {task_name}", file=sys.stderr)
        sys.exit(0)

    try:
        lockfile.write_text("Running", encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"Error creating lockfile: {e}", file=sys.stderr)
        sys.exit(1)

    command = read_command_file(task_path)
    args = command.strip().split()
    print(f"Executing: {' '.join(args)}")

    try:
        result = subprocess.run(args, cwd=task_path, capture_output=True, text=True, check=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Error running gallery-dl: {e.stderr}", file=sys.stderr)
    finally:
        if lockfile.exists():
            lockfile.unlink()
        update_last_run(task_path)


if __name__ == "__main__":
    main()
