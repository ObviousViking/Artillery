<?php
$task = isset($_GET['task']) ? basename($_GET['task']) : '';
$task_path = "/tasks/$task";

if (!$task || !is_dir($task_path)) {
    die("Invalid task.");
}

// Load files
$urls = file_exists("$task_path/url_list.txt") ? file_get_contents("$task_path/url_list.txt") : '';
$interval = file_exists("$task_path/interval.txt") ? intval(trim(file_get_contents("$task_path/interval.txt"))) : '';
$command_raw = file_exists("$task_path/command.txt") ? file_get_contents("$task_path/command.txt") : '';
$flags = array_values(array_filter($flags, function($f) {
    return $f !== '--config' && !str_starts_with($f, '/config/');
}));


// Parse flags
$enabled_flags = [];
$values = [];
foreach ($flags as $i => $flag) {
    if ($flag === "--write-unsupported" || $flag === "--write-metadata" || $flag === "--write-info-json" || $flag === "--write-tags" || $flag === "--no-skip") {
        $enabled_flags[] = $flag;
    }
    if ($flag === "--download-archive") {
        $enabled_flags[] = $flag;
    }
    if (in_array($flag, ["--retries", "--limit-rate", "--sleep", "--sleep-request", "--sleep-429", "--sleep-extractor", "--rename", "--rename-to"])) {
        $values[$flag] = $flags[$i + 1] ?? '';
    }
    if ($flag === "-C" && $flags[$i + 1] === "cookies.txt") {
        $enabled_flags[] = 'use_cookies';
    }
}
?>

