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

// Input options
$inputMode   = $_POST['input_mode'] ?? 'file'; // 'file' | 'filter'
$inputFile   = trim($_POST['input_file'] ?? 'url_list.txt'); // used when mode=file
$inputFilter = trim($_POST['input_filter'] ?? '');           // used when mode=filter

log_debug("Parsed: task_name = $taskName, interval = $interval, input_mode = $inputMode, input_file = $inputFile");

if (!$taskName || !$urlList || $interval < 1) {
    log_debug("❌ Missing required fields. Aborting.");
    die("Missing task name, URL list, or invalid interval.");
}

// --- CREATE TASK DIR ---
$taskDir = "/tasks/$taskName";
if (file_exists($taskDir)) {
    log_debug("❌ Task already exists: $taskDir");
    die("Task already exists.");
}

if (!mkdir($taskDir, 0777, true)) {
    log_debug("❌ Failed to create task directory: $taskDir");
    die("Failed to create task directory.");
}

// --- WRITE BASIC FILES ---
// Always save the textarea content (handy for reference even when using -I)
file_put_contents("$taskDir/url_list.txt", $urlList);
file_put_contents("$taskDir/interval.txt", $interval);

// If user chose a custom list filename for -i mode, also write it
if ($inputMode === 'file') {
    if ($inputFile === '') { $inputFile = 'url_list.txt'; }
    // If the custom filename differs, mirror the content
    if ($inputFile !== 'url_list.txt') {
        file_put_contents("$taskDir/$inputFile", $urlList);
    }
}

// --- COMMAND BASE (no hard-coded -i here) ---
$cmd = "gallery-dl -f /O --no-input --verbose --write-log log.txt --no-part";
$flags = [];

// --- BUILD INPUT PART ---
$inputPart = '';
if ($inputMode === 'file') {
    // Use -i <file>; command runs from $taskDir so we reference relative filename
    $inputPart = "-i " . escapeshellarg($inputFile ?: 'url_list.txt');
    log_debug("Input: using -i with file '$inputFile'");
} else {
    // -I <filter> <URL>; use first non-empty line from textarea
    $lines = preg_split('/\r\n|\r|\n/', $urlList);
    $firstUrl = '';
    foreach ($lines as $line) {
        $line = trim($line);
        if ($line !== '') { $firstUrl = $line; break; }
    }

    if ($firstUrl === '') {
        log_debug("❌ -I selected but no non-empty URL line found in textarea.");
        die("When using -I, the first non-empty line of the URL textarea must be a URL.");
    }
    if ($inputFilter === '') {
        log_debug("❌ -I selected but filter expression is empty.");
        die("Please provide a filter expression for -I.");
    }

    $inputPart = "-I " . escapeshellarg($inputFilter) . " " . escapeshellarg($firstUrl);
    // For convenience, also write out what URL/filter were used
    file_put_contents("$taskDir/target_url.txt", $firstUrl . PHP_EOL);
    file_put_contents("$taskDir/filter.txt", $inputFilter . PHP_EOL);
    log_debug("Input: using -I with filter and URL '$firstUrl'");
}

// --- FLAG HELPERS ---
function addFlag($key, $val = null) {
    global $flags;
    if ($val !== null && $val !== '') {
        $flags[] = "--$key " . escapeshellarg($val);
    }
}

// --- BOOLEAN FLAGS ---
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

// --- FINAL COMMAND ---
$fullCmd = trim($cmd . ' ' . $inputPart . ' ' . implode(' ', $flags));

// Persist command (runner assumes CWD = $taskDir, so relative paths are OK)
file_put_contents("$taskDir/command.txt", $fullCmd);

log_debug("✅ Task created successfully: $taskName");
log_debug("Command: $fullCmd");

header("Location: index.php");
exit;
?>