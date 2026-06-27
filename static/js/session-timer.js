/**
 * session-timer.js — Loom work session active-time tracker.
 *
 * Accrues time only while:
 *   1. The tab is visible (Page Visibility API)
 *   2. The annotator has been active within the idle threshold (90 s)
 *   3. Not manually paused
 *
 * Sends heartbeats to the server every 15 s with {active_delta, idle_delta}.
 * On page unload, sends a final keepalive fetch marked {ended: true}.
 *
 * Usage:
 *   SessionTimer.init(sessionPk, heartbeatUrl, csrfToken, initialActiveSeconds);
 *   document.getElementById('session-pause-btn').onclick = () => SessionTimer.toggle();
 */

const SessionTimer = {
    HEARTBEAT_INTERVAL_MS: 15_000,
    IDLE_THRESHOLD_MS: 90_000,
    TICK_MS: 1_000,

    _pk: null,
    _url: null,
    _csrf: null,
    _paused: false,
    _tabVisible: true,
    _lastActivity: 0,

    // Running total (baseline from server + ticks since page load)
    _activeSeconds: 0,

    // Deltas accumulated since the last heartbeat
    _pendingActive: 0,
    _pendingIdle: 0,

    _tickTimer: null,
    _heartbeatTimer: null,

    init(sessionPk, heartbeatUrl, csrfToken, initialActiveSeconds = 0) {
        this._pk = sessionPk;
        this._url = heartbeatUrl;
        this._csrf = csrfToken;
        this._activeSeconds = initialActiveSeconds;
        this._lastActivity = Date.now();
        this._tabVisible = !document.hidden;

        // Activity listeners — any interaction resets the idle clock
        ['keydown', 'mousedown', 'scroll', 'selectionchange'].forEach((ev) => {
            document.addEventListener(ev, () => { this._lastActivity = Date.now(); }, { passive: true });
        });

        document.addEventListener('visibilitychange', () => {
            this._tabVisible = !document.hidden;
            if (!this._tabVisible) {
                // Flush pending before pausing for hidden tab
                this._sendHeartbeat();
            } else {
                this._lastActivity = Date.now();
            }
            this._render();
        });

        // Final flush on navigation away; keepalive keeps the request alive
        window.addEventListener('beforeunload', () => {
            if (this._pk) {
                const payload = JSON.stringify({
                    active_delta: this._pendingActive,
                    idle_delta: this._pendingIdle,
                    ended: true,
                });
                this._pendingActive = 0;
                this._pendingIdle = 0;
                fetch(this._url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this._csrf,
                    },
                    body: payload,
                    keepalive: true,
                });
            }
        });

        this._tickTimer = setInterval(() => this._tick(), this.TICK_MS);
        this._heartbeatTimer = setInterval(() => this._sendHeartbeat(), this.HEARTBEAT_INTERVAL_MS);

        this._render();
    },

    toggle() {
        if (this._paused) {
            this._paused = false;
            this._lastActivity = Date.now();
        } else {
            this._paused = true;
            this._sendHeartbeat();
        }
        this._render();
    },

    _isActive() {
        if (this._paused || !this._tabVisible) return false;
        return Date.now() - this._lastActivity < this.IDLE_THRESHOLD_MS;
    },

    _tick() {
        if (this._isActive()) {
            this._activeSeconds++;
            this._pendingActive++;
        } else if (this._tabVisible && !this._paused) {
            this._pendingIdle++;
        }
        this._render();
    },

    _render() {
        const displayEl = document.getElementById('session-timer-display');
        if (displayEl) {
            const h = Math.floor(this._activeSeconds / 3600);
            const m = Math.floor((this._activeSeconds % 3600) / 60);
            const s = this._activeSeconds % 60;
            displayEl.textContent =
                `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
        }

        const pauseBtn = document.getElementById('session-pause-btn');
        if (pauseBtn) {
            pauseBtn.textContent = this._paused ? 'Resume' : 'Pause';
        }

        const statusEl = document.getElementById('session-status');
        if (statusEl) {
            if (this._paused) statusEl.textContent = '(paused)';
            else if (!this._tabVisible) statusEl.textContent = '(hidden)';
            else if (!this._isActive()) statusEl.textContent = '(idle)';
            else statusEl.textContent = '';
        }
    },

    async _sendHeartbeat(ended = false) {
        if (!this._pk) return;
        const active = this._pendingActive;
        const idle = this._pendingIdle;
        if (active === 0 && idle === 0 && !ended) return;

        this._pendingActive = 0;
        this._pendingIdle = 0;

        try {
            const response = await fetch(this._url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this._csrf,
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: JSON.stringify({ active_delta: active, idle_delta: idle, ended }),
            });
            if (!response.ok) throw new Error(`Heartbeat failed: ${response.status}`);
        } catch {
            if (!ended) {
                this._pendingActive += active;
                this._pendingIdle += idle;
            }
        }
    },
};
