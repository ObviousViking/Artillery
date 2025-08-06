<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <title>Footer with Ko-fi Widget</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <style>
    :root {
        --bg: #121212;
        --card-bg: #1e1e1e;
        --text: #e5e5e5;
        --muted: #888;
        --accent: #e5be01;
        --accent-2: #d4ab01;
    }

    body {
        margin: 0;
        padding-bottom: 70px;
        /* Space for fixed footer */
        background-color: var(--bg);
        color: var(--text);
        font-family: Arial, sans-serif;
    }

    .banner {
        background-color: #252525;
        padding: 1rem 1.5rem;
        position: fixed;
        bottom: 0;
        width: 100%;
        border-top: 1px solid #333;
        z-index: 1000;
    }

    .banner-inner {
        display: flex;
        justify-content: space-between;
        align-items: center;
        width: 100%;
    }

    #current-time {
        color: #00b7c3;
        font-weight: 500;
        font-size: 0.95rem;
    }

    #kofi-widget {
        display: inline-block;
        transform: scale(0.85);
        transform-origin: right;
    }

    #kofi-widget>div,
    #kofi-widget iframe {
        position: static !important;
        float: none !important;
        margin: 0 !important;
        padding: 0 !important;
        display: inline-block !important;
    }

    @media (max-width: 600px) {
        .banner-inner {
            flex-direction: column;
            align-items: center;
            gap: 0.75rem;
        }

        #current-time {
            font-size: 0.85rem;
        }

        #kofi-widget {
            transform: scale(0.9);
            transform-origin: center;
        }
    }
    </style>
</head>

<body>

    <!-- Your main content here -->
    <div style="padding: 2rem;">
        <h1>Sample Page</h1>
        <p>This is just a demo page to test Ko-fi widget placement inside a sticky footer.</p>
    </div>

    <!-- Footer -->
    <footer class="banner">
        <div class="banner-inner">
            <div id="current-time"></div>
            <div id="kofi-widget"></div>
        </div>
    </footer>

    <!-- Ko-fi Script -->
    <script type='text/javascript' src='https://storage.ko-fi.com/cdn/widget/Widget_2.js'></script>
    <script type='text/javascript'>
    kofiwidget2.init('Buy me a coffee', '#72a4f2', 'P5P61JA9LQ');
    kofiwidget2.draw('kofi-widget');

    function updateCurrentTime() {
        const now = new Date();
        const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        const dayName = days[now.getDay()];
        const day = String(now.getDate()).padStart(2, '0');
        const month = months[now.getMonth()];
        const year = now.getFullYear();
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        const seconds = String(now.getSeconds()).padStart(2, '0');
        const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        const timeString = `${dayName}, ${day} ${month} ${year} ${hours}:${minutes}:${seconds} ${timeZone}`;
        document.getElementById('current-time').textContent = timeString;
    }

    updateCurrentTime();
    setInterval(updateCurrentTime, 1000);
    </script>

</body>

</html>