<?php
// config.php

// Enable error reporting for debugging
ini_set('display_errors', 1);
ini_set('display_startup_errors', 1);
error_reporting(E_ALL);

// Start session for flashed messages
session_start();

// Initialize variables
$config_file = __DIR__ . '/config/gallery-dl.conf';
$config_content = '';
$flash_messages = [];

// Load existing config
if (file_exists($config_file)) {
    $config_content = file_get_contents($config_file);
    if ($config_content === false) {
        $flash_messages[] = ['error', 'Error reading config file.'];
    }
} else {
    $flash_messages[] = ['warning', 'Config file not found. A new one will be created on save.'];
}

// Handle form submission
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['config_content'])) {
    $new_content = trim($_POST['config_content']);
    if (file_put_contents($config_file, $new_content) !== false) {
        $flash_messages[] = ['success', 'Config saved successfully.'];
        $config_content = $new_content;
    } else {
        $flash_messages[] = ['error', 'Error saving config file.'];
    }
}

// Merge with existing flash messages (e.g., from fetch-default-config.php)
if (!empty($_SESSION['flash_messages'])) {
    $flash_messages = array_merge($flash_messages, $_SESSION['flash_messages']);
    $_SESSION['flash_messages'] = []; // Clear after merging
}
?>

<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <title>Edit Config | Artillery</title>
    <link rel="icon" href="favicon.ico" type="image/x-icon">

    <style>
    body {
        background-color: #111;
        color: #eee;
        font-family: sans-serif;
        margin: 0;
    }

    .banner {
        background: #222;
        padding: 15px 20px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .title {
        font-size: 1.8rem;
        font-weight: bold;
    }

    .nav a {
        margin-left: 15px;
        color: #00eaff;
        text-decoration: none;
    }

    .nav a:hover {
        text-decoration: underline;
    }

    .content {
        max-width: 900px;
        margin: 20px auto;
        padding: 10px;
    }

    h1 {
        font-size: 1.8rem;
        font-weight: bold;
        margin-bottom: 20px;
    }

    textarea {
        width: 90%;
        background: #1a1a1a;
        color: #00eaff;
        border: 1px solid #00eaff;
        font-family: monospace;
        font-size: 0.9rem;
        padding: 10px;
        border-radius: 4px;
        resize: vertical;
    }

    button {
        padding: 10px 20px;
        margin: 10px 5px;
        background-color: #28a745;
        color: white;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-size: 0.9rem;
    }

    button:hover {
        opacity: 0.9;
    }

    .btn-default {
        background-color: #6c757d;
    }

    .btn-default:hover {
        opacity: 0.9;
    }

    .flash {
        padding: 10px;
        margin-bottom: 15px;
        border-radius: 4px;
    }

    .flash.success {
        background-color: #28a745;
        color: white;
    }

    .flash.error {
        background-color: #dc3545;
        color: white;
    }

    .flash.warning {
        background-color: #ff8800;
        color: white;
    }
    </style>
</head>

<body>
    <?php include 'header.php'; ?>


    <main class="content">
        <h1>Edit gallery-dl Config</h1>

        <?php
        // Display flash messages
        foreach ($flash_messages as $message) {
            list($category, $text) = $message;
            echo "<div class=\"flash $category\">" . htmlspecialchars($text) . "</div>";
        }
        ?>

        <form method="post">
            <textarea name="config_content" rows="25"><?php echo htmlspecialchars($config_content); ?></textarea>
            <br><br>
            <button type="submit">Save Config</button>
        </form>

        <form method="POST" action="fetch-default-config.php">
            <button type="submit" class="btn-default">Fetch Default Config</button>
        </form>
    </main>
</body>

</html>