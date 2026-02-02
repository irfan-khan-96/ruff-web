document.addEventListener('DOMContentLoaded', () => {
    const themeToggle = document.getElementById('theme-toggle');

    const applyTheme = (mode) => {
        document.body.classList.remove('light-theme', 'dark-theme');
        if (mode === 'dark') {
            document.body.classList.add('dark-theme');
            themeToggle.textContent = '☀️';
        } else {
            themeToggle.textContent = '🌙';
        }
        localStorage.setItem('theme', mode);
    };

    const current = localStorage.getItem('theme') || 'light';
    applyTheme(current);

    themeToggle.addEventListener('click', () => {
        const next = document.body.classList.contains('dark-theme') ? 'light' : 'dark';
        applyTheme(next);
    });

    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {
            // Silent fail for unsupported environments
        });
    }
});

