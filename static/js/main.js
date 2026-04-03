// ====== Dropdowns ======
function toggleNotifs() {
  document.getElementById('notifDropdown').classList.toggle('open');
  document.getElementById('userDropdown')?.classList.remove('open');
}
function toggleUserMenu() {
  document.getElementById('userDropdown').classList.toggle('open');
  document.getElementById('notifDropdown')?.classList.remove('open');
}
document.addEventListener('click', function(e) {
  if (!e.target.closest('.notif-wrapper')) document.getElementById('notifDropdown')?.classList.remove('open');
  if (!e.target.closest('.user-menu-wrapper')) document.getElementById('userDropdown')?.classList.remove('open');
});

function toggleMobileMenu() {
  document.getElementById('mobileMenu').classList.toggle('open');
}

// ====== Mark notifications read ======
function markAllRead() {
  fetch('/notifications/read', { method: 'POST', headers: { 'X-CSRFToken': '' } })
    .then(() => {
      document.querySelectorAll('.notif-item.unread').forEach(n => n.classList.remove('unread'));
      const badge = document.querySelector('.notif-badge');
      if (badge) badge.remove();
    });
}

// ====== Save / Bookmark ======
const SAVE_ICON_FILLED = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="currentColor" viewBox="0 0 24 24"><path d="M6 5a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v13.131a1 1 0 0 1-1.555.832l-3.89-2.593a1 1 0 0 0-1.11 0l-3.89 2.593A1 1 0 0 1 6 18.131V5Z"></path></svg>`;
const SAVE_ICON_OUTLINE = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="18" height="18" fill="currentColor"><path d="M23 5H9C7.346 5 6 6.346 6 8v19a1 1 0 0 0 1.614.789L16 21.267l8.386 6.522a.996.996 0 0 0 1.053.109A1 1 0 0 0 26 27V8c0-1.654-1.346-3-3-3zm1 19.956-7.386-5.745a.999.999 0 0 0-1.228-.001L8 24.956V8c0-.551.449-1 1-1h14c.551 0 1 .449 1 1v16.956z"></path></svg>`;

function updateSaveBtn(btn, saved) {
  btn.classList.toggle('saved', saved);
  btn.setAttribute('aria-pressed', saved ? 'true' : 'false');
  // Handle full-width detail-page button or icon-only card button
  const isFullBtn = btn.classList.contains('btn');
  if (isFullBtn) {
    btn.innerHTML = saved
      ? SAVE_ICON_FILLED + ' <span>Saved to Bookmarks</span>'
      : SAVE_ICON_OUTLINE + ' <span>Save to Bookmarks</span>';
  } else {
    // icon-only action-btn on note cards — add a tiny label
    btn.innerHTML = saved ? SAVE_ICON_FILLED : SAVE_ICON_OUTLINE;
    btn.title = saved ? 'Remove from bookmarks' : 'Save to bookmarks';
  }
}

function toggleSave(noteId, btn) {
  btn.disabled = true;
  fetch(`/save/${noteId}`, { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      updateSaveBtn(btn, data.saved);
      showToast(data.saved ? 'Note saved to bookmarks!' : 'Removed from bookmarks', data.saved ? 'success' : 'info');
    })
    .catch(() => showToast('Something went wrong. Try again.', 'error'))
    .finally(() => { btn.disabled = false; });
}

