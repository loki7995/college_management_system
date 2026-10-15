(() => {
  const root = document.documentElement;
  const toggle = document.getElementById('themeToggle');
  const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');

  const setTheme = (theme, persist) => {
    root.dataset.theme = theme;
    if (persist) localStorage.setItem('campus-theme', theme);
    if (toggle) {
      const dark = theme === 'dark';
      toggle.setAttribute('aria-pressed', String(dark));
      toggle.setAttribute('aria-label', `Switch to ${dark ? 'light' : 'dark'} mode`);
      toggle.querySelector('.theme-toggle-icon').textContent = dark ? '☀' : '☾';
      toggle.querySelector('.theme-toggle-label').textContent = dark ? 'Light mode' : 'Dark mode';
    }
  };

  const savedTheme = localStorage.getItem('campus-theme');
  setTheme(savedTheme || (systemTheme.matches ? 'dark' : 'light'), false);
  toggle?.addEventListener('click', () => {
    setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark', true);
  });

  const dialog = document.getElementById('commandPalette');
  const input = document.getElementById('commandSearchInput');
  const openButton = document.getElementById('commandOpen');
  if (!dialog || !input || !openButton) return;

  const openPalette = () => {
    if (!dialog.open) dialog.showModal();
    input.focus();
    input.select();
  };
  openButton.addEventListener('click', openPalette);
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      openPalette();
    }
    if (event.key === 'Escape' && dialog.open) dialog.close();
  });
  dialog.addEventListener('click', (event) => {
    if (event.target.closest('.command-result')) dialog.close();
    if (event.target === dialog) dialog.close();
  });
})();
