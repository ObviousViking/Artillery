<?php
$task_dir = '/tasks';
$statuses = [];

if (is_dir($task_dir)) {
    foreach (scandir($task_dir) as $subfolder) {
        if ($subfolder === '.' || $subfolder === '..')
            continue;
        $path = "$task_dir/$subfolder";
        if (!is_dir($path))
            continue;

        $lockfile = "$path/lockfile";
        $statuses[$subfolder] = file_exists($lockfile) ? 'Running' : 'Idle';
    }
}

header('Content-Type: application/json');
echo json_encode($statuses);