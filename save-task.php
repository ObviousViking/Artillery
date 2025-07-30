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

$taskDir = __DIR__ . "/tasks/$taskName";

// Prevent overwriting
if (is_dir($taskDir)) {
    die("Task '$taskName' already exists.");
}

mkdir($taskDir, 0777, true);

// Save URL list
file_put_contents("$taskDir/url_list.txt", $urlList);

// Save schedule
file_put_contents("$taskDir/schedule.txt", $schedule);

// Build command
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

file_put_contents("$taskDir/command.txt", $command);

header("Location: tasks.php");
exit();