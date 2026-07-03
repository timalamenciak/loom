/**
 * coordinate-list.js — Loom "coordinate_list" widget.
 *
 * Renders a "latitude,longitude" entry field, the sibling country/state
 * fields (embedded inline by schema_engine.py/form_field.html — see
 * loom_ui.yaml's geonames_autofill config), and a "Save location" button
 * that appends a WGS84 coordinate pair to a schema-driven multivalued,
 * class-ranged slot (e.g. SourceDocument.study_coordinates, range
 * StudyCoordinates, inlined_as_list: true). Saved entries are POSTed as
 * `<field>__<index>__latitude` / `<field>__<index>__longitude` hidden inputs
 * — the numeric-index nesting the generic form binder
 * (apps/schemas/input_binding.py) requires for multivalued inlined classes.
 * Posting a flat value under the bare field name is rejected by the binder
 * ("Use the schema-defined nested fields for this value.").
 *
 * As soon as a valid coordinate pair is typed, and a GeoNames endpoint is
 * configured (data-geonames-endpoint), the widget calls it and fills the
 * country/state inputs named via data-country-field-id / data-state-field-id
 * (this widget never hardcodes study_country / study_state_or_province
 * itself). The saved-locations listbox shows the country/state alongside
 * each entry for audit, purely as display metadata — only latitude/longitude
 * are schema attributes of StudyCoordinates and get posted. Clicking a saved
 * entry loads its coordinates/country/state back into the editable fields;
 * clicking "Save location" again then updates that entry in place instead of
 * appending a new one.
 *
 * Initialization (called once on DOMContentLoaded, and again after each HTMX
 * swap of #form-panel — see annotate.html):
 *   CoordinateList.init();
 */
