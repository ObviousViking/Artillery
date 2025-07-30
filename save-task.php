<?php
// Basic validation
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    header("Location: new-task.php");
    exit();
}

$taskName = preg_replace('/[^\w\-]/', '_', $_POST['task_name'] ?? '');
$schedule = trim($_POST['schedule'] ?? '');
$urlList  = trim($_POST['url_list'] ?? '');

if (empty($taskName) || empty($schedule) || empty($urlList)) {
    die("Missing required fields.");
}

// Use the mounted volume path
$taskDir = "/tasks/$taskName";

// Prevent overwriting
if (is_dir($taskDir)) {
    die("Task '$taskName' already exists.");
}

// Create the task directory
if (!mkdir($taskDir, 0777, true)) {
    die("Failed to create task directory.");
}

// Save URL list
if (file_put_contents("$taskDir/url_list.txt", $urlList) === false) {
    die("Failed to write url_list.txt");
}

// Save schedule
if (file_put_contents("$taskDir/schedule.txt", $schedule) === false) {
    die("Failed to write schedule.txt");
}

// Build base command
$command = "gallery-dl -i url_list.txt -f /O -d /downloads --no-input --verbose --write-log log.txt --no-part";

$flags = [];

foreach ($_POST as $key => $value) {
    if (strpos($key, 'flag_') === 0) {
        $flag = '--' . str_replace('_', '-', substr($key, 5));
        $flags[] = $flag;
    }

    if ($key === 'use_cookies') {
        $flags[] = '-C cookies.txt';
    }

    if ($key === 'use_download_archive') {
        $flags[] = "--download-archive {$taskName}.sqlite";
    }

    // Optional values
    $optionalFlags = [
        'retries', 'limit_rate', 'sleep', 'sleep_request',
        'sleep_429', 'sleep_extractor', 'rename', 'rename_to'
    ];
    if (in_array($key, $optionalFlags) && !empty($value)) {
        $flagName = '--' . str_replace('_', '-', $key);
        $flags[] = "$flagName $value";
    }
}

if (!empty($flags)) {
    $command .= ' ' . implode(' ', $flags);
}

// Save command
if (file_put_contents("$taskDir/command.txt", $command) === false) {
    die("Failed to write command.txt");
}

header("Location: tasks.php");
exit();