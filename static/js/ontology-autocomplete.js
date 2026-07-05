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
 * Conditional routing: an input carrying [data-ontology-condition-slot] (the
 * DOM id of a sibling field, e.g. entity_type) and [data-ontology-routes]
 * (a JSON map of that field's value -> {prefixes, wikidata_live}) re-queries
 * with the matching route whenever the sibling field changes. See
 * config/loom_ui.yaml's ontology_routing `condition_slot` shape.
 *
 * Free text: an input carrying [data-ontology-allow-free-text="true"] gets a
 * "Propose new term" row in its dropdown. Picking it stores the typed text
 * as the slot's value (schema must allow a string alternative to uriorcurie)
 * and opens a small form to log an OntologyTermSuggestion for a curator to
 * process upstream, via the suggestUrl passed to init().
 *
 * Initialization (called once on DOMContentLoaded):
 *   OntologyAutocomplete.init('/ontology/search/', '/ontology/suggest/');
 *
 * Or attach to a single input:
 *   OntologyAutocomplete.attach(inputEl);
 */

const OntologyAutocomplete = {
    _searchUrl: '/ontology/search/',
    _suggestUrl: '',
    _activeDropdown: null,

    init(searchUrl = '/ontology/search/', suggestUrl = '') {
        this._searchUrl = searchUrl;
        this._suggestUrl = suggestUrl;
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
        input._oaSelectedLabel = '';
        input._oaAbort = null;
        if (input.dataset.ontologyMultivalue === 'true') {
            this._renderSelected(input);
        }
        this._hydrate(input);
        this._wireConditionalRouting(input);

        input.addEventListener('input', () => {
            clearTimeout(debounceTimer);
            const q = input.value.trim();
            if (input.dataset.ontologyMultivalue !== 'true') {
                const hidden = this._hiddenInput(input);
                const allowFreeText = input.dataset.ontologyAllowFreeText === 'true';
                if (hidden && q !== input._oaSelectedLabel) {
                    if (allowFreeText) {
                        // CAMO's any_of [uriorcurie, string] pattern (entity_term,
                        // measured_attribute, ...) accepts free text as a real
                        // value in its own right — it isn't just a staging area
                        // for a "Propose new term" click. Keep the submitted
                        // value in sync with what's typed; picking an actual
                        // suggestion (_selectTerm) overwrites it with the CURIE.
                        hidden.value = q;
                        this._clearWikidataHints(input);
                    } else {
                        hidden.value = '';
                    }
                }
                input.setCustomValidity(
                    q && !allowFreeText && q !== input._oaSelectedLabel
                        ? 'Select a term from the suggestions.'
                        : ''
                );
            }
            if (q.length < 2) {
                dropdown.style.display = 'none';
                this._setStatus(input, '');
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

        if (input._oaAbort) input._oaAbort.abort();
        input._oaAbort = new AbortController();
        this._setStatus(input, 'Searching…');
        let data;
        try {
            const resp = await fetch(url, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                signal: input._oaAbort.signal,
            });
            if (!resp.ok) throw new Error(`Search failed (${resp.status})`);
            data = await resp.json();
        } catch (error) {
            if (error.name === 'AbortError') return;
            dropdown.style.display = 'none';
            this._setStatus(input, 'Ontology search is temporarily unavailable.', true);
            return;
        }

        this._positionDropdown(input, dropdown);
        dropdown.innerHTML = '';

        if (!data.results || data.results.length === 0) {
            const empty = document.createElement('div');
            empty.textContent = 'No terms found.';
            Object.assign(empty.style, { padding: '8px 12px', color: '#888', fontSize: '13px' });
            dropdown.appendChild(empty);
            if (input.dataset.ontologyAllowFreeText === 'true') {
                _ensureOaStyles();
                dropdown.appendChild(this._buildFreeTextItem(input, q));
            }
            dropdown.style.display = 'block';
            const unavailable = data.meta?.unavailable_prefixes || [];
            this._setStatus(
                input,
                unavailable.length
                    ? `Not loaded: ${unavailable.join(', ')}.`
                    : 'No matching cached terms.',
                unavailable.length > 0,
            );
            return;
        }

        _ensureOaStyles();
        data.results.forEach((term, idx) => {
            dropdown.appendChild(this._buildItem(input, term, idx === 0));
        });
        if (input.dataset.ontologyAllowFreeText === 'true') {
            dropdown.appendChild(this._buildFreeTextItem(input, q));
        }

        const unavailable = data.meta?.unavailable_prefixes || [];
        this._setStatus(
            input,
            unavailable.length ? `Some ontologies are not loaded: ${unavailable.join(', ')}.` : '',
            unavailable.length > 0,
        );
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
        input._oaSelectedLabel = term.label;
        input.setCustomValidity('');

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

    async _hydrate(input) {
        const hidden = this._hiddenInput(input);
        if (!hidden) return;
        const values = this._hiddenValues(hidden);
        if (!values.length) return;

        const prefixes = input.dataset.ontologyPrefixes || '';
        const separator = this._searchUrl.includes('?') ? '&' : '?';
        const url = `${this._searchUrl}${separator}curies=${encodeURIComponent(values.join(','))}&prefixes=${encodeURIComponent(prefixes)}`;
        try {
            const resp = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
            if (!resp.ok) throw new Error(`Lookup failed (${resp.status})`);
            const data = await resp.json();
            (data.results || []).forEach((term) => input._oaLabels.set(term.curie, term.label));
            if (input.dataset.ontologyMultivalue === 'true') {
                this._renderSelected(input);
            } else {
                const match = (data.results || []).find((term) => term.curie === hidden.value);
                if (match) {
                    input.value = match.label;
                    input._oaSelectedLabel = match.label;
                    input.setCustomValidity('');
                }
            }
        } catch {
            this._setStatus(input, 'Saved term label could not be resolved.', true);
        }
    },

    _setStatus(input, message, isError = false) {
        const status = input.closest('.field')?.querySelector('[data-ontology-status]');
        if (!status) return;
        status.textContent = message;
        status.style.color = isError ? '#b91c1c' : '';
    },

    // ── Conditional (sibling-field-aware) routing ──────────────────────────

    _wireConditionalRouting(input) {
        const conditionId = input.dataset.ontologyConditionSlot;
        if (!conditionId) return;
        let routes = {};
        try {
            routes = JSON.parse(input.dataset.ontologyRoutes || '{}');
        } catch (_) {
            return;
        }
        const conditionEl = document.getElementById(conditionId);
        if (!conditionEl) return;

        const applyRoute = (isChange) => {
            const route = routes[conditionEl.value];
            if (!route) return; // no match — keep the server-rendered default route
            input.dataset.ontologyPrefixes = (route.prefixes || []).join(',');
            if (route.wikidata_live) {
                input.dataset.wikidataLive = 'true';
                if (route.wikidata_live.root_qid) {
                    input.dataset.wikidataRootQid = route.wikidata_live.root_qid;
                } else {
                    delete input.dataset.wikidataRootQid;
                }
            } else {
                delete input.dataset.wikidataLive;
                delete input.dataset.wikidataRootQid;
            }
            if (isChange) {
                // The entity type changed after a term was already picked for
                // the old type — that pick is very likely wrong for the new
                // type, so clear it rather than silently keep a mismatched CURIE.
                input.value = '';
                input._oaSelectedLabel = '';
                const hidden = this._hiddenInput(input);
                if (hidden) {
                    hidden.value = '';
                    hidden.dispatchEvent(new Event('change', { bubbles: true }));
                }
                this._clearWikidataHints(input);
            }
        };

        applyRoute(false);
        conditionEl.addEventListener('change', () => applyRoute(true));
    },

    // ── Free text + "propose new term" ──────────────────────────────────────

    _buildFreeTextItem(input, query) {
        const item = document.createElement('div');
        item.className = 'oa-item oa-freetext-item';
        item.innerHTML = `<span class="oa-label">+ Propose new term: "${_esc(query)}"</span>`;
        Object.assign(item.style, {
            padding: '6px 12px',
            cursor: 'pointer',
            borderTop: '1px dashed var(--border, #ddd)',
            fontSize: '13px',
            color: 'var(--accent, #1558d6)',
        });
        item.addEventListener('mouseenter', () => {
            item.closest('.oa-dropdown').querySelectorAll('.oa-item')
                .forEach((i) => i.classList.remove('active'));
            item.classList.add('active');
        });
        item.addEventListener('click', () => {
            this._selectFreeText(input, query);
            item.closest('.oa-dropdown').style.display = 'none';
        });
        return item;
    },

    _selectFreeText(input, query) {
        if (!query) return;
        if (input.dataset.ontologyMultivalue === 'true') {
            this._addMultivalueTerm(input, { curie: query, label: query });
        } else {
            input.value = query;
            input._oaSelectedLabel = query;
            input.setCustomValidity('');
            const hidden = this._hiddenInput(input);
            if (hidden) {
                hidden.value = query;
                hidden.dispatchEvent(new Event('change', { bubbles: true }));
            }
            this._clearWikidataHints(input);
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }
        this._openSuggestForm(input, query);
    },

    _openSuggestForm(input, query) {
        if (!this._suggestUrl) return; // free text is still saved; logging is just unavailable
        const field = input.closest('.field');
        if (!field) return;
        const existing = field.querySelector('[data-ontology-suggest-panel]');
        if (existing) existing.remove();

        _ensureOaStyles();
        const prefixes = (input.dataset.ontologyPrefixes || '')
            .split(',').map((p) => p.trim()).filter(Boolean);
        const options = [...prefixes];
        if (input.dataset.wikidataLive === 'true') options.push('Wikidata');

        const panel = document.createElement('div');
        panel.dataset.ontologySuggestPanel = 'true';
        panel.className = 'oa-suggest-panel';
        panel.innerHTML = `
            <div class="oa-suggest-title">"${_esc(query)}" isn't in the cached ontology yet. Propose it?</div>
            <label class="oa-suggest-label">Target ontology
                <select class="oa-suggest-target">
                    ${options.map((o) => `<option value="${_esc(o)}">${_esc(o)}</option>`).join('')}
                    <option value="other">Other / not sure</option>
                </select>
            </label>
            <label class="oa-suggest-label">Suggested parent term (optional)
                <input type="text" class="oa-suggest-parent" placeholder="Broader existing term…">
            </label>
            <label class="oa-suggest-label">Definition (optional)
                <textarea class="oa-suggest-definition" rows="2" placeholder="Plain-language definition…"></textarea>
            </label>
            <div class="oa-suggest-actions">
                <button type="button" class="oa-suggest-submit">Log suggestion</button>
                <button type="button" class="oa-suggest-dismiss">Not now</button>
            </div>
            <div class="oa-suggest-status" aria-live="polite"></div>
        `;
        panel.querySelector('.oa-suggest-dismiss').addEventListener('click', () => panel.remove());
        panel.querySelector('.oa-suggest-submit').addEventListener('click', () => {
            this._submitSuggestion(input, query, panel);
        });
        field.appendChild(panel);
    },

    async _submitSuggestion(input, query, panel) {
        const status = panel.querySelector('.oa-suggest-status');
        const target = panel.querySelector('.oa-suggest-target').value;
        const parent = panel.querySelector('.oa-suggest-parent').value.trim();
        const definition = panel.querySelector('.oa-suggest-definition').value.trim();
        const hidden = this._hiddenInput(input);
        status.textContent = 'Logging…';
        status.style.color = '';
        try {
            const resp = await fetch(this._suggestUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': _csrfToken(),
                },
                body: JSON.stringify({
                    slot: hidden ? hidden.name : '',
                    label: query,
                    target_ontology: target,
                    suggested_parent: parent,
                    definition,
                }),
            });
            if (!resp.ok) throw new Error(`Failed (${resp.status})`);
            status.textContent = 'Logged for review — thank you.';
            setTimeout(() => panel.remove(), 2500);
        } catch (error) {
            status.textContent = 'Could not log the suggestion right now; your annotation is still saved.';
            status.style.color = '#b91c1c';
        }
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
        .oa-suggest-panel {
            margin-top: 6px;
            padding: 8px 10px;
            border: 1px solid var(--border, #d1d5db);
            border-radius: 6px;
            background: var(--surface, #f9fafb);
            font-size: 12px;
        }
        .oa-suggest-title { margin-bottom: 6px; font-weight: 500; }
        .oa-suggest-label {
            display: block;
            margin-bottom: 6px;
            font-size: 11px;
            color: var(--muted, #666);
        }
        .oa-suggest-label select,
        .oa-suggest-label input,
        .oa-suggest-label textarea {
            display: block;
            width: 100%;
            margin-top: 2px;
            font-size: 12px;
            box-sizing: border-box;
        }
        .oa-suggest-actions { display: flex; gap: 6px; margin-top: 4px; }
        .oa-suggest-status { margin-top: 4px; font-size: 11px; color: var(--muted, #666); }
    `;
    document.head.appendChild(s);
}

function _csrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : '';
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
