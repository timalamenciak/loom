/**
 * LoomGraphPreview — in-workbench vis-network render of the annotator's
 * in-progress causal graph.
 *
 * Ported/trimmed from the standalone linkml-graph-viewer tool. The payload is
 * produced server-side by apps.export.renderers.render_graph_preview() and
 * embedded as a <script type="application/json"> block; this module reads it,
 * lazily loads the vendored vis-network bundle, and draws the graph.
 *
 * Public API (all idempotent):
 *   LoomGraphPreview.ensureVis()            -> Promise (resolves when window.vis ready)
 *   LoomGraphPreview.render(dataEl, hostEl) -> draws / redraws into hostEl
 *   LoomGraphPreview.destroy(hostEl)        -> tears down the network for hostEl
 */
(function () {
    'use strict';

    var visPromise = null;
    var networks = new Map(); // hostEl -> { network, handlers }

    function ensureVis() {
        if (window.vis && window.vis.Network && window.vis.DataSet) {
            return Promise.resolve(window.vis);
        }
        if (visPromise) return visPromise;

        var assets = window.LOOM_VIS_ASSETS || {};
        visPromise = new Promise(function (resolve, reject) {
            if (assets.css && !document.querySelector('link[data-loom-vis]')) {
                var link = document.createElement('link');
                link.rel = 'stylesheet';
                link.href = assets.css;
                link.setAttribute('data-loom-vis', '1');
                document.head.appendChild(link);
            }
            if (!assets.js) {
                reject(new Error('vis-network asset URL missing'));
                return;
            }
            var script = document.createElement('script');
            script.src = assets.js;
            script.async = true;
            script.onload = function () {
                if (window.vis && window.vis.Network) resolve(window.vis);
                else reject(new Error('vis-network loaded but window.vis missing'));
            };
            script.onerror = function () {
                reject(new Error('vis-network failed to load from ' + assets.js));
            };
            document.head.appendChild(script);
        });
        return visPromise;
    }

    // Deterministic group -> colour. Same palette as the standalone tool.
    var PALETTE = [
        { background: '#dbeafe', border: '#2563eb' },
        { background: '#dcfce7', border: '#16a34a' },
        { background: '#fef3c7', border: '#d97706' },
        { background: '#fce7f3', border: '#db2777' },
        { background: '#ede9fe', border: '#7c3aed' },
        { background: '#ccfbf1', border: '#0f766e' },
        { background: '#fee2e2', border: '#dc2626' },
        { background: '#e0f2fe', border: '#0284c7' },
        { background: '#f5d0fe', border: '#c026d3' },
        { background: '#e2e8f0', border: '#475569' }
    ];
    var EDGE_PALETTE = [
        '#b45309', '#2563eb', '#16a34a', '#db2777',
        '#7c3aed', '#0f766e', '#dc2626', '#475569'
    ];

    function groupStyles(groups) {
        var out = {};
        groups.forEach(function (group, i) {
            var c = PALETTE[i % PALETTE.length];
            out[group] = {
                shape: 'box',
                color: {
                    background: c.background,
                    border: c.border,
                    highlight: { background: c.background, border: c.border },
                    hover: { background: c.background, border: c.border }
                },
                font: { color: '#0f172a' }
            };
        });
        out.missing = {
            shape: 'box',
            color: {
                background: '#f8fafc',
                border: '#94a3b8',
                highlight: { background: '#f1f5f9', border: '#64748b' }
            },
            shapeProperties: { borderDashes: [4, 3] },
            font: { color: '#64748b' }
        };
        return out;
    }

    function edgeColor(payload, group) {
        var i = Math.max(0, payload.edge_groups.indexOf(group));
        var c = EDGE_PALETTE[i % EDGE_PALETTE.length];
        return { color: c, highlight: c, hover: c };
    }

    function scalar(value) {
        if (value === null || value === undefined || value === '') return '';
        if (Array.isArray(value)) {
            return value.map(scalar).filter(Boolean).join('; ');
        }
        if (typeof value === 'object') {
            return value.entity_term || value.term || value.name || value.id ||
                Object.keys(value).length + ' field' + (Object.keys(value).length === 1 ? '' : 's');
        }
        return String(value);
    }

    function shortValue(value) {
        var text = scalar(value);
        return text.length > 120 ? text.slice(0, 117) + '…' : text;
    }

    // Cosmetic best-effort labels — a schema mismatch just degrades the tooltip.
    function summaryRows(kind, props) {
        props = props || {};
        if (kind === 'node') {
            return [
                ['id', props.id || props.node_id],
                ['entity type', props.entity_type || props.category],
                ['entity term', props.entity_term],
                ['attribute', props.measured_attribute || props.attribute],
                ['state / change', props.state_or_change_qualifier || props.change_direction],
                ['applied to', props.applied_to]
            ];
        }
        return [
            ['id', props.edge_id],
            ['predicate', props.predicate],
            ['claim strength', props.claim_strength],
            ['confidence', props.annotation_confidence],
            ['sentence', props.original_sentence]
        ];
    }

    function tooltip(kind, label, props) {
        var rows = summaryRows(kind, props)
            .filter(function (r) { return r[1] !== undefined && r[1] !== null && r[1] !== ''; })
            .map(function (r) { return r[0] + ': ' + shortValue(r[1]); });
        return [label].concat(rows).join('\n');
    }

    function fillSelect(select, groups, counts, allLabel) {
        if (!select) return;
        select.replaceChildren();
        var all = document.createElement('option');
        all.value = '__all__';
        all.textContent = allLabel;
        select.appendChild(all);
        groups.forEach(function (group) {
            var opt = document.createElement('option');
            opt.value = group;
            opt.textContent = group + ' (' + (counts[group] || 0) + ')';
            select.appendChild(opt);
        });
    }

    function renderDetails(host, kind, label, props) {
        if (!host) return;
        host.hidden = false;
        host.replaceChildren();
        var heading = document.createElement('h4');
        heading.className = 'graph-preview-details-title';
        heading.textContent = (kind === 'node' ? 'Node' : 'Edge') + ' · ' + label;
        host.appendChild(heading);
        var pre = document.createElement('pre');
        pre.className = 'graph-preview-details-json';
        pre.textContent = JSON.stringify(props, null, 2);
        host.appendChild(pre);
    }

    function build(payload, host) {
        var vis = window.vis;
        // A Refresh swaps in a new #preview-network, orphaning the previous one.
        // Tear down any network whose host is no longer in the document.
        networks.forEach(function (_entry, priorHost) {
            if (priorHost !== host && !document.contains(priorHost)) destroy(priorHost);
        });
        destroy(host);

        var nodeSearch = new Map();
        var visNodes = new vis.DataSet(payload.nodes.map(function (n) {
            nodeSearch.set(n.id, JSON.stringify(n).toLowerCase());
            return {
                id: n.id,
                label: n.label,
                group: n.group,
                title: tooltip('node', n.label, n.properties)
            };
        }));

        var edgeSearch = new Map();
        var visEdges = new vis.DataSet(payload.edges.map(function (e) {
            edgeSearch.set(e.id, JSON.stringify(e).toLowerCase());
            return {
                id: e.id,
                from: e.from,
                to: e.to,
                label: e.label,
                title: tooltip('edge', e.label, e.properties),
                arrows: { to: { enabled: true, scaleFactor: 0.7 } },
                color: edgeColor(payload, e.group),
                font: { size: 11, align: 'middle', color: '#334155', strokeWidth: 4, strokeColor: '#fff' }
            };
        }));

        var network = new vis.Network(host, { nodes: visNodes, edges: visEdges }, {
            groups: groupStyles(payload.node_groups),
            nodes: {
                shape: 'box',
                borderWidth: 1.5,
                margin: { top: 7, right: 10, bottom: 7, left: 10 },
                widthConstraint: { maximum: 190 },
                font: { face: 'inherit', size: 13, color: '#0f172a', multi: false }
            },
            edges: { smooth: { type: 'dynamic', roundness: 0.3 }, selectionWidth: 2 },
            physics: {
                solver: 'forceAtlas2Based',
                stabilization: { enabled: true, iterations: 200, updateInterval: 25 },
                forceAtlas2Based: {
                    gravitationalConstant: -60,
                    centralGravity: 0.012,
                    springLength: 140,
                    springConstant: 0.08,
                    damping: 0.45,
                    avoidOverlap: 0.3
                }
            },
            interaction: { hover: true, tooltipDelay: 120, keyboard: false, navigationButtons: true }
        });

        var handlers = { network: network, dom: [] };
        networks.set(host, handlers);

        var physicsRunning = true;
        var physicsBtn = document.getElementById('preview-physics');
        function setPhysics(running) {
            physicsRunning = running;
            network.setOptions({ physics: running });
            if (physicsBtn) physicsBtn.textContent = running ? 'Pause physics' : 'Resume physics';
        }
        network.once('stabilizationIterationsDone', function () {
            setPhysics(false);
            network.fit({ animation: { duration: 350 } });
        });

        var details = document.getElementById('preview-details');
        var nodeById = new Map(payload.nodes.map(function (n) { return [n.id, n]; }));
        var edgeById = new Map(payload.edges.map(function (e) { return [e.id, e]; }));

        network.on('selectNode', function (p) {
            var n = nodeById.get(p.nodes[0]);
            if (n) renderDetails(details, 'node', n.label, n.properties);
        });
        network.on('selectEdge', function (p) {
            if (p.nodes.length) return;
            var e = edgeById.get(p.edges[0]);
            if (e) renderDetails(details, 'edge', e.label, e.properties);
        });
        network.on('deselectNode', function (p) {
            if (!p.nodes.length && !p.edges.length && details) details.hidden = true;
        });

        // Toolbar wiring
        var search = document.getElementById('preview-search');
        var nodeGroup = document.getElementById('preview-node-group');
        var edgeGroup = document.getElementById('preview-edge-group');
        var fitBtn = document.getElementById('preview-fit');

        fillSelect(nodeGroup, payload.node_groups.concat(
            payload.node_group_counts.missing ? ['missing'] : []
        ), payload.node_group_counts, 'All node groups');
        fillSelect(edgeGroup, payload.edge_groups, payload.edge_group_counts, 'All edge types');

        function applyFilters() {
            var q = (search && search.value || '').trim().toLowerCase();
            var ng = nodeGroup ? nodeGroup.value : '__all__';
            var eg = edgeGroup ? edgeGroup.value : '__all__';
            var visibleNodes = new Set();

            visNodes.update(payload.nodes.map(function (n) {
                var hidden = (ng !== '__all__' && n.group !== ng) ||
                    (q && !(nodeSearch.get(n.id) || '').includes(q));
                if (!hidden) visibleNodes.add(n.id);
                return { id: n.id, hidden: hidden };
            }));
            visEdges.update(payload.edges.map(function (e) {
                var hidden = (eg !== '__all__' && e.group !== eg) ||
                    !visibleNodes.has(e.from) || !visibleNodes.has(e.to) ||
                    (q && !(edgeSearch.get(e.id) || '').includes(q));
                return { id: e.id, hidden: hidden };
            }));
        }

        function bind(el, event, fn) {
            if (!el) return;
            el.addEventListener(event, fn);
            handlers.dom.push([el, event, fn]);
        }
        bind(search, 'input', applyFilters);
        bind(nodeGroup, 'change', applyFilters);
        bind(edgeGroup, 'change', applyFilters);
        bind(fitBtn, 'click', function () { network.fit({ animation: { duration: 350 } }); });
        bind(physicsBtn, 'click', function () { setPhysics(!physicsRunning); });
    }

    function destroy(host) {
        var entry = networks.get(host);
        if (!entry) return;
        (entry.dom || []).forEach(function (h) { h[0].removeEventListener(h[1], h[2]); });
        try { entry.network.destroy(); } catch (e) { /* already gone */ }
        networks.delete(host);
    }

    function render(dataEl, host) {
        if (!dataEl || !host) return;
        // The partial's inline <script> plus the afterSwap/afterSettle hooks all
        // fire for the same freshly-swapped element — render it once. A Refresh
        // swaps in a new element, which is not yet marked, so it re-renders.
        if (dataEl.dataset.rendered === '1') return;
        dataEl.dataset.rendered = '1';
        var payload;
        try {
            payload = JSON.parse(dataEl.textContent);
        } catch (e) {
            host.innerHTML = '<p class="no-text-msg">Could not read the graph preview data.</p>';
            return;
        }
        ensureVis().then(function () {
            build(payload, host);
        }).catch(function (err) {
            dataEl.dataset.rendered = '';
            host.innerHTML = '<p class="no-text-msg">Graph preview library failed to load.<br>' +
                (err && err.message ? String(err.message) : '') + '</p>';
        });
    }

    window.LoomGraphPreview = { ensureVis: ensureVis, render: render, destroy: destroy };
})();
