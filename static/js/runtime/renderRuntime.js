import { buildRenderIframeDocument } from './renderIframeTemplate.js';
import { RUNTIME_CHANNEL } from './renderFrameScripts.js';
import { removeRuntime, upsertRuntime } from './runtimeManager.js';

const DEFAULT_MIN_HEIGHT = 240;
const DEFAULT_MAX_HEIGHT = 560;

const runtimeByHost = new WeakMap();
const runtimes = new Map();

let runtimeCounter = 0;
let listenersAttached = false;

function toBoundedNumber(value, fallback) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed)) {
        return fallback;
    }
    return parsed;
}

function resolveMaxHeight(host, provided) {
    if (Number.isFinite(Number(provided))) {
        return Math.max(220, Number(provided));
    }

    const rectHeight = Math.floor(host.getBoundingClientRect().height || 0);
    if (rectHeight > 0) {
        return Math.max(220, rectHeight);
    }

    return DEFAULT_MAX_HEIGHT;
}

function ensureGlobalListeners() {
    if (listenersAttached) {
        return;
    }

    listenersAttached = true;

    window.addEventListener('message', event => {
        const data = event && event.data ? event.data : null;
        if (!data || data.channel !== RUNTIME_CHANNEL || data.type !== 'height' || !data.runtimeId) {
            return;
        }

        const runtime = runtimes.get(data.runtimeId);
        if (!runtime) {
            return;
        }

        if (!runtime.host.isConnected) {
            runtime.destroy();
            return;
        }

        runtime.applyMeasuredHeight(Number(data.height));
    });

    window.addEventListener('resize', () => {
        runtimes.forEach(runtime => {
            if (!runtime.host.isConnected) {
                runtime.destroy();
                return;
            }
            runtime.syncViewport();
            runtime.applyMeasuredHeight(runtime.lastMeasuredHeight || runtime.resolveMinHeight());
        });
    }, { passive: true });
}

function cleanupDisconnectedRuntimes() {
    runtimes.forEach(runtime => {
        if (!runtime.host.isConnected) {
            runtime.destroy();
        }
    });
}

class RenderIframeRuntime {
    constructor(host) {
        this.host = host;
        this.runtimeId = `stm-render-${++runtimeCounter}`;
        this.startedAt = Date.now();
        this.shadowRoot = host.shadowRoot || host.attachShadow({ mode: 'open' });
        this.objectUrl = '';
        this.documentHtml = '';
        this.lastMeasuredHeight = 0;
        this.options = {};

        this.mount();
        runtimes.set(this.runtimeId, this);
        runtimeByHost.set(host, this);
        this.publishState('idle');
    }

    mount() {
        this.shadowRoot.innerHTML = '';

        const style = document.createElement('style');
        style.textContent = `
            :host {
                display: block !important;
                width: 100% !important;
                min-width: 0 !important;
                position: relative;
                color: inherit;
            }
            .stm-render-shell {
                display: block;
                width: 100%;
                overflow: hidden;
                background: var(--bg-body, #000);
                border-radius: 6px;
            }
            .stm-render-frame {
                display: block;
                width: 100%;
                min-width: 0;
                border: none;
                background: transparent;
            }
        `;

        const shell = document.createElement('div');
        shell.className = 'stm-render-shell';

        const iframe = document.createElement('iframe');
        iframe.className = 'stm-render-frame';
        iframe.setAttribute('title', 'ST Manager isolated preview');
        iframe.setAttribute('loading', 'lazy');
        iframe.setAttribute('referrerpolicy', 'no-referrer');
        iframe.setAttribute('frameborder', '0');
        iframe.addEventListener('load', () => {
            this.syncViewport();
            this.applyMeasuredHeight(this.lastMeasuredHeight || this.resolveMinHeight());
        });

        shell.appendChild(iframe);
        this.shadowRoot.append(style, shell);

        this.styleNode = style;
        this.shell = shell;
        this.iframe = iframe;
    }

