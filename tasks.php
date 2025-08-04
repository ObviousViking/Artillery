<?php
session_start();

$task_dir = '/tasks';
$log_dir = '/logs';
$tasks = [];
$output = "";
$error = "";
$success = "";

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

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (isset($_POST['pause_toggle'], $_POST['task_name'])) {
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

    if (isset($_POST['run_task'], $_POST['task_name'])) {
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
}

if (is_dir($task_dir)) {
    foreach (scandir($task_dir) as $subfolder) {
        if ($subfolder === '.' || $subfolder === '..')
            continue;
        $path = "$task_dir/$subfolder";
        if (!is_dir($path))
            continue;

        $command_file = "$path/command.txt";
        $interval_file = "$path/interval.txt";
        $last_run_file = "$path/last_run.txt";
        $lockfile = "$path/lockfile";
        $pause_file = "$path/paused.txt";

        $display_name = str_replace('_', ' ', $subfolder);

        $schedule = 'Manual';
        if (file_exists($interval_file)) {
            $mins = intval(trim(file_get_contents($interval_file)));
            $schedule = $mins > 0 ? "Every $mins min" : 'Manual';
        }

        $tasks[] = [
            'name' => $subfolder,
            'display_name' => $display_name,
            'schedule' => $schedule,
            'command' => file_exists($command_file) ? trim(file_get_contents($command_file)) : '',
            'status' => file_exists($lockfile) ? 'Running' : 'Idle',
            'last_run' => file_exists($last_run_file) ? date('d M Y H:i', strtotime(trim(file_get_contents($last_run_file)))) : '-',
            'has_log' => file_exists("$path/log.txt"),
            'is_paused' => file_exists($pause_file),
        ];
    }
}
?>

<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <title>Artillery - Task List</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
    body {
        background-color: #181818;
        color: #eee;
        font-family: Arial, sans-serif;
        margin: 0;
        padding: 1rem;
    }

    table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 1rem;
    }

    th,
    td {
        border: 1px solid #444;
        padding: 0.5rem;
        text-align: left;
    }

    th {
        background-color: #222;
    }

    tr:nth-child(even) {
        background-color: #2a2a2a;
    }

    tr:hover {
        background-color: #333;
    }

    .actions button {
        background-color: #333;
        border: none;
        padding: 0.4rem 0.6rem;
        color: white;
        cursor: pointer;
        margin-right: 0.2rem;
    }
    </style>
</head>

<body>
    <h1>Task List</h1>

    <?php if ($error): ?>
    <div style="color: red;"><?= htmlspecialchars($error) ?></div>
    <?php endif; ?>
    <?php if ($success): ?>
    <div style="color: green;"><?= htmlspecialchars($success) ?></div>
    <?php endif; ?>

    <table>
        <thead>
            <tr>
                <th>Name</th>
                <th>Schedule</th>
                <th>Command</th>
                <th>Status</th>
                <th>Last Run</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            <?php foreach ($tasks as $task): ?>
            <tr>
                <td><?= htmlspecialchars($task['display_name']) ?></td>
                <td><?= htmlspecialchars($task['schedule']) ?></td>
                <td><?= htmlspecialchars($task['command']) ?></td>
                <td id="status-<?= htmlspecialchars($task['name']) ?>">
                    <?php if ($task['status'] === 'Running'): ?>
                    <i class="fas fa-spinner fa-spin" title="Running" style="color:#00e676;"></i>
                    <?php else: ?>
                    <i class="fas fa-circle" title="Idle" style="color:#888;"></i>
                    <?php endif; ?>
                </td>
                <td id="lastrun-<?= htmlspecialchars($task['name']) ?>"><?= htmlspecialchars($task['last_run']) ?></td>
                <td class="actions">
                    <form method="POST" action="" style="display:inline;">
                        <input type="hidden" name="task_name" value="<?= htmlspecialchars($task['name']) ?>">
                        <input type="hidden" name="run_task" value="1">
                        <button type="submit">Run</button>
                    </form>
                    <form method="POST" action="" style="display:inline;">
                        <input type="hidden" name="task_name" value="<?= htmlspecialchars($task['name']) ?>">
                        <input type="hidden" name="pause_toggle" value="1">
                        <button type="submit"><?= $task['is_paused'] ? 'Resume' : 'Pause' ?></button>
                    </form>
                </td>
            </tr>
            <?php endforeach; ?>
        </tbody>
    </table>

    <script>
    function updateStatuses() {
        fetch('task-statuses.php')
            .then(res => res.json())
            .then(data => {
                for (const [taskName, values] of Object.entries(data)) {
                    const statusEl = document.getElementById("status-" + taskName);
                    const runEl = document.getElementById("lastrun-" + taskName);

                    if (statusEl) {
                        statusEl.innerHTML = (values.status.toLowerCase() === 'running') ?
                            '<i class="fas fa-spinner fa-spin" title="Running" style="color:#00e676;"></i>' :
                            '<i class="fas fa-circle" title="Idle" style="color:#888;"></i>';
                    }

                    if (runEl) {
                        runEl.textContent = values.last_run || '-';
                    }
                }
            });
    }
    setInterval(updateStatuses, 5000);
    window.addEventListener('load', updateStatuses);
    </script>
</body>

</html>