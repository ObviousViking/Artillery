<style>
/* Shared header banner + nav styling */
.banner {
    background-color: #222;
    padding: 15px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #444;
}

.banner .title {
    font-size: 1.8rem;
    color: #00eaff;
    font-weight: bold;
}

nav.nav a {
    color: #00eaff;
    margin-left: 20px;
    text-decoration: none;
    font-weight: bold;
    transition: color 0.2s ease;
}

nav.nav a:hover {
    text-decoration: underline;
}
</style>

<header>
    <div class="banner">
        <div class="title">ARTILLERY</div>
        <nav class="nav">
            <a href="index.php">Home</a>
            <a href="new-task.php">New Task</a>
            <a href="tasks.php">View Tasks</a>
            <a href="config.php">Config</a>
        </nav>
    </div>
</header>