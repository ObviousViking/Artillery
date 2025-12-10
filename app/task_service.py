import json
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".svg"}

BOOLEAN_FLAGS = {
    "--write-unsupported": "write_unsupported",
    "--no-skip": "no_skip",
    "--write-metadata": "write_metadata",
    "--write-info-json": "write_info_json",
    "--write-tags": "write_tags",
}

TEXT_FLAGS = {
    "--retries": "retries",
    "--limit-rate": "limit_rate",
    "--sleep": "sleep",
    "--sleep-request": "sleep_request",
    "--sleep-429": "sleep_429",
    "--sleep-extractor": "sleep_extractor",
    "--rename": "rename",
    "--rename-to": "rename_to",
}


class TaskService:
    def __init__(
        self,
        task_dir: Path,
        download_dir: Path,
        log_dir: Path,
        config_file: Path,
        runner_task: Path,
        runner_single: Path,
        python_bin: str,
    ) -> None:
        self.task_dir = task_dir
        self.download_dir = download_dir
        self.log_dir = log_dir
        self.config_file = config_file
        self.runner_task = runner_task
        self.runner_single = runner_single
        self.python_bin = python_bin

    def list_tasks(self) -> List[Dict]:
        tasks: List[Dict] = []
        if not self.task_dir.exists():
            return tasks

        for entry in sorted(self.task_dir.iterdir()):
            if not entry.is_dir():
                continue
            task = self._build_task(entry)
            tasks.append(task)
        return tasks

    def _build_task(self, path: Path) -> Dict:
        name = path.name
        interval_file = path / "interval.txt"
        last_run_file = path / "last_run.txt"
        lockfile = path / "lockfile"
        pause_file = path / "paused.txt"
        log_file = path / "log.txt"

        interval = self._read(interval_file)
        last_run = self._read(last_run_file)

        interval_minutes = int(interval) if interval and interval.isdigit() else 0
        last_run_dt = datetime.strptime(last_run, "%Y-%m-%d %H:%M:%S") if last_run else None
        next_run = None
        if interval_minutes and last_run_dt and not pause_file.exists():
            next_run = last_run_dt + timedelta(minutes=interval_minutes)

        return {
            "name": name,
            "display_name": name.replace("_", " "),
            "interval": interval_minutes,
            "last_run": last_run if last_run else "-",
            "next_run": next_run.strftime("%Y-%m-%d %H:%M:%S") if next_run else "-",
            "status": "Running" if lockfile.exists() else "Paused" if pause_file.exists() else "Idle",
            "has_log": log_file.exists(),
            "command": self._read(path / "command.txt") or "",
        }

    def load_task(self, name: str) -> Optional[Dict]:
        path = self.task_dir / name
        if not path.is_dir():
            return None
        data = self._build_task(path)
        data.update(
            {
                "url_list": self._read(path / "url_list.txt") or "",
                "input_mode": "i",
                "flags": {value: False for value in BOOLEAN_FLAGS.values()},
                "values": {value: "" for value in TEXT_FLAGS.values()},
                "use_cookies": False,
                "use_download_archive": False,
            }
        )

        command = self._read(path / "command.txt") or ""
        parsed = self.parse_command(command)
        data.update(parsed)
        return data

    def parse_command(self, command: str) -> Dict:
        tokens = shlex.split(command)
        flags = {value: False for value in BOOLEAN_FLAGS.values()}
        values = {value: "" for value in TEXT_FLAGS.values()}
        input_mode = "i"
        use_cookies = False
        use_download_archive = False

        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token in ("-i", "-I"):
                input_mode = token[1]
            if token in BOOLEAN_FLAGS:
                flags[BOOLEAN_FLAGS[token]] = True
            if token in TEXT_FLAGS and i + 1 < len(tokens):
                values[TEXT_FLAGS[token]] = tokens[i + 1]
                i += 1
            if token == "-C" and i + 1 < len(tokens) and tokens[i + 1] == "cookies.txt":
                use_cookies = True
                i += 1
            if token == "--download-archive":
                use_download_archive = True
                i += 1
            i += 1

        return {
            "input_mode": input_mode,
            "flags": flags,
            "values": values,
            "use_cookies": use_cookies,
            "use_download_archive": use_download_archive,
        }

    def create_task(self, name: str, url_list: str, interval: int, form_data: Dict) -> None:
        safe_name = re.sub(r"[^\w\-]", "_", name.strip())
        if not safe_name:
            raise ValueError("Task name is required")
        task_path = self.task_dir / safe_name
        task_path.mkdir(parents=True, exist_ok=False)

        (task_path / "url_list.txt").write_text(url_list.strip(), encoding="utf-8")
        (task_path / "interval.txt").write_text(str(interval), encoding="utf-8")

        command = self._build_command(safe_name, task_path, form_data)
        (task_path / "command.txt").write_text(command, encoding="utf-8")

    def update_task(self, name: str, url_list: str, interval: int, form_data: Dict) -> None:
        task_path = self.task_dir / name
        if not task_path.is_dir():
            raise FileNotFoundError("Task not found")

        (task_path / "url_list.txt").write_text(url_list.strip(), encoding="utf-8")
        (task_path / "interval.txt").write_text(str(interval), encoding="utf-8")

        command = self._build_command(name, task_path, form_data)
        (task_path / "command.txt").write_text(command, encoding="utf-8")

    def _build_command(self, name: str, task_path: Path, form_data: Dict) -> str:
        input_mode = form_data.get("input_mode", "i")
        flags = []
        for cli_flag, field in BOOLEAN_FLAGS.items():
            if form_data.get(field):
                flags.append(cli_flag)

        for cli_flag, field in TEXT_FLAGS.items():
            value = form_data.get(field)
            if value:
                flags.append(cli_flag)
                flags.append(str(value))

        if form_data.get("use_cookies"):
            flags.append("-C")
            flags.append("cookies.txt")

        if form_data.get("use_download_archive"):
            flags.append("--download-archive")
            flags.append(f"{name}.sqlite")

        input_part = f"-{input_mode} url_list.txt"
        base_command = (
            "gallery-dl -f /O -d /downloads --config /config/config.json --no-input "
            "--verbose --write-log log.txt --no-part"
        )
        return " ".join([base_command, input_part, " ".join(flags)]).strip()

    def delete_task(self, name: str) -> None:
        path = self.task_dir / name
        if not path.is_dir():
            raise FileNotFoundError("Task not found")
        shutil.rmtree(path)

    def delete_archive(self, name: str) -> bool:
        archive = self.task_dir / name / f"{name}.sqlite"
        if archive.exists():
            archive.unlink()
            return True
        return False

    def toggle_pause(self, name: str) -> bool:
        pause_file = self.task_dir / name / "paused.txt"
        if pause_file.exists():
            pause_file.unlink()
            return False
        pause_file.write_text("paused", encoding="utf-8")
        return True

    def run_task(self, name: str) -> subprocess.Popen:
        task_path = self.task_dir / name
        if not task_path.is_dir():
            raise FileNotFoundError("Task not found")
        return subprocess.Popen([self.python_bin, str(self.runner_task), str(task_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def run_single(self, url: str) -> subprocess.CompletedProcess:
        if not re.match(r"^https?://", url):
            raise ValueError("Invalid URL format")
        return subprocess.run([self.python_bin, str(self.runner_single), url], capture_output=True, text=True)

    def read_log(self, name: str) -> str:
        log_path = self.task_dir / name / "log.txt"
        if log_path.exists():
            return log_path.read_text(encoding="utf-8", errors="replace")
        return "Log not found."

    def _read(self, path: Path) -> Optional[str]:
        try:
            return path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None

    def get_recent_images(self, cache_file: Path, cache_ttl: int = 120, limit: int = 200) -> List[str]:
        cache_mtime = cache_file.stat().st_mtime if cache_file.exists() else 0
        downloads_mtime = self.download_dir.stat().st_mtime if self.download_dir.exists() else 0

        if cache_file.exists() and cache_mtime >= downloads_mtime and (datetime.now().timestamp() - cache_mtime) < cache_ttl:
            try:
                cached = json.loads(cache_file.read_text())
                if isinstance(cached, dict):
                    return cached.get("images", [])[:limit]
                if isinstance(cached, list):
                    return cached[:limit]
            except Exception:
                pass

        files = [f for f in self.download_dir.glob("*") if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        images = [f.name for f in files[:limit]]

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"time": datetime.now().timestamp(), "dir_mtime": downloads_mtime, "images": images}
        cache_file.write_text(json.dumps(payload), encoding="utf-8")
        return images
