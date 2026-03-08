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

function buildCompatScript(context) {
    const contextLiteral = serializeForInlineScript(context || {});

    return [
        '(function () {',
        `  const appContext = ${contextLiteral};`,
        '  function createStorageShim() {',
        '    const store = new Map();',
        '    return {',
        '      getItem(key) {',
        '        const normalized = String(key);',
        '        return store.has(normalized) ? store.get(normalized) : null;',
        '      },',
        '      setItem(key, value) {',
        '        store.set(String(key), String(value));',
        '      },',
        '      removeItem(key) {',
        '        store.delete(String(key));',
        '      },',
        '      clear() {',
        '        store.clear();',
        '      },',
        '      key(index) {',
        '        return Array.from(store.keys())[Number(index)] || null;',
        '      },',
        '      get length() {',
        '        return store.size;',
        '      },',
        '    };',
        '  }',
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
        '  function ensureStorage(name) {',
        '    try {',
        '      const existing = window[name];',
        '      const probeKey = `__stm_probe__${name}`;',
        '      existing.setItem(probeKey, probeKey);',
        '      existing.removeItem(probeKey);',
        '      return existing;',
        '    } catch (error) {',
        '      const shim = createStorageShim();',
        '      try {',
        '        Object.defineProperty(window, name, {',
        '          configurable: true,',
        '          enumerable: true,',
        '          get() { return shim; },',
        '        });',
        '      } catch (defineError) {',
        '      }',
        '      return shim;',
        '    }',
        '  }',
        '  ensureStorage("localStorage");',
        '  ensureStorage("sessionStorage");',
        '  window.STManagerAppContext = cloneValue(appContext);',
        '  if (!window.Mvu) {',
        '    window.Mvu = {',
        '      getMvuData(request) {',
        '        const payload = cloneValue(appContext.latestMessageData || {});',
        '        if (request && typeof request === "object") {',
        '          payload.request = cloneValue(request);',
        '          if (request.message_id && request.message_id !== "latest") {',
        '            payload.message_id = String(request.message_id);',
        '          }',
        '        }',
        '        return payload;',
        '      },',
        '    };',
        '  }',
        '  if (!window.triggerSlash) {',
        '    window.triggerSlash = function (command) {',
        '      window.parent.postMessage({',
        '        channel: "st-manager:chat-app-stage",',
        '        type: "trigger-slash",',
        '        command: String(command || ""),',
        '      }, "*");',
        '    };',
        '  }',
        '  window.addEventListener("error", function (event) {',
        '    window.parent.postMessage({',
        '      channel: "st-manager:chat-app-stage",',
        '      type: "app-error",',
        '      message: String((event && event.message) || "App runtime error"),',
        '      stack: event && event.error && event.error.stack ? String(event.error.stack) : "",',
        '    }, "*");',
        '  });',
        '  window.addEventListener("unhandledrejection", function (event) {',
        '    const reason = event ? event.reason : null;',
        '    window.parent.postMessage({',
        '      channel: "st-manager:chat-app-stage",',
        '      type: "app-error",',
        '      message: reason && reason.message ? String(reason.message) : String(reason || "Unhandled rejection"),',
        '      stack: reason && reason.stack ? String(reason.stack) : "",',
        '    }, "*");',
        '  });',
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

function buildChatAppDocument({ htmlPayload, assetBase = '', context = {} }) {
    const baseHref = normalizeAssetBase(assetBase);
    const compatScript = buildCompatScript(context).replace(/<\/script>/gi, '<\\/script>');
    const sanitizedPayload = String(htmlPayload || '');
    const injectedHead = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        `<base href="${baseHref}">`,
        '<style>html, body { min-height: 100%; margin: 0; }</style>',
        `<script>${compatScript}</script>`,
    ].join('');

    if (/<!doctype html/i.test(sanitizedPayload) || /<html[\s>]/i.test(sanitizedPayload)) {
        return injectIntoFullDocument(sanitizedPayload, injectedHead);
    }

    return `<!DOCTYPE html><html><head>${injectedHead}</head><body>${sanitizedPayload}</body></html>`;
}

export class ChatAppStage {
    constructor(callbacks = {}) {
        this.callbacks = callbacks;
        this.host = null;
        this.shell = null;
        this.iframe = null;
        this.signature = '';

        this.onWindowMessage = this.onWindowMessage.bind(this);
        window.addEventListener('message', this.onWindowMessage);
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

            shell.appendChild(iframe);
            this.shell = shell;
            this.iframe = iframe;
        }

        if (this.shell.parentNode !== this.host) {
            this.host.replaceChildren(this.shell);
        }
    }

    update(options = {}) {
        if (!this.iframe) {
            return;
        }

        const signature = JSON.stringify({
            htmlPayload: String(options.htmlPayload || ''),
            assetBase: String(options.assetBase || ''),
            context: cloneValue(options.context || {}),
        });

        if (signature === this.signature) {
            return;
        }

        this.signature = signature;
        this.iframe.srcdoc = buildChatAppDocument({
            htmlPayload: String(options.htmlPayload || ''),
            assetBase: options.assetBase || '',
            context: options.context || {},
        });
    }

    clear() {
        this.signature = '';
        if (this.iframe) {
            this.iframe.srcdoc = '<!DOCTYPE html><html><body></body></html>';
        }
    }

    destroy() {
        this.clear();
        window.removeEventListener('message', this.onWindowMessage);
        if (this.host && this.shell && this.shell.parentNode === this.host) {
            this.host.innerHTML = '';
        }
        this.host = null;
        this.shell = null;
        this.iframe = null;
    }

    onWindowMessage(event) {
        const data = event && event.data ? event.data : null;
        if (!data || data.channel !== 'st-manager:chat-app-stage') {
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
        }
    }
}
