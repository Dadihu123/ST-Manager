import { buildScriptRuntimeDocument, SCRIPT_RUNTIME_CHANNEL } from './scriptRuntimeTemplate.js';
import { removeRuntime, upsertRuntime } from './runtimeManager.js';
import { getActiveRuntimeContext } from './runtimeContext.js';

const DEFAULT_STAGE_MIN_HEIGHT = 220;
const DEFAULT_STAGE_MAX_HEIGHT = 420;

function cloneValue(value) {
    if (typeof structuredClone === 'function') {
        try {
            return structuredClone(value);
        } catch (error) {
        }
    }

    try {
        return JSON.parse(JSON.stringify(value));
    } catch (error) {
        return value;
    }
}

function normalizeError(error) {
    if (error && typeof error === 'object') {
        return {
            name: String(error.name || 'Error'),
            message: String(error.message || error.toString() || 'Unknown error'),
            stack: error.stack ? String(error.stack) : '',
        };
    }

    return {
        name: 'Error',
        message: String(error || 'Unknown error'),
        stack: '',
    };
}

function isPlainObject(value) {
    return Object.prototype.toString.call(value) === '[object Object]';
}

function sanitizeButtons(buttonConfig) {
    const buttons = Array.isArray(buttonConfig?.buttons) ? buttonConfig.buttons : [];
    return {
        enabled: buttonConfig?.enabled !== false,
        buttons: buttons
            .map(button => {
                if (typeof button === 'string') {
                    return { name: button.trim(), visible: true };
                }
                if (!button || typeof button !== 'object') {
                    return null;
                }
                return {
                    name: String(button.name || '').trim(),
                    visible: button.visible !== false,
                };
            })
            .filter(button => button && button.name),
    };
}

function createRuntimeSnapshot(script) {
    return {
        id: String(script?.id || ''),
        name: String(script?.name || ''),
        info: String(script?.info || ''),
        content: String(script?.content || ''),
        data: cloneValue(script?.data || {}),
        button: sanitizeButtons(script?.button || {}),
    };
}

function normalizeLogEntry(payload) {
    return {
        level: String(payload?.level || 'info'),
        message: String(payload?.message || ''),
        timestamp: Number.isFinite(Number(payload?.timestamp)) ? Number(payload.timestamp) : Date.now(),
    };
}

function getGlobalStore() {
    try {
        if (window.Alpine && typeof window.Alpine.store === 'function') {
            return window.Alpine.store('global');
        }
    } catch (error) {
    }
    return null;
}

function toHeadersObject(headers) {
    if (headers instanceof Headers) {
        return Object.fromEntries(headers.entries());
    }
    if (!headers || typeof headers !== 'object') {
        return {};
    }
    return Object.fromEntries(Object.entries(headers).map(([key, value]) => [key, String(value)]));
}

function toSafeUrl(url) {
    const normalized = new URL(String(url || ''), window.location.origin);
    if (normalized.origin !== window.location.origin) {
        throw new Error('Cross-origin requests are not allowed in safe bridge mode');
    }
    return normalized;
}

export class ManagerScriptRuntime {
    constructor(callbacks = {}, options = {}) {
        this.callbacks = callbacks;
        this.options = {
            minHeight: options.minHeight || DEFAULT_STAGE_MIN_HEIGHT,
            maxHeight: options.maxHeight || DEFAULT_STAGE_MAX_HEIGHT,
        };

        this.host = null;
        this.shell = null;
        this.iframe = null;
        this.objectUrl = '';
        this.runtimeId = '';
        this.status = 'idle';
        this.scriptSnapshot = null;
        this.lastMeasuredHeight = 0;
        this.startedAt = 0;

        this.onWindowMessage = this.onWindowMessage.bind(this);
        window.addEventListener('message', this.onWindowMessage);
    }

    setCallbacks(callbacks = {}) {
        this.callbacks = callbacks;
    }

    attachHost(host) {
        this.host = host || null;
        if (!this.host) {
            return;
        }

        if (this.shell) {
            this.host.replaceChildren(this.shell);
        } else {
            this.host.innerHTML = '';
        }
    }

