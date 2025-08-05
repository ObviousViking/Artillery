<?php
// Start session to retrieve messages
session_start();

// Define directories and initialize
$task_dir = '/tasks';
$log_dir = '/logs';
$tasks = [];
$output = "";
$error = "";
$success = "";

// Set server timezone to UTC for consistency
date_default_timezone_set('UTC');

// Check if this is an AJAX request for task status
if (isset($_GET['action']) && $_GET['action'] === 'get_task_status') {
    $tasks = [];
    if (is_dir($task_dir)) {
        foreach (scandir($task_dir) as $subfolder) {
            if ($subfolder === '.' || $subfolder === '..' || !is_dir("$task_dir/$subfolder")) {
                continue;
            }
            $last_run_file = "$task_dir/$subfolder/last_run.txt";
            $lockfile = "$task_dir/$subfolder/lockfile";
            $interval_file = "$task_dir/$subfolder/interval.txt";
            $pause_file = "$task_dir/$subfolder/paused.txt";
            
            $task = [
                'name' => $subfolder,
                'status' => file_exists($lockfile) ? 'Running' : 'Idle',
                'last_run' => file_exists($last_run_file) ? trim(file_get_contents($last_run_file)) : '-',
                'interval' => file_exists($interval_file) ? trim(file_get_contents($interval_file)) : '0',
                'is_paused' => file_exists($pause_file)
            ];
            
            // Calculate next run if last run and interval are available and task is not paused
            if ($task['last_run'] !== '-' && $task['interval'] !== '0' && !$task['is_paused']) {
                $last_run_time = strtotime($task['last_run']);
                $interval_minutes = (int)$task['interval'];
                $next_run_time = $last_run_time + ($interval_minutes * 60);
                $task['next_run'] = date('Y-m-d H:i:s', $next_run_time);
            } else {
                $task['next_run'] = '-';
            }
            
            $tasks[] = $task;
        }
    }
    header('Content-Type: application/json');
    echo json_encode($tasks);
    exit;
}

// Retrieve and clear session messages
if (isset($_SESSION['error'])) {
    $error = $_SESSION['error'];
    unset($_SESSION['error']);
}
if (isset($_SESSION['success'])) {
    $success = $_SESSION['success'];
    unset($_SESSION['success']);
}
if (isset($_SESSION['output'])) {
    $output = $_SESSION['output'];
    unset($_SESSION['output']);
}

// Handle pause/resume toggle
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['pause_toggle'], $_POST['task_name'])) {
    $task_name = basename($_POST['task_name']);
    $pause_file = "$task_dir/$task_name/paused.txt";

    if (file_exists($pause_file)) {
        unlink($pause_file);
        $_SESSION['success'] = "Task '$task_name' resumed.";
    } else {
        file_put_contents($pause_file, 'paused');
        $_SESSION['success'] = "Task '$task_name' paused.";
    }

    header("Location: " . $_SERVER['PHP_SELF']);
    exit();
}

// Handle manual run
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['run_task'], $_POST['task_name'])) {
    $task_name = basename($_POST['task_name']);
    $task_path = "$task_dir/$task_name";
    $command_file = "$task_path/command.txt";
    $runner = '/opt/venv/bin/python3 /var/www/html/runner-task.py';

    if (!file_exists($command_file)) {
        $_SESSION['error'] = "Task command not found.";
        header("Location: tasks.php");
        exit();
    }

    if (!file_exists($task_path)) {
        $_SESSION['error'] = "Task directory not found.";
        header("Location: tasks.php");
        exit();
    }

    $escaped_path = escapeshellarg($task_path);
    $cmd = "$runner $escaped_path 2>&1";
    $result = shell_exec($cmd);

    if ($result === null) {
        $_SESSION['error'] = "Failed to run task.";
    } else {
        file_put_contents("$log_dir/$task_name.log", "[" . date('Y-m-d H:i:s') . "]\n$cmd\n$result\n\n", FILE_APPEND);
        $_SESSION['success'] = "Task '$task_name' executed successfully.";
        $_SESSION['output'] = $result;
    }

    header("Location: tasks.php");
    exit();
}