    resolveMinHeight() {
        return Math.max(160, toBoundedNumber(this.options.minHeight, DEFAULT_MIN_HEIGHT));
    }

    resolveMaxHeight() {
        return Math.max(this.resolveMinHeight(), resolveMaxHeight(this.host, this.options.maxHeight));
    }

    applyMeasuredHeight(height) {
        if (!this.shell || !this.iframe) {
            return;
        }

        const fallbackHeight = this.resolveMinHeight();
        const numericHeight = Number.isFinite(height) && height > 0 ? Math.ceil(height) : fallbackHeight;
        const clampedHeight = Math.max(this.resolveMinHeight(), Math.min(this.resolveMaxHeight(), numericHeight));

        this.lastMeasuredHeight = numericHeight;
        this.shell.style.minHeight = `${this.resolveMinHeight()}px`;
        this.shell.style.maxHeight = `${this.resolveMaxHeight()}px`;
        this.shell.style.height = `${clampedHeight}px`;
        this.iframe.style.minHeight = `${this.resolveMinHeight()}px`;
        this.iframe.style.maxHeight = `${this.resolveMaxHeight()}px`;
        this.iframe.style.height = `${clampedHeight}px`;
        this.publishState('running');
    }

    setDocument(documentHtml) {
        if (documentHtml === this.documentHtml) {
            return;
        }

        this.documentHtml = documentHtml;

        if (this.objectUrl) {
            URL.revokeObjectURL(this.objectUrl);
            this.objectUrl = '';
        }

        this.objectUrl = URL.createObjectURL(new Blob([documentHtml], { type: 'text/html' }));
        this.iframe.src = this.objectUrl;
    }

    update(options) {
        this.options = { ...options };
        this.applyMeasuredHeight(this.lastMeasuredHeight || this.resolveMinHeight());
        this.setDocument(buildRenderIframeDocument({
            runtimeId: this.runtimeId,
            htmlPayload: options.htmlPayload,
            noteHtml: options.noteHtml || '',
            assetBase: options.assetBase || '',
        }));
        this.syncViewport();
        this.publishState('running');
    }

    publishState(status) {
        upsertRuntime({
            runtimeId: this.runtimeId,
            kind: 'render',
            ownerId: this.host?.id || this.host?.dataset?.runtimeOwner || '',
            label: this.host?.dataset?.runtimeLabel || this.runtimeId,
            status,
            startedAt: this.startedAt || Date.now(),
            metrics: {
                measuredHeight: this.lastMeasuredHeight,
                minHeight: this.resolveMinHeight(),
                maxHeight: this.resolveMaxHeight(),
            },
            meta: {
                hasContent: Boolean(this.documentHtml),
            },
        });
    }

    syncViewport() {
        if (!this.iframe || !this.iframe.contentWindow) {
            return;
        }

        this.iframe.contentWindow.postMessage({
            channel: RUNTIME_CHANNEL,
            type: 'viewport',
            runtimeId: this.runtimeId,
            height: window.innerHeight,
        }, '*');
    }

    destroy({ clearShadow = false } = {}) {
        if (this.objectUrl) {
            URL.revokeObjectURL(this.objectUrl);
            this.objectUrl = '';
        }

        if (this.iframe) {
            this.iframe.src = 'about:blank';
        }

        if (clearShadow && this.shadowRoot) {
            this.shadowRoot.innerHTML = '';
        }

        runtimes.delete(this.runtimeId);
        runtimeByHost.delete(this.host);
        removeRuntime(this.runtimeId);
    }
}

export function renderIsolatedHtml(host, options) {
    if (!host) {
        return null;
    }

    ensureGlobalListeners();
    cleanupDisconnectedRuntimes();

    let runtime = runtimeByHost.get(host);
    if (!runtime) {
        runtime = new RenderIframeRuntime(host);
    }

    runtime.update(options);
    return runtime;
}

export function clearIsolatedHtml(host, options = {}) {
    const runtime = host ? runtimeByHost.get(host) : null;
    if (!runtime) {
        return;
    }
    runtime.destroy(options);
}
