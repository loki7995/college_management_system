(() => {
  const sidebar = document.getElementById('sidebar');
  const toggle = document.getElementById('menuToggle');
  const scrim = document.getElementById('sidebarScrim');
  if (!sidebar || !toggle || !scrim) return;

  const setOpen = (open) => {
    sidebar.classList.toggle('is-open', open);
    scrim.classList.toggle('is-visible', open);
    toggle.setAttribute('aria-expanded', String(open));
    document.body.classList.toggle('nav-open', open);
    if (open) {
      const firstLink = sidebar.querySelector('a[href]');
      firstLink?.focus();
    } else if (document.activeElement && sidebar.contains(document.activeElement)) {
      toggle.focus();
    }
  };

  toggle.addEventListener('click', () => {
    setOpen(!sidebar.classList.contains('is-open'));
  });
  scrim.addEventListener('click', () => setOpen(false));
  sidebar.addEventListener('click', (event) => {
    if (event.target.closest('a[href]') && window.matchMedia('(max-width: 900px)').matches) {
      setOpen(false);
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setOpen(false);
  });
  window.addEventListener('resize', () => {
    if (!window.matchMedia('(max-width: 900px)').matches) setOpen(false);
  });
})();