// ====== Star Rating ======
function initRating(noteId) {
  const stars = document.querySelectorAll('.star[data-val]');
  stars.forEach(star => {
    star.addEventListener('mouseenter', () => {
      const val = +star.dataset.val;
      stars.forEach(s => s.classList.toggle('active', +s.dataset.val <= val));
    });
    star.addEventListener('mouseleave', () => {
      const current = +document.querySelector('.star-rating').dataset.current || 0;
      stars.forEach(s => s.classList.toggle('active', +s.dataset.val <= current));
    });
    star.addEventListener('click', () => {
      const val = +star.dataset.val;
      fetch(`/rate/${noteId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: val })
      })
      .then(r => r.json())
      .then(data => {
        document.querySelector('.star-rating').dataset.current = val;
        stars.forEach(s => s.classList.toggle('active', +s.dataset.val <= val));
        const info = document.getElementById('rating-info');
        if (info) info.textContent = `${data.avg} / 5 (${data.count} ratings)`;
        showToast('Rating saved!', 'success');
      });
    });
  });
}

// ====== File Upload Drag & Drop ======
function initFileUpload() {
  const area = document.querySelector('.file-upload-area');
  if (!area) return;
  const input = area.querySelector('input[type=file]');

  area.addEventListener('dragover', e => { e.preventDefault(); area.classList.add('drag-over'); });
  area.addEventListener('dragleave', () => area.classList.remove('drag-over'));
  area.addEventListener('drop', e => {
    e.preventDefault(); area.classList.remove('drag-over');
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      updateFileDisplay(e.dataTransfer.files[0]);
    }
  });
  input?.addEventListener('change', () => { if (input.files[0]) updateFileDisplay(input.files[0]); });
}
function updateFileDisplay(file) {
  let display = document.getElementById('file-display');
  if (!display) {
    display = document.createElement('div');
    display.id = 'file-display';
    display.className = 'file-selected';
    document.querySelector('.file-upload-area').after(display);
  }
  const size = file.size < 1024*1024 ? `${(file.size/1024).toFixed(0)} KB` : `${(file.size/(1024*1024)).toFixed(1)} MB`;
  display.textContent = `📎 ${file.name} · ${size}`;
}

// ====== Password Toggle ======
function togglePassword(id) {
  const input = document.getElementById(id);
  const btn = input.nextElementSibling;
  if (input.type === 'password') {
    input.type = 'text';
    btn.textContent = '🙈';
  } else {
    input.type = 'password';
    btn.textContent = '👁';
  }
}

// ====== Search Autocomplete ======
function initAutocomplete() {
  const input = document.getElementById('searchInput');
  const suggestions = document.getElementById('suggestions');
  if (!input || !suggestions) return;

  let timer;
  let currentFocus = -1;
  input.addEventListener('input', () => {
    const q = input.value.trim();
    currentFocus = -1;
    if (timer) clearTimeout(timer);
    if (q.length < 2) {
      suggestions.style.display = 'none';
      return;
    }

    timer = setTimeout(() => {
      fetch(`/autocomplete?q=${encodeURIComponent(q)}`)
      .then(r => r.json())
      .then(data => {
        if (!data.length) {
          suggestions.style.display = 'none';
          return;
        }
        suggestions.innerHTML = data.map(item => `<div class="suggestion-item" data-id="${item.id}" data-title="${(item.title||'').replace(/"/g, '&quot;')}">${item.text}</div>`).join('');
        suggestions.style.display = 'block';
      });
    }, 220);
  });

  input.addEventListener('keydown', (e) => {
    let items = suggestions.querySelectorAll('.suggestion-item');
    if (!items.length || suggestions.style.display === 'none') return;
    
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      currentFocus++;
      addActive(items);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      currentFocus--;
      addActive(items);
    } else if (e.key === 'Enter') {
      if (currentFocus > -1) {
        e.preventDefault();
        items[currentFocus].click();
      }
    }
  });

  function addActive(items) {
    items.forEach(item => item.classList.remove('active'));
    if (currentFocus >= items.length) currentFocus = 0;
    if (currentFocus < 0) currentFocus = items.length - 1;
    items[currentFocus].classList.add('active');
    items[currentFocus].scrollIntoView({ block: 'nearest' });
  }

  document.addEventListener('click', (e) => {
    if (!e.target.closest('#searchInput') && !e.target.closest('#suggestions')) {
      suggestions.style.display = 'none';
    }
  });

  suggestions.addEventListener('click', (e) => {
    const item = e.target.closest('.suggestion-item');
    if (!item) return;
    input.value = item.dataset.title || item.innerText;
    document.getElementById('filter-form').submit();
  });
}

window.addEventListener('DOMContentLoaded', initAutocomplete);

// ====== Toast ======
function showToast(message, type = 'info') {
  const tc = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `flash flash-${type}`;
  toast.innerHTML = `<span>${message}</span><button onclick="this.parentElement.remove()">✕</button>`;
  tc.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ====== Auto-dismiss flashes ======
setTimeout(() => {
  document.querySelectorAll('.flash').forEach(f => f.remove());
}, 5000);

// ====== Filter Form Auto-submit ======
document.querySelectorAll('.filter-select, .sort-select').forEach(el => {
  el.addEventListener('change', () => el.closest('form')?.submit());
});
document.querySelectorAll('.filter-chip').forEach(chip => {
  chip.addEventListener('click', () => {
    const form = chip.closest('form') || document.getElementById('filter-form');
    const input = chip.dataset.input;
    const val = chip.dataset.val;
    if (form && input) {
      const hidden = form.querySelector(`[name=${input}]`);
      if (hidden) {
        hidden.value = hidden.value === val ? '' : val;
        chip.classList.toggle('active', hidden.value === val);
        form.submit();
      }
    }
  });
});

// ====== Init ======
document.addEventListener('DOMContentLoaded', () => {
  initFileUpload();
  const noteId = document.body.dataset.noteId;
  if (noteId) initRating(noteId);
  
  // Apply dynamic background colors safely (bypass IDE CSS linters)
  document.querySelectorAll('[data-bg]').forEach(el => {
      el.style.setProperty('background-color', el.getAttribute('data-bg'), 'important');
  });
});
