#!/usr/bin/env python3
import sys
import subprocess
import os
import site
import shlex
import re
from datetime import datetime

def main():
    # Log Python environment for debugging
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {sys.version}")
    print(f"Site-packages: {site.getsitepackages()}")
    print(f"Current working directory: {os.getcwd()}")

    # Check if command is provided
    if len(sys.argv) < 2:
        print("Error: No command or URL provided", file=sys.stderr)
        sys.exit(1)

    # Get the command string
    command = sys.argv[1]
    print(f"Received command: {command}")

    # Ensure downloads directory exists (relative to project root)
    download_dir = os.path.join(os.path.dirname(__file__), "downloads")
    os.makedirs(download_dir, exist_ok=True)
    print(f"Download directory set to: {download_dir}")

    # Create lockfile in current working directory (task directory)
    lockfile = os.path.join(os.getcwd(), "lockfile")
    task_path = os.getcwd()  # Track the path for last_run.txt
    try:
        with open(lockfile, 'w') as f:
            f.write("Task running")
        print(f"Created lockfile: {lockfile}")
    except Exception as e:
        print(f"Error creating lockfile: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        # Check if input is a URL or a gallery-dl command
        is_url = bool(re.match(r'^https?://', command))
        if is_url:
            cmd = ["gallery-dl", "--dest", download_dir, "--verbose", "--no-part", command]
        else:
            try:
                args = shlex.split(command)
            except ValueError as e:
                print(f"Error parsing command: {e}", file=sys.stderr)
                sys.exit(1)

            if not args or args[0] != "gallery-dl":
                print("Error: Command must start with 'gallery-dl'", file=sys.stderr)
                sys.exit(1)

            # Replace or append --dest to ensure correct download directory
            if "-d" in args:
                d_index = args.index("-d")
                args[d_index + 1] = download_dir
            else:
                args.insert(1, "--dest")
                args.insert(2, download_dir)
            cmd = args

        print(f"Executing command with download directory: {download_dir}")

        # Run gallery-dl
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

    except subprocess.CalledProcessError as e:
        print(f"Error running gallery-dl: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("Error: gallery-dl not found. Ensure it is installed and in PATH.", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            # Remove lockfile
            if os.path.exists(lockfile):
                os.remove(lockfile)
                print(f"Removed lockfile: {lockfile}")

                # Write last_run.txt
                last_run_path = os.path.join(task_path, "last_run.txt")
                with open(last_run_path, "w", encoding="utf-8") as f:
                    f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                print(f"Updated last run timestamp at: {last_run_path}")

        except Exception as e:
            print(f"Error during cleanup: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
