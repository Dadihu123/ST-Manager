import { getActiveRuntimeContext, subscribeRuntimeContext } from './runtimeContext.js';


const CHAT_APP_STAGE_CHANNEL = 'st-manager:chat-app-stage';
const CHAT_APP_VIEWPORT_VAR = 'var(--TH-viewport-height)';
const DEFAULT_STAGE_MIN_HEIGHT = 260;
const DEFAULT_STAGE_MAX_HEIGHT = 3200;


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


function createStageId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
        return `stm-chat-app-${window.crypto.randomUUID()}`;
    }

    return `stm-chat-app-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}


function normalizeAssetBase(assetBase = '') {
    const raw = String(assetBase || '').trim();
    if (!raw) {
        return `${window.location.origin}/`;
    }

    try {
        const resolved = new URL(raw, window.location.origin);
        const pathname = resolved.pathname.endsWith('/') ? resolved.pathname : `${resolved.pathname}/`;
        return `${resolved.origin}${pathname}`;
    } catch {
        return `${window.location.origin}/`;
    }
}


function serializeForInlineScript(value) {
    return JSON.stringify(value)
        .replace(/<\/script>/gi, '<\\/script>')
        .replace(/\u2028/g, '\\u2028')
        .replace(/\u2029/g, '\\u2029');
}


function normalizeStorageSnapshot(snapshot = {}) {
    if (!snapshot || typeof snapshot !== 'object') {
        return {};
    }

    return Object.fromEntries(
        Object.entries(snapshot).map(([key, value]) => [String(key), String(value)]),
    );
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


function getGlobalStore() {
    try {
        if (window.Alpine && typeof window.Alpine.store === 'function') {
            return window.Alpine.store('global');
        }
    } catch (error) {
    }

    return null;
}


function showGlobalToast(message, duration) {
    const store = getGlobalStore();
    if (!store || typeof store.showToast !== 'function') {
        return false;
    }

    store.showToast(String(message || ''), Number.isFinite(Number(duration)) ? Number(duration) : 2200);
    return true;
}


function toSafeUrl(url) {
    const normalized = new URL(String(url || ''), window.location.origin);
    if (normalized.origin !== window.location.origin) {
        throw new Error('Cross-origin requests are not allowed in chat app stage');
    }
    return normalized;
}


function normalizeHeaders(headers) {
    if (headers instanceof Headers) {
        return Object.fromEntries(headers.entries());
    }
    if (!headers || typeof headers !== 'object') {
        return {};
    }

    return Object.fromEntries(Object.entries(headers).map(([key, value]) => [key, String(value)]));
}


function convertViewportUnitValue(value) {
    return String(value || '').replace(/(\d+(?:\.\d+)?)vh\b/gi, (match, rawNumber) => {
        const parsed = Number.parseFloat(rawNumber);
        if (!Number.isFinite(parsed)) {
            return match;
        }
        if (parsed === 100) {
            return CHAT_APP_VIEWPORT_VAR;
        }
        return `calc(${CHAT_APP_VIEWPORT_VAR} * ${parsed / 100})`;
    });
}


function replaceViewportUnits(content) {
    if (!content || !/\d+(?:\.\d+)?vh\b/i.test(content)) {
        return content;
    }

    content = content.replace(
        /((?:min-|max-)?height\s*:\s*)([^;{}]*?\d+(?:\.\d+)?vh)(?=\s*[;}])/gi,
        (_match, prefix, value) => `${prefix}${convertViewportUnitValue(value)}`,
    );

    content = content.replace(
        /(style\s*=\s*(["']))([^"']*?)\2/gi,
        (match, prefix, quote, styleContent) => {
            if (!/(?:min-|max-)?height\s*:\s*[^;]*vh/i.test(styleContent)) {
                return match;
            }
            const replaced = styleContent.replace(
                /((?:min-|max-)?height\s*:\s*)([^;]*?\d+(?:\.\d+)?vh)/gi,
                (_innerMatch, innerPrefix, value) => `${innerPrefix}${convertViewportUnitValue(value)}`,
            );
            return `${prefix}${replaced}${quote}`;
        },
    );

    content = content.replace(
        /(\.style\.(?:minHeight|maxHeight|height)\s*=\s*(["']))([\s\S]*?)(\2)/gi,
        (match, prefix, _quote, value, suffix) => {
            if (!/\b\d+(?:\.\d+)?vh\b/i.test(value)) {
                return match;
            }
            return `${prefix}${convertViewportUnitValue(value)}${suffix}`;
        },
    );

    content = content.replace(
        /(setProperty\s*\(\s*(["'])(?:min-height|max-height|height)\2\s*,\s*(["']))([\s\S]*?)(\3\s*\))/gi,
        (match, prefix, _quoteOne, _quoteTwo, value, suffix) => {
            if (!/\b\d+(?:\.\d+)?vh\b/i.test(value)) {
                return match;
            }
            return `${prefix}${convertViewportUnitValue(value)}${suffix}`;
        },
    );

    return content;
}


function createSupportStyle(initialViewportHeight, options = {}) {
    const resolvedHeight = Number.isFinite(Number(initialViewportHeight)) && Number(initialViewportHeight) > 0
        ? `${Math.ceil(Number(initialViewportHeight))}px`
        : '100vh';

    return [
        '<style>',
        ':root {',
        `  --TH-viewport-height: ${resolvedHeight};`,
        '  color-scheme: normal;',
        '}',
        '</style>',
    ].join('');
}


function buildCompatScript({ stageId, context = {}, activeContext = {}, storageState = {}, initialViewportHeight = 0 }) {
    const stageLiteral = serializeForInlineScript(stageId || '');
    const contextLiteral = serializeForInlineScript(context || {});
    const activeContextLiteral = serializeForInlineScript(activeContext || {});
    const storageLiteral = serializeForInlineScript({
        localStorage: normalizeStorageSnapshot(storageState.localStorage || {}),
        sessionStorage: normalizeStorageSnapshot(storageState.sessionStorage || {}),
    });
    const initialViewportLiteral = serializeForInlineScript(Number(initialViewportHeight) || 0);

    return [
        '(function () {',
        `  const CHANNEL = ${serializeForInlineScript(CHAT_APP_STAGE_CHANNEL)};`,
        `  const STAGE_ID = ${stageLiteral};`,
        `  const INITIAL_APP_CONTEXT = ${contextLiteral};`,
        `  const INITIAL_ACTIVE_CONTEXT = ${activeContextLiteral};`,
        `  const INITIAL_STORAGE_STATE = ${storageLiteral};`,
        `  const INITIAL_VIEWPORT_HEIGHT = ${initialViewportLiteral};`,
        '  const root = document.documentElement;',
        '  const pendingRequests = new Map();',
        '  let requestSequence = 0;',
        '  let stageState = {',
        '    appContext: cloneValue(INITIAL_APP_CONTEXT),',
        '    activeContext: cloneValue(INITIAL_ACTIVE_CONTEXT),',
        '  };',
        '',
        '  function cloneValue(value) {',
        '    if (typeof structuredClone === "function") {',
        '      try {',
        '        return structuredClone(value);',
        '      } catch (error) {',
        '      }',
        '    }',
        '    try {',
        '      return JSON.parse(JSON.stringify(value));',
        '    } catch (error) {',
        '      return value;',
        '    }',
        '  }',
        '',
        '  function postToHost(type, payload) {',
        '    if (!window.parent) return;',
        '    window.parent.postMessage({',
        '      channel: CHANNEL,',
        '      stageId: STAGE_ID,',
        '      type: String(type || ""),',
        '      ...(payload && typeof payload === "object" ? payload : {}),',
        '    }, "*");',
        '  }',
        '',
        '  function applyViewportHeight(height) {',
            '    if (!Number.isFinite(height) || height <= 0) return;',
            '    root.style.setProperty("--TH-viewport-height", `${Math.ceil(height)}px`);',
        '  }',
        '',
        '  function syncContextSnapshot() {',
        '    window.STManagerAppContext = cloneValue(stageState.appContext);',
        '    window.STManagerActiveContext = cloneValue(stageState.activeContext);',
        '  }',
        '',
        '  function createStorageShim(name, initialEntries) {',
        '    const store = new Map(Object.entries(initialEntries || {}).map(([key, value]) => [String(key), String(value)]));',
        '    let muted = false;',
        '    function emit() {',
        '      if (muted) return;',
        '      postToHost("storage-sync", {',
        '        storage: name,',
        '        entries: Object.fromEntries(store.entries()),',
        '      });',
        '    }',
        '    return {',
        '      getItem(key) {',
        '        const normalized = String(key);',
        '        return store.has(normalized) ? store.get(normalized) : null;',
        '      },',
        '      setItem(key, value) {',
        '        store.set(String(key), String(value));',
        '        emit();',
        '      },',
        '      removeItem(key) {',
        '        store.delete(String(key));',
        '        emit();',
        '      },',
        '      clear() {',
        '        store.clear();',
        '        emit();',
        '      },',
        '      key(index) {',
        '        return Array.from(store.keys())[Number(index)] || null;',
        '      },',
        '      replaceAll(entries) {',
        '        muted = true;',
        '        store.clear();',
        '        Object.entries(entries || {}).forEach(([key, value]) => {',
        '          store.set(String(key), String(value));',
        '        });',
        '        muted = false;',
        '      },',
        '      get length() {',
        '        return store.size;',
        '      },',
        '    };',
        '  }',
        '',
        '  const localStorageShim = createStorageShim("localStorage", INITIAL_STORAGE_STATE.localStorage);',
        '  const sessionStorageShim = createStorageShim("sessionStorage", INITIAL_STORAGE_STATE.sessionStorage);',
        '  try {',
        '    Object.defineProperty(window, "localStorage", {',
        '      configurable: true,',
        '      enumerable: true,',
        '      get() { return localStorageShim; },',
        '    });',
        '  } catch (error) {',
        '  }',
        '  try {',
        '    Object.defineProperty(window, "sessionStorage", {',
        '      configurable: true,',
        '      enumerable: true,',
        '      get() { return sessionStorageShim; },',
        '    });',
        '  } catch (error) {',
        '  }',
        '',
        '  function getAppContext() {',
        '    return cloneValue(stageState.appContext);',
        '  }',
        '',
        '  function getActiveContext() {',
        '    return cloneValue(stageState.activeContext);',
        '  }',
        '',
        '  function syncHostPayload(payload) {',
        '    const nextPayload = payload && typeof payload === "object" ? payload : {};',
        '    if (Object.prototype.hasOwnProperty.call(nextPayload, "appContext")) {',
        '      stageState.appContext = cloneValue(nextPayload.appContext || {});',
        '    }',
        '    if (Object.prototype.hasOwnProperty.call(nextPayload, "activeContext")) {',
        '      stageState.activeContext = cloneValue(nextPayload.activeContext || {});',
        '    }',
        '    if (nextPayload.storageState && typeof nextPayload.storageState === "object") {',
        '      localStorageShim.replaceAll(nextPayload.storageState.localStorage || {});',
        '      sessionStorageShim.replaceAll(nextPayload.storageState.sessionStorage || {});',
        '    }',
        '    syncContextSnapshot();',
        '    window.dispatchEvent(new CustomEvent("st-manager:context-update", {',
        '      detail: {',
        '        appContext: getAppContext(),',
        '        activeContext: getActiveContext(),',
        '      },',
        '    }));',
        '  }',
        '',
        '  function request(action, payload, options) {',
        '    const requestId = `${STAGE_ID}:${++requestSequence}`;',
        '    const timeoutMs = Math.max(1000, Math.min(30000, Number(options && options.timeout) || 10000));',
        '    return new Promise((resolve, reject) => {',
        '      const timeoutId = setTimeout(() => {',
        '        pendingRequests.delete(requestId);',
        '        reject(new Error(`Host request timed out: ${String(action || "unknown")}`));',
        '      }, timeoutMs);',
        '      pendingRequests.set(requestId, { resolve, reject, timeoutId });',
        '      postToHost("request", {',
        '        requestId,',
        '        action: String(action || ""),',
        '        payload: cloneValue(payload || {}),',
        '      });',
        '    });',
        '  }',
        '',
        '  function measureHeight() {',
        '    const body = document.body;',
        '    const html = document.documentElement;',
        '    if (!body || !html) return;',
        '    const height = Math.max(',
        '      body.scrollHeight || 0,',
        '      body.offsetHeight || 0,',
        '      html.scrollHeight || 0,',
        '      html.offsetHeight || 0',
        '    );',
        '    if (!Number.isFinite(height) || height <= 0) return;',
        '    postToHost("height", { height: Math.ceil(height) });',
        '  }',
        '',
        '  const scheduleMeasure = (() => {',
        '    let scheduled = false;',
        '    return function () {',
        '      if (scheduled) return;',
        '      scheduled = true;',
        '      const runner = () => {',
        '        scheduled = false;',
        '        measureHeight();',
        '      };',
        '      if (typeof window.requestAnimationFrame === "function") {',
        '        window.requestAnimationFrame(runner);',
        '      } else {',
        '        setTimeout(runner, 16);',
        '      }',
        '    };',
        '  })();',
        '',
        '  function observeDocument() {',
        '    if (typeof ResizeObserver === "function") {',
        '      const resizeObserver = new ResizeObserver(scheduleMeasure);',
        '      if (document.documentElement) resizeObserver.observe(document.documentElement);',
        '      if (document.body) resizeObserver.observe(document.body);',
        '    }',
        '    if (typeof MutationObserver === "function" && document.documentElement) {',
        '      const mutationObserver = new MutationObserver(scheduleMeasure);',
        '      mutationObserver.observe(document.documentElement, {',
        '        subtree: true,',
        '        childList: true,',
        '        characterData: true,',
        '        attributes: true,',
        '      });',
        '    }',
        '  }',
        '',
        '  syncContextSnapshot();',
        '  applyViewportHeight(Number(INITIAL_VIEWPORT_HEIGHT));',
        '  window.__STM_IFRAME_ID = STAGE_ID;',
        '  if (!window.name) {',
        '    window.name = STAGE_ID;',
        '  }',
        '',
        '  window.Mvu = window.Mvu || {',
        '    getMvuData(requestPayload) {',
        '      const payload = cloneValue(stageState.appContext.latestMessageData || {});',
        '      if (requestPayload && typeof requestPayload === "object") {',
        '        payload.request = cloneValue(requestPayload);',
        '        if (requestPayload.message_id && requestPayload.message_id !== "latest") {',
        '          payload.message_id = String(requestPayload.message_id);',
        '        }',
        '      }',
        '      return payload;',
        '    },',
        '  };',
        '',
        '  window.triggerSlash = window.triggerSlash || function (command) {',
        '    postToHost("trigger-slash", { command: String(command || "") });',
        '  };',
        '',
        '  window.STManagerBridge = {',
        '    channel: CHANNEL,',
        '    stageId: STAGE_ID,',
        '    getAppContext,',
        '    getActiveContext,',
        '    getActiveChat: () => cloneValue(stageState.activeContext && stageState.activeContext.chat),',
        '    getLatestMessageData: () => cloneValue(stageState.appContext.latestMessageData || {}),',
        '    request,',
        '    showToast: (message, duration) => request("toast", {',
        '      message: String(message || ""),',
        '      duration: Number.isFinite(Number(duration)) ? Number(duration) : undefined,',
        '    }),',
        '    fetch: (url, options) => request("fetch", { url, ...(options || {}) }),',
        '    fetchText: (url, options) => request("fetch", { url, ...(options || {}), responseType: "text" }).then(result => result.body),',
        '    fetchJson: (url, options) => request("fetch", { url, ...(options || {}), responseType: "json" }).then(result => result.body),',
        '    syncHeight: () => scheduleMeasure(),',
        '  };',
        '  window.TavernHelper = window.TavernHelper || window.STManagerBridge;',
        '  window.SillyTavern = window.SillyTavern || {',
        '    getContext() {',
        '      return {',
        '        STManagerBridge: window.STManagerBridge,',
        '        chat: cloneValue(stageState.activeContext && stageState.activeContext.chat),',
        '        appContext: getAppContext(),',
        '      };',
        '    },',
        '  };',
        '  window.toastr = window.toastr || {',
        '    info(message, title, options) {',
        '      const prefix = title ? `${title}: ` : "";',
        '      return window.STManagerBridge.showToast(`${prefix}${String(message || "")}`, options && options.timeOut);',
        '    },',
        '    success(message, title, options) {',
        '      const prefix = title ? `${title}: ` : "";',
        '      return window.STManagerBridge.showToast(`${prefix}${String(message || "")}`, options && options.timeOut);',
        '    },',
        '    warning(message, title, options) {',
        '      const prefix = title ? `${title}: ` : "";',
        '      return window.STManagerBridge.showToast(`${prefix}${String(message || "")}`, options && options.timeOut);',
        '    },',
        '    error(message, title, options) {',
        '      const prefix = title ? `${title}: ` : "";',
        '      return window.STManagerBridge.showToast(`${prefix}${String(message || "")}`, options && options.timeOut);',
        '    },',
        '  };',
        '',
        '  window.addEventListener("message", function (event) {',
        '    const message = event && event.data ? event.data : null;',
        '    if (!message || message.channel !== CHANNEL || message.stageId !== STAGE_ID) {',
        '      return;',
        '    }',
        '    if (message.type === "viewport") {',
        '      applyViewportHeight(Number(message.payload && message.payload.height));',
        '      scheduleMeasure();',
        '      return;',
        '    }',
        '    if (message.type === "host-sync") {',
        '      syncHostPayload(message.payload || {});',
        '      scheduleMeasure();',
        '      return;',
        '    }',
        '    if (message.type === "response") {',
        '      const pending = pendingRequests.get(String(message.requestId || ""));',
        '      if (!pending) return;',
        '      clearTimeout(pending.timeoutId);',
        '      pendingRequests.delete(String(message.requestId || ""));',
        '      if (message.ok === false) {',
        '        const error = new Error(message.error && message.error.message ? String(message.error.message) : "Host request failed");',
        '        if (message.error && message.error.name) {',
        '          error.name = String(message.error.name);',
        '        }',
        '        if (message.error && message.error.stack) {',
        '          error.stack = String(message.error.stack);',
        '        }',
        '        pending.reject(error);',
        '      } else {',
        '        pending.resolve(cloneValue(message.result));',
        '      }',
        '    }',
        '  });',
        '',
        '  window.addEventListener("error", function (event) {',
        '    postToHost("app-error", {',
        '      message: String((event && event.message) || "App runtime error"),',
        '      stack: event && event.error && event.error.stack ? String(event.error.stack) : "",',
        '    });',
        '  });',
        '',
        '  window.addEventListener("unhandledrejection", function (event) {',
        '    const reason = event ? event.reason : null;',
        '    postToHost("app-error", {',
        '      message: reason && reason.message ? String(reason.message) : String(reason || "Unhandled rejection"),',
        '      stack: reason && reason.stack ? String(reason.stack) : "",',
        '    });',
        '  });',
        '',
        '  if (document.readyState === "loading") {',
        '    document.addEventListener("DOMContentLoaded", function () {',
        '      observeDocument();',
        '      scheduleMeasure();',
        '    }, { once: true });',
        '  } else {',
        '    observeDocument();',
        '    scheduleMeasure();',
        '  }',
        '',
        '  window.addEventListener("load", function () {',
        '    scheduleMeasure();',
        '    setTimeout(scheduleMeasure, 80);',
        '    setTimeout(scheduleMeasure, 320);',
        '  });',
        '',
        '  scheduleMeasure();',
        '})();',
    ].join('\n');
}


function injectIntoFullDocument(htmlPayload, injectedHead) {
    if (/<head[\s>]/i.test(htmlPayload)) {
        return htmlPayload.replace(/<head([^>]*)>/i, `<head$1>${injectedHead}`);
    }

    if (/<html[\s>]/i.test(htmlPayload)) {
        return htmlPayload.replace(/<html([^>]*)>/i, `<html$1><head>${injectedHead}</head>`);
    }

    return `<!DOCTYPE html><html><head>${injectedHead}</head><body>${htmlPayload}</body></html>`;
}


function buildChatAppDocument({ stageId, htmlPayload, assetBase = '', context = {}, activeContext = {}, storageState = {}, initialViewportHeight = 0 }) {
    const baseHref = normalizeAssetBase(assetBase);
    const compatScript = buildCompatScript({
        stageId,
        context,
        activeContext,
        storageState,
        initialViewportHeight,
    }).replace(/<\/script>/gi, '<\\/script>');
    const sanitizedPayload = replaceViewportUnits(String(htmlPayload || ''));
    const injectedHead = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        `<base href="${baseHref}">`,
        createSupportStyle(initialViewportHeight),
        `<script>${compatScript}</script>`,
    ].join('');

    if (/<!doctype html/i.test(sanitizedPayload) || /<html[\s>]/i.test(sanitizedPayload)) {
        return injectIntoFullDocument(sanitizedPayload, injectedHead);
    }

    return `<!DOCTYPE html><html><head>${injectedHead}</head><body>${sanitizedPayload}</body></html>`;
}


function detectAppFrameHeight(htmlPayload = '') {
    const source = String(htmlPayload || '');
    const compactSignals = [
        'modern-dark-log',
        'sakura-collapsible',
        'evidence-details',
    ];

    if (compactSignals.some(signal => source.includes(signal))) {
        return 260;
    }

    if (/<!doctype html/i.test(source) || /<html[\s>]/i.test(source)) {
        return 960;
    }

    return 520;
}


export class ChatAppStage {
    constructor(callbacks = {}) {
        this.callbacks = callbacks;
        this.host = null;
        this.shell = null;
        this.iframe = null;
        this.signature = '';
        this.stageId = createStageId();
        this.currentHtmlPayload = '';
        this.currentAssetBase = '';
        this.currentContext = {};
        this.storageState = {
            localStorage: {},
            sessionStorage: {},
        };
        this.activeRuntimeContext = getActiveRuntimeContext();
        this.lastMeasuredHeight = 0;

        this.onWindowMessage = this.onWindowMessage.bind(this);
        this.onWindowResize = this.onWindowResize.bind(this);
        window.addEventListener('message', this.onWindowMessage);
        window.addEventListener('resize', this.onWindowResize, { passive: true });

        this.unsubscribeRuntimeContext = subscribeRuntimeContext((snapshot) => {
            this.activeRuntimeContext = snapshot;
            this.syncHostState();
        }, { emitCurrent: false });
    }

    resetSessionState() {
        this.signature = '';
        this.stageId = createStageId();
        this.currentHtmlPayload = '';
        this.currentAssetBase = '';
        this.currentContext = {};
        this.storageState = {
            localStorage: {},
            sessionStorage: {},
        };
        this.lastMeasuredHeight = 0;
    }

    isViewportStage() {
        return Boolean(this.host && this.host.classList.contains('chat-reader-app-stage-host'));
    }

    resolveViewportStageHeight() {
        const rectHeight = Math.ceil(this.host?.getBoundingClientRect?.().height || 0);
        return Math.max(360, rectHeight || detectAppFrameHeight(this.currentHtmlPayload));
    }

    resolveMinHeight() {
        if (this.isViewportStage()) {
            return this.resolveViewportStageHeight();
        }

        return Math.max(DEFAULT_STAGE_MIN_HEIGHT, detectAppFrameHeight(this.currentHtmlPayload));
    }

    resolveMaxHeight() {
        if (this.isViewportStage()) {
            return this.resolveViewportStageHeight();
        }

        return Math.max(this.resolveMinHeight(), DEFAULT_STAGE_MAX_HEIGHT);
    }

    applyMeasuredHeight(height) {
        if (!this.shell || !this.iframe) {
            return;
        }

        if (this.isViewportStage()) {
            const viewportHeight = this.resolveViewportStageHeight();
            this.lastMeasuredHeight = viewportHeight;
            this.shell.style.minHeight = `${viewportHeight}px`;
            this.shell.style.maxHeight = `${viewportHeight}px`;
            this.shell.style.height = `${viewportHeight}px`;
            this.iframe.style.minHeight = `${viewportHeight}px`;
            this.iframe.style.maxHeight = `${viewportHeight}px`;
            this.iframe.style.height = `${viewportHeight}px`;
            return;
        }

        const fallbackHeight = this.resolveMinHeight();
        const numericHeight = Number.isFinite(Number(height)) && Number(height) > 0 ? Math.ceil(Number(height)) : fallbackHeight;
        const clampedHeight = Math.max(this.resolveMinHeight(), Math.min(this.resolveMaxHeight(), numericHeight));

        this.lastMeasuredHeight = numericHeight;
        this.shell.style.minHeight = `${this.resolveMinHeight()}px`;
        this.shell.style.maxHeight = `${this.resolveMaxHeight()}px`;
        this.shell.style.height = `${clampedHeight}px`;
        this.iframe.style.minHeight = `${this.resolveMinHeight()}px`;
        this.iframe.style.maxHeight = `${this.resolveMaxHeight()}px`;
        this.iframe.style.height = `${clampedHeight}px`;
    }

    attachHost(host) {
        this.host = host || null;
        if (!this.host) {
            return;
        }

        if (!this.shell) {
            const shell = document.createElement('div');
            shell.className = 'chat-reader-app-stage-shell';

            const iframe = document.createElement('iframe');
            iframe.className = 'chat-reader-app-stage-frame';
            iframe.setAttribute('title', 'Chat Reader App Stage');
            iframe.setAttribute('frameborder', '0');
            iframe.setAttribute('sandbox', 'allow-scripts');
            iframe.setAttribute('referrerpolicy', 'no-referrer');
            iframe.addEventListener('load', () => {
                this.syncViewport();
                this.syncHostState();
                this.applyMeasuredHeight(this.lastMeasuredHeight || this.resolveMinHeight());
            });

            shell.appendChild(iframe);
            this.shell = shell;
            this.iframe = iframe;
        }

        if (this.shell.parentNode !== this.host) {
            this.host.replaceChildren(this.shell);
        }

        this.applyMeasuredHeight(this.lastMeasuredHeight || this.resolveMinHeight());
    }

    postToIframe(type, payload = {}) {
        if (!this.iframe || !this.iframe.contentWindow) {
            return;
        }

        this.iframe.contentWindow.postMessage({
            channel: CHAT_APP_STAGE_CHANNEL,
            stageId: this.stageId,
            type,
            payload: cloneValue(payload),
        }, '*');
    }

    syncViewport() {
        this.postToIframe('viewport', {
            height: window.innerHeight,
        });
    }

    syncHostState() {
        this.postToIframe('host-sync', {
            appContext: cloneValue(this.currentContext || {}),
            activeContext: cloneValue(this.activeRuntimeContext || {}),
            storageState: cloneValue(this.storageState),
        });
    }

    update(options = {}) {
        if (!this.iframe) {
            return;
        }

        this.currentHtmlPayload = String(options.htmlPayload || '');
        this.currentAssetBase = String(options.assetBase || '');
        this.currentContext = cloneValue(options.context || {});

        const signature = JSON.stringify({
            htmlPayload: this.currentHtmlPayload,
            assetBase: this.currentAssetBase,
            context: this.currentContext,
        });

        if (signature === this.signature) {
            this.syncViewport();
            this.syncHostState();
            this.applyMeasuredHeight(this.lastMeasuredHeight || this.resolveMinHeight());
            return;
        }

        this.signature = signature;
        this.lastMeasuredHeight = 0;
        this.applyMeasuredHeight(this.resolveMinHeight());
        this.iframe.srcdoc = buildChatAppDocument({
            stageId: this.stageId,
            htmlPayload: this.currentHtmlPayload,
            assetBase: this.currentAssetBase,
            context: this.currentContext,
            activeContext: this.activeRuntimeContext,
            storageState: this.storageState,
            initialViewportHeight: window.innerHeight,
        });
    }

    clear(options = {}) {
        const resetSession = options.resetSession === true;
        this.signature = '';
        this.currentHtmlPayload = '';
        this.currentAssetBase = '';
        this.currentContext = {};
        this.lastMeasuredHeight = 0;
        if (resetSession) {
            this.stageId = createStageId();
            this.storageState = {
                localStorage: {},
                sessionStorage: {},
            };
        }
        if (this.iframe) {
            this.applyMeasuredHeight(DEFAULT_STAGE_MIN_HEIGHT);
            this.iframe.srcdoc = '<!DOCTYPE html><html><body></body></html>';
        }
    }

    destroy() {
        this.clear({ resetSession: true });
        window.removeEventListener('message', this.onWindowMessage);
        window.removeEventListener('resize', this.onWindowResize);
        if (typeof this.unsubscribeRuntimeContext === 'function') {
            this.unsubscribeRuntimeContext();
            this.unsubscribeRuntimeContext = null;
        }
        if (this.host && this.shell && this.shell.parentNode === this.host) {
            this.host.innerHTML = '';
        }
        this.host = null;
        this.shell = null;
        this.iframe = null;
    }

    async handleHostRequest(action, payload = {}) {
        switch (String(action || '')) {
            case 'toast': {
                const message = String(payload.message || '');
                const duration = Number.isFinite(Number(payload.duration)) ? Number(payload.duration) : 2200;
                if (typeof this.callbacks.onToast === 'function') {
                    this.callbacks.onToast(message, duration);
                    return true;
                }
                return showGlobalToast(message, duration);
            }
            case 'fetch': {
                const url = toSafeUrl(payload.url || '');
                const headers = normalizeHeaders(payload.headers || {});
                const init = {
                    method: String(payload.method || 'GET').toUpperCase(),
                    headers,
                };

                if (payload.body !== undefined && payload.body !== null && init.method !== 'GET' && init.method !== 'HEAD') {
                    if (typeof payload.body === 'string') {
                        init.body = payload.body;
                    } else if (payload.body && typeof payload.body === 'object') {
                        init.body = JSON.stringify(payload.body);
                        if (!Object.keys(headers).some(key => key.toLowerCase() === 'content-type')) {
                            init.headers = {
                                ...headers,
                                'Content-Type': 'application/json',
                            };
                        }
                    } else {
                        init.body = String(payload.body);
                    }
                }

                const response = await fetch(url, init);
                const responseType = String(payload.responseType || 'text').toLowerCase();
                const body = responseType === 'json'
                    ? await response.json()
                    : await response.text();

                return {
                    ok: response.ok,
                    status: response.status,
                    statusText: response.statusText,
                    headers: normalizeHeaders(response.headers),
                    body,
                };
            }
            case 'get-app-context':
                return cloneValue(this.currentContext || {});
            case 'get-active-context':
                return getActiveRuntimeContext();
            case 'get-active-card':
                return getActiveRuntimeContext().card;
            case 'get-active-preset':
                return getActiveRuntimeContext().preset;
            case 'get-active-chat':
                return getActiveRuntimeContext().chat;
            case 'get-host-state':
                return {
                    stageId: this.stageId,
                    appContext: cloneValue(this.currentContext || {}),
                    activeContext: getActiveRuntimeContext(),
                    storageState: cloneValue(this.storageState),
                    isViewportStage: this.isViewportStage(),
                    measuredHeight: this.lastMeasuredHeight,
                };
            default:
                throw new Error(`Unsupported chat app stage request: ${String(action || 'unknown')}`);
        }
    }

    async respondToRequest(data) {
        if (!this.iframe || !this.iframe.contentWindow) {
            return;
        }

        const requestId = String(data.requestId || '');
        if (!requestId) {
            return;
        }

        try {
            const result = await this.handleHostRequest(data.action, data.payload || {});
            this.iframe.contentWindow.postMessage({
                channel: CHAT_APP_STAGE_CHANNEL,
                stageId: this.stageId,
                type: 'response',
                requestId,
                ok: true,
                result: cloneValue(result),
            }, '*');
        } catch (error) {
            this.iframe.contentWindow.postMessage({
                channel: CHAT_APP_STAGE_CHANNEL,
                stageId: this.stageId,
                type: 'response',
                requestId,
                ok: false,
                error: normalizeError(error),
            }, '*');
        }
    }

    onWindowResize() {
        this.syncViewport();
        this.applyMeasuredHeight(this.lastMeasuredHeight || this.resolveMinHeight());
    }

    onWindowMessage(event) {
        const data = event && event.data ? event.data : null;
        if (!data || data.channel !== CHAT_APP_STAGE_CHANNEL || data.stageId !== this.stageId) {
            return;
        }

        if (this.iframe && event.source && this.iframe.contentWindow && event.source !== this.iframe.contentWindow) {
            return;
        }

        if (data.type === 'trigger-slash' && typeof this.callbacks.onTriggerSlash === 'function') {
            this.callbacks.onTriggerSlash(String(data.command || ''));
            return;
        }

        if (data.type === 'app-error' && typeof this.callbacks.onAppError === 'function') {
            this.callbacks.onAppError({
                message: String(data.message || 'App runtime error'),
                stack: String(data.stack || ''),
            });
            return;
        }

        if (data.type === 'height') {
            this.applyMeasuredHeight(Number(data.height || data.payload?.height));
            return;
        }

        if (data.type === 'storage-sync') {
            const storageName = String(data.storage || '');
            if (storageName === 'localStorage' || storageName === 'sessionStorage') {
                this.storageState[storageName] = normalizeStorageSnapshot(data.entries || {});
            }
            return;
        }

        if (data.type === 'request') {
            this.respondToRequest(data);
        }
    }
}
