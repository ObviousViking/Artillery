<?php
// Start session to store messages
session_start();

$output = "";
$recent_images = [];
$error = "";
$success = "";

// Retrieve and clear session messages
if (isset($_SESSION['error'])) {
    $error = $_SESSION['error'];
    unset($_SESSION['error']);
}
if (isset($_SESSION['success'])) {
    $success = $_SESSION['success'];
    unset($_SESSION['success']);
}

// Ensure logs and downloads directories exist
$logDir = realpath(__DIR__ . DIRECTORY_SEPARATOR . 'logs');
$downloadsDir = realpath(__DIR__ . DIRECTORY_SEPARATOR . 'downloads');
foreach ([$logDir, $downloadsDir] as $dir) {
    if (!is_dir($dir)) {
        mkdir($dir, 0755, true);
    }
}

// Handle form submission
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $url = trim($_POST['gallery_url'] ?? '');
    if (!$url) {
        $_SESSION['error'] = "Please enter a URL.";
    } elseif (!filter_var($url, FILTER_VALIDATE_URL)) {
        $_SESSION['error'] = "Invalid URL format.";
    } else {
        $python = '"C:\\Program Files\\Python313\\python.exe"';
        $script = realpath(__DIR__ . DIRECTORY_SEPARATOR . 'runner.py');
        if (!file_exists($script)) {
            $_SESSION['error'] = "Python script not found.";
        } else {
            $escaped_url = escapeshellarg($url);
            $command = "$python $script $escaped_url 2>&1";
            $output = shell_exec($command);

            if ($output === null) {
                $_SESSION['error'] = "Failed to execute the download script.";
            } else {
                file_put_contents("$logDir/manual-run.log", "[" . date('Y-m-d H:i:s') . "] $command\n$output\n\n", FILE_APPEND);
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

// Collect recent images
$allowed_ext = ['jpg', 'jpeg', 'png'];
$all_images = [];
if (is_dir($downloadsDir)) {
    $dir_iterator = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($downloadsDir, RecursiveDirectoryIterator::SKIP_DOTS),
        RecursiveIteratorIterator::SELF_FIRST
    );

    foreach ($dir_iterator as $file) {
        if ($file->isFile() && in_array(strtolower($file->getExtension()), $allowed_ext)) {
            $relativePath = str_replace(__DIR__, '', $file->getPathname());
            $all_images[$file->getMTime()] = ltrim($relativePath, '/\\');
        }
    }
}

krsort($all_images);
$recent_images = array_slice($all_images, 0, 60);
$columns = max(1, floor(count($recent_images) / 3));
$rows = array_chunk(array_values($recent_images), $columns);
?>
<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <title>Artillery</title>
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

    form input[type="text"] {
        width: 70%;
        padding: 10px;
        border: 1px solid #444;
        background: #222;
        color: #fff;
        border-radius: 4px;
    }

    form button {
        padding: 10px 20px;
        margin-left: 10px;
        background-color: #28a745;
        color: white;
        border: none;
        border-radius: 4px;
        cursor: pointer;
    }

    .output {
        background: #1e1e1e;
        padding: 15px;
        margin-top: 20px;
        border-left: 4px solid #00eaff;
        border-radius: 5px;
    }

    .error {
        color: #ff4444;
        margin: 10px 0;
    }

    .success {
        color: #28a745;
        margin: 10px 0;
    }

    .scroll-wall {
        margin: 40px auto;
        max-width: 96%;
        display: flex;
        flex-direction: column;
        gap: 20px;
        padding-bottom: 40px;
    }

    .scroll-row {
        overflow: hidden;
        white-space: nowrap;
        position: relative;
        border-radius: 10px;
        mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent);
    }

    .scroll-track {
        display: flex;
        gap: 12px;
        animation: scroll-left 60s linear infinite;
    }

    .scroll-row-right .scroll-track {
        animation-name: scroll-right;
    }

    .scroll-image {
        flex: 0 0 auto;
        width: 120px;
        height: 120px;
        border: 1px solid #333;
        border-radius: 6px;
        overflow: hidden;
        background-color: #222;
    }

    .scroll-image img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
        transition: opacity 0.3s ease-in;
        will-change: transform, opacity;
        backface-visibility: hidden;

    }

    .scroll-image img[src=""] {
        opacity: 0;
    }

    @keyframes scroll-left {
        0% {
            transform: translateX(0);
        }

        100% {
            transform: translateX(-100%);
        }
    }

    @keyframes scroll-right {
        0% {
            transform: translateX(-100%);
        }

        100% {
            transform: translateX(0);
        }
    }
    </style>
</head>

<body>
    <?php 
    $headerFile = __DIR__ . DIRECTORY_SEPARATOR . 'header.php';
    if (file_exists($headerFile)) {
        include $headerFile;
    } else {
        echo "<div class='banner'><span class='title'>Artillery</span><div class='nav'><a href='index.php'>Home</a></div></div>";
    }
    ?>
    <main class="content">
        <h1>Welcome to Artillery</h1>
        <p>Enter a gallery URL below to start firing off downloads.</p>
        <?php if ($error): ?><div class="error"><?= htmlspecialchars($error) ?></div><?php endif; ?>
        <?php if ($success): ?><div class="success"><?= htmlspecialchars($success) ?></div><?php endif; ?>
        <form action="index.php" method="post">
            <input type="text" name="gallery_url" placeholder="https://example.com/gallery" required>
            <button type="submit">Fire!</button>
        </form>
    </main>

    <h2 style="text-align:center; margin-top: 30px;">🖼️ Recently Downloaded Images</h2>
    <?php if (empty($recent_images)): ?>
    <p style="text-align:center; color:#aaa;">No images found.</p>
    <?php else: ?>
    <div class="scroll-wall">
        <?php foreach ($rows as $i => $row): ?>
        <div class="scroll-row scroll-row-<?= $i % 2 === 0 ? 'left' : 'right' ?>">
            <div class="scroll-track">
                <?php foreach (array_merge($row, $row, $row) as $img): ?>
                <div class="scroll-image">
                    <a href="<?= htmlspecialchars($img) ?>" target="_blank">
                        <img src="<?= htmlspecialchars($img) ?>" alt="Image">
                    </a>
                </div>
                <?php endforeach; ?>
            </div>
        </div>
        <?php endforeach; ?>
    </div>
    <?php endif; ?>
</body>

</html>