const CoordinateList = {
    init() {
        document.querySelectorAll('[data-coordinate-list]').forEach((el) => this.attach(el));
    },

    attach(container) {
        if (container.dataset.coordinateListAttached === 'true') return;
        container.dataset.coordinateListAttached = 'true';

        const fieldName = container.dataset.fieldName;
        const entryInput = container.querySelector('[data-coordinate-entry]');
        const saveBtn = container.querySelector('[data-coordinate-save]');
        const removeBtn = container.querySelector('[data-coordinate-remove]');
        const listbox = container.querySelector('[data-coordinate-listbox]');
        const hiddenWrap = container.querySelector('[data-coordinate-hidden-inputs]');
        const status = container.querySelector('[data-coordinate-status]');
        const countryField = container.dataset.countryFieldId
            ? document.getElementById(container.dataset.countryFieldId)
            : null;
        const stateField = container.dataset.stateFieldId
            ? document.getElementById(container.dataset.stateFieldId)
            : null;

        let entries = [];
        try {
            const parsed = JSON.parse(container.dataset.initial || '[]');
            if (Array.isArray(parsed)) entries = parsed;
        } catch (e) {
            entries = [];
        }
        // Older saved entries only carry latitude/longitude — normalize so
        // every entry has the same shape for rendering/editing.
        entries = entries.map((e) => ({
            latitude: e.latitude,
            longitude: e.longitude,
            country: e.country || '',
            state: e.state || '',
        }));

        let editingIndex = null;
        let lookupTimer = null;

        const setStatus = (message, isError) => {
            if (!status) return;
            status.textContent = message;
            status.style.color = isError ? '#dc2626' : '#6b7280';
        };

        const render = () => {
            hiddenWrap.innerHTML = '';
            listbox.innerHTML = '';
            entries.forEach((entry, index) => {
                ['latitude', 'longitude'].forEach((key) => {
                    const value = entry[key];
                    if (value === null || value === undefined || value === '') return;
                    const input = document.createElement('input');
                    input.type = 'hidden';
                    input.name = `${fieldName}__${index}__${key}`;
                    input.value = value;
                    hiddenWrap.appendChild(input);
                });
                const option = document.createElement('option');
                option.value = String(index);
                const place = [entry.country, entry.state].filter((v) => v).join(', ');
                option.textContent = place
                    ? `${entry.latitude}, ${entry.longitude} — ${place}`
                    : `${entry.latitude}, ${entry.longitude}`;
                if (index === editingIndex) option.selected = true;
                listbox.appendChild(option);
            });
        };

        const parseEntry = (raw) => {
            const parts = raw.split(',').map((p) => p.trim()).filter((p) => p.length);
            if (parts.length !== 2) return null;
            const lat = Number(parts[0]);
            const lon = Number(parts[1]);
            if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
            if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
            return { latitude: lat, longitude: lon };
        };

        const lookupGeonames = (lat, lon) => {
            const endpoint = container.dataset.geonamesEndpoint;
            if (!endpoint || (!countryField && !stateField)) return;
            setStatus('Looking up location…', false);
            const url = new URL(endpoint, window.location.origin);
            url.searchParams.set('latitude', String(lat));
            url.searchParams.set('longitude', String(lon));
            fetch(url)
                .then((r) => r.json())
                .then((data) => {
                    if (data.error) {
                        setStatus(data.error, true);
                        return;
                    }
                    if (countryField && data.study_country) countryField.value = data.study_country;
                    if (stateField && data.study_state_or_province) {
                        stateField.value = data.study_state_or_province;
                    }
                    setStatus('Country/state filled from GeoNames — check before saving.', false);
                })
                .catch(() => setStatus('GeoNames lookup failed.', true));
        };

        // Auto-lookup as soon as a valid pair is typed, debounced so it
        // doesn't fire on every keystroke.
        entryInput?.addEventListener('input', () => {
            if (lookupTimer) clearTimeout(lookupTimer);
            const raw = entryInput.value;
            lookupTimer = setTimeout(() => {
                const parsed = parseEntry(raw);
                if (parsed) lookupGeonames(parsed.latitude, parsed.longitude);
            }, 500);
        });

        const saveLocation = () => {
            const parsed = parseEntry(entryInput.value || '');
            if (!parsed) {
                setStatus(
                    'Enter coordinates as "latitude,longitude" (e.g. 43.466752,-80.5371904).',
                    true
                );
                return;
            }
            const entry = {
                latitude: parsed.latitude,
                longitude: parsed.longitude,
                country: countryField ? countryField.value.trim() : '',
                state: stateField ? stateField.value.trim() : '',
            };
            if (editingIndex !== null && editingIndex < entries.length) {
                entries[editingIndex] = entry;
                setStatus('Location updated.', false);
            } else {
                entries.push(entry);
                setStatus('Location saved.', false);
            }
            editingIndex = null;
            entryInput.value = '';
            render();
        };

        saveBtn?.addEventListener('click', saveLocation);
        entryInput?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                saveLocation();
            }
        });

        // Click (or ctrl/shift-click for bulk removal) a saved entry to load
        // it back into the editable fields above.
        listbox?.addEventListener('change', () => {
            const selected = listbox.selectedOptions;
            if (selected.length !== 1) return;
            const index = Number(selected[0].value);
            const entry = entries[index];
            if (!entry) return;
            editingIndex = index;
            entryInput.value = `${entry.latitude},${entry.longitude}`;
            if (countryField) countryField.value = entry.country || '';
            if (stateField) stateField.value = entry.state || '';
            setStatus(
                'Editing saved location — change the fields and click "Save location" to update it.',
                false
            );
        });

        removeBtn?.addEventListener('click', () => {
            const selected = new Set(Array.from(listbox.selectedOptions).map((o) => Number(o.value)));
            if (!selected.size) return;
            entries = entries.filter((_, index) => !selected.has(index));
            if (editingIndex !== null && selected.has(editingIndex)) {
                editingIndex = null;
                entryInput.value = '';
            }
            render();
        });

        render();
    },
};

window.CoordinateList = CoordinateList;