<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <title>Edit Task - Artillery</title>
    <link rel="icon" href="favicon.ico" type="image/x-icon">
    <style>
    * {
        box-sizing: border-box;
    }

    body {
        background-color: #181818;
        color: #e0e0e0;
        font-family: 'Inter', system-ui, -apple-system, sans-serif;
        margin: 0;
        padding: 0;
        line-height: 1.5;
    }

    .banner {
        background-color: #252525;
        padding: 1rem 1.5rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #333;
    }

    .banner .title {
        font-size: 1.75rem;
        color: #00b7c3;
        font-weight: 600;
    }

    nav.nav a {
        color: #00b7c3;
        margin-left: 1.5rem;
        text-decoration: none;
        font-weight: 500;
        transition: color 0.2s ease, opacity 0.2s ease;
    }

    nav.nav a:hover {
        opacity: 0.8;
        text-decoration: underline;
    }

    button,
    input[type="submit"] {
        background: linear-gradient(135deg, #00b7c3, #008c95);
        color: #fff;
        border: none;
        padding: 0.75rem 1.5rem;
        border-radius: 6px;
        font-weight: 500;
        cursor: pointer;
        transition: transform 0.2s ease, background 0.2s ease;
    }

    button:hover,
    input[type="submit"]:hover {
        background: linear-gradient(135deg, #00c7d3, #009ca5);
        transform: scale(1.02);
    }

    main.content {
        max-width: 960px;
        margin: 2rem auto;
        padding: 2rem;
        background-color: #252525;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }

    h1 {
        font-size: 2rem;
        font-weight: 600;
        color: #e0e0e0;
        margin-bottom: 1.5rem;
    }

    label {
        font-weight: 500;
        display: block;
        margin-top: 1.25rem;
        color: #e0e0e0;
    }

    input[type="text"],
    textarea {
        width: 100%;
        padding: 0.75rem;
        background-color: #2e2e2e;
        color: #e0e0e0;
        border: 1px solid #444;
        border-radius: 6px;
        margin-top: 0.25rem;
        transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }

    input[type="text"]:focus,
    textarea:focus {
        border-color: #00b7c3;
        box-shadow: 0 0 0 2px rgba(0, 183, 195, 0.3);
        outline: none;
    }

    pre.command-preview {
        background-color: #2e2e2e;
        border: 1px solid #444;
        padding: 1rem;
        color: #00b7c3;
        border-radius: 6px;
        margin-top: 1rem;
        font-family: 'JetBrains Mono', monospace;
        white-space: pre-wrap;
        word-wrap: break-word;
    }

    .tabs {
        display: flex;
        border-bottom: 1px solid #333;
        margin-top: 2rem;
        flex-wrap: wrap;
    }

    .tabs button {
        background: none;
        border: none;
        padding: 0.75rem 1.5rem;
        cursor: pointer;
        color: #a0a0a0;
        font-weight: 500;
        border-bottom: 2px solid transparent;
        transition: color 0.2s ease, border-color 0.2s ease, background 0.2s ease;
    }

    .tabs button:hover {
        color: #e0e0e0;
        background: #2e2e2e;
    }

    .tabs button.active {
        color: #00b7c3;
        border-color: #00b7c3;
        background: #2e2e2e;
    }

    .tab-content {
        display: none;
        padding: 1.5rem 0;
    }

    .tab-content.active {
        display: block;
    }

    .flag-group {
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
    }

    .flag-group label {
        font-weight: 400;
        margin-left: 0.5rem;
        color: #e0e0e0;
    }

    small {
        display: block;
        margin-top: 0.25rem;
        color: #a0a0a0;
        font-size: 0.875rem;
    }

    small a {
        color: #00b7c3;
        text-decoration: none;
    }

    small a:hover {
        text-decoration: underline;
        opacity: 0.8;
    }
    </style>
</head>

<body>
    <?php include 'header.php'; ?>

    <main class="content">
        <h1>Edit Task: <?= htmlspecialchars(str_replace('_', ' ', $task)) ?></h1>
        <form method="post" action="update-task.php">
            <input type="hidden" name="task_name" value="<?= htmlspecialchars($task) ?>">

            <label>Gallery URLs (one per line)</label>
            <textarea name="url_list" rows="5" required><?= htmlspecialchars($urls) ?></textarea>

            <label for="interval">Run Every (Minutes)</label>
            <input type="number" name="interval" id="interval" min="1" required placeholder="e.g. 60"
                value="<?= htmlspecialchars($interval) ?>">
            <small style="display: block; margin-top: 0.25rem; color: #ccc;">
                This task will run every X minutes, starting from its last run time.
            </small>


            <label>Command Preview</label>
            <pre id="command_preview" class="command-preview">Generating...</pre>

            <div class="tabs">
                <button type="button">Output</button>
                <button type="button">Networking</button>
                <button type="button">Downloader</button>
                <button type="button">Post-processing</button>
                <button type="button">Cookies</button>
            </div>

            <div class="tab-content">
                <div class="flag-group">
                    <input type="checkbox" name="flag_write_unsupported"
                        <?= in_array('--write-unsupported', $enabled_flags) ? 'checked' : '' ?>>
                    <label>--write-unsupported</label>
                </div>
                <div class="flag-group">
                    <input type="checkbox" name="use_download_archive" id="use_download_archive"
                        <?= in_array('--download-archive', $enabled_flags) ? 'checked' : '' ?>>
                    <label for="use_download_archive">--download-archive</label>
                </div>
            </div>

            <div class="tab-content">
                <input type="text" name="retries" placeholder="--retries"
                    value="<?= htmlspecialchars($values['--retries'] ?? '') ?>">
            </div>

            <div class="tab-content">
                <input type="text" name="limit_rate" placeholder="--limit-rate"
                    value="<?= htmlspecialchars($values['--limit-rate'] ?? '') ?>">
                <input type="text" name="sleep" placeholder="--sleep"
                    value="<?= htmlspecialchars($values['--sleep'] ?? '') ?>">
                <input type="text" name="sleep_request" placeholder="--sleep-request"
                    value="<?= htmlspecialchars($values['--sleep-request'] ?? '') ?>">
                <input type="text" name="sleep_429" placeholder="--sleep-429"
                    value="<?= htmlspecialchars($values['--sleep-429'] ?? '') ?>">
                <input type="text" name="sleep_extractor" placeholder="--sleep-extractor"
                    value="<?= htmlspecialchars($values['--sleep-extractor'] ?? '') ?>">
                <div class="flag-group">
                    <input type="checkbox" name="flag_no_skip"
                        <?= in_array('--no-skip', $enabled_flags) ? 'checked' : '' ?>>
                    <label>--no-skip</label>
                </div>
            </div>

            <div class="tab-content">
                <div class="flag-group">
                    <input type="checkbox" name="flag_write_metadata"
                        <?= in_array('--write-metadata', $enabled_flags) ? 'checked' : '' ?>>
                    <label>--write-metadata</label>
                </div>
                <div class="flag-group">
                    <input type="checkbox" name="flag_write_info_json"
                        <?= in_array('--write-info-json', $enabled_flags) ? 'checked' : '' ?>>
                    <label>--write-info-json</label>
                </div>
                <div class="flag-group">
                    <input type="checkbox" name="flag_write_tags"
                        <?= in_array('--write-tags', $enabled_flags) ? 'checked' : '' ?>>
                    <label>--write-tags</label>
                </div>
                <input type="text" name="rename" placeholder="--rename FORMAT"
                    value="<?= htmlspecialchars($values['--rename'] ?? '') ?>">
                <input type="text" name="rename_to" placeholder="--rename-to FORMAT"
                    value="<?= htmlspecialchars($values['--rename-to'] ?? '') ?>">
            </div>

            <div class="tab-content">
                <div class="flag-group">
                    <input type="checkbox" name="use_cookies"
                        <?= in_array('use_cookies', $enabled_flags) ? 'checked' : '' ?>>
                    <label>Use cookies.txt (place it manually in the task folder)</label>
                </div>
            </div>

            <input type="submit" value="Update Task">
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

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("input, textarea").forEach(el => {
            el.addEventListener("input", updateCommand);
            el.addEventListener("change", updateCommand);
        });
        setupTabs();
        updateCommand();
    });
    </script>
</body>

</html>
