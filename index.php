<?php
session_start();

$output = "";
$recent_images = [];
$error = "";
$success = "";

if (isset($_SESSION['error'])) {
    $error = $_SESSION['error'];
    unset($_SESSION['error']);
}
if (isset($_SESSION['success'])) {
    $success = $_SESSION['success'];
    unset($_SESSION['success']);
}

$logDir = '/logs';
$downloadsDir = '/downloads';
$cacheFile = "$logDir/image_cache.json";
$cacheTTL = 120; // seconds

foreach ([$logDir, $downloadsDir] as $dir) {
    if (!is_dir($dir)) {
        mkdir($dir, 0755, true);
    }
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $url = trim($_POST['gallery_url'] ?? '');
    if (!$url) {
        $_SESSION['error'] = "Please enter a URL.";
    } elseif (!filter_var($url, FILTER_VALIDATE_URL)) {
        $_SESSION['error'] = "Invalid URL format.";
    } else {
        $python = '/opt/venv/bin/python3';
        $script = realpath(__DIR__ . '/runner-single.py');

        if (!file_exists($script)) {
            $_SESSION['error'] = "Python script not found.";
        } else {
            $escaped_url = escapeshellarg($url);
            $command = "$python $script $escaped_url 2>&1";
            $output = shell_exec($command);

            if ($output === null) {
                $_SESSION['error'] = "Failed to execute the download script.";
            } else {
                file_put_contents("$logDir/homepage-run.log", "[" . date('Y-m-d H:i:s') . "] $command\n$output\n\n", FILE_APPEND);
                $_SESSION['success'] = "Download started successfully. Check recent images below.";
                $_SESSION['output'] = $output;
            }
        }
    }
    header("Location: index.php");
    exit;
}

if (isset($_SESSION['output'])) {
    $output = $_SESSION['output'];
    unset($_SESSION['output']);
}

$allowed_ext = ['jpg', 'jpeg', 'png'];
$recent_images = [];

if (file_exists($cacheFile) && (time() - filemtime($cacheFile) < $cacheTTL)) {
    $cached = json_decode(file_get_contents($cacheFile), true);
    if (is_array($cached)) {
        $recent_images = array_slice($cached, 0, 60);
    }
} else {
    $all_images = [];
    $dir_iterator = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($downloadsDir, RecursiveDirectoryIterator::SKIP_DOTS),
        RecursiveIteratorIterator::CHILD_FIRST
    );
    foreach ($dir_iterator as $file) {
        if ($file->isFile() && in_array(strtolower($file->getExtension()), $allowed_ext)) {
            $relativePath = str_replace(__DIR__, '', $file->getPathname());
            $all_images[$file->getMTime()] = ltrim($relativePath, '/\\');
        }
    }
    krsort($all_images);
    $recent_images = array_slice($all_images, 0, 60);
    file_put_contents($cacheFile, json_encode(array_values($all_images), JSON_UNESCAPED_SLASHES));
}
?>


