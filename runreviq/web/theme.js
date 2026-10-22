'use strict';
(() => {
  // Runs before styles load to avoid a light flash for saved dark preferences.
  const key = 'runreviq-theme';
  let preference = 'system';
  try {
    const saved = localStorage.getItem(key) || localStorage.getItem('opslens-theme');
    if (['system', 'light', 'dark'].includes(saved)) preference = saved;
  } catch (_) { /* Theme remains usable when browser storage is unavailable. */ }
  document.documentElement.dataset.theme = preference;
  document.addEventListener('DOMContentLoaded', () => {
    const control = document.getElementById('theme');
    control.value = preference;
    control.addEventListener('change', () => {
      const value = control.value;
      if (!['system', 'light', 'dark'].includes(value)) return;
      document.documentElement.dataset.theme = value;
      try { localStorage.setItem(key, value); } catch (_) { /* Page-only preference. */ }
    });
  });
})();
