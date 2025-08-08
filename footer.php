<footer class="footer-banner"
    style="position: fixed; bottom: 0; width: 100%; border-top: 1px solid #333; border-bottom: none; z-index: 1000;">
    <div style="display: flex; justify-content: space-between; align-items: center; width: 100%; padding: 0 1.5rem;">
        <div id="current-time" style="color: #00b7c3; font-weight: 500;"></div>
        <div id="kofi-widget">
            <a href='https://ko-fi.com/P5P61JA9LQ' target='_blank'>
                <img height='36' style='border:0px;height:36px;' src='https://storage.ko-fi.com/cdn/kofi6.png?v=6'
                    border='0' alt='Buy Me a Coffee at ko-fi.com' />
            </a>
        </div>
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
    console.log(`Footer time updated: ${timeString}`);
}

// Update time on load and every second
updateCurrentTime();
setInterval(updateCurrentTime, 1000);

// Log Ko-fi widget load
console.log('Ko-fi image widget loaded');
</script>

<style>
.footer-banner {
    background-color: #252525;
    padding: 1rem 1.5rem;
}

#kofi-widget {
    display: inline-block;
    line-height: 1;
}

#kofi-widget img {
    vertical-align: middle;
    max-height: 36px;
}

@media (max-width: 600px) {
    .footer-banner>div {
        flex-direction: row;
        align-items: center;
        gap: 0.5rem;
    }

    #current-time {
        font-size: 0.85rem;
    }

    #kofi-widget {
        font-size: 0.9rem;
    }

    #kofi-widget img {
        height: 32px;
    }
}
</style>