<footer class="banner">
    <div class="banner-inner">
        <div id="current-time"></div>
        <a class="kofi-button" href="https://ko-fi.com/P5P61JA9LQ" target="_blank" rel="noopener noreferrer">
            ☕ Donate via Ko-fi
        </a>
    </div>
</footer>

<script>
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

<style>
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

.kofi-button {
    background-color: #72a4f2;
    color: #fff;
    border: none;
    border-radius: 4px;
    padding: 0.5rem 1rem;
    font-size: 0.9rem;
    font-weight: bold;
    cursor: pointer;
    text-decoration: none;
    transition: background-color 0.2s ease;
}

.kofi-button:hover {
    background-color: #5a92e6;
}

@media (max-width: 600px) {
    .banner-inner {
        flex-direction: column;
        align-items: center;
        gap: 0.75rem;
        text-align: center;
    }

    #current-time {
        font-size: 0.85rem;
    }

    .kofi-button {
        width: 100%;
        max-width: 200px;
    }
}
</style>