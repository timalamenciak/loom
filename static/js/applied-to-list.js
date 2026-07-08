/**
 * applied-to-list.js — Loom "applied_to_list" widget.
 *
 * Manages an editable list of AppliedToEntity records on a CausalNode.
 * Each record is {entity_type (EntityTypeEnum) + entity_term (CURIE or
 * free text)}. Saved entries are POSTed as:
 *   applied_to__<index>__entity_type
 *   applied_to__<index>__entity_term
 * matching the generic inlined-list convention in apps/schemas/input_binding.py.
 *
 * The entity_term field uses OntologyAutocomplete with conditional routing
 * driven by entity_type, mirroring the node-level entity_term field (see
 * config/loom_ui.yaml ontology_routing.applied_to).
 *
 * Initialization:
 *   AppliedToList.init();
 */

let _appliedToCounter = 0;

const AppliedToList = {
    init() {
        document.querySelectorAll('[data-applied-to-list]').forEach((el) => this.attach(el));
    },

    attach(container) {
        if (container.dataset.appliedToListAttached === 'true') return;
        container.dataset.appliedToListAttached = 'true';

        const uid = ++_appliedToCounter;
        const fieldName = container.dataset.fieldName;
        const allowFreeText = container.dataset.allowFreeText === 'true';

        let entityTypeChoices = [];
        try {
            entityTypeChoices = JSON.parse(container.dataset.entityTypeChoices || '[]');
        } catch (_) {}

        let routes = {};
        try {
            routes = JSON.parse(container.dataset.ontologyRoutes || '{}');
        } catch (_) {}

        let defaultPrefixes = container.dataset.defaultPrefixes || '';
        let defaultWdLive = null;
        try {
            if (container.dataset.defaultWikidataLive) {
                defaultWdLive = JSON.parse(container.dataset.defaultWikidataLive);
            }
        } catch (_) {}

        let entries = [];
        try {
            const parsed = JSON.parse(container.dataset.initial || '[]');
            if (Array.isArray(parsed)) entries = parsed;
        } catch (_) {}
        entries = entries
            .filter((e) => e && (e.entity_type || e.entity_term))
            .map((e) => ({ entity_type: e.entity_type || '', entity_term: e.entity_term || '' }));

        const hiddenWrap = container.querySelector('[data-applied-to-hidden-inputs]');
        const entryList = container.querySelector('[data-applied-to-entry-list]');
        const typeSelect = container.querySelector('[data-applied-to-type]');
        const termLabel = container.querySelector('[data-applied-to-term-label]');
        const termValue = container.querySelector('[data-applied-to-term-value]');
        const addBtn = container.querySelector('[data-applied-to-add]');
        const statusEl = container.querySelector('[data-applied-to-status]');

        // Unique IDs so OntologyAutocomplete can find the condition element.
        const typeSelectId = `applied-to-type-${uid}`;
        const termValueId = `applied-to-term-val-${uid}`;
        if (typeSelect) typeSelect.id = typeSelectId;
        if (termValue) termValue.id = termValueId;

        const setStatus = (msg, isError = false) => {
            if (!statusEl) return;
            statusEl.textContent = msg;
            statusEl.style.color = isError ? '#dc2626' : '#6b7280';
        };

        const choiceLabel = (value) => {
            const c = entityTypeChoices.find((ch) => ch.value === value);
            return c ? c.label : value;
        };

        const render = () => {
            if (hiddenWrap) hiddenWrap.innerHTML = '';
            if (entryList) entryList.innerHTML = '';

            entries.forEach((entry, index) => {
                // Hidden inputs for form submission.
                ['entity_type', 'entity_term'].forEach((key) => {
                    const val = entry[key];
                    if (val === null || val === undefined || val === '') return;
                    const input = document.createElement('input');
                    input.type = 'hidden';
                    input.name = `${fieldName}__${index}__${key}`;
                    input.value = val;
                    hiddenWrap?.appendChild(input);
                });

                // Visible list item.
                const li = document.createElement('li');
                li.style.cssText =
                    'display:flex;align-items:center;gap:.4rem;padding:.3rem .4rem;' +
                    'border:1px solid #e5e7eb;border-radius:4px;margin-bottom:.3rem;font-size:.82rem';
                const typeLabel = choiceLabel(entry.entity_type) || entry.entity_type;
                const termDisplay = entry.entity_term || '—';
                const text = document.createElement('span');
                text.style.flex = '1';
                text.innerHTML = `<strong>${_atEsc(typeLabel)}</strong>: ${_atEsc(termDisplay)}`;
                const del = document.createElement('button');
                del.type = 'button';
                del.textContent = '×';
                del.title = 'Remove this entry';
                del.style.cssText =
                    'background:none;border:none;color:#b91c1c;cursor:pointer;font-size:1rem;' +
                    'line-height:1;padding:0 .25rem;flex-shrink:0';
                del.addEventListener('click', () => {
                    entries.splice(index, 1);
                    render();
                });
                li.appendChild(text);
                li.appendChild(del);
                entryList?.appendChild(li);
            });
        };

        // Wire up the entity_term label input with OntologyAutocomplete so it
        // gets conditional routing from entity_type (mirrors node-level entity_term).
        if (termLabel && termValue) {
            termLabel.dataset.ontologyPrefixes = defaultPrefixes;
            termLabel.dataset.curieTarget = termValueId;
            termLabel.dataset.ontologyConditionSlot = typeSelectId;
            termLabel.dataset.ontologyRoutes = JSON.stringify(routes);
            if (allowFreeText) termLabel.dataset.ontologyAllowFreeText = 'true';
            if (defaultWdLive) {
                termLabel.dataset.wikidataLive = 'true';
                if (defaultWdLive.root_qid) {
                    termLabel.dataset.wikidataRootQid = defaultWdLive.root_qid;
                }
            }
            // OntologyAutocomplete.attach() is idempotent (guards on dataset flag).
            window.OntologyAutocomplete?.attach(termLabel);
        }

        const resetAddForm = () => {
            if (typeSelect) typeSelect.value = '';
            if (termLabel) {
                termLabel.value = '';
                termLabel._oaSelectedLabel = '';
                termLabel.setCustomValidity?.('');
            }
            if (termValue) termValue.value = '';
            setStatus('');
        };

        const addEntry = () => {
            const entityType = typeSelect?.value || '';
            const entityTerm = termValue?.value?.trim() || '';

            if (!entityType) {
                setStatus('Select an entity type before adding.', true);
                return;
            }
            if (!entityTerm) {
                setStatus('Enter or select an entity term before adding.', true);
                return;
            }

            entries.push({ entity_type: entityType, entity_term: entityTerm });
            render();
            resetAddForm();
            setStatus('Entry added.', false);
        };

        addBtn?.addEventListener('click', addEntry);

        // Allow Enter in the term label input to trigger add.
        termLabel?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                addEntry();
            }
        });

        render();
    },
};

window.AppliedToList = AppliedToList;

function _atEsc(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
