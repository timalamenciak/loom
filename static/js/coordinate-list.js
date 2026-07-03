/**
 * coordinate-list.js — Loom "coordinate_list" widget.
 *
 * Renders a single "latitude,longitude" entry field plus a "Save location"
 * button that appends a WGS84 coordinate pair to a schema-driven multivalued,
 * class-ranged slot (e.g. SourceDocument.study_coordinates, range
 * StudyCoordinates, inlined_as_list: true). Saved entries are POSTed as
 * `<field>__<index>__latitude` / `<field>__<index>__longitude` hidden inputs
 * — the numeric-index nesting the generic form binder
 * (apps/schemas/input_binding.py) requires for multivalued inlined classes.
 * Posting a flat value under the bare field name is rejected by the binder
 * ("Use the schema-defined nested fields for this value.").
 *
 * On each successful save, if a GeoNames endpoint is configured
 * (data-geonames-endpoint) the widget calls it and fills the sibling
 * country/state inputs named via data-country-field-id / data-state-field-id
 * (see loom_ui.yaml's geonames_autofill config — this widget never hardcodes
 * study_country / study_state_or_province itself).
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

        let entries = [];
        try {
            const parsed = JSON.parse(container.dataset.initial || '[]');
            if (Array.isArray(parsed)) entries = parsed;
        } catch (e) {
            entries = [];
        }

        const setStatus = (message, isError) => {
            if (!status) return;
            status.textContent = message;
            status.style.color = isError ? '#dc2626' : '#6b7280';
        };

        const render = () => {
            hiddenWrap.innerHTML = '';
            listbox.innerHTML = '';
            entries.forEach((entry, index) => {
                Object.entries(entry).forEach(([key, value]) => {
                    if (value === null || value === undefined || value === '') return;
                    const input = document.createElement('input');
                    input.type = 'hidden';
                    input.name = `${fieldName}__${index}__${key}`;
                    input.value = value;
                    hiddenWrap.appendChild(input);
                });
                const option = document.createElement('option');
                option.value = String(index);
                option.textContent = `${entry.latitude}, ${entry.longitude}`;
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
            if (!endpoint) return;
            const countryField = container.dataset.countryFieldId
                ? document.getElementById(container.dataset.countryFieldId)
                : null;
            const stateField = container.dataset.stateFieldId
                ? document.getElementById(container.dataset.stateFieldId)
                : null;
            if (!countryField && !stateField) return;

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
                    setStatus('Location saved — country/state filled from GeoNames.', false);
                })
                .catch(() => setStatus('Location saved, but the GeoNames lookup failed.', true));
        };

        const saveLocation = () => {
            const parsed = parseEntry(entryInput.value || '');
            if (!parsed) {
                setStatus(
                    'Enter coordinates as "latitude,longitude" (e.g. 43.466752,-80.5371904).',
                    true
                );
                return;
            }
            entries.push(parsed);
            render();
            entryInput.value = '';
            setStatus('Location saved.', false);
            lookupGeonames(parsed.latitude, parsed.longitude);
        };

        saveBtn?.addEventListener('click', saveLocation);
        entryInput?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                saveLocation();
            }
        });

        removeBtn?.addEventListener('click', () => {
            const selected = new Set(Array.from(listbox.selectedOptions).map((o) => Number(o.value)));
            if (!selected.size) return;
            entries = entries.filter((_, index) => !selected.has(index));
            render();
        });

        render();
    },
};

window.CoordinateList = CoordinateList;
