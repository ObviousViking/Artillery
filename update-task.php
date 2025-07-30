<?php
// update-task.php

$task_name = isset($_POST['task_name']) ? basename($_POST['task_name']) : '';
if (!$task_name) {
    die("Invalid task name.");
}

$task_path = __DIR__ . "/tasks/$task_name";
if (!is_dir($task_path)) {
    die("Task folder does not exist.");
}

// Save URL list
$url_list = $_POST['url_list'] ?? '';
file_put_contents("$task_path/url_list.txt", $url_list);

// Save schedule
$schedule = $_POST['schedule'] ?? '';
file_put_contents("$task_path/schedule.txt", trim($schedule));

// Build command
$flags = [];
$flags[] = "gallery-dl -i url_list.txt -f /O --no-input --verbose --write-log log.txt --no-part";

if (!empty($_POST['flag_write_unsupported'])) {
    $flags[] = "--write-unsupported";
}
if (!empty($_POST['use_download_archive'])) {
    $flags[] = "--download-archive $task_name.sqlite";
}
if (!empty($_POST['flag_no_skip'])) {
    $flags[] = "--no-skip";
}
if (!empty($_POST['flag_write_metadata'])) {
    $flags[] = "--write-metadata";
}
if (!empty($_POST['flag_write_info_json'])) {
    $flags[] = "--write-info-json";
}
if (!empty($_POST['flag_write_tags'])) {
    $flags[] = "--write-tags";
}
if (!empty($_POST['use_cookies'])) {
    $flags[] = "-C cookies.txt";
}

$fields = [
    'retries' => '--retries',
    'limit_rate' => '--limit-rate',
    'sleep' => '--sleep',
    'sleep_request' => '--sleep-request',
    'sleep_429' => '--sleep-429',
    'sleep_extractor' => '--sleep-extractor',
    'rename' => '--rename',
    'rename_to' => '--rename-to'
];

foreach ($fields as $field => $flag) {
    $value = trim($_POST[$field] ?? '');
    if ($value !== '') {
        $flags[] = "$flag $value";
    }
}

file_put_contents("$task_path/command.txt", implode(" ", $flags));

header("Location: tasks.php");
exit;