<?php
// --- DEBUG SETUP ---
$debugLog = "/tmp/artillery-debug.log";
function log_debug($msg) {
    global $debugLog;
    file_put_contents($debugLog, "[" . date('c') . "] " . $msg . "\n", FILE_APPEND);
}

log_debug("==== Incoming POST ====");
log_debug(print_r($_POST, true));

// --- BASIC CHECK ---
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    log_debug("❌ Invalid request method.");
    die("Invalid request method.");
}

// --- BASIC INPUTS ---
$taskName = preg_replace('/[^\w\-]/', '_', trim($_POST['task_name'] ?? ''));
$urlList  = trim($_POST['url_list'] ?? '');
$interval = intval($_POST['interval'] ?? 0);

log_debug("Parsed: task_name = $taskName, interval = $interval");
if (!$taskName || !$urlList || $interval < 1) {
    log_debug("❌ Missing required fields. Aborting.");
    die("Missing task name, URL list, or invalid interval.");
}

// --- CREATE TASK DIR ---
$taskDir = __DIR__ . "/tasks/$taskName";
if (file_exists($taskDir)) {
    log_debug("❌ Task already exists: $taskDir");
    die("Task already exists.");
}

if (!mkdir($taskDir, 0777, true)) {
    log_debug("❌ Failed to create task directory: $taskDir");
    die("Failed to create task directory.");
}

// --- WRITE BASIC FILES ---
file_put_contents("$taskDir/url_list.txt", $urlList);
file_put_contents("$taskDir/interval.txt", $interval);

// --- COMMAND BUILDING ---
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
    if ($key === 'flag_no_skip')           $flags[] = "--no-skip";
    if ($key === 'flag_write_metadata')    $flags[] = "--write-metadata";
    if ($key === 'flag_write_info_json')   $flags[] = "--write-info-json";
    if ($key === 'flag_write_tags')        $flags[] = "--write-tags";
    if ($key === 'use_cookies')            $flags[] = "-C cookies.txt";
    if ($key === 'use_download_archive')   $flags[] = "--download-archive " . escapeshellarg("$taskName.sqlite");
}

// --- TEXT FLAGS ---
addFlag('retries',          $_POST['retries'] ?? null);
addFlag('limit-rate',       $_POST['limit_rate'] ?? null);
addFlag('sleep',            $_POST['sleep'] ?? null);
addFlag('sleep-request',    $_POST['sleep_request'] ?? null);
addFlag('sleep-429',        $_POST['sleep_429'] ?? null);
addFlag('sleep-extractor',  $_POST['sleep_extractor'] ?? null);
addFlag('rename',           $_POST['rename'] ?? null);
addFlag('rename-to',        $_POST['rename_to'] ?? null);

if (!empty($flags)) {
    $cmd .= ' ' . implode(' ', $flags);
}

file_put_contents("$taskDir/command.txt", $cmd);
log_debug("✅ Task created successfully: $taskName");

header("Location: index.php");
exit;
?>