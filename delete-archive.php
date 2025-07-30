<?php
session_start();

$task_name = $_POST['task_name'] ?? '';
$archive_file = "/tasks/$task_name/{$task_name}.sqlite";

if ($task_name && file_exists($archive_file)) {
    unlink($archive_file);
    $_SESSION['success'] = "Download archive for '$task_name' deleted.";
} else {
    $_SESSION['error'] = "Archive not found.";
}

header("Location: tasks.php");
exit;