<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <title>Artillery - Home</title>
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
        overflow-x: hidden;
    }

    .banner {
        background-color: #252525;
        padding: 1rem 1.5rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #333;
    }

    .banner .title {
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
        max-width: 800px;
        /* Reduced from 1200px for a more compact form */
        margin: 2rem auto;
        padding: 2rem;
        background-color: #252525;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        text-align: center;
    }

    h1 {
        font-size: 2rem;
        font-weight: 600;
        color: #e0e0e0;
        margin-bottom: 1rem;
    }

    h2 {
        font-size: 1.5rem;
        font-weight: 500;
        color: #e0e0e0;
        text-align: center;
        margin-top: 2.5rem;
        margin-bottom: 1.5rem;
    }

    p {
        color: #a0a0a0;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }

    form {
        display: flex;
        gap: 0.3rem;
        align-items: center;
        justify-content: center;
    }

    input[type="text"] {
        flex: 1;
        min-width: 0;
        padding: 0.75rem;
        background-color: #2e2e2e;
        color: #e0e0e0;
        border: 1px solid #444;
        border-radius: 6px;
        font-size: 0.9rem;
        transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }

    input[type="text"]:focus {
        border-color: #00b7c3;
        box-shadow: 0 0 0 2px rgba(0, 183, 195, 0.3);
        outline: none;
    }

    .btn-fire {
        padding: 0.5rem 1rem;
        /* Slightly larger for text */
        border: none;
        border-radius: 6px;
        color: #fff;
        cursor: pointer;
        font-family: 'Inter', system-ui, -apple-system, sans-serif;
        font-size: 0.9rem;
        font-weight: 500;
        text-transform: uppercase;
        background: linear-gradient(135deg, #00b7c3, #008c95);
        transition: transform 0.2s ease, background 0.2s ease, box-shadow 0.2s ease;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        position: relative;
    }

    .btn-fire:hover {
        background: linear-gradient(135deg, #00c7d3, #009ca5);
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

    .error,
    .success {
        padding: 0.75rem;
        border-radius: 6px;
        margin-bottom: 1rem;
        font-size: 0.95rem;
    }

    .error {
        background-color: #2e2e2e;
        color: #ff5555;
    }

    .success {
        background-color: #2e2e2e;
        color: #2e7d32;
    }

    .scroll-wall {
        display: flex;
        flex-direction: column;
        gap: 1.5rem;
        margin: 2rem auto 3rem;
        max-width: 98%;
    }

    .scroll-row {
        overflow: hidden;
        white-space: nowrap;
        position: relative;
        mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent);
    }

    .scroll-track {
        display: flex;
        gap: 0.75rem;
        will-change: transform;
        min-width: 200%;
    }

    .scroll-track img {
        width: 100px;
        height: 100px;
        object-fit: cover;
        border-radius: 6px;
        border: 1px solid #444;
        box-shadow: 0 2px 6px rgba(0, 183, 195, 0.3);
        transition: transform 0.2s ease;
    }

    .scroll-track img:hover {
        transform: scale(1.05);
    }

    .scroll-row.left .scroll-track {
        animation: scroll-left 60s linear infinite;
    }

    .scroll-row.right .scroll-track {
        animation: scroll-right 60s linear infinite;
    }

    .no-images {
        text-align: center;
        color: #00b7c3;
        font-size: 1.2rem;
        font-weight: 500;
        padding: 2rem;
        background-color: #2e2e2e;
        border-radius: 6px;
        margin: 2rem auto;
    }

    @keyframes scroll-left {
        from {
            transform: translateX(-50%);
        }

        to {
            transform: translateX(0%);
        }
    }

    @keyframes scroll-right {
        from {
            transform: translateX(0%);
        }

        to {
            transform: translateX(-50%);
        }
    }

    @media (max-width: 600px) {
        .content {
            margin: 1rem;
            padding: 1.5rem;
        }

        input[type="text"] {
            padding: 0.5rem;
            font-size: 0.85rem;
        }

        .btn-fire {
            padding: 0.4rem 0.8rem;
            /* Slightly smaller for mobile */
            font-size: 0.85rem;
        }

        .scroll-track img {
            width: 80px;
            height: 80px;
        }

        .no-images {
            font-size: 1rem;
            padding: 1.5rem;
        }
    }
    </style>
</head>

<body>
    <?php include 'header.php'; ?>

    <main class="content">
        <h1>Welcome to Artillery</h1>
        <p>Enter a gallery URL below to start firing off downloads.</p>

        <?php if ($error): ?>
        <div class="error"><?= htmlspecialchars($error) ?></div>
        <?php endif; ?>

        <?php if ($success): ?>
        <div class="success"><?= htmlspecialchars($success) ?></div>
        <?php endif; ?>

        <form action="index.php" method="post">
            <input type="text" name="gallery_url" placeholder="https://example.com/gallery" required>
            <button type="submit" class="btn-fire" aria-label="Start Download"
                data-tooltip="Start Download">FIRE</button>
        </form>
    </main>

    <h2>Recently Downloaded Images</h2>

    <div class="scroll-wall">
        <?php if (empty($recent_images)): ?>
        <div class="no-images">No images yet, time to fire up some downloads!</div>
        <?php else: ?>
        <?php
        $numRows = 3;
        $chunks = array_chunk($recent_images, ceil(count($recent_images) / $numRows));
        $directions = ['left', 'right', 'left'];

        for ($i = 0; $i < $numRows; $i++):
            $row = $chunks[$i] ?? [];
            $dir = $directions[$i % count($directions)];
            if (!empty($row)):
        ?>
        <div class="scroll-row <?= $dir ?>">
            <div class="scroll-track">
                <?php foreach (array_merge($row, $row) as $img): ?>
                <a href="<?= htmlspecialchars($img) ?>" target="_blank">
                    <img src="<?= htmlspecialchars($img) ?>" alt="Downloaded image">
                </a>
                <?php endforeach; ?>
            </div>
        </div>
        <?php endif; endfor; ?>
        <?php endif; ?>
    </div>
</body>

</html>