<?php
session_start();

$task_name = $_POST['task_name'] ?? '';
$task_path = "/tasks/$task_name";

if ($task_name && is_dir($task_path)) {
    function rrmdir($dir) {
        foreach (scandir($dir) as $item) {
            if ($item === '.' || $item === '..') continue;
            $path = "$dir/$item";
            is_dir($path) ? rrmdir($path) : unlink($path);
        }
        rmdir($dir);
    }

    rrmdir($task_path);
    $_SESSION['success'] = "Task '$task_name' deleted.";
} else {
    $_SESSION['error'] = "Task not found or invalid.";
}

header("Location: tasks.php");
exit;