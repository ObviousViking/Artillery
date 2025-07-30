<?php
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    die("Invalid request method.");
}

$taskName = preg_replace('/[^\w\-]/', '_', trim($_POST['task_name'] ?? ''));
$urlList = trim($_POST['url_list'] ?? '');
$interval = intval($_POST['interval'] ?? 0);

if (!$taskName || !$urlList || $interval < 1) {
    die("Missing task name, URL list, or invalid interval.");
}

$taskDir = __DIR__ . "/tasks/$taskName";
if (file_exists($taskDir)) {
    die("Task already exists.");
}

mkdir($taskDir, 0777, true);
file_put_contents("$taskDir/url_list.txt", $urlList);
file_put_contents("$taskDir/interval.txt", $interval);

// Build command
$cmd = "gallery-dl -i url_list.txt -f /O --no-input --verbose --write-log log.txt --no-part";

$flags = [];

function addFlag($key, $val = null) {
    global $flags;
    if (!empty($val)) {
        $flags[] = "--$key " . escapeshellarg($val);
    }
}

foreach ($_POST as $key => $val) {
    if ($key === 'flag_write_unsupported') $flags[] = "--write-unsupported";
    if ($key === 'flag_no_skip') $flags[] = "--no-skip";
    if ($key === 'flag_write_metadata') $flags[] = "--write-metadata";
    if ($key === 'flag_write_info_json') $flags[] = "--write-info-json";
    if ($key === 'flag_write_tags') $flags[] = "--write-tags";
    if ($key === 'use_cookies') $flags[] = "-C cookies.txt";
    if ($key === 'use_download_archive') {
        $flags[] = "--download-archive " . escapeshellarg("$taskName.sqlite");
    }
}

// Text inputs
addFlag('retries', $_POST['retries'] ?? null);
addFlag('limit-rate', $_POST['limit_rate'] ?? null);
addFlag('sleep', $_POST['sleep'] ?? null);
addFlag('sleep-request', $_POST['sleep_request'] ?? null);
addFlag('sleep-429', $_POST['sleep_429'] ?? null);
addFlag('sleep-extractor', $_POST['sleep_extractor'] ?? null);
addFlag('rename', $_POST['rename'] ?? null);
addFlag('rename-to', $_POST['rename_to'] ?? null);

if (!empty($flags)) {
    $cmd .= ' ' . implode(' ', $flags);
}

file_put_contents("$taskDir/command.txt", $cmd);

header("Location: index.php");
exit;
?>