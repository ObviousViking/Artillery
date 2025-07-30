<?php
$task = isset($_GET['task']) ? basename($_GET['task']) : '';
$log_file = "/tasks/$task/log.txt";

if (!$task || !file_exists($log_file)) {
    http_response_code(404);
    echo "Log not found.";
    exit;
}

header('Content-Type: text/plain');
header('Content-Disposition: attachment; filename="' . $task . '-log.txt"');
readfile($log_file);
exit;