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

<!-- Include the same HTML head & style you already have -->
<!-- Skip repeating it here for brevity -->

<!-- Inside <tbody> loop -->
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
    <td id="status-<?= htmlspecialchars($task['name']) ?>">
        <?php if (strtolower($task['status']) === 'running'): ?>
        <i class="fas fa-spinner fa-spin" title="Running" style="color:#00e676;"></i>
        <?php else: ?>
        <i class="fas fa-circle" title="Idle" style="color:#888;"></i>
        <?php endif; ?>
    </td>
    <td><?= htmlspecialchars($task['last_run']) ?></td>
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
            <a href="edit-task.php?task=<?= urlencode($task['name']) ?>" class="btn-edit" aria-label="Edit Task"
                data-tooltip="Edit">
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

<!-- Add this to bottom of the page -->
<script>
function updateStatuses() {
    fetch('task-statuses.php')
        .then(res => res.json())
        .then(data => {
            for (const [task, status] of Object.entries(data)) {
                const el = document.getElementById("status-" + task);
                if (!el) continue;
                el.innerHTML = (status.toLowerCase() === "running") ?
                    '<i class="fas fa-spinner fa-spin" title="Running" style="color:#00e676;"></i>' :
                    '<i class="fas fa-circle" title="Idle" style="color:#888;"></i>';
            }
        });
}
setInterval(updateStatuses, 5000);
window.addEventListener('load', updateStatuses);
</script>