// Load task data
if (is_dir($task_dir)) {
    foreach (scandir($task_dir) as $subfolder) {
        if ($subfolder === '.' || $subfolder === '..' || !is_dir("$task_dir/$subfolder")) {
            continue;
        }

        $command_file = "$task_dir/$subfolder/command.txt";
        $interval_file = "$task_dir/$subfolder/interval.txt";
        $last_run_file = "$task_dir/$subfolder/last_run.txt";
        $lockfile = "$task_dir/$subfolder/lockfile";
        $pause_file = "$task_dir/$subfolder/paused.txt";

        $display_name = str_replace('_', ' ', $subfolder);

        $task = [
            'name' => $subfolder,
            'display_name' => $display_name,
            'schedule' => file_exists($interval_file) ? trim(file_get_contents($interval_file)) . ' minutes' : '-',
            'command' => '',
            'status' => file_exists($lockfile) ? 'Running' : 'Idle',
            'last_run' => file_exists($last_run_file) ? trim(file_get_contents($last_run_file)) : '-',
            'has_log' => file_exists("$task_dir/$subfolder/log.txt"),
            'is_paused' => file_exists($pause_file),
            'interval' => file_exists($interval_file) ? trim(file_get_contents($interval_file)) : '0',
            'next_run' => '-'
        ];

        if ($task['last_run'] !== '-' && $task['interval'] !== '0' && !$task['is_paused']) {
            $last_run_time = strtotime($task['last_run']);
            $interval_minutes = (int)$task['interval'];
            $next_run_time = $last_run_time + ($interval_minutes * 60);
            $task['next_run'] = date('Y-m-d H:i:s', $next_run_time);
        }

        if (file_exists($command_file)) {
            $task['command'] = trim(file_get_contents($command_file));
        }

        if ($task['schedule'] !== '-' || $task['command'] !== '') {
            $tasks[] = $task;
        }
    }
}
?>

