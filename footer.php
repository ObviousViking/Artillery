<footer class="banner"
    style="position: fixed; bottom: 0; width: 100%; border-top: 1px solid #333; border-bottom: none; z-index: 1000;">
    <div style="display: flex; justify-content: space-between; align-items: center; width: 100%; padding: 0 1.5rem;">
        <div id="current-time" style="color: #00b7c3; font-weight: 500;"></div>
        <div id="kofi-widget"></div>
    </div>
</footer>

<script type='text/javascript' src='https://storage.ko-fi.com/cdn/widget/Widget_2.js'></script>
<script type='text/javascript'>
kofiwidget2.init('Buy me a coffee', '#72a4f2', 'P5P61JA9LQ');
kofiwidget2.draw();

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
    console.log(`Footer time updated: ${timeString}`);
}

// Update time on load and every second
updateCurrentTime();
setInterval(updateCurrentTime, 1000);

// Log Ko-fi widget load
console.log('Ko-fi widget initialized');
</script>

<style>
.banner {
    background-color: #252525;
    padding: 1rem 1.5rem;
}

#kofi-widget {
    display: inline-block;
}

@media (max-width: 600px) {
    .banner>div {
        flex-direction: row;
        /* Keep time and Ko-fi side by side */
        align-items: center;
        gap: 1rem;
    }

    #current-time {
        font-size: 0.85rem;
        /* Slightly smaller font for mobile */
    }

    #kofi-widget {
        transform: scale(0.9);
        /* Slightly scale down Ko-fi button for mobile */
    }
}
</style>