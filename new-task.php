<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8" />
    <title>Create New Task - Artillery</title>
    <link rel="icon" href="favicon.ico" type="image/x-icon" />
    <style>
    * {
        box-sizing: border-box;
    }

    body {
        background: #181818;
        color: #e0e0e0;
        font-family: 'Inter', system-ui, -apple-system, sans-serif;
        margin: 0;
        padding: 0;
        line-height: 1.5;
    }

    .banner {
        background: #252525;
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
        transition: color .2s, opacity .2s;
    }

    nav.nav a:hover {
        opacity: .8;
        text-decoration: underline;
    }

    button,
    input[type="submit"] {
        background: linear-gradient(135deg, #00b7c3, #008c95);
        color: #fff;
        border: 0;
        padding: .75rem 1.5rem;
        border-radius: 6px;
        font-weight: 500;
        cursor: pointer;
        transition: transform .2s, background .2s;
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
        background: #252525;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, .3);
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
    textarea,
    input[type="number"] {
        width: 100%;
        padding: .75rem;
        background: #2e2e2e;
        color: #e0e0e0;
        border: 1px solid #444;
        border-radius: 6px;
        margin-top: .25rem;
        transition: border-color .2s, box-shadow .2s;
    }

    input[type="text"]:focus,
    input[type="number"]:focus,
    textarea:focus {
        border-color: #00b7c3;
        box-shadow: 0 0 0 2px rgba(0, 183, 195, .3);
        outline: none;
    }

    pre.command-preview {
        background: #2e2e2e;
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
        gap: .25rem;
    }

    .tabs button {
        background: none;
        border: none;
        padding: .75rem 1.5rem;
        cursor: pointer;
        color: #a0a0a0;
        font-weight: 500;
        border-bottom: 2px solid transparent;
        border-radius: 6px 6px 0 0;
        transition: color .2s, border-color .2s, background .2s;
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
        padding: 1.25rem 0;
    }

    .tab-content.active {
        display: block;
    }

    .flag-group {
        margin: .75rem 0;
        display: flex;
        align-items: center;
        gap: .5rem;
        min-height: 28px;
    }

    .flag-group label {
        font-weight: 400;
        color: #e0e0e0;
        cursor: pointer;
        user-select: none;
        margin: 0;
    }

    .hint {
        display: block;
        margin-top: .25rem;
        color: #a0a0a0;
        font-size: .875rem;
    }

    /* Visible, consistent controls (no custom pseudo-elements) */
    input[type="checkbox"],
    input[type="radio"] {
        appearance: auto !important;
        /* use native control */
        width: 18px;
        height: 18px;
        margin: 0 .5rem 0 0;
        vertical-align: middle;
        accent-color: #00b7c3;
        /* tint */
        cursor: pointer;
        outline: none;
    }

    /* optional: focus ring for accessibility */
    input[type="checkbox"]:focus,
    input[type="radio"]:focus {
        box-shadow: 0 0 0 2px rgba(0, 183, 195, .35);
        border-radius: 3px;
    }


    input[type="checkbox"]::after,
    input[type="radio"]::after {
        content: "";
        position: absolute;
        inset: 3px;
        background: #00b7c3;
        display: none;
        border-radius: 2px;
    }

    input[type="checkbox"]:checked::after,
    input[type="radio"]:checked::after {
        display: block;
    }
    </style>
</head>

<body>
    <?php include 'header.php'; ?>

    <main class="content">
        <h1>Create New Task</h1>
        <form id="new-task-form" method="post" action="save-task.php">
            <label>Task Name</label>
            <input type="text" name="task_name" required />

            <label>Gallery URLs (one per line)</label>
            <textarea name="url_list" id="gallery_url" rows="5" required></textarea>

            <label for="interval">Run Every (Minutes)</label>
            <input type="number" name="interval" id="interval" min="1" required placeholder="e.g. 60" />
            <small class="hint">This task will run every X minutes, starting from its last run time.</small>

            <label>Command Preview</label>
            <pre id="command_preview" class="command-preview">Generating...</pre>

            <div class="tabs">
                <button type="button">Input Options</button>
                <button type="button">Output</button>
                <button type="button">Networking</button>
                <button type="button">Downloader</button>
                <button type="button">Post-processing</button>
                <button type="button">Cookies</button>
            </div>

            <!-- Input Options -->
            <div class="tab-content">
                <h3 style="margin:0 0 .5rem;">Input Options</h3>
                <div class="flag-group">
                    <input type="radio" name="input_mode" id="mode_i" value="i" checked />
                    <label for="mode_i">Read-only list (<code>-i url_list.txt</code>)</label>
                </div>
                <div class="flag-group">
                    <input type="radio" name="input_mode" id="mode_I" value="I" />
                    <label for="mode_I">Consumptive list (<code>-I url_list.txt</code>, comments processed
                        lines)</label>
                </div>
                <small class="hint">Both modes use <code>url_list.txt</code> in the task folder.</small>
            </div>

            <!-- Output -->
            <div class="tab-content">
                <div class="flag-group">
                    <input type="checkbox" name="flag_write_unsupported" id="flag_write_unsupported" />
                    <label for="flag_write_unsupported">--write-unsupported</label>
                </div>
                <div class="flag-group">
                    <input type="checkbox" name="use_download_archive" id="use_download_archive" />
                    <label for="use_download_archive">--download-archive</label>
                </div>
            </div>

            <!-- Networking -->
            <div class="tab-content">
                <input type="text" name="retries" placeholder="--retries" />
            </div>

            <!-- Downloader -->
            <div class="tab-content">
                <input type="text" name="limit_rate" placeholder="--limit-rate" />
                <input type="text" name="sleep" placeholder="--sleep" />
                <input type="text" name="sleep_request" placeholder="--sleep-request" />
                <input type="text" name="sleep_429" placeholder="--sleep-429" />
                <input type="text" name="sleep_extractor" placeholder="--sleep-extractor" />
                <div class="flag-group">
                    <input type="checkbox" name="flag_no_skip" id="flag_no_skip" />
                    <label for="flag_no_skip">--no-skip</label>
                </div>
            </div>

            <!-- Post-processing -->
            <div class="tab-content">
                <div class="flag-group">
                    <input type="checkbox" name="flag_write_metadata" id="flag_write_metadata" />
                    <label for="flag_write_metadata">--write-metadata</label>
                </div>
                <div class="flag-group">
                    <input type="checkbox" name="flag_write_info_json" id="flag_write_info_json" />
                    <label for="flag_write_info_json">--write-info-json</label>
                </div>
                <div class="flag-group">
                    <input type="checkbox" name="flag_write_tags" id="flag_write_tags" />
                    <label for="flag_write_tags">--write-tags</label>
                </div>
                <input type="text" name="rename" placeholder="--rename FORMAT" />
                <input type="text" name="rename_to" placeholder="--rename-to FORMAT" />
            </div>

            <!-- Cookies -->
            <div class="tab-content">
                <div class="flag-group">
                    <input type="checkbox" name="use_cookies" id="use_cookies" />
                    <label for="use_cookies">Use cookies.txt (place it manually in the task folder)</label>
                </div>
            </div>

            <button type="submit">Create Task</button>
        </form>
    </main>

    <?php include 'footer.php'; ?>

    <script>
    function updateCommand() {
        let base =
            "gallery-dl -f /O -d /downloads --config /config/config.json --no-input --verbose --write-log log.txt --no-part";
        let flags = [];

        // Input mode => -i url_list.txt OR -I url_list.txt
        const mode = document.querySelector('input[name="input_mode"]:checked')?.value || 'i';
        const inputPart = `-${mode} url_list.txt`;

        // Checkboxes
        document.querySelectorAll('input[type="checkbox"]:checked').forEach(el => {
            if (el.name.startsWith("flag_")) {
                flags.push("--" + el.name.replace("flag_", "").replace(/_/g, "-"));
            }
            if (el.name === "use_cookies") flags.push("-C cookies.txt");
            if (el.name === "use_download_archive") {
                const taskName = document.querySelector('[name="task_name"]').value || "taskname";
                flags.push(`--download-archive ${taskName}.sqlite`);
            }
        });

        // Text inputs -> flags
        ["retries", "limit_rate", "sleep", "sleep_request", "sleep_429", "sleep_extractor", "rename", "rename_to"]
        .forEach(name => {
            const el = document.querySelector(`[name="${name}"]`);
            if (el && el.value) {
                const flag = "--" + name.replace(/_/g, "-");
                flags.push(`${flag} ${el.value}`);
            }
        });

        document.getElementById("command_preview").textContent =
            `${base} ${inputPart} ${flags.join(" ")}`.trim();
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
        if (buttons.length && contents.length) {
            buttons[0].classList.add("active");
            contents[0].classList.add("active");
        }
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