/**
 * ontology-autocomplete.js — Loom ontology term autocomplete widget.
 *
 * Attaches to any input with [data-ontology-prefixes].  On each keypress
 * (debounced 250 ms) it queries GET /ontology/search/?q=<term>&prefixes=<p>
 * and shows a dropdown of results.
 *
 * Slot value semantics:
 *   - The visible input (data-ontology-prefixes) stores the human label.
 *   - A sibling hidden input (name="${slot}_curie" or data-curie-input="#id")
 *     stores the CURIE that the CAMO slot actually requires.
 *   - If no hidden input is found the visible input stores the CURIE itself.
 *
 * Initialization (called once on DOMContentLoaded):
 *   OntologyAutocomplete.init('/ontology/search/');
 *
 * Or attach to a single input:
 *   OntologyAutocomplete.attach(inputEl, '/ontology/search/');
 */

const OntologyAutocomplete = {
    _searchUrl: '/ontology/search/',
    _activeDropdown: null,

    init(searchUrl = '/ontology/search/') {
        this._searchUrl = searchUrl;
        document.querySelectorAll('[data-ontology-prefixes]').forEach((el) => {
            this.attach(el);
        });
    },

    attach(input) {
        let debounceTimer = null;
        const dropdown = this._buildDropdown();
        input.setAttribute('autocomplete', 'off');

        input.addEventListener('input', () => {
            clearTimeout(debounceTimer);
            const q = input.value.trim();
            if (q.length < 2) {
                dropdown.style.display = 'none';
                return;
            }
            debounceTimer = setTimeout(() => this._fetch(input, dropdown, q), 250);
        });

        input.addEventListener('keydown', (e) => {
            if (dropdown.style.display === 'none') return;
            const items = dropdown.querySelectorAll('.oa-item');
            const active = dropdown.querySelector('.oa-item.active');
            let idx = Array.from(items).indexOf(active);

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                idx = Math.min(idx + 1, items.length - 1);
                items.forEach((i, n) => i.classList.toggle('active', n === idx));
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                idx = Math.max(idx - 1, 0);
                items.forEach((i, n) => i.classList.toggle('active', n === idx));
            } else if (e.key === 'Enter' && active) {
                e.preventDefault();
                active.click();
            } else if (e.key === 'Escape') {
                dropdown.style.display = 'none';
            }
        });

        input.addEventListener('blur', () => {
            // Delay hide so clicks on dropdown items register first
            setTimeout(() => { dropdown.style.display = 'none'; }, 150);
        });

        input.addEventListener('focus', () => {
            if (dropdown.children.length > 0) dropdown.style.display = 'block';
        });

        document.body.appendChild(dropdown);
        this._positionDropdown(input, dropdown);
        window.addEventListener('resize', () => this._positionDropdown(input, dropdown));
    },

    _buildDropdown() {
        const el = document.createElement('div');
        el.className = 'oa-dropdown';
        Object.assign(el.style, {
            position: 'absolute',
            zIndex: '8888',
            background: 'var(--bg, #fff)',
            border: '1px solid var(--border, #ddd)',
            borderRadius: '4px',
            boxShadow: '0 4px 12px rgba(0,0,0,.15)',
            maxHeight: '260px',
            overflowY: 'auto',
            display: 'none',
            minWidth: '300px',
        });
        return el;
    },

    _positionDropdown(input, dropdown) {
        const rect = input.getBoundingClientRect();
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;
        dropdown.style.left = `${rect.left + scrollLeft}px`;
        dropdown.style.top = `${rect.bottom + scrollTop + 2}px`;
        dropdown.style.width = `${Math.max(rect.width, 320)}px`;
    },

    async _fetch(input, dropdown, q) {
        const prefixes = input.dataset.ontologyPrefixes || '';
        const url = `${this._searchUrl}?q=${encodeURIComponent(q)}&prefixes=${encodeURIComponent(prefixes)}`;

        let data;
        try {
            const resp = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
            data = await resp.json();
        } catch {
            dropdown.style.display = 'none';
            return;
        }

        this._positionDropdown(input, dropdown);
        dropdown.innerHTML = '';

        if (!data.results || data.results.length === 0) {
            const empty = document.createElement('div');
            empty.textContent = 'No terms found.';
            Object.assign(empty.style, { padding: '8px 12px', color: '#888', fontSize: '13px' });
            dropdown.appendChild(empty);
            dropdown.style.display = 'block';
            return;
        }

        data.results.forEach((term, idx) => {
            const item = document.createElement('div');
            item.className = 'oa-item' + (idx === 0 ? ' active' : '');
            item.dataset.curie = term.curie;
            item.dataset.label = term.label;
            item.innerHTML = `
                <div style="display:flex;justify-content:space-between;align-items:start;gap:8px">
                  <span class="oa-label">${_esc(term.label)}</span>
                  <code class="oa-curie">${_esc(term.curie)}</code>
                </div>
                ${term.definition ? `<div class="oa-def">${_esc(term.definition.slice(0, 120))}${term.definition.length > 120 ? '…' : ''}</div>` : ''}
            `;
            Object.assign(item.style, {
                padding: '6px 12px',
                cursor: 'pointer',
                borderBottom: '1px solid var(--border, #eee)',
                fontSize: '13px',
            });
            item.addEventListener('mouseenter', () => {
                dropdown.querySelectorAll('.oa-item').forEach((i) => i.classList.remove('active'));
                item.classList.add('active');
            });
            item.addEventListener('click', () => {
                this._selectTerm(input, term);
                dropdown.style.display = 'none';
            });
            dropdown.appendChild(item);
        });

        dropdown.style.display = 'block';

        // Style active items
        const style = document.getElementById('oa-style');
        if (!style) {
            const s = document.createElement('style');
            s.id = 'oa-style';
            s.textContent = `
                .oa-item.active { background: var(--surface, #f5f5f5); }
                .oa-label { font-weight: 500; }
                .oa-curie { font-size: 11px; color: var(--muted, #888); flex-shrink: 0; }
                .oa-def { font-size: 11px; color: var(--muted, #888); margin-top: 2px; }
            `;
            document.head.appendChild(s);
        }
    },

    _selectTerm(input, term) {
        // Write label to the visible input
        input.value = term.label;

        // Write CURIE to sibling hidden input (if found)
        const curieTarget = input.dataset.curieTarget;
        if (curieTarget) {
            const hidden = document.getElementById(curieTarget)
                || document.querySelector(`[name="${curieTarget}"]`);
            if (hidden) {
                hidden.value = term.curie;
            }
        } else {
            // No hidden input: store curie in the visible field itself
            input.value = term.curie;
            input.title = term.label;
        }

        // Dispatch change event so Alpine.js and HTMX know
        input.dispatchEvent(new Event('change', { bubbles: true }));
    },
};

window.OntologyAutocomplete = OntologyAutocomplete;

function _esc(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