<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <title>Artillery - View Tasks</title>
    <link rel="icon" href="favicon.ico" type="image/x-icon">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono&display=swap">
    <style>
    * {
        box-sizing: border-box;
    }

    html,
    body {
        margin: 0;
        padding: 0;
        background-color: #181818;
        color: #e0e0e0;
        font-family: 'Inter', system-ui, -apple-system, sans-serif;
        line-height: 1.5;
        min-height: 100vh;
    }

    body {
        display: flex;
        flex-direction: column;
    }

    .banner {
        background-color: #252525;
        padding: 1rem 1.5rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #333;
    }

    .title {
        font-size: 1.75rem;
        color: #00b7c3;
        font-weight: 600;
    }

    .nav a {
        color: #00b7c3;
        margin-left: 1.5rem;
        text-decoration: none;
        font-weight: 500;
        transition: color 0.2s ease, opacity 0.2s ease;
    }

    .nav a:hover {
        opacity: 0.8;
        text-decoration: underline;
    }

    .content {
        max-width: 1200px;
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

    table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 1.5rem;
        background-color: #252525;
        border-radius: 6px;
        overflow: hidden;
    }

    th,
    td {
        padding: 0.75rem;
        border: 1px solid #444;
        text-align: left;
    }

    th {
        background-color: #2e2e2e;
        font-weight: 600;
        color: #e0e0e0;
        font-size: 0.95rem;
    }

    td {
        background-color: #252525;
        color: #e0e0e0;
        font-size: 0.9rem;
        transition: background 0.2s ease;
    }

    tr:hover td {
        background-color: #2e2e2e;
    }

    .overdue {
        color: #ff5555;
        font-weight: 600;
    }

    th:nth-child(1),
    td:nth-child(1) {
        width: 20%;
    }

    th:nth-child(2),
    td:nth-child(2) {
        width: 15%;
    }

    th:nth-child(3),
    td:nth-child(3) {
        width: 20%;
    }

    th:nth-child(4),
    td:nth-child(4) {
        width: 10%;
    }

    th:nth-child(5),
    td:nth-child(5) {
        width: 15%;
    }

    th:nth-child(6),
    td:nth-child(6) {
        width: 15%;
    }

    th:nth-child(7),
    td:nth-child(7) {
        width: 10%;
    }

    th:nth-child(8),
    td:nth-child(8) {
        width: 25%;
        min-width: 180px;
    }

    .actions {
        display: flex;
        flex-wrap: nowrap;
        gap: 0.3rem;
        align-items: center;
    }

    .run-btn,
    .btn-edit,
    .btn-delete,
    .btn-delete-archive,
    .btn-pause {
        padding: 0.5rem;
        border: none;
        border-radius: 6px;
        color: #fff;
        cursor: pointer;
        font-size: 0.9rem;
        line-height: 1;
        width: 2rem;
        height: 2rem;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: transform 0.2s ease, background 0.2s ease, box-shadow 0.2s ease;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
        position: relative;
    }

    .run-btn {
        background: linear-gradient(135deg, #00b7c3, #008c95);
    }

    .run-btn:hover {
        background: linear-gradient(135deg, #00c7d3, #009ca5);
        transform: scale(1.05);
        box-shadow: 0 3px 6px rgba(0, 0, 0, 0.3);
    }

    .btn-edit {
        background: linear-gradient(135deg, #1e88e5, #1565c0);
    }

    .btn-edit:hover {
        background: linear-gradient(135deg, #2196f3, #1976d2);
        transform: scale(1.05);
        box-shadow: 0 3px 6px rgba(0, 0, 0, 0.3);
    }

    .btn-delete {
        background: linear-gradient(135deg, #d32f2f, #b71c1c);
    }

    .btn-delete:hover {
        background: linear-gradient(135deg, #e53935, #c62828);
        transform: scale(1.05);
        box-shadow: 0 3px 6px rgba(0, 0, 0, 0.3);
    }

    .btn-delete-archive {
        background: linear-gradient(135deg, #f57c00, #d46b08);
    }

    .btn-delete-archive:hover {
        background: linear-gradient(135deg, #fb8c00, #e57c00);
        transform: scale(1.05);
        box-shadow: 0 3px 6px rgba(0, 0, 0, 0.3);
    }

    .btn-pause {
        background: linear-gradient(135deg, #546e7a, #455a64);
    }

    .btn-pause:hover {
        background: linear-gradient(135deg, #607d8b, #546e7a);
        transform: scale(1.05);
        box-shadow: 0 3px 6px rgba(0, 0, 0, 0.3);
    }

    [data-tooltip]:hover:after {
        content: attr(data-tooltip);
        position: absolute;
        bottom: 100%;
        left: 50%;
        transform: translateX(-50%);
        background: #2e2e2e;
        color: #e0e0e0;
        padding: 0.3rem 0.6rem;
        border-radius: 4px;
        font-size: 0.75rem;
        white-space: nowrap;
        z-index: 10;
        margin-bottom: 0.5rem;
    }

    .log-link,
    .toggle-command-link {
        color: #00b7c3;
        text-decoration: none;
        transition: opacity 0.2s ease;
    }

    .log-link:hover,
    .toggle-command-link:hover {
        opacity: 0.8;
        text-decoration: underline;
    }

    .command-preview {
        background: #2e2e2e;
        padding: 1rem;
        margin-top: 0.5rem;
        border-left: 4px solid #00b7c3;
        border-radius: 6px;
        display: none;
        font-family: 'JetBrains Mono', monospace;
        color: #00b7c3;
        font-size: 0.9rem;
        white-space: pre-wrap;
        word-wrap: break-word;
    }

    .error-message {
        color: #ff5555;
        margin: 1rem 0;
        font-size: 0.95rem;
        padding: 0.75rem;
        background: #2e2e2e;
        border-radius: 6px;
    }

    .success {
        color: #2e7d32;
        margin: 1rem 0;
        font-size: 0.95rem;
        padding: 0.75rem;
        background: #2e2e2e;
        border-radius: 6px;
    }

    footer {
        position: fixed;
        bottom: 0;
        width: 100%;
        z-index: 1000;
    }

    @media (max-width: 600px) {
        .content {
            margin: 1rem;
            padding: 1.5rem;
            padding-bottom: 4rem;
            /* Space for footer */
        }

        table {
            font-size: 0.85rem;
        }

        th,
        td {
            padding: 0.5rem;
        }

        .actions {
            flex-direction: column;
            align-items: flex-start;
        }

        .run-btn,
        .btn-edit,
        .btn-delete,
        .btn-delete-archive,
        .btn-pause {
            padding: 0.4rem;
            width: 1.8rem;
            height: 1.8rem;
        }
    }
    </style>
</head>

<body>
    <?php include 'header.php'; ?>

    <main class="content">
        <h1>Task List</h1>

        <?php if ($error): ?>
        <div class="error-message"><?= htmlspecialchars($error) ?></div>
        <?php endif; ?>

        <?php if ($success): ?>
        <div class="success"><?= htmlspecialchars($success) ?></div>
        <?php endif; ?>

        <?php if (!empty($tasks)): ?>
        <table>
            <thead>
                <tr>
                    <th scope="col">Task Name</th>
                    <th scope="col">Schedule</th>
                    <th scope="col">Command</th>
                    <th scope="col">Status</th>
                    <th scope="col">Last Run</th>
                    <th scope="col">Next Run</th>
                    <th scope="col">Log</th>
                    <th scope="col">Actions</th>
                </tr>
            </thead>
            <tbody>
                <?php foreach ($tasks as $task): ?>
                <tr data-task-name="<?= htmlspecialchars($task['name']) ?>">
                    <td><?= htmlspecialchars($task['display_name']) ?><?= $task['is_paused'] ? ' (Paused)' : '' ?></td>
                    <td><?= htmlspecialchars($task['schedule']) ?></td>
                    <td>
                        <a href="javascript:void(0);" class="toggle-command-link"
                            onclick="toggleCommand('<?= htmlspecialchars($task['name']) ?>')">Show Command</a>
                        <pre id="cmd-<?= htmlspecialchars($task['name']) ?>"
                            class="command-preview"><?= htmlspecialchars($task['command']) ?></pre>
                    </td>
                    <td class="status-cell">
                        <?php if (strtolower($task['status']) === 'running'): ?>
                        <i class="fas fa-spinner fa-spin" title="Running" style="color:#00e676;"></i>
                        <?php else: ?>
                        <i class="fas fa-circle" title="Idle" style="color:#888;"></i>
                        <?php endif; ?>
                    </td>
                    <td class="last-run-cell" data-utc-time="<?= htmlspecialchars($task['last_run']) ?>"></td>
                    <td class="next-run-cell" data-utc-time="<?= htmlspecialchars($task['next_run']) ?>"></td>
                    <td>
                        <?php if ($task['has_log']): ?>
                        <a class="log-link" href="download-log.php?task=<?= urlencode($task['name']) ?>">Download</a>
                        <?php else: ?>
                        No log
                        <?php endif; ?>
                    </td>
                    <td>
                        <div class="actions">
                            <form method="POST" action="run-task.php" style="display:inline;">
                                <input type="hidden" name="task_name" value="<?= htmlspecialchars($task['name']) ?>">
                                <button type="submit" class="run-btn" aria-label="Run Task" data-tooltip="Run">
                                    <i class="fas fa-play"></i>
                                </button>
                            </form>
                            <a href="edit-task.php?task=<?= urlencode($task['name']) ?>" class="btn-edit"
                                aria-label="Edit Task" data-tooltip="Edit">
                                <i class="fas fa-pencil-alt"></i>
                            </a>
                            <form method="POST" action="" style="display:inline;">
                                <input type="hidden" name="task_name" value="<?= htmlspecialchars($task['name']) ?>">
                                <input type="hidden" name="pause_toggle" value="1">
                                <button type="submit" class="btn-pause"
                                    aria-label="<?= $task['is_paused'] ? 'Resume Task' : 'Pause Task' ?>"
                                    data-tooltip="<?= $task['is_paused'] ? 'Resume' : 'Pause' ?>">
                                    <i class="fas <?= $task['is_paused'] ? 'fa-play' : 'fa-pause' ?>"></i>
                                </button>
                            </form>
                            <form method="POST" action="delete-task.php"
                                onsubmit="return confirmDeleteTask('<?= htmlspecialchars($task['display_name']) ?>');"
                                style="display:inline;">
                                <input type="hidden" name="task_name" value="<?= htmlspecialchars($task['name']) ?>">
                                <button type="submit" class="btn-delete" aria-label="Delete Task" data-tooltip="Delete">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </form>
                            <form method="POST" action="delete-archive.php"
                                onsubmit="return confirmDeleteArchive('<?= htmlspecialchars($task['display_name']) ?>');"
                                style="display:inline;">
                                <input type="hidden" name="task_name" value="<?= htmlspecialchars($task['name']) ?>">
                                <button type="submit" class="btn-delete-archive" aria-label="Delete Archive"
                                    data-tooltip="Delete Archive">
                                    <i class="fas fa-archive"></i>
                                </button>
                            </form>
                        </div>
                    </td>
                </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
        <?php else: ?>
        <div class="error-message">No tasks found or error reading task files.</div>
        <?php endif; ?>
    </main>

    <?php include 'footer.php'; ?>

    <script>
    function toggleCommand(taskName) {
        const el = document.getElementById("cmd-" + taskName);
        el.style.display = (el.style.display === "none") ? "block" : "none";
    }

    function confirmDeleteTask(taskName) {
        return confirm(
            `Are you sure you want to delete the entire task "${taskName}"?\nThis will NOT delete downloaded media.`
        );
    }

    function confirmDeleteArchive(taskName) {
        return confirm(
            `Are you sure you want to delete the download archive for "${taskName}"?\nThis will cause files to be re-downloaded.`
        );
    }

    // Format UTC date to local timezone in "d M Y H:i" format
    function formatDateToLocal(utcDate) {
        if (utcDate === '-' || !utcDate) {
            console.log(`No valid UTC date provided: ${utcDate}`);
            return '-';
        }
        try {
            // Parse UTC date (e.g., "2025-08-05 09:58:00")
            const [datePart, timePart] = utcDate.split(' ');
            const [year, month, day] = datePart.split('-').map(Number);
            const [hours, minutes, seconds] = timePart.split(':').map(Number);
            const utc = new Date(Date.UTC(year, month - 1, day, hours, minutes, seconds));
            if (isNaN(utc.getTime())) {
                console.error(`Invalid date parsed: ${utcDate}`);
                return '-';
            }
            const local = new Date(utc.getTime() - (utc.getTimezoneOffset() * 60000));
            const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
            const localDay = String(local.getDate()).padStart(2, '0');
            const localMonth = months[local.getMonth()];
            const localYear = local.getFullYear();
            const localHours = String(local.getHours()).padStart(2, '0');
            const localMinutes = String(local.getMinutes()).padStart(2, '0');
            const offsetMinutes = -local.getTimezoneOffset();
            const offsetHours = Math.floor(Math.abs(offsetMinutes) / 60);
            const offsetSign = offsetMinutes >= 0 ? '+' : '-';
            console.log(
                `UTC ${utcDate} -> Local: ${localDay} ${localMonth} ${localYear} ${localHours}:${localMinutes}, Offset: ${offsetSign}${offsetHours}h`
                );
            return `${localDay} ${localMonth} ${localYear} ${localHours}:${localMinutes}`;
        } catch (e) {
            console.error(`Error formatting date ${utcDate}:`, e);
            return '-';
        }
    }

    // Auto-update status, last run, and next run
    function updateTaskStatus() {
        console.log('Fetching task status...');
        fetch('?action=get_task_status')
            .then(response => {
                if (!response.ok) {
                    console.error(`Fetch error: HTTP status ${response.status} ${response.statusText}`);
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(tasks => {
                console.log('Fetched tasks:', tasks);
                tasks.forEach(task => {
                    const row = document.querySelector(`tr[data-task-name="${task.name}"]`);
                    if (row) {
                        const statusCell = row.querySelector('.status-cell');
                        const lastRunCell = row.querySelector('.last-run-cell');
                        const nextRunCell = row.querySelector('.next-run-cell');
                        const nameCell = row.querySelector('td:first-child');
                        if (statusCell) {
                            statusCell.innerHTML = task.status.toLowerCase() === 'running' ?
                                '<i class="fas fa-spinner fa-spin" title="Running" style="color:#00e676;"></i>' :
                                '<i class="fas fa-circle" title="Idle" style="color:#888;"></i>';
                        }
                        if (lastRunCell) {
                            lastRunCell.setAttribute('data-utc-time', task.last_run);
                            lastRunCell.textContent = formatDateToLocal(task.last_run);
                        }
                        if (nextRunCell) {
                            nextRunCell.setAttribute('data-utc-time', task.next_run);
                            const nextRunTime = task.next_run !== '-' ? Date.parse(task.next_run.replace(
                                ' ', 'T') + 'Z') : null;
                            const now = Date.now();
                            const isOverdue = nextRunTime && nextRunTime < now && task.status
                            .toLowerCase() !== 'running' && !task.is_paused;
                            nextRunCell.textContent = formatDateToLocal(task.next_run);
                            nextRunCell.classList.toggle('overdue', isOverdue);
                        }
                        if (nameCell) {
                            nameCell.textContent = task.is_paused ?
                                `${task.name.replace(/_/g, ' ')} (Paused)` :
                                task.name.replace(/_/g, ' ');
                        }
                    } else {
                        console.warn(`Row for task ${task.name} not found in table`);
                    }
                });
            })
            .catch(error => {
                console.error('Error fetching task status:', error);
                if (!window.fetchRetryCount) window.fetchRetryCount = 0;
                window.fetchRetryCount++;
                if (window.fetchRetryCount >= 3) {
                    console.log('Too many failed fetches, reloading page');
                    window.location.reload();
                }
            });
    }

    // Log browser timezone offset on load
    const offsetMinutes = new Date().getTimezoneOffset();
    const offsetHours = Math.floor(Math.abs(offsetMinutes) / 60);
    const offsetSign = offsetMinutes <= 0 ? '+' : '-';
    console.log(`Browser timezone offset: ${offsetSign}${offsetHours}h`);

    // Convert initial UTC times to local timezone on page load
    document.querySelectorAll('.last-run-cell, .next-run-cell').forEach(cell => {
        const utcTime = cell.getAttribute('data-utc-time');
        cell.textContent = formatDateToLocal(utcTime);
    });

    // Log content height for debugging
    window.addEventListener('load', () => {
        const content = document.querySelector('.content');
        console.log(`Content height: ${content.offsetHeight}px`);
    });

    // Poll every 5 seconds
    setInterval(updateTaskStatus, 5000);
    // Initial update
    updateTaskStatus();
    </script>
</body>

</html>