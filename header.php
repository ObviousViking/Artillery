<style>
* {
    box-sizing: border-box;
}

.banner {
    background-color: #252525;
    padding: 1rem 1.5rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #333;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
    position: relative;
    z-index: 1;
}

.banner .title {
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    font-size: 1.75rem;
    color: #00b7c3;
    font-weight: 600;
    user-select: none;
}

.nav {
    display: flex;
    gap: 1.5rem;
}

.nav a {
    color: #00b7c3;
    text-decoration: none;
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    font-weight: 500;
    font-size: 1rem;
    transition: color 0.2s ease, opacity 0.2s ease;
}

.nav a:hover {
    opacity: 0.8;
    text-decoration: underline;
}

@media (max-width: 600px) {
    .banner {
        flex-direction: column;
        align-items: flex-start;
        padding: 1rem;
    }

    .nav {
        flex-direction: column;
        gap: 0.5rem;
        margin-top: 1rem;
    }

    .nav a {
        font-size: 0.9rem;
    }
}
</style>

<header>
    <div class="banner">
        <div class="title">ARTILLERY</div>
        <nav class="nav">
            <a href="index.php" aria-label="Go to Home page">Home</a>
            <a href="new-task.php" aria-label="Go to New Task page">New Task</a>
            <a href="tasks.php" aria-label="Go to View Tasks page">View Tasks</a>
            <a href="config.php" aria-label="Go to Config page">Config</a>
        </nav>
    </div>
</header>