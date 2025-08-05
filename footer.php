<footer class="banner" style="border-top: 1px solid #333; border-bottom: none;">
    <div id="current-time" style="color: #00b7c3; font-weight: 500;"></div>
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

// Update time on load and every minute
updateCurrentTime();
setInterval(updateCurrentTime, 60000);
</script>