    ensureMounted() {
        if (!this.host) {
            throw new Error('Script runtime host is not mounted');
        }

        if (!this.shell) {
            this.shell = document.createElement('div');
            this.shell.className = 'stm-script-runtime-shell';
            Object.assign(this.shell.style, {
                width: '100%',
                minHeight: `${this.options.minHeight}px`,
                maxHeight: `${this.options.maxHeight}px`,
                overflow: 'hidden',
                borderRadius: '10px',
                border: '1px solid var(--border-light, rgba(255,255,255,0.08))',
                background: 'rgba(2, 6, 23, 0.78)',
            });

            this.iframe = document.createElement('iframe');
            this.iframe.className = 'stm-script-runtime-frame';
            this.iframe.setAttribute('title', 'ST Manager script runtime');
            this.iframe.setAttribute('loading', 'lazy');
            this.iframe.setAttribute('referrerpolicy', 'no-referrer');
            this.iframe.setAttribute('frameborder', '0');
            this.iframe.setAttribute('sandbox', 'allow-scripts');
            Object.assign(this.iframe.style, {
                display: 'block',
                width: '100%',
                minHeight: `${this.options.minHeight}px`,
                maxHeight: `${this.options.maxHeight}px`,
                height: `${this.options.minHeight}px`,
                border: 'none',
                background: 'transparent',
            });
            this.iframe.addEventListener('load', () => {
                this.syncViewport();
                this.applyMeasuredHeight(this.lastMeasuredHeight || this.options.minHeight);
            });

            this.shell.appendChild(this.iframe);
        }

        if (this.shell.parentNode !== this.host) {
            this.host.replaceChildren(this.shell);
        }
    }

    emitStatus(status, detail = null) {
        this.status = status;
        this.publishState(status, detail);
        if (this.callbacks.onStatus) {
            this.callbacks.onStatus(status, detail);
        }
    }

    emitLog(entry) {
        if (this.callbacks.onLog) {
            this.callbacks.onLog(entry);
        }
    }

    emitToast(message, duration) {
        if (this.callbacks.onToast) {
            this.callbacks.onToast(message, duration);
        }
    }

    emitDataChange(data) {
        if (this.callbacks.onDataChange) {
            this.callbacks.onDataChange(cloneValue(data));
        }
    }

    emitButtonChange(button) {
        if (this.callbacks.onButtonsChange) {
            this.callbacks.onButtonsChange(cloneValue(button));
        }
    }

    emitEvent(eventName, detail) {
        if (this.callbacks.onEvent) {
            this.callbacks.onEvent(eventName, cloneValue(detail));
        }
    }

    publishState(status = this.status, detail = null) {
        upsertRuntime({
            runtimeId: this.runtimeId || `stm-script-pending-${this.scriptSnapshot?.id || 'unknown'}`,
            kind: 'script',
            ownerId: this.scriptSnapshot?.id || '',
            label: this.scriptSnapshot?.name || this.runtimeId || 'Script Runtime',
            status,
            startedAt: this.startedAt || Date.now(),
            metrics: {
                measuredHeight: this.lastMeasuredHeight,
                minHeight: this.options.minHeight,
                maxHeight: this.options.maxHeight,
            },
            meta: {
                lastError: detail ? normalizeError(detail) : null,
                scriptId: this.scriptSnapshot?.id || '',
                scriptName: this.scriptSnapshot?.name || '',
            },
        });
    }

    getRuntimeSnapshot() {
        return {
            runtimeId: this.runtimeId,
            status: this.status,
            startedAt: this.startedAt || null,
            script: cloneValue(this.scriptSnapshot),
            height: this.lastMeasuredHeight,
        };
    }

    applyMeasuredHeight(height) {
        if (!this.shell || !this.iframe) {
            return;
        }

        const minHeight = Math.max(160, Number(this.options.minHeight) || DEFAULT_STAGE_MIN_HEIGHT);
        const maxHeight = Math.max(minHeight, Number(this.options.maxHeight) || DEFAULT_STAGE_MAX_HEIGHT);
        const numericHeight = Number.isFinite(Number(height)) && Number(height) > 0 ? Math.ceil(Number(height)) : minHeight;
        const clampedHeight = Math.max(minHeight, Math.min(maxHeight, numericHeight));

        this.lastMeasuredHeight = numericHeight;
        this.shell.style.minHeight = `${minHeight}px`;
        this.shell.style.maxHeight = `${maxHeight}px`;
        this.shell.style.height = `${clampedHeight}px`;
        this.iframe.style.minHeight = `${minHeight}px`;
        this.iframe.style.maxHeight = `${maxHeight}px`;
        this.iframe.style.height = `${clampedHeight}px`;
    }

    setDocument(documentHtml) {
        if (!this.iframe) {
            return;
        }

        if (this.objectUrl) {
            URL.revokeObjectURL(this.objectUrl);
            this.objectUrl = '';
        }

        this.objectUrl = URL.createObjectURL(new Blob([documentHtml], { type: 'text/html' }));
        this.iframe.src = this.objectUrl;
    }

