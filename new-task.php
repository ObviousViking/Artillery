<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <title>Create New Task - Artillery</title>
    <link rel="icon" href="favicon.ico" type="image/x-icon">
    <style>
    * {
        box-sizing: border-box;
    }

    body {
        background-color: #111;
        color: #eee;
        font-family: sans-serif;
        margin: 0;
        padding: 0;
    }

    .banner {
        background-color: #222;
        padding: 15px 20px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #444;
    }

    .banner .title {
        font-size: 1.8rem;
        color: #00eaff;
        font-weight: bold;
    }

    nav.nav a {
        color: #00eaff;
        margin-left: 20px;
        text-decoration: none;
        font-weight: bold;
        transition: color 0.2s ease;
    }

    nav.nav a:hover {
        text-decoration: underline;
    }

    button,
    input[type="submit"] {
        background-color: #28a745;
        color: white;
        border: none;
        padding: 10px 15px;
        border-radius: 5px;
        font-weight: bold;
        cursor: pointer;
    }

    button:hover,
    input[type="submit"]:hover {
        background-color: #218838;
    }

    main.content {
        max-width: 900px;
        margin: 20px auto;
        padding: 10px;
        background-color: #1a1a1a;
        border-radius: 10px;
        box-shadow: 0 0 10px rgba(0, 0, 0, 0.5);
    }

    label {
        font-weight: bold;
        display: block;
        margin-top: 1rem;
    }

    input[type="text"],
    textarea {
        width: 100%;
        padding: 0.5rem;
        background-color: #1e1e1e;
        color: #eee;
        border: 1px solid #00eaff;
        border-radius: 5px;
        margin-top: 0.25rem;
    }

    pre.command-preview {
        background-color: #1e1e1e;
        border: 1px solid #00eaff;
        padding: 1rem;
        color: #00eaff;
        border-radius: 5px;
        margin-top: 1rem;
    }

    .tabs {
        display: flex;
        border-bottom: 1px solid #444;
        margin-top: 2rem;
        flex-wrap: wrap;
    }

    .tabs button {
        background: none;
        border: none;
        padding: 0.75rem 1.25rem;
        cursor: pointer;
        color: #00eaff;
        border-bottom: 3px solid transparent;
        font-weight: bold;
    }

    .tabs button.active {
        border-color: #00eaff;
    }

    .tab-content {
        display: none;
        padding: 1rem 0;
    }

    .tab-content.active {
        display: block;
    }

    .flag-group {
        margin-bottom: 1rem;
    }

    .flag-group label {
        font-weight: normal;
        margin-left: 0.5rem;
    }

    small {
        display: block;
        margin-top: 0.25rem;
        color: #ccc;
    }

    small a {
        color: #00eaff;
        text-decoration: none;
    }

    small a:hover {
        text-decoration: underline;
    }
    </style>

</head>

