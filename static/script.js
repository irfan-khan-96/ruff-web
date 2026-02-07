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
            row.draggable = true;

            const handle = document.createElement('span');
            handle.className = 'drag-handle';
            handle.textContent = '☰';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = Boolean(item.done);

            const textInput = document.createElement('input');
            textInput.type = 'text';
            textInput.placeholder = 'Add a task...';
            textInput.value = item.text || '';

            const removeButton = document.createElement('button');
            removeButton.type = 'button';
            removeButton.className = 'checklist-remove';
            removeButton.setAttribute('aria-label', 'Remove item');
            removeButton.textContent = '✕';

            row.appendChild(handle);
            row.appendChild(checkbox);
            row.appendChild(textInput);
            row.appendChild(removeButton);
            itemsContainer.appendChild(row);
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