    run(script) {
        this.ensureMounted();
        this.scriptSnapshot = createRuntimeSnapshot(script);
        if (!this.scriptSnapshot.content.trim()) {
            throw new Error('Script content is empty');
        }

        if (this.iframe && this.objectUrl) {
            this.iframe.src = 'about:blank';
        }
        this.runtimeId = `stm-script-runtime-${crypto.randomUUID()}`;
        this.lastMeasuredHeight = 0;
        this.startedAt = Date.now();
        this.emitStatus('starting');
        this.setDocument(buildScriptRuntimeDocument(this.runtimeId, this.scriptSnapshot));
        this.syncViewport();
        return this.runtimeId;
    }

    reload(script) {
        return this.run(script || this.scriptSnapshot || {});
    }

    updateContext(script) {
        this.scriptSnapshot = createRuntimeSnapshot(script || this.scriptSnapshot || {});
        if (!this.runtimeId || !this.iframe || !this.iframe.contentWindow) {
            return;
        }

        this.iframe.contentWindow.postMessage({
            channel: SCRIPT_RUNTIME_CHANNEL,
            runtimeId: this.runtimeId,
            type: 'host-sync',
            payload: {
                name: this.scriptSnapshot.name,
                info: this.scriptSnapshot.info,
                data: cloneValue(this.scriptSnapshot.data),
                button: cloneValue(this.scriptSnapshot.button),
            },
        }, '*');
    }

    triggerButton(name) {
        if (!this.runtimeId || !this.iframe || !this.iframe.contentWindow) {
            return;
        }

        this.iframe.contentWindow.postMessage({
            channel: SCRIPT_RUNTIME_CHANNEL,
            runtimeId: this.runtimeId,
            type: 'host-event',
            payload: {
                event: 'button',
                name: String(name || ''),
            },
        }, '*');
    }

    syncViewport() {
        if (!this.runtimeId || !this.iframe || !this.iframe.contentWindow) {
            return;
        }

        this.iframe.contentWindow.postMessage({
            channel: SCRIPT_RUNTIME_CHANNEL,
            runtimeId: this.runtimeId,
            type: 'viewport',
            payload: {
                height: window.innerHeight,
            },
        }, '*');
    }

    stop() {
        const runtimeId = this.runtimeId;
        const previousSnapshot = cloneValue(this.scriptSnapshot);
        if (this.objectUrl) {
            URL.revokeObjectURL(this.objectUrl);
            this.objectUrl = '';
        }

        if (this.iframe) {
            this.iframe.src = 'about:blank';
            this.iframe.style.height = `${this.options.minHeight}px`;
        }

        this.runtimeId = '';
        this.lastMeasuredHeight = 0;
        this.startedAt = 0;
        this.scriptSnapshot = previousSnapshot;
        this.emitStatus('stopped');
        if (runtimeId) {
            removeRuntime(runtimeId);
        }
    }

    destroy() {
        this.stop();
        window.removeEventListener('message', this.onWindowMessage);
        if (this.host && this.shell && this.shell.parentNode === this.host) {
            this.host.innerHTML = '';
        }
        this.shell = null;
        this.iframe = null;
        this.host = null;
    }

    postResponse(requestId, result) {
        if (!this.iframe || !this.iframe.contentWindow || !this.runtimeId || !requestId) {
            return;
        }

        this.iframe.contentWindow.postMessage({
            channel: SCRIPT_RUNTIME_CHANNEL,
            runtimeId: this.runtimeId,
            type: 'response',
            requestId,
            ok: true,
            result: cloneValue(result),
        }, '*');
    }

    postResponseError(requestId, error) {
        if (!this.iframe || !this.iframe.contentWindow || !this.runtimeId || !requestId) {
            return;
        }

        this.iframe.contentWindow.postMessage({
            channel: SCRIPT_RUNTIME_CHANNEL,
            runtimeId: this.runtimeId,
            type: 'response',
            requestId,
            ok: false,
            error: normalizeError(error),
        }, '*');
    }

