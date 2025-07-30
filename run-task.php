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
$command = "$python $script $escaped_task";

$descriptorspec = [
    0 => ["pipe", "r"],                          // STDIN
    1 => ["file", "/dev/null", "a"],             // STDOUT → null
    2 => ["file", "/dev/null", "a"]              // STDERR → null
];

$process = proc_open($command, $descriptorspec, $pipes);

if (is_resource($process)) {
    proc_close($process);
    $_SESSION['success'] = "Task '$task_name' started in background.";
} else {
    $_SESSION['error'] = "Failed to launch task.";
}

header("Location: tasks.php");
exit();