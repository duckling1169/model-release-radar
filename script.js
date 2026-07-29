(() => {
  const root = document.documentElement;
  const toggleBtn = document.getElementById('theme-toggle');
  const STORAGE_KEY = 'mrr-theme';

  function systemPrefersDark() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function applyTheme(theme) {
    root.setAttribute('data-theme', theme);
    toggleBtn.textContent = theme === 'dark' ? '☀ Light' : '● Dark';
  }

  const stored = localStorage.getItem(STORAGE_KEY);
  applyTheme(stored || (systemPrefersDark() ? 'dark' : 'light'));

  toggleBtn.addEventListener('click', () => {
    const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    localStorage.setItem(STORAGE_KEY, next);
  });
})();
