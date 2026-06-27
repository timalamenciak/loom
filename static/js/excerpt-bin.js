/** Persistent multi-excerpt collection and grounding-form launcher. */
(function () {
    const state = {
        nodeFormUrl: '',
        edgeFormUrl: '',
        formTarget: '#form-panel',
    };

    function choices() {
        return Array.from(document.querySelectorAll('#excerpt-bin [data-excerpt-choice]'));
    }

    function selectedIds() {
        return choices().filter((input) => input.checked).map((input) => input.value);
    }

    function updateControls() {
        const count = selectedIds().length;
        document.querySelectorAll('#excerpt-bin [data-excerpt-action]').forEach((button) => {
            button.disabled = count === 0;
        });
        const label = document.querySelector('#excerpt-bin .excerpt-selection-count');
        if (label) label.textContent = `${count} selected`;
    }

    function csrfToken(form) {
        return form.querySelector('input[name="csrfmiddlewaretoken"]')?.value || '';
    }

    async function deleteExcerpt(form) {
        if (!window.confirm('Delete this excerpt? Any grounding links to it will also be removed.')) return;
        const response = await fetch(form.action, {
            method: 'POST',
            headers: {
                'HX-Request': 'true',
                'X-CSRFToken': csrfToken(form),
            },
            body: new FormData(form),
        });
        if (!response.ok) return;
        refreshFromHtml(await response.text());
    }

    function refreshFromHtml(html, newlySelectedId) {
        if (!html) return;
        const preserved = new Set(selectedIds());
        if (newlySelectedId) preserved.add(String(newlySelectedId));

        const parsed = new DOMParser().parseFromString(html, 'text/html');
        const replacement = parsed.querySelector('#excerpt-bin');
        const current = document.getElementById('excerpt-bin');
        if (!replacement || !current) return;
        current.replaceWith(replacement);

        choices().forEach((input) => {
            input.checked = preserved.has(input.value);
        });
        updateControls();
    }

    function withSelected(url, ids) {
        const chosen = ids || selectedIds();
        if (!chosen.length) return url;
        const next = new URL(url, window.location.href);
        next.searchParams.set('span_pks', chosen.join(','));
        return next.pathname + next.search;
    }

    function useSelected(kind) {
        const ids = selectedIds();
        if (!ids.length) return;
        const base = kind === 'node' ? state.nodeFormUrl : state.edgeFormUrl;
        const loader = window.LoomAnnotationActions?.load;
        if (loader) {
            loader(withSelected(base, ids), state.formTarget);
            return;
        }
        window.location.href = withSelected(base, ids);
    }

    function showDocumentView(view) {
        const text = document.getElementById('document-view-text');
        const pdf = document.getElementById('document-view-pdf');
        if (text) text.hidden = view !== 'text';
        if (pdf) pdf.hidden = view !== 'pdf';
        document.querySelectorAll('[data-document-view-button]').forEach((button) => {
            button.classList.toggle('active', button.dataset.documentViewButton === view);
        });
    }

    function reveal(spanId) {
        showDocumentView('text');
        const marks = Array.from(document.querySelectorAll('#canonical-text mark[data-span-pks]'));
        const mark = marks.find((candidate) =>
            (candidate.dataset.spanPks || '').split(',').includes(String(spanId))
        );
        document.querySelectorAll('mark.excerpt-active').forEach((candidate) => {
            candidate.classList.remove('excerpt-active');
        });
        if (mark) {
            mark.classList.add('excerpt-active');
            mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    function flash(message) {
        const header = document.querySelector('#excerpt-bin .excerpt-bin-header p');
        if (!header) return;
        const previous = header.textContent;
        header.textContent = message;
        window.setTimeout(() => { header.textContent = previous; }, 1800);
    }

    function init(options) {
        Object.assign(state, options || {});
        updateControls();
    }

    document.addEventListener('change', (event) => {
        if (event.target.matches?.('#excerpt-bin [data-excerpt-choice]')) updateControls();
    });
    document.addEventListener('submit', (event) => {
        const form = event.target.closest?.('.excerpt-delete-form');
        if (!form) return;
        event.preventDefault();
        deleteExcerpt(form);
    }, true);
    document.addEventListener('htmx:afterSettle', updateControls);

    window.ExcerptBin = {
        init,
        refreshFromHtml,
        reveal,
        selectedIds,
        showDocumentView,
        useSelected,
        withSelected,
        flash,
    };
})();
