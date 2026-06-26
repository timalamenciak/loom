/**
 * pdf-viewer.js — PDF.js page renderer for the Loom document reader.
 *
 * Called from the reader template after PDF.js is loaded via ESM import.
 * Not used directly — the template inlines the init call as an ES module.
 *
 * Exported separately so Phase 5 can import scroll-to-page linking.
 */

const PdfViewer = {
    /**
     * Scroll the PDF viewer to the page that contains charOffset.
     * @param {string} containerId
     * @param {number} charOffset
     * @param {Array<{page:number, start_char:number, end_char:number}>} pageMap
     */
    scrollToChar(containerId, charOffset, pageMap) {
        const container = document.getElementById(containerId);
        if (!container || !pageMap || !pageMap.length) return;
        for (const entry of pageMap) {
            if (charOffset >= entry.start_char && charOffset < entry.end_char) {
                const pageEl = container.querySelector(`[data-page="${entry.page}"]`);
                if (pageEl) pageEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
                return;
            }
        }
    },

    /**
     * Return the page number (1-based) for a given char offset.
     */
    pageForChar(charOffset, pageMap) {
        for (const entry of pageMap) {
            if (charOffset >= entry.start_char && charOffset < entry.end_char) {
                return entry.page;
            }
        }
        return null;
    },
};

export { PdfViewer };
