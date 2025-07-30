<?php
session_start();

$task_name = basename($_POST['task_name'] ?? '');
if (!$task_name) {
    $_SESSION['error'] = "No task specified.";
    header("Location: tasks.php");
    exit;
}

$task_dir = __DIR__ . "/tasks/$task_name";
$command_file = "$task_dir/command.txt";

if (!file_exists($command_file)) {
    $_SESSION['error'] = "Command not found for task '$task_name'.";
    header("Location: tasks.php");
    exit;
}

$command = trim(file_get_contents($command_file));
$escaped_command = escapeshellarg($command);
$escaped_dir = escapeshellarg($task_dir);
$runner_path = escapeshellarg(__DIR__ . "/runner.py");

// Build the background command for Windows
$cmd = "start /B cmd /C \"cd $escaped_dir && python $runner_path $escaped_command\"";
pclose(popen($cmd, "r"));

$_SESSION['success'] = "Task '$task_name' started in background.";
header("Location: tasks.php");
exit;