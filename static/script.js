document.addEventListener('DOMContentLoaded', () => {
    const themeToggle = document.getElementById('theme-toggle');
    const storage = (() => {
        try {
            localStorage.setItem('__ruff_theme', '1');
            localStorage.removeItem('__ruff_theme');
            return localStorage;
        } catch {
            return null;
        }
    })();

    const applyTheme = (mode) => {
        document.body.classList.remove('light-theme', 'dark-theme');
        if (mode === 'dark') {
            document.body.classList.add('dark-theme');
            if (themeToggle) themeToggle.textContent = '☀️';
        } else {
            if (themeToggle) themeToggle.textContent = '🌙';
        }
        if (storage) {
            storage.setItem('theme', mode);
        }
    };

    const current = storage?.getItem('theme') || 'light';
    applyTheme(current);

    themeToggle?.addEventListener('click', () => {
        const next = document.body.classList.contains('dark-theme') ? 'light' : 'dark';
        applyTheme(next);
    });

    // Navbar toggle for small screens
    const navToggle = document.getElementById('nav-toggle');
    navToggle?.addEventListener('click', () => {
        const container = document.querySelector('.navbar-container');
        container?.classList.toggle('open');
    });

    // Ensure menu state is consistent on load/resize
    const navbarContainer = document.querySelector('.navbar-container');
    const normalizeNav = () => {
        if (!navbarContainer) return;
        if (window.innerWidth > 600) {
            navbarContainer.classList.remove('open');
        }
    };
    window.addEventListener('resize', normalizeNav);
    normalizeNav();

    // Initialize aria-expanded for dropdown toggles
    document.querySelectorAll('.dropdown-toggle').forEach((t) => t.setAttribute('aria-expanded', 'false'));

    // Dropdown toggle support (click to open on both desktop & mobile)
    document.querySelectorAll('.nav-dropdown').forEach((drop) => {
        const toggle = drop.querySelector('.dropdown-toggle');
        const menu = drop.querySelector('.dropdown-menu');
        if (!toggle || !menu) return;

        toggle.addEventListener('click', (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            // close other open dropdowns
            document.querySelectorAll('.nav-dropdown.open').forEach((d) => {
                if (d !== drop) {
                    d.classList.remove('open');
                    const t = d.querySelector('.dropdown-toggle');
                    t?.setAttribute('aria-expanded', 'false');
                }
            });
            drop.classList.toggle('open');
            toggle.setAttribute('aria-expanded', String(drop.classList.contains('open')));
        });
    });

    // Close dropdowns / nav when clicking outside
    document.addEventListener('click', (ev) => {
        document.querySelectorAll('.nav-dropdown.open').forEach((d) => {
            d.classList.remove('open');
            const t = d.querySelector('.dropdown-toggle');
            t?.setAttribute('aria-expanded', 'false');
        });
        if (navbarContainer && window.innerWidth <= 600) {
            // close mobile nav when clicking outside the navbar
            const inside = ev.target instanceof Element && ev.target.closest('.navbar-container');
            if (!inside) navbarContainer.classList.remove('open');
        }
    });

    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {
            // Silent fail for unsupported environments
        });
    }

    document.querySelectorAll('[data-note-toggle]').forEach((toggle) => {
        if (!(toggle instanceof Element)) return;
        const wrapper = toggle.closest('.writing-hero');
        const note = wrapper?.querySelector('[data-note]');
        if (!note) return;

        const setOpen = (open) => {
            note.classList.toggle('is-open', open);
            toggle.classList.toggle('is-open', open);
            toggle.setAttribute('aria-expanded', String(open));
            note.setAttribute('aria-hidden', String(!open));
        };

        const hiddenInput = note.querySelector('input[type=\"hidden\"][name$=\"checklist\"]') || note.querySelector('#checklist-data');
        if (hiddenInput) {
            try {
                const data = JSON.parse(hiddenInput.value || '[]');
                if (Array.isArray(data) && data.length > 0) {
                    setOpen(true);
                }
            } catch {
                // ignore invalid data
            }
        }

        toggle.addEventListener('click', () => {
            const open = note.classList.contains('is-open');
            setOpen(!open);
        });

        toggle.addEventListener('keydown', (event) => {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            const open = note.classList.contains('is-open');
            setOpen(!open);
        });
    });

    function initChecklist(root) {
        const itemsContainer = root.querySelector('[data-checklist-items]');
        const hiddenInput = root.querySelector('input[type="hidden"][name$="checklist"]') || root.querySelector('#checklist-data');

        if (!itemsContainer || !hiddenInput) return;
        const getRow = (target) => (target instanceof Element ? target.closest('.checklist-item') : null);

        const parseItems = () => {
            try {
                const data = JSON.parse(hiddenInput.value || '[]');
                return Array.isArray(data) ? data : [];
            } catch {
                return [];
            }
        };

        const syncItems = () => {
            const items = Array.from(itemsContainer.querySelectorAll('.checklist-item')).map((row) => {
                const textInput = row.querySelector('input[type="text"]');
                const checkbox = row.querySelector('input[type="checkbox"]');
                return {
                    text: (textInput?.value || '').trim(),
                    done: Boolean(checkbox?.checked)
                };
            }).filter(item => item.text.length > 0);

            hiddenInput.value = JSON.stringify(items);
        };

        const createItem = (item = { text: '', done: false }) => {
            const row = document.createElement('div');
            row.className = 'checklist-item';
            row.classList.add('new');

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = Boolean(item.done);

            const textInput = document.createElement('input');
            textInput.type = 'text';
            textInput.placeholder = 'Add a task...';
            textInput.value = item.text || '';

            // When Enter is pressed, create/focus the next checklist input
            textInput.addEventListener('keydown', (ev) => {
                if (ev.key === 'Enter') {
                    ev.preventDefault();
                    const rows = Array.from(itemsContainer.querySelectorAll('.checklist-item'));
                    const idx = rows.indexOf(row);
                    const nextRow = rows[idx + 1];
                    if (nextRow) {
                        const nextInput = nextRow.querySelector('input[type="text"]');
                        nextInput?.focus();
                    } else {
                        createItem();
                        // Small timeout to ensure element is in DOM
                        setTimeout(() => {
                            const updated = Array.from(itemsContainer.querySelectorAll('.checklist-item'));
                            const lastInput = updated[updated.length - 1]?.querySelector('input[type="text"]');
                            lastInput?.focus();
                        }, 0);
                    }
                    ensureTrailingBlank();
                    syncItems();
                }
            });

            const removeButton = document.createElement('button');
            removeButton.type = 'button';
            removeButton.className = 'checklist-remove';
            removeButton.setAttribute('aria-label', 'Remove item');
            removeButton.textContent = '✕';

            row.appendChild(checkbox);
            row.appendChild(textInput);
            row.appendChild(removeButton);
            itemsContainer.appendChild(row);

            // Remove the 'new' class after animation completes
            setTimeout(() => row.classList.remove('new'), 250);
        };

        const ensureTrailingBlank = () => {
            const rows = Array.from(itemsContainer.querySelectorAll('.checklist-item'));
            const lastInput = rows.length ? rows[rows.length - 1].querySelector('input[type="text"]') : null;
            const lastHasText = lastInput && lastInput.value.trim().length > 0;
            if (!rows.length || lastHasText) {
                createItem();
            }

            const updatedRows = Array.from(itemsContainer.querySelectorAll('.checklist-item'));
            for (let i = updatedRows.length - 2; i >= 0; i -= 1) {
                const input = updatedRows[i].querySelector('input[type="text"]');
                if (!input || input.value.trim().length > 0) break;
                if (updatedRows.length > 1) {
                    updatedRows[i].remove();
                }
            }
        };

        const seedItems = parseItems();
        if (seedItems.length) {
            seedItems.forEach(createItem);
        }
        ensureTrailingBlank();

        itemsContainer.addEventListener('input', () => {
            ensureTrailingBlank();
            syncItems();
        });
        itemsContainer.addEventListener('change', () => {
            ensureTrailingBlank();
            syncItems();
        });
        itemsContainer.addEventListener('click', (event) => {
            if (!(event.target instanceof Element)) return;
            if (event.target.classList.contains('checklist-remove')) {
                getRow(event.target)?.remove();
                ensureTrailingBlank();
                syncItems();
            }
        });

        let draggedRow = null;
        itemsContainer.addEventListener('dragstart', (event) => {
            const row = getRow(event.target);
            if (!row) return;
            draggedRow = row;
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', '');
            }
        });
        itemsContainer.addEventListener('dragover', (event) => {
            event.preventDefault();
            const row = getRow(event.target);
            if (!row || row === draggedRow) return;
            const rect = row.getBoundingClientRect();
            const next = (event.clientY - rect.top) > rect.height / 2;
            itemsContainer.insertBefore(draggedRow, next ? row.nextSibling : row);
        });
        itemsContainer.addEventListener('drop', () => {
            draggedRow = null;
            ensureTrailingBlank();
            syncItems();
        });

        const form = root.closest('form');
        form?.addEventListener('submit', () => {
            ensureTrailingBlank();
            syncItems();
        });
    }

    document.querySelectorAll('[data-checklist]').forEach(initChecklist);
});
