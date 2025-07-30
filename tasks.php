<?php
// Start session to retrieve messages
session_start();

// Load tasks from /tasks folder (subfolders)
$tasks = [];
$task_dir = __DIR__ . '/tasks';
$output = "";
$error = "";
$success = "";

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

if (is_dir($task_dir)) {
    foreach (scandir($task_dir) as $subfolder) {
        if ($subfolder === '.' || $subfolder === '..' || !is_dir("$task_dir/$subfolder")) {
            continue;
        }
        $command_file = "$task_dir/$subfolder/command.txt";
        $schedule_file = "$task_dir/$subfolder/schedule.txt";
        $last_run_file = "$task_dir/$subfolder/last_run.txt";
        $lockfile = "$task_dir/$subfolder/lockfile";

        $display_name = str_replace('_', ' ', $subfolder);

        $task = [
            'name' => $subfolder,
            'display_name' => $display_name,
            'schedule' => '',
            'command' => '',
            'status' => file_exists($lockfile) ? 'Running' : 'Idle',
            'last_run' => file_exists($last_run_file) ? date('d M Y H:i', strtotime(trim(file_get_contents($last_run_file)))) : '-',
            'has_log' => file_exists(__DIR__ . "/logs/$subfolder.log"),
            'is_paused' => file_exists("$task_dir/$subfolder/paused.txt")
        ];

        if (file_exists($schedule_file) && ($schedule_content = file_get_contents($schedule_file)) !== false) {
            $task['schedule'] = trim($schedule_content);
        }

        if (file_exists($command_file) && ($command_content = file_get_contents($command_file)) !== false) {
            $task['command'] = trim($command_content);
        }

        if ($task['schedule'] !== '' || $task['command'] !== '') {
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

    <style>
    body {
        background-color: #111;
        color: #eee;
        font-family: sans-serif;
        margin: 0;
    }

    .banner {
        background: #222;
        padding: 15px 20px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .title {
        font-size: 1.8rem;
        font-weight: bold;
    }

    .nav a {
        margin-left: 15px;
        color: #00eaff;
        text-decoration: none;
    }

    .nav a:hover {
        text-decoration: underline;
    }

    .content {
        max-width: 900px;
        margin: 20px auto;
        padding: 10px;
    }

    h1 {
        font-size: 1.8rem;
        font-weight: bold;
        margin-bottom: 20px;
    }

    table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 1em;
    }

    th,
    td {
        padding: 10px;
        border: 1px solid #444;
        text-align: left;
    }

    th {
        background-color: #222;
        font-weight: bold;
    }

    td {
        background-color: #111;
    }

    .run-btn,
    .btn-edit,
    .btn-delete,
    .btn-delete-archive,
    .btn-pause,
    .btn-watcher {
        padding: 10px 20px;
        margin: 2px 5px;
        background-color: #28a745;
        color: white;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        text-decoration: none;
        display: inline-block;
        font-size: 0.9rem;
    }

    .btn-edit {
        background-color: #007bff;
    }

    .btn-delete {
        background-color: #dc3545;
    }

    .btn-delete-archive {
        background-color: #ff8800;
    }

    .btn-pause {
        background-color: #6c757d;
    }

    .btn-watcher {
        background-color: #17a2b8;
    }

    .run-btn:hover,
    .btn-edit:hover,
    .btn-delete:hover,
    .btn-delete-archive:hover,
    .btn-pause:hover,
    .btn-watcher:hover {
        opacity: 0.9;
    }

    .log-link,
    .toggle-command-link {
        color: #00eaff;
        text-decoration: none;
    }

    .log-link:hover,
    .toggle-command-link:hover {
        text-decoration: underline;
    }

    .command-preview {
        background: #1e1e1e;
        padding: 15px;
        margin-top: 10px;
        border-left: 4px solid #00eaff;
        border-radius: 5px;
        display: none;
    }

    .error-message {
        color: #ff5555;
        margin: 10px 0;
    }

    .success {
        color: #28a745;
        margin: 10px 0;
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
                    <th>Task Name</th>
                    <th>Schedule</th>
                    <th>Command</th>
                    <th>Status</th>
                    <th>Last Run</th>
                    <th>Log</th>
                    <th>Action</th>
                    <th>Active</th>
                    <th>Danger Zone</th>
                </tr>
            </thead>
            <tbody>
                <?php foreach ($tasks as $task): ?>
                <tr>
                    <td><?= htmlspecialchars($task['display_name']) ?></td>
                    <td><?= htmlspecialchars($task['schedule']) ?></td>
                    <td>
                        <a href="javascript:void(0);" class="toggle-command-link"
                            onclick="toggleCommand('<?= htmlspecialchars($task['name']) ?>')">Show Command</a>
                        <pre id="cmd-<?= htmlspecialchars($task['name']) ?>"
                            class="command-preview"><?= htmlspecialchars($task['command']) ?></pre>
                    </td>
                    <td><?= htmlspecialchars($task['status']) ?></td>
                    <td><?= htmlspecialchars($task['last_run']) ?></td>
                    <td>
                        <?php if ($task['has_log']): ?>
                        <a class="log-link" href="logs/<?= urlencode($task['name']) ?>.log">Download</a>
                        <?php else: ?>
                        No log
                        <?php endif; ?>
                    </td>
                    <td>
                        <a href="edit-task.php?task=<?= urlencode($task['name']) ?>" class="btn-edit">Edit</a>
                        <form method="POST" action="run-task.php" style="display:inline;">
                            <input type="hidden" name="task_name" value="<?= htmlspecialchars($task['name']) ?>">
                            <button type="submit" class="run-btn">Run</button>
                        </form>
                    </td>
                    <td>
                        <form method="POST" action="" style="display:inline;">
                            <input type="hidden" name="task_name" value="<?= htmlspecialchars($task['name']) ?>">
                            <input type="hidden" name="pause_toggle" value="1">
                            <button type="submit" class="btn-pause">
                                <?= $task['is_paused'] ? 'Resume' : 'Pause' ?>
                            </button>
                        </form>
                    </td>
                    <td>
                        <form method="POST" action="delete-task.php"
                            onsubmit="return confirmDeleteTask('<?= htmlspecialchars($task['display_name']) ?>');">
                            <input type="hidden" name="task_name" value="<?= htmlspecialchars($task['name']) ?>">
                            <button type="submit" class="btn-delete">Delete</button>
                        </form>
                        <form method="POST" action="delete-archive.php"
                            onsubmit="return confirmDeleteArchive('<?= htmlspecialchars($task['display_name']) ?>');">
                            <input type="hidden" name="task_name" value="<?= htmlspecialchars($task['name']) ?>">
                            <button type="submit" class="btn-delete-archive">Delete Archive</button>
                        </form>
                    </td>
                </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
        <?php else: ?>
        <div class="error-message">No tasks found or error reading task files.</div>
        <?php endif; ?>
    </main>

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
    </script>
</body>

</html>