<body>
    <?php include 'header.php'; ?>



    <main class="content">
        <h1>Create New Task</h1>
        <form method="post" action="save-task.php">
            <label>Task Name</label>
            <input type="text" name="task_name" required>

            <label>Gallery URLs (one per line)</label>
            <textarea name="url_list" rows="5" required></textarea>

            <label for="schedule">Schedule (Cron Expression)</label>
            <input type="text" name="schedule" id="schedule" required placeholder="e.g. 0 */6 * * *">
            <small style="display: block; margin-top: 0.25rem; color: #ccc;">
                Use <a href="https://crontab.guru/" target="_blank" style="color: #00eaff;">crontab.guru</a><br>
                Example: <code>0 */6 * * *</code> = every 6 hours
            </small>

            <label>Command Preview</label>
            <pre id="command_preview" class="command-preview">Generating...</pre>

            <!-- Tabbed Settings -->
            <div class="tabs">
                <button type="button">Output</button>
                <button type="button">Networking</button>
                <button type="button">Downloader</button>
                <button type="button">Post-processing</button>
                <button type="button">Cookies</button>
            </div>

            <div class="tab-content">
                <div class="flag-group">
                    <input type="checkbox" name="flag_write_unsupported">
                    <label>--write-unsupported</label>
                </div>
                <div class="flag-group">
                    <input type="checkbox" name="use_download_archive" id="use_download_archive">
                    <label for="use_download_archive">--download-archive</label>
                </div>
            </div>

            <div class="tab-content">
                <input type="text" name="retries" placeholder="--retries">
            </div>

            <div class="tab-content">
                <input type="text" name="limit_rate" placeholder="--limit-rate">
                <input type="text" name="sleep" placeholder="--sleep">
                <input type="text" name="sleep_request" placeholder="--sleep-request">
                <input type="text" name="sleep_429" placeholder="--sleep-429">
                <input type="text" name="sleep_extractor" placeholder="--sleep-extractor">
                <div class="flag-group">
                    <input type="checkbox" name="flag_no_skip">
                    <label>--no-skip</label>
                </div>
            </div>

            <div class="tab-content">
                <div class="flag-group">
                    <input type="checkbox" name="flag_write_metadata">
                    <label>--write-metadata</label>
                </div>
                <div class="flag-group">
                    <input type="checkbox" name="flag_write_info_json">
                    <label>--write-info-json</label>
                </div>
                <div class="flag-group">
                    <input type="checkbox" name="flag_write_tags">
                    <label>--write-tags</label>
                </div>
                <input type="text" name="rename" placeholder="--rename FORMAT">
                <input type="text" name="rename_to" placeholder="--rename-to FORMAT">
            </div>

            <div class="tab-content">
                <div class="flag-group">
                    <input type="checkbox" name="use_cookies">
                    <label>Use cookies.txt (place it manually in the task folder)</label>
                </div>
            </div>

            <button type="submit">Create Task</button>
        </form>
    </main>

    <script>
    function updateCommand() {
        let base = "gallery-dl -i url_list.txt -f /O --no-input --verbose --write-log log.txt --no-part";
        let flags = [];

        document.querySelectorAll("input[type=checkbox]:checked").forEach(el => {
            if (el.name.startsWith("flag_")) {
                flags.push("--" + el.name.replace("flag_", "").replace(/_/g, "-"));
            }
            if (el.name === "use_cookies") {
                flags.push("-C cookies.txt");
            }
            if (el.name === "use_download_archive") {
                const taskName = document.querySelector('[name="task_name"]').value || "taskname";
                flags.push(`--download-archive ${taskName}.sqlite`);
            }
        });

        ["retries", "limit_rate", "sleep", "sleep_request", "sleep_429", "sleep_extractor", "rename", "rename_to"]
        .forEach(name => {
            const el = document.querySelector(`[name="${name}"]`);
            if (el && el.value) {
                const flag = "--" + name.replace(/_/g, "-");
                flags.push(`${flag} ${el.value}`);
            }
        });

        document.getElementById("command_preview").textContent = base + " " + flags.join(" ");
    }

    function setupTabs() {
        const buttons = document.querySelectorAll(".tabs button");
        const contents = document.querySelectorAll(".tab-content");
        buttons.forEach((btn, i) => {
            btn.addEventListener("click", () => {
                buttons.forEach(b => b.classList.remove("active"));
                contents.forEach(c => c.classList.remove("active"));
                btn.classList.add("active");
                contents[i].classList.add("active");
            });
        });
        buttons[0].click();
    }

    function isValidCron(cron) {
        const parts = cron.trim().split(/\s+/);
        return parts.length === 5 && parts.every(p => p.length > 0);
    }

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("input, textarea").forEach(el => {
            el.addEventListener("input", updateCommand);
            el.addEventListener("change", updateCommand);
        });
        setupTabs();
        updateCommand();

        document.querySelector("form").addEventListener("submit", function(e) {
            const schedule = document.querySelector("[name='schedule']").value;
            if (!isValidCron(schedule)) {
                e.preventDefault();
                alert("Invalid cron expression. It must have 5 fields (e.g. 0 */6 * * *)");
            }
        });
    });
    </script>
</body>

</html>