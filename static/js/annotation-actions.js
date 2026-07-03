/**
 * annotation-actions.js
 *
 * Small local handler for the HTMX patterns used by the annotation screen.
 * This keeps Add Node/Add Edge usable even when CDN HTMX is absent, late, or
 * present but not bound to these controls.
 */

(function () {
    function csrfToken(scope) {
        const input = scope?.querySelector?.('input[name="csrfmiddlewaretoken"]')
            || document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (input?.value) return input.value;

        const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    function targetFor(el) {
        const selector = el.getAttribute('hx-target') || el.closest('[hx-target]')?.getAttribute('hx-target');
        return selector ? document.querySelector(selector) : null;
    }

    function parseHxVals(el) {
        const raw = el.getAttribute('hx-vals');
        if (!raw) return {};
        try {
            return JSON.parse(raw);
        } catch (err) {
            console.warn('Could not parse hx-vals:', err);
            return {};
        }
    }

    function initFormEnhancements() {
        window.OntologyAutocomplete?.init(window.loomOntologySearchUrl || '/ontology/search/');
        window.EnumAutocomplete?.init();
        initAutoSaveForms();
    }

    // Auto-save with debounce and save indicator
    function debounce(func, wait) {
        let timeout;
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    function updateSaveIndicator(timestamp) {
        const indicator = document.querySelector('[data-save-indicator]');
        const icon = document.getElementById('save-indicator');
        if (indicator && timestamp) {
            const time = new Date(timestamp).toLocaleTimeString();
            indicator.innerHTML = `Saved ${time}`;
            indicator.setAttribute('title', `Last saved: ${timestamp}`);
            if (icon) {
                icon.setAttribute('stroke', '#059669');
                icon.setAttribute('fill', '#6ee7b7');
            }
        }
    }

    async function autoSaveField(field, csrfToken, baseUrl) {
        if (!field.name || !field.closest('form')) return;
        
        const form = field.closest('form');
        const graphId = form.dataset.graphId;
        const annotationType = form.dataset.annotationType;
        const annotationId = form.dataset.annotationId;

        if (!graphId || !annotationType || !annotationId) return;

        const fieldData = { [field.name]: field.value };
        
        try {
            const response = await fetch(`${baseUrl}/${graphId}/documents/${field.dataset.docId}/autosave/${annotationType}/${annotationId}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken(form)
                },
                body: JSON.stringify(fieldData)
            });
            
            if (response.ok) {
                const data = await response.json();
                updateSaveIndicator(data.last_saved);
            }
        } catch (err) {
            console.error('Auto-save failed:', err);
        }
    }

    function initAutoSaveForms() {
        const saveIndicatorBase = window.loomAutoSaveUrl || '/annotation/';
        const csrfTokens = new WeakMap();

        document.querySelectorAll('.form-panel-inner form').forEach(form => {
            const fields = form.querySelectorAll('input, select, textarea');
            const docId = form.dataset.docId;
            
            fields.forEach(field => {
                const debouncedSave = debounce(async () => {
                    if (!csrfTokens.has(form)) {
                        csrfTokens.set(form, csrfToken(form));
                    }
                    await autoSaveField(field, csrfTokens.get(form), saveIndicatorBase);
                    field.dataset.lastSave = Date.now().toString();
                }, 500);

                field.addEventListener('input', debouncedSave);
                field.dataset.docId = docId;
            });
        });
    }

    function swapHtml(target, html) {
        if (!target) return;

        const template = document.createElement('template');
        template.innerHTML = html.trim();

        template.content.querySelectorAll('[hx-swap-oob="true"]').forEach((node) => {
            if (node.id) {
                const existing = document.getElementById(node.id);
                if (existing) existing.innerHTML = node.innerHTML;
            }
            node.remove();
        });

        target.innerHTML = template.innerHTML;
        initFormEnhancements();
        target.dispatchEvent(new CustomEvent('htmx:afterSwap', { bubbles: true, detail: { target } }));
        document.dispatchEvent(new CustomEvent('htmx:afterSettle', { detail: { target } }));
    }

    async function requestHtml(method, url, options) {
        let target = options?.target ? document.querySelector(options.target) : options?.targetElement;
        const body = options?.body || null;
        const headers = {
            'HX-Request': 'true',
        };

        const token = options?.csrfToken || csrfToken(target || document);
        if (token) headers['X-CSRFToken'] = token;

        let response;
        try {
            response = await fetch(url, { method, headers, body });
        } catch (err) {
            if (target) target.innerHTML = '<p class="message message-error">Request failed. Check the server and try again.</p>';
            console.error('Annotation request failed:', err);
            return null;
        }

        const contentType = response.headers.get('content-type') || '';
        const text = await response.text();
        const retarget = response.headers.get('HX-Retarget');
        if (retarget) target = document.querySelector(retarget) || target;

        if (!response.ok) {
            if (target && contentType.includes('text/html') && text) {
                swapHtml(target, text);
                return response;
            }
            let message = 'Could not save this annotation.';
            if (contentType.includes('application/json')) {
                try {
                    const data = JSON.parse(text);
                    message = data.error || message;
                } catch {
                    // Keep the generic message.
                }
            }
            if (target) target.innerHTML = `<p class="message message-error">${escapeHtml(message)}</p>`;
            return response;
        }

        if (target && text) swapHtml(target, text);
        return response;
    }

    function fallbackAjax(method, url, options) {
        const targetSelector = typeof options?.target === 'string' ? options.target : null;
        const targetElement = options?.target instanceof Element ? options.target : null;
        return requestHtml(method, url, {
            target: targetSelector,
            targetElement,
        });
    }

    function stopHtmx(event) {
        event.preventDefault();
        event.stopPropagation();
        if (event.stopImmediatePropagation) event.stopImmediatePropagation();
    }

    function installFallback() {
        if (window.LoomAnnotationActions?.installed) return;

        window.LoomAnnotationActions = {
            ajax: fallbackAjax,
            /** Direct form-panel loader — call from onclick to bypass event delegation. */
            load: function (url, targetSel) {
                return requestHtml('GET', url, { target: targetSel });
            },
            installed: true,
        };

        document.addEventListener('click', (event) => {
            if (!event.target.closest) return;

            const getEl = event.target.closest('[hx-get]');
            if (getEl && !getEl.disabled) {
                // Skip containers triggered by 'load' (e.g. #graph-panel); those
                // are not click targets and intercepting them swallows onclick handlers
                // on child elements.
                const hxTrigger = getEl.getAttribute('hx-trigger') || '';
                const isLoadTriggered = hxTrigger.split(/[\s,]+/).includes('load');
                if (!isLoadTriggered) {
                    stopHtmx(event);
                    requestHtml('GET', getEl.getAttribute('hx-get'), {
                        targetElement: targetFor(getEl),
                    });
                    return;
                }
            }

            const postEl = event.target.closest('button[hx-post], a[hx-post]');
            if (!postEl || postEl.disabled) return;
            if (postEl.closest('form[hx-post]')) return;

            const confirmText = postEl.getAttribute('hx-confirm');
            if (confirmText && !window.confirm(confirmText)) {
                stopHtmx(event);
                return;
            }

            stopHtmx(event);
            const data = new URLSearchParams(parseHxVals(postEl));
            if (!data.has('csrfmiddlewaretoken')) {
                const token = csrfToken(document);
                if (token) data.set('csrfmiddlewaretoken', token);
            }
            requestHtml('POST', postEl.getAttribute('hx-post'), {
                targetElement: targetFor(postEl),
                body: data,
                csrfToken: data.get('csrfmiddlewaretoken') || csrfToken(document),
            });
        }, true);

        document.addEventListener('submit', (event) => {
            if (!event.target.closest) return;

            const form = event.target.closest('form[hx-post]');
            if (!form) return;

            stopHtmx(event);
            const data = new FormData(form);
            requestHtml('POST', form.getAttribute('hx-post'), {
                targetElement: targetFor(form),
                body: data,
                csrfToken: csrfToken(form),
            });
        }, true);
    }

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', installFallback);
    } else {
        installFallback();
    }
})();
