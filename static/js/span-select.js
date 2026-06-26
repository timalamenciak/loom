/**
 * span-select.js — Text selection → character offsets for Loom span creation.
 *
 * Attaches to a canonical-text container and shows a floating "Create span"
 * button when the user selects text within it.  Character offsets are computed
 * by walking all text nodes via TreeWalker, which correctly handles <mark> and
 * other inline elements injected for existing span highlights.
 *
 * Usage (in template):
 *   SpanSelector.init('canonical-text', '/reader/42/spans/', '{{ csrf_token }}');
 */

const SpanSelector = {
    _container: null,
    _createUrl: null,
    _csrfToken: null,
    _tooltip: null,
    _current: null,

    init(containerId, createUrl, csrfToken) {
        this._container = document.getElementById(containerId);
        if (!this._container) return;
        this._createUrl = createUrl;
        this._csrfToken = csrfToken;
        this._buildTooltip();
        document.addEventListener('mouseup', () => this._onSelectionChange());
        document.addEventListener('keyup', (e) => {
            const nav = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'];
            if (e.shiftKey && nav.includes(e.key)) this._onSelectionChange();
        });
        // Hide on click outside
        document.addEventListener('mousedown', (e) => {
            if (!this._tooltip.contains(e.target)) {
                this._tooltip.style.display = 'none';
            }
        });
    },

    _buildTooltip() {
        const el = document.createElement('div');
        el.id = 'span-tooltip';
        Object.assign(el.style, {
            position: 'absolute',
            zIndex: '9999',
            background: '#1a1a2e',
            color: '#fff',
            borderRadius: '4px',
            padding: '4px 12px',
            fontSize: '13px',
            display: 'none',
            cursor: 'pointer',
            boxShadow: '0 2px 8px rgba(0,0,0,.35)',
            userSelect: 'none',
            whiteSpace: 'nowrap',
        });
        el.textContent = 'Highlight this text';
        el.addEventListener('mousedown', (e) => {
            e.preventDefault();  // Keep selection alive
            this._onCreate();
        });
        document.body.appendChild(el);
        this._tooltip = el;
    },

    /**
     * Walk text nodes from the container start to (domNode, domOffset),
     * counting characters.  Handles nested elements (<mark> etc.) correctly
     * because TreeWalker visits only TEXT_NODE nodes.
     */
    _charsBefore(domNode, domOffset) {
        const walker = document.createTreeWalker(
            this._container,
            NodeFilter.SHOW_TEXT,
        );
        let count = 0;
        while (walker.nextNode()) {
            if (walker.currentNode === domNode) {
                return count + domOffset;
            }
            count += walker.currentNode.textContent.length;
        }
        // domNode not found inside container (shouldn't happen if checked earlier)
        return count;
    },

    _getSelection() {
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
        const range = sel.getRangeAt(0);

        // Ensure both endpoints are inside the container
        if (
            !this._container.contains(range.startContainer) ||
            !this._container.contains(range.endContainer)
        ) {
            return null;
        }

        const text = range.toString();
        if (!text.trim()) return null;

        const startChar = this._charsBefore(range.startContainer, range.startOffset);
        const endChar = this._charsBefore(range.endContainer, range.endOffset);
        if (endChar <= startChar) return null;

        return { startChar, endChar, text, range };
    },

    _onSelectionChange() {
        // Small delay so the browser has settled the selection
        setTimeout(() => {
            const result = this._getSelection();
            if (!result) {
                this._tooltip.style.display = 'none';
                this._current = null;
                return;
            }
            this._current = result;

            // Position tooltip just below the selection
            const rect = result.range.getBoundingClientRect();
            const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
            const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;
            this._tooltip.style.left = `${Math.max(0, rect.left + scrollLeft)}px`;
            this._tooltip.style.top = `${rect.bottom + scrollTop + 6}px`;
            this._tooltip.style.display = 'block';
        }, 15);
    },

    // nodeFormUrl: set by AnnotationView to enable span-first node creation
    _nodeFormUrl: null,
    // edgeFormUrl: set by AnnotationView to enable span-first edge creation
    _edgeFormUrl: null,

    setAnnotationUrls(nodeFormUrl, edgeFormUrl) {
        this._nodeFormUrl = nodeFormUrl;
        this._edgeFormUrl = edgeFormUrl;
    },

    async _onCreate() {
        if (!this._current) return;
        const { startChar, endChar, text } = this._current;

        this._tooltip.style.display = 'none';
        window.getSelection()?.removeAllRanges();

        const body = new URLSearchParams({ start_char: startChar, end_char: endChar });
        let resp;
        try {
            resp = await fetch(this._createUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this._csrfToken,
                    'HX-Request': 'true',
                    'X-Span-Select': 'true',
                },
                body,
            });
        } catch (err) {
            console.error('Span create network error:', err);
            return;
        }

        if (!resp.ok) {
            console.error('Span create failed:', resp.status);
            return;
        }

        // Parse span pk from JSON response {span_pk: N, html: ...}
        let spanPk = null;
        try {
            const data = await resp.json();
            spanPk = data.span_pk || null;
        } catch {
            // Response was HTML (Phase 3 fallback) — reload
            window.location.reload();
            return;
        }

        // If we have annotation URLs and a span pk, show action popup
        if (spanPk && (this._nodeFormUrl || this._edgeFormUrl)) {
            this._showSpanActions(spanPk, text, startChar, endChar);
        } else {
            window.location.reload();
        }
    },

    _showSpanActions(spanPk, text, startChar, endChar) {
        const popup = document.createElement('div');
        Object.assign(popup.style, {
            position: 'fixed',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            background: '#fff',
            border: '1px solid #d1d5db',
            borderRadius: '6px',
            padding: '1rem',
            boxShadow: '0 8px 24px rgba(0,0,0,.18)',
            zIndex: '9999',
            maxWidth: '340px',
            width: '90%',
        });

        const preview = text.length > 80 ? text.slice(0, 80) + '…' : text;
        popup.innerHTML = `
            <p style="font-size:.8rem;color:#6b7280;margin:0 0 .4rem">Text highlighted:</p>
            <p style="font-size:.85rem;margin:0 0 .75rem;font-style:italic;color:#374151">"${_escHtml(preview)}"</p>
            <p style="font-size:.8rem;color:#374151;margin:0 0 .75rem">What would you like to create from this passage?</p>
            <div style="display:flex;gap:.5rem;flex-wrap:wrap">
              ${this._nodeFormUrl ? `<button class="btn btn-primary" id="spa-node" style="flex:1" title="Create a new entity node anchored to this highlighted text">Create node</button>` : ''}
              ${this._edgeFormUrl ? `<button class="btn btn-secondary" id="spa-edge" style="flex:1" title="Create a new causal edge anchored to this highlighted text">Create edge</button>` : ''}
              <button class="btn btn-secondary" id="spa-dismiss" style="flex:1" title="Keep the highlight but do nothing else for now">Cancel</button>
            </div>
        `;

        const overlay = document.createElement('div');
        Object.assign(overlay.style, {
            position: 'fixed', inset: '0', background: 'rgba(0,0,0,.25)', zIndex: '9998',
        });

        document.body.appendChild(overlay);
        document.body.appendChild(popup);

        const close = () => {
            overlay.remove();
            popup.remove();
        };

        overlay.addEventListener('click', close);
        popup.querySelector('#spa-dismiss')?.addEventListener('click', close);

        if (this._nodeFormUrl) {
            popup.querySelector('#spa-node')?.addEventListener('click', () => {
                close();
                const url = `${this._nodeFormUrl}?span_pk=${spanPk}`;
                this._loadAnnotationForm(url);
            });
        }

        if (this._edgeFormUrl) {
            popup.querySelector('#spa-edge')?.addEventListener('click', () => {
                close();
                const url = `${this._edgeFormUrl}?span_pk=${spanPk}`;
                this._loadAnnotationForm(url);
            });
        }
    },

    _loadAnnotationForm(url) {
        const ajax = window.htmx?.ajax || window.LoomAnnotationActions?.ajax;
        if (ajax) {
            ajax('GET', url, { target: '#form-panel', swap: 'innerHTML' });
            return;
        }
        window.location.href = url;
    },
};

function _escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
