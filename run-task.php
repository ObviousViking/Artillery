<?php
session_start();

$task_name = basename($_POST['task_name'] ?? '');

if (!$task_name) {
    $_SESSION['error'] = "Task name not provided.";
    header("Location: tasks.php");
    exit();
}

$python = '/opt/venv/bin/python3';
$script = '/var/www/html/runner-task.py';
$escaped_task = escapeshellarg($task_name);
$command = "$python $script $escaped_task 2>&1";

$output = shell_exec($command);

if ($output === null) {
    $_SESSION['error'] = "Failed to execute task.";
} else {
    file_put_contents("/logs/$task_name.log", "[" . date('Y-m-d H:i:s') . "] $command\n$output\n\n", FILE_APPEND);
    $_SESSION['success'] = "Task '$task_name' started.";
    $_SESSION['output'] = $output;
}

header("Location: tasks.php");
exit();