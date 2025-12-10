import json
from pathlib import Path
from typing import Dict

from flask import Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request, send_from_directory, url_for

from .task_service import TaskService

bp = Blueprint("artillery", __name__)


def service() -> TaskService:
    cfg = current_app.config
    return TaskService(
        task_dir=cfg["TASK_DIR"],
        download_dir=cfg["DOWNLOAD_DIR"],
        log_dir=cfg["LOG_DIR"],
        config_file=cfg["CONFIG_FILE"],
        runner_task=cfg["RUNNER_TASK"],
        runner_single=cfg["RUNNER_SINGLE"],
        python_bin=cfg["PYTHON_BIN"],
    )


@bp.route("/", methods=["GET", "POST"])
def home() -> str:
    svc = service()
    output = None
    if request.method == "POST":
        url = request.form.get("gallery_url", "").strip()
        if not url:
            flash("Please enter a URL.", "error")
        else:
            try:
                result = svc.run_single(url)
                output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
                if result.returncode == 0:
                    flash("Download started successfully. Check recent images below.", "success")
                    cache_file = current_app.config["LOG_DIR"] / "image_cache.json"
                    svc.get_recent_images(cache_file)
                else:
                    flash("Download reported an error.", "error")
            except Exception as exc:  # noqa: BLE001
                flash(str(exc), "error")

    cache_file = current_app.config["LOG_DIR"] / "image_cache.json"
    images = svc.get_recent_images(cache_file)
    return render_template("home.html", images=images, output=output)


@bp.route("/tasks", methods=["GET"])
def list_tasks() -> str:
    svc = service()
    tasks = svc.list_tasks()
    return render_template("tasks.html", tasks=tasks)


@bp.route("/tasks/status")
def task_status() -> Response:
    svc = service()
    tasks = svc.list_tasks()
    payload = [
        {
            "name": t["name"],
            "status": t["status"],
            "last_run": t["last_run"],
            "interval": t["interval"],
            "next_run": t["next_run"],
            "is_paused": t["status"] == "Paused",
        }
        for t in tasks
    ]
    return jsonify(payload)


def _extract_form_flags(form: Dict) -> Dict:
    boolean_fields = [
        "write_unsupported",
        "no_skip",
        "write_metadata",
        "write_info_json",
        "write_tags",
        "use_cookies",
        "use_download_archive",
    ]
    text_fields = [
        "retries",
        "limit_rate",
        "sleep",
        "sleep_request",
        "sleep_429",
        "sleep_extractor",
        "rename",
        "rename_to",
    ]
    data: Dict[str, object] = {}
    for field in boolean_fields:
        data[field] = form.get(field) is not None
    for field in text_fields:
        data[field] = form.get(field, "").strip()
    data["input_mode"] = form.get("input_mode", "i")
    return data


@bp.route("/tasks/new", methods=["GET", "POST"])
def new_task() -> str:
    svc = service()
    if request.method == "POST":
        name = request.form.get("task_name", "")
        urls = request.form.get("url_list", "")
        interval = int(request.form.get("interval", 0))
        flags = _extract_form_flags(request.form)

        if not name or not urls or interval < 1:
            flash("Task name, URLs, and a valid interval are required.", "error")
        else:
            try:
                svc.create_task(name, urls, interval, flags)
                flash(f"Task '{name}' created.", "success")
                return redirect(url_for("artillery.list_tasks"))
            except FileExistsError:
                flash("Task already exists.", "error")
            except Exception as exc:  # noqa: BLE001
                flash(str(exc), "error")

    return render_template("task_form.html", mode="new", task=None, task_name="")


@bp.route("/tasks/<task_name>/edit", methods=["GET", "POST"])
def edit_task(task_name: str) -> str:
    svc = service()
    task = svc.load_task(task_name)
    if not task:
        flash("Task not found.", "error")
        return redirect(url_for("artillery.list_tasks"))

    if request.method == "POST":
        urls = request.form.get("url_list", "")
        interval = int(request.form.get("interval", 0))
        flags = _extract_form_flags(request.form)

        if not urls or interval < 1:
            flash("URL list and valid interval are required.", "error")
        else:
            try:
                svc.update_task(task_name, urls, interval, flags)
                flash(f"Task '{task_name}' updated.", "success")
                return redirect(url_for("artillery.list_tasks"))
            except Exception as exc:  # noqa: BLE001
                flash(str(exc), "error")

        task = svc.load_task(task_name)

    return render_template("task_form.html", mode="edit", task=task, task_name=task_name)


@bp.route("/tasks/<task_name>/run", methods=["POST"])
def run_task(task_name: str) -> Response:
    svc = service()
    try:
        svc.run_task(task_name)
        flash(f"Task '{task_name}' started.", "success")
    except Exception as exc:  # noqa: BLE001
        flash(str(exc), "error")
    return redirect(url_for("artillery.list_tasks"))


@bp.route("/tasks/<task_name>/pause", methods=["POST"])
def pause_task(task_name: str) -> Response:
    svc = service()
    try:
        paused = svc.toggle_pause(task_name)
        flash(("Task paused" if paused else "Task resumed") + f": {task_name}", "success")
    except Exception as exc:  # noqa: BLE001
        flash(str(exc), "error")
    return redirect(url_for("artillery.list_tasks"))


@bp.route("/tasks/<task_name>/delete", methods=["POST"])
def delete_task(task_name: str) -> Response:
    svc = service()
    try:
        svc.delete_task(task_name)
        flash(f"Task '{task_name}' deleted.", "success")
    except Exception as exc:  # noqa: BLE001
        flash(str(exc), "error")
    return redirect(url_for("artillery.list_tasks"))


@bp.route("/tasks/<task_name>/archive", methods=["POST"])
def delete_archive(task_name: str) -> Response:
    svc = service()
    if svc.delete_archive(task_name):
        flash(f"Archive for '{task_name}' deleted.", "success")
    else:
        flash("Archive not found.", "error")
    return redirect(url_for("artillery.list_tasks"))


@bp.route("/tasks/<task_name>/log")
def view_log(task_name: str) -> str:
    svc = service()
    log_contents = svc.read_log(task_name)
    return render_template("log_view.html", task_name=task_name, log_contents=log_contents)


@bp.route("/config", methods=["GET", "POST"])
def config_editor() -> str:
    cfg_file: Path = current_app.config["CONFIG_FILE"]
    current_content = cfg_file.read_text(encoding="utf-8") if cfg_file.exists() else ""

    if request.method == "POST":
        new_content = request.form.get("config_content", "")
        try:
            json.loads(new_content)
        except json.JSONDecodeError:
            flash("Invalid JSON. Config not saved.", "error")
            return render_template("config.html", content=current_content)

        if cfg_file.exists():
            backup = cfg_file.with_suffix(cfg_file.suffix + ".bak")
            backup.write_text(current_content, encoding="utf-8")

        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        cfg_file.write_text(new_content, encoding="utf-8")
        flash("Config saved successfully.", "success")
        current_content = new_content

    return render_template("config.html", content=current_content)


@bp.route("/downloads/<path:filename>")
def downloads(filename: str) -> Response:
    return send_from_directory(current_app.config["DOWNLOAD_DIR"], filename)


@bp.route("/favicon.ico")
def favicon() -> Response:
    repo_root = Path(current_app.root_path).parent
    return send_from_directory(repo_root, "favicon.ico")
