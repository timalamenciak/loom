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
    _secondaryContainer: null,
    _createUrl: null,
    _csrfToken: null,
    _tooltip: null,
    _current: null,

    init(containerId, createUrl, csrfToken, options = {}) {
        this._container = document.getElementById(containerId);
        if (!this._container) return;
        this._secondaryContainer = null;
        this._createUrl = createUrl;
        this._csrfToken = csrfToken;
        this._buildTooltip(options);
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

    _buildTooltip(options) {
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
        el.textContent = options.label || 'Highlight this text';
        el.addEventListener('mousedown', (e) => {
            e.preventDefault();  // Keep selection alive
            this._onCreate();
        });
        document.body.appendChild(el);
        this._tooltip = el;
    },

    /**
     * Register a secondary container (e.g. the markdown view).  Selections
     * inside it are mapped back to canonical_text via text search rather than
     * DOM offset walking, since the markdown HTML has different structure.
     */
    initSecondary(containerId) {
        this._secondaryContainer = document.getElementById(containerId);
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
        const text = range.toString();
        if (!text.trim()) return null;

        // Primary container: compute char offsets directly from DOM text nodes.
        if (
            this._container.contains(range.startContainer) &&
            this._container.contains(range.endContainer)
        ) {
            const startChar = this._charsBefore(range.startContainer, range.startOffset);
            const endChar = this._charsBefore(range.endContainer, range.endOffset);
            if (endChar <= startChar) return null;
            return { startChar, endChar, text, range };
        }

        // Secondary container (markdown view): show the tooltip immediately;
        // the server searches canonical_text for source_text at creation time.
        if (
            this._secondaryContainer &&
            this._secondaryContainer.contains(range.startContainer) &&
            this._secondaryContainer.contains(range.endContainer)
        ) {
            const trimmed = text.trim();
            if (!trimmed) return null;
            return { startChar: null, endChar: null, text: trimmed, fromMarkdown: true, range };
        }

        return null;
    },

    /**
     * Find selectedText inside canonical_text and return span offsets.
     *
     * Marker and pdfplumber produce slightly different text, so we try four
     * strategies from most- to least-specific:
     *   1. Exact trimmed match.
     *   2. Whitespace-collapsed (HTML line-breaks → space).
     *   3. NFKC + typography normalisation (ligatures ﬁ/ﬂ, curly quotes,
     *      en/em-dashes, non-breaking spaces).
     *   4. Same as 3 but searching the normalised canonical text.
     *
     * Returns null (no tooltip, no span) when the passage cannot be located.
     * A console.warn in that case lets developers diagnose mismatches.
     */
    _findInCanonical_UNUSED(selectedText, range) {
        const canonical = this._container.textContent;

        // Shared normaliser — matches what Marker and pdfplumber commonly differ on
        const norm = s => s
            .normalize('NFKC')                              // ﬁ→fi, ﬂ→fl, etc.
            .replace(/[‘’`´]/g, "'")   // curly/grave/acute → '
            .replace(/[“”]/g, '"')                // curly double → "
            .replace(/[–—―−]/g, '-')   // en/em-dash, minus → -
            .replace(/ /g, ' ')                        // NBSP → space
            .replace(/\s+/g, ' ')
            .trim();

        const strategies = [
            { needle: selectedText.trim(), searchIn: canonical },
            { needle: selectedText.replace(/\s+/g, ' ').trim(), searchIn: canonical },
            { needle: norm(selectedText), searchIn: canonical },
            { needle: norm(selectedText), searchIn: norm(canonical) },
        ];

        for (const { needle, searchIn } of strategies) {
            if (!needle) continue;
            const idx = searchIn.indexOf(needle);
            if (idx !== -1) {
                // For strategy 4 the index is in normalised canonical; it may be
                // slightly off when NFKC expanded ligatures earlier in the text,
                // but it's accurate enough to pin the excerpt.
                return { startChar: idx, endChar: idx + needle.length, text: needle, range };
            }
        }

        console.warn(
            '[Loom] Markdown excerpt not found in canonical text — tooltip suppressed.\n' +
            'Selected (normalised):', JSON.stringify(norm(selectedText).slice(0, 120)), '\n' +
            'Canonical text starts:', JSON.stringify(canonical.slice(0, 120)),
        );
        return null;
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
        const { startChar, endChar, text, fromMarkdown, range } = this._current;

        this._tooltip.style.display = 'none';
        window.getSelection()?.removeAllRanges();

        // Markdown selections: send the text string; server searches canonical_text.
        // Text-view selections: send pre-computed char offsets.
        const body = fromMarkdown
            ? new URLSearchParams({ source_text: text })
            : new URLSearchParams({ start_char: startChar, end_char: endChar });

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

        if (resp.status === 422) {
            // Server couldn't locate the passage in canonical_text
            if (window.ExcerptBin) {
                window.ExcerptBin.flash(
                    'Passage not found in extracted text — try a longer or more distinctive phrase.'
                );
            }
            return;
        }

        if (!resp.ok) {
            console.error('Span create failed:', resp.status);
            return;
        }

        // Parse span pk from JSON response {span_pk: N, html: ...}
        let spanPk = null;
        let data = null;
        try {
            data = await resp.json();
            spanPk = data.span_pk || null;
        } catch {
            // Response was HTML (Phase 3 fallback) — reload
            window.location.reload();
            return;
        }

        if (spanPk && window.ExcerptBin) {
            window.ExcerptBin.refreshFromHtml(data.excerpt_bin_html, spanPk);
            this._markRange(range, spanPk);
            window.ExcerptBin.flash('Excerpt added. Select another passage or use the checked excerpts.');
            this._current = null;
        } else {
            window.location.reload();
        }
    },

    _markRange(range, spanPk) {
        if (!range) return;
        const mark = document.createElement('mark');
        mark.className = 'span-highlight excerpt-active';
        mark.dataset.spanPk = String(spanPk);
        mark.dataset.spanPks = String(spanPk);
        try {
            range.surroundContents(mark);
        } catch {
            // Cross-element selections are still safely pinned in the excerpt bin.
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
