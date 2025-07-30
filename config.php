<?php
// config.php (updated)
ini_set('display_errors', 1);
ini_set('display_startup_errors', 1);
error_reporting(E_ALL);

session_start();

$config_file = '/config/config.json';
$config_content = '';
$flash_messages = [];

if (file_exists($config_file)) {
    $config_content = file_get_contents($config_file);
    if ($config_content === false) {
        $flash_messages[] = ['error', 'Error reading config file.'];
    }
} else {
    $flash_messages[] = ['warning', 'Config file not found. A new one will be created on save.'];
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['config_content'])) {
    $new_content = trim($_POST['config_content']);
    json_decode($new_content);
    if (json_last_error() === JSON_ERROR_NONE) {
        if (file_put_contents($config_file, $new_content) !== false) {
            $flash_messages[] = ['success', 'Config saved successfully.'];
            $config_content = $new_content;
        } else {
            $flash_messages[] = ['error', 'Error saving config file.'];
        }
    } else {
        $flash_messages[] = ['error', 'Invalid JSON. Config not saved.'];
    }
}

if (!empty($_SESSION['flash_messages'])) {
    $flash_messages = array_merge($flash_messages, $_SESSION['flash_messages']);
    $_SESSION['flash_messages'] = [];
}
?>

<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <title>Edit Config | Artillery</title>
    <link rel="icon" href="favicon.ico" type="image/x-icon">
    <link rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono&display=swap">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">

    <style>
    * {
        box-sizing: border-box;
    }

    body {
        background-color: #181818;
        color: #e0e0e0;
        font-family: 'Inter', system-ui, -apple-system, sans-serif;
        margin: 0;
        padding: 0;
        line-height: 1.5;
    }

    .banner {
        background-color: #252525;
        padding: 1rem 1.5rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #333;
    }

    .title {
        font-size: 1.75rem;
        color: #00b7c3;
        font-weight: 600;
    }

    .nav a {
        color: #00b7c3;
        margin-left: 1.5rem;
        text-decoration: none;
        font-weight: 500;
        transition: color 0.2s ease, opacity 0.2s ease;
    }

    .nav a:hover {
        opacity: 0.8;
        text-decoration: underline;
    }

    .content {
        max-width: 1200px;
        margin: 2rem auto;
        padding: 2rem;
        background-color: #252525;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }

    h1 {
        font-size: 2rem;
        font-weight: 600;
        color: #e0e0e0;
        margin-bottom: 1.5rem;
    }

    textarea {
        width: 100%;
        padding: 0.75rem;
        background-color: #2e2e2e;
        color: #e0e0e0;
        border: 1px solid #444;
        border-radius: 6px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.9rem;
        resize: vertical;
        min-height: 400px;
        transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }

    textarea:focus {
        border-color: #00b7c3;
        box-shadow: 0 0 0 2px rgba(0, 183, 195, 0.3);
        outline: none;
    }

    .btn-save,
    .btn-default {
        padding: 0.5rem;
        border: none;
        border-radius: 6px;
        color: #fff;
        cursor: pointer;
        font-size: 0.9rem;
        line-height: 1;
        width: 2rem;
        height: 2rem;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        transition: transform 0.2s ease, background 0.2s ease, box-shadow 0.2s ease;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        position: relative;
        margin: 0.25rem;
    }

    .btn-save {
        background: linear-gradient(135deg, #00b7c3, #008c95);
    }

    .btn-save:hover {
        background: linear-gradient(135deg, #00c7d3, #009ca5);
        transform: scale(1.05);
        box-shadow: 0 3px 6px rgba(0, 0, 0, 0.3);
    }

    .btn-default {
        background: linear-gradient(135deg, #546e7a, #455a64);
    }

    .btn-default:hover {
        background: linear-gradient(135deg, #607d8b, #546e7a);
        transform: scale(1.05);
        box-shadow: 0 3px 6px rgba(0, 0, 0, 0.3);
    }

    [data-tooltip]:hover:after {
        content: attr(data-tooltip);
        position: absolute;
        bottom: 100%;
        left: 50%;
        transform: translateX(-50%);
        background: #2e2e2e;
        color: #e0e0e0;
        padding: 0.3rem 0.6rem;
        border-radius: 4px;
        font-size: 0.75rem;
        white-space: nowrap;
        z-index: 10;
        margin-bottom: 0.5rem;
    }

    .flash {
        padding: 0.75rem;
        margin-bottom: 1rem;
        border-radius: 6px;
        font-size: 0.95rem;
    }

    .flash.success {
        background-color: #2e2e2e;
        color: #2e7d32;
    }

    .flash.error {
        background-color: #2e2e2e;
        color: #ff5555;
    }

    .flash.warning {
        background-color: #2e2e2e;
        color: #f57c00;
    }

    @media (max-width: 600px) {
        .content {
            margin: 1rem;
            padding: 1.5rem;
        }

        textarea {
            padding: 0.5rem;
            font-size: 0.85rem;
        }

        .btn-save,
        .btn-default {
            padding: 0.4rem;
            width: 1.8rem;
            height: 1.8rem;
        }
    }
    </style>
</head>

<body>
    <?php include 'header.php'; ?>

    <main class="content">
        <h1>Edit gallery-dl Config</h1>

        <?php
        foreach ($flash_messages as $message) {
            list($category, $text) = $message;
            echo "<div class=\"flash $category\">" . htmlspecialchars($text) . "</div>";
        }
        ?>

        <form method="post">
            <textarea name="config_content" rows="25"><?php echo htmlspecialchars($config_content); ?></textarea>
            <div style="display: flex; gap: 0.3rem; margin-top: 1rem;">
                <button type="submit" class="btn-save" aria-label="Save Config" data-tooltip="Save Config">
                    <i class="fas fa-save"></i>
                </button>
                <a href="fetch-default-config.php" class="btn-default" aria-label="Fetch Default Config"
                    data-tooltip="Fetch Default Config">
                    <i class="fas fa-download"></i>
                </a>
            </div>
        </form>
    </main>
</body>

</html>