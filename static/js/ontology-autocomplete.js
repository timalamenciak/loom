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
        if (input.dataset.ontologyAutocompleteAttached === 'true') return;
        input.dataset.ontologyAutocompleteAttached = 'true';
        let debounceTimer = null;
        const dropdown = this._buildDropdown();
        input.setAttribute('autocomplete', 'off');
        input._oaLabels = input._oaLabels || new Map();
        if (input.dataset.ontologyMultivalue === 'true') {
            this._renderSelected(input);
        }

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
            if (dropdown.style.display === 'none') {
                if (e.key === 'Enter' && input.dataset.ontologyMultivalue === 'true') {
                    this._addRawValue(input, e);
                }
                return;
            }
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
            } else if (e.key === 'Enter' && input.dataset.ontologyMultivalue === 'true') {
                this._addRawValue(input, e);
                dropdown.style.display = 'none';
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
        const separator = this._searchUrl.includes('?') ? '&' : '?';
        let url = `${this._searchUrl}${separator}q=${encodeURIComponent(q)}&prefixes=${encodeURIComponent(prefixes)}`;
        if (input.dataset.wikidataLive === 'true') {
            url += '&wikidata_live=1';
            if (input.dataset.wikidataRootQid) {
                url += `&root_qid=${encodeURIComponent(input.dataset.wikidataRootQid)}`;
            }
        }

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

        _ensureOaStyles();
        data.results.forEach((term, idx) => {
            dropdown.appendChild(this._buildItem(input, term, idx === 0));
        });

        dropdown.style.display = 'block';
    },

    _buildItem(input, term, isFirst) {
        const item = document.createElement('div');
        item.className = 'oa-item' + (isFirst ? ' active' : '');
        item.dataset.curie = term.curie;
        item.dataset.label = term.label;

        const prefix = term.prefix || _prefixFromCurie(term.curie);
        const prefixPill = prefix
            ? `<span class="oa-prefix-pill">${_esc(prefix)}</span>`
            : '';
        const defHtml = term.definition
            ? `<div class="oa-def">${_esc(term.definition.slice(0, 120))}${term.definition.length > 120 ? '…' : ''}</div>`
            : '';

        item.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
              <span class="oa-label">${_esc(term.label)}</span>
              <span style="display:flex;align-items:center;gap:4px;flex-shrink:0">
                ${prefixPill}
                <code class="oa-curie">${_esc(term.curie)}</code>
              </span>
            </div>
            ${defHtml}
        `;
        Object.assign(item.style, {
            padding: '6px 12px',
            cursor: 'pointer',
            borderBottom: '1px solid var(--border, #eee)',
            fontSize: '13px',
        });
        item.addEventListener('mouseenter', () => {
            item.closest('.oa-dropdown').querySelectorAll('.oa-item')
                .forEach((i) => i.classList.remove('active'));
            item.classList.add('active');
        });
        item.addEventListener('click', () => {
            this._selectTerm(input, term);
            item.closest('.oa-dropdown').style.display = 'none';
        });
        return item;
    },

    _selectTerm(input, term) {
        if (input.dataset.ontologyMultivalue === 'true') {
            this._addMultivalueTerm(input, term);
            input.value = '';
            return;
        }

        // Write label to the visible input
        input.value = term.label;

        const curieTarget = input.dataset.curieTarget;
        if (curieTarget) {
            // Write CURIE to sibling hidden input
            const hidden = document.getElementById(curieTarget)
                || document.querySelector(`[name="${curieTarget}"]`);
            if (hidden) {
                hidden.value = term.curie;
                hidden.dispatchEvent(new Event('change', { bubbles: true }));
            }

            // Populate Wikidata hint inputs so the server can validate the pick.
            // For non-WD terms these are cleared so stale WD metadata isn't submitted.
            const isWd = term.source === 'wikidata';
            const wdLabel = document.getElementById(curieTarget + '_wd_label');
            if (wdLabel) wdLabel.value = isWd ? term.label : '';
            const wdDef = document.getElementById(curieTarget + '_wd_def');
            if (wdDef) wdDef.value = (isWd && term.definition) ? term.definition : '';
        } else {
            // No hidden input: store curie in the visible field itself
            input.value = term.curie;
            input.title = term.label;
        }

        // Dispatch change event so Alpine.js and HTMX know
        input.dispatchEvent(new Event('change', { bubbles: true }));
    },

    _addMultivalueTerm(input, term) {
        const hidden = this._hiddenInput(input);
        if (!hidden || !term.curie) return;
        const values = this._hiddenValues(hidden);
        if (!values.includes(term.curie)) {
            values.push(term.curie);
        }
        if (term.label) input._oaLabels.set(term.curie, term.label);
        hidden.value = values.join('\n');
        this._clearWikidataHints(input);
        this._renderSelected(input);
        hidden.dispatchEvent(new Event('change', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
    },

    _addRawValue(input, event) {
        const value = input.value.trim();
        if (!value || !value.includes(':')) return;
        event.preventDefault();
        this._addMultivalueTerm(input, { curie: value, label: value });
        input.value = '';
    },

    _hiddenInput(input) {
        const curieTarget = input.dataset.curieTarget;
        if (!curieTarget) return null;
        return document.getElementById(curieTarget)
            || document.querySelector(`[name="${curieTarget}"]`);
    },

    _hiddenValues(hidden) {
        return hidden.value
            .split(/\r?\n/)
            .map((value) => value.trim())
            .filter(Boolean);
    },

    _renderSelected(input) {
        const hidden = this._hiddenInput(input);
        const container = input.closest('.field')?.querySelector('[data-ontology-selected]');
        if (!hidden || !container) return;
        _ensureOaStyles();
        const values = this._hiddenValues(hidden);
        container.innerHTML = '';
        values.forEach((curie) => {
            const chip = document.createElement('span');
            chip.className = 'oa-chip';
            const prefix = _prefixFromCurie(curie);
            const label = input._oaLabels.get(curie) || curie;
            chip.innerHTML = `
                ${prefix ? `<span class="oa-prefix-pill">${_esc(prefix)}</span>` : ''}
                <span class="oa-chip-label" title="${_esc(curie)}">${_esc(label)}</span>
                <button type="button" class="oa-chip-remove" aria-label="Remove ${_esc(curie)}">x</button>
            `;
            chip.querySelector('.oa-chip-remove').addEventListener('click', () => {
                hidden.value = values.filter((value) => value !== curie).join('\n');
                input._oaLabels.delete(curie);
                this._renderSelected(input);
                hidden.dispatchEvent(new Event('change', { bubbles: true }));
            });
            container.appendChild(chip);
        });
        container.style.display = values.length ? 'flex' : 'none';
    },

    _clearWikidataHints(input) {
        const curieTarget = input.dataset.curieTarget;
        if (!curieTarget) return;
        const wdLabel = document.getElementById(curieTarget + '_wd_label');
        if (wdLabel) wdLabel.value = '';
        const wdDef = document.getElementById(curieTarget + '_wd_def');
        if (wdDef) wdDef.value = '';
    },
};

window.OntologyAutocomplete = OntologyAutocomplete;

// ── EnumAutocomplete ────────────────────────────────────────────────────────
// Client-side filterable dropdown for large LinkML enums (e.g. EcosystemFunctionalGroupEnum).
// Attaches to inputs with [data-enum-autocomplete] that carry a [data-choices] JSON array
// of {value, label} objects, and a [data-hidden-target] pointing to the hidden <input>
// that holds the submitted enum value.

const EnumAutocomplete = {
    init() {
        document.querySelectorAll('[data-enum-autocomplete]').forEach((el) => {
            this.attach(el);
        });
    },

    attach(input) {
        if (input.dataset.enumAutocompleteAttached === 'true') return;
        input.dataset.enumAutocompleteAttached = 'true';

        const hiddenId = input.dataset.hiddenTarget;
        const hidden = hiddenId ? document.getElementById(hiddenId) : null;

        let choices = [];
        try {
            choices = JSON.parse(input.getAttribute('data-choices') || '[]');
        } catch (_) {
            return;
        }

        // Pre-fill visible label from the stored enum value.
        if (hidden && hidden.value) {
            const match = choices.find((c) => c.value === hidden.value);
            if (match) input.value = match.label;
        }

        const dropdown = this._buildDropdown();
        input.setAttribute('autocomplete', 'off');

        let debounceTimer = null;

        input.addEventListener('input', () => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => this._render(input, dropdown, choices, hidden), 150);
        });

        input.addEventListener('focus', () => {
            this._render(input, dropdown, choices, hidden);
        });

        input.addEventListener('keydown', (e) => {
            if (dropdown.style.display === 'none') {
                if (e.key === 'ArrowDown' || e.key === 'Enter') {
                    e.preventDefault();
                    this._render(input, dropdown, choices, hidden);
                }
                return;
            }
            const items = dropdown.querySelectorAll('.oa-item');
            const active = dropdown.querySelector('.oa-item.active');
            let idx = Array.from(items).indexOf(active);

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                idx = Math.min(idx + 1, items.length - 1);
                items.forEach((item, n) => item.classList.toggle('active', n === idx));
                items[idx]?.scrollIntoView({ block: 'nearest' });
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                idx = Math.max(idx - 1, 0);
                items.forEach((item, n) => item.classList.toggle('active', n === idx));
                items[idx]?.scrollIntoView({ block: 'nearest' });
            } else if (e.key === 'Enter' && active) {
                e.preventDefault();
                active.click();
            } else if (e.key === 'Escape') {
                dropdown.style.display = 'none';
            }
        });

        input.addEventListener('blur', () => {
            setTimeout(() => {
                dropdown.style.display = 'none';
                // If the visible text is blank, clear the hidden value too.
                if (!input.value.trim() && hidden) {
                    hidden.value = '';
                }
            }, 150);
        });

        document.body.appendChild(dropdown);
        window.addEventListener('resize', () => this._positionDropdown(input, dropdown));
    },

    _render(input, dropdown, choices, hidden) {
        const q = input.value.trim().toLowerCase();
        const filtered = q
            ? choices.filter(
                (c) =>
                    c.label.toLowerCase().includes(q) ||
                    c.value.toLowerCase().replace(/_/g, ' ').includes(q)
              )
            : choices;

        this._positionDropdown(input, dropdown);
        dropdown.innerHTML = '';

        if (filtered.length === 0) {
            const empty = document.createElement('div');
            empty.textContent = 'No matches.';
            Object.assign(empty.style, { padding: '8px 12px', color: '#888', fontSize: '13px' });
            dropdown.appendChild(empty);
            dropdown.style.display = 'block';
            return;
        }

        _ensureOaStyles();
        filtered.slice(0, 60).forEach((choice, idx) => {
            const item = document.createElement('div');
            item.className = 'oa-item' + (idx === 0 ? ' active' : '');
            item.innerHTML = `<span class="oa-label">${_esc(choice.label)}</span>`;
            Object.assign(item.style, {
                padding: '6px 12px',
                cursor: 'pointer',
                borderBottom: '1px solid var(--border, #eee)',
                fontSize: '13px',
            });
            item.addEventListener('mouseenter', () => {
                item.closest('.oa-dropdown').querySelectorAll('.oa-item')
                    .forEach((i) => i.classList.remove('active'));
                item.classList.add('active');
            });
            item.addEventListener('click', () => {
                input.value = choice.label;
                if (hidden) hidden.value = choice.value;
                dropdown.style.display = 'none';
                input.dispatchEvent(new Event('change', { bubbles: true }));
            });
            dropdown.appendChild(item);
        });

        dropdown.style.display = 'block';
    },

    _buildDropdown() {
        const el = document.createElement('div');
        el.className = 'oa-dropdown';
        Object.assign(el.style, {
            position: 'fixed',
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
        dropdown.style.left = `${rect.left}px`;
        dropdown.style.top = `${rect.bottom + 2}px`;
        dropdown.style.width = `${Math.max(rect.width, 320)}px`;
    },
};

window.EnumAutocomplete = EnumAutocomplete;

function _ensureOaStyles() {
    if (document.getElementById('oa-style')) return;
    const s = document.createElement('style');
    s.id = 'oa-style';
    s.textContent = `
        .oa-item.active { background: var(--surface, #f5f5f5); }
        .oa-label { font-weight: 500; }
        .oa-curie { font-size: 11px; color: var(--muted, #888); flex-shrink: 0; }
        .oa-def { font-size: 11px; color: var(--muted, #888); margin-top: 2px; }
        .oa-prefix-pill {
            display: inline-flex;
            align-items: center;
            height: 18px;
            font-size: 10px;
            line-height: 1;
            padding: 0 6px;
            border-radius: 999px;
            background: var(--ontology-pill-bg, #e8f0fe);
            color: var(--ontology-pill-fg, #1558d6);
            border: 1px solid var(--ontology-pill-border, #c5d7fb);
            font-weight: 500;
            letter-spacing: 0;
            white-space: nowrap;
        }
        .oa-selected {
            display: none;
            flex-wrap: wrap;
            gap: 4px;
            margin: 4px 0 6px;
        }
        .oa-chip {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            max-width: 100%;
            padding: 2px 4px;
            border: 1px solid var(--border, #d1d5db);
            border-radius: 999px;
            background: var(--bg, #fff);
            font-size: 12px;
        }
        .oa-chip-label {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .oa-chip-remove {
            border: 0;
            background: transparent;
            color: var(--muted, #666);
            cursor: pointer;
            font-size: 12px;
            line-height: 1;
            padding: 0 3px;
        }
    `;
    document.head.appendChild(s);
}

function _prefixFromCurie(curie) {
    const text = String(curie || '');
    const idx = text.indexOf(':');
    return idx > 0 ? text.slice(0, idx) : '';
}

function _esc(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