    async handleRequest(requestId, payload) {
        const action = String(payload?.action || '');
        const requestPayload = payload?.payload || {};

        switch (action) {
            case 'toast': {
                this.emitToast(String(requestPayload.message || ''), Number(requestPayload.duration) || 3000);
                return { ok: true };
            }
            case 'get-host-state': {
                const store = getGlobalStore();
                return store ? {
                    currentMode: store.currentMode,
                    deviceType: store.deviceType,
                    darkMode: store.isDarkMode,
                    settings: cloneValue(store.settingsForm || {}),
                    viewState: cloneValue(store.viewState || {}),
                } : null;
            }
            case 'get-active-context':
                return getActiveRuntimeContext();
            case 'get-active-card':
                return getActiveRuntimeContext().card;
            case 'get-active-preset':
                return getActiveRuntimeContext().preset;
            case 'get-active-chat':
                return getActiveRuntimeContext().chat;
            case 'list-runtimes': {
                const module = await import('./runtimeManager.js');
                return module.getRuntimeManagerState();
            }
            case 'get-runtime-state':
                return this.getRuntimeSnapshot();
            case 'open-detail': {
                const target = requestPayload.target || 'card';
                if (target === 'card' && requestPayload.id) {
                    const { getCardDetail } = await import('../api/card.js');
                    const res = await getCardDetail(String(requestPayload.id));
                    if (!res.success || !res.card) {
                        throw new Error(res.msg || 'Failed to open card detail');
                    }
                    window.dispatchEvent(new CustomEvent('open-detail', { detail: res.card }));
                    return { opened: true, target, id: String(requestPayload.id) };
                }
                if (target === 'preset' && requestPayload.id) {
                    window.dispatchEvent(new CustomEvent('open-preset-reader', {
                        detail: { id: String(requestPayload.id) },
                    }));
                    return { opened: true, target, id: String(requestPayload.id) };
                }
                if (target === 'chat' && requestPayload.id) {
                    window.dispatchEvent(new CustomEvent('open-chat-reader', {
                        detail: { chat_id: String(requestPayload.id) },
                    }));
                    return { opened: true, target, id: String(requestPayload.id) };
                }
                throw new Error('Unsupported open-detail target or missing id');
            }
            case 'refresh-list': {
                const target = String(requestPayload.target || 'cards');
                const eventName = target === 'worldinfo'
                    ? 'refresh-wi-list'
                    : target === 'chats'
                        ? 'refresh-chat-list'
                        : target === 'presets'
                            ? 'refresh-preset-list'
                            : 'refresh-card-list';
                window.dispatchEvent(new CustomEvent(eventName));
                return { refreshed: true, target };
            }
            case 'reload-runtime': {
                if (!this.scriptSnapshot) {
                    throw new Error('No script snapshot available for reload');
                }
                this.reload(this.scriptSnapshot);
                return this.getRuntimeSnapshot();
            }
            case 'stop-runtime': {
                this.stop();
                return { stopped: true };
            }
            case 'fetch': {
                const targetUrl = toSafeUrl(requestPayload.url);
                const method = String(requestPayload.method || 'GET').toUpperCase();
                const responseType = String(requestPayload.responseType || 'text').toLowerCase();
                const init = {
                    method,
                    headers: toHeadersObject(requestPayload.headers),
                    credentials: requestPayload.credentials === 'include' ? 'include' : 'same-origin',
                };

                if (requestPayload.body !== undefined && method !== 'GET' && method !== 'HEAD') {
                    init.body = typeof requestPayload.body === 'string'
                        ? requestPayload.body
                        : JSON.stringify(requestPayload.body);
                }

                const response = await fetch(targetUrl.toString(), init);
                const body = responseType === 'json'
                    ? await response.json()
                    : await response.text();

                return {
                    ok: response.ok,
                    status: response.status,
                    statusText: response.statusText,
                    url: response.url,
                    headers: toHeadersObject(response.headers),
                    body,
                };
            }
            default:
                throw new Error(`Unsupported safe bridge action: ${action}`);
        }
    }

    onWindowMessage(event) {
        const message = event && event.data ? event.data : null;
        if (!message || message.channel !== SCRIPT_RUNTIME_CHANNEL || message.runtimeId !== this.runtimeId) {
            return;
        }

        const payload = message.payload || {};

        switch (message.type) {
            case 'request':
                this.handleRequest(String(payload.requestId || ''), payload)
                    .then(result => this.postResponse(String(payload.requestId || ''), result))
                    .catch(error => this.postResponseError(String(payload.requestId || ''), error));
                return;
            case 'ready':
                this.emitStatus('running');
                this.updateContext(this.scriptSnapshot);
                return;
            case 'status':
                this.emitStatus(String(payload.status || 'running'), payload.detail || null);
                return;
            case 'log':
                this.emitLog(normalizeLogEntry(payload));
                return;
            case 'toast':
                this.emitToast(String(payload.message || ''), Number(payload.duration));
                return;
            case 'sync-data':
                this.scriptSnapshot = {
                    ...(this.scriptSnapshot || {}),
                    data: cloneValue(payload.data || {}),
                };
                this.emitDataChange(this.scriptSnapshot.data);
                return;
            case 'sync-button-config':
                this.scriptSnapshot = {
                    ...(this.scriptSnapshot || {}),
                    button: sanitizeButtons(payload.button || {}),
                };
                this.emitButtonChange(this.scriptSnapshot.button);
                return;
            case 'event':
                this.emitEvent(String(payload.eventName || ''), payload.detail);
                return;
            case 'height':
                this.emitEvent('__runtime_height__', { height: payload.height });
                this.applyMeasuredHeight(payload.height);
                return;
            default:
                return;
        }
    }
}
