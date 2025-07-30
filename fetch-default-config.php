<?php
// fetch-default-config.php

ini_set('display_errors', 1);
ini_set('display_startup_errors', 1);
error_reporting(E_ALL);
session_start();

$config_file = '/config/gallery-dl.conf';
$default_config_file = '/config/gallery-dl.default.conf';
$github_default_url = 'https://raw.githubusercontent.com/mikf/gallery-dl/master/docs/gallery-dl.conf';

$flash_messages = [];

function replace_base_directory($content) {
    return preg_replace(
        '/("base-directory"\s*:\s*")[^"]*(")/',
        '$1/downloads/$2',
        $content
    );
}

// 1. Try local default first
if (file_exists($default_config_file)) {
    $default_content = file_get_contents($default_config_file);
    if ($default_content !== false) {
        $default_content = replace_base_directory($default_content);
        if (file_put_contents($config_file, $default_content) !== false) {
            $flash_messages[] = ['success', 'Default config loaded from local copy.'];
        } else {
            $flash_messages[] = ['error', 'Failed to save local default config.'];
        }
    } else {
        $flash_messages[] = ['error', 'Error reading local default config.'];
    }
} else {
    // 2. Try GitHub
    $default_content = @file_get_contents($github_default_url);
    if ($default_content !== false) {
        $default_content = replace_base_directory($default_content);
        if (file_put_contents($config_file, $default_content) !== false) {
            $flash_messages[] = ['success', 'Default config loaded from GitHub.'];
        } else {
            $flash_messages[] = ['error', 'Failed to save GitHub config to local file.'];
        }
    } else {
        $flash_messages[] = ['error', 'Could not retrieve default config from GitHub.'];
    }
}

$_SESSION['flash_messages'] = $flash_messages;
header('Location: config.php');
exit;