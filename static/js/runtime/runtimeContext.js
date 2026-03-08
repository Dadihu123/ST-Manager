let activeContext = {
    card: null,
    preset: null,
    chat: null,
    updatedAt: 0,
};

const subscribers = new Set();

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

function buildSnapshot() {
    return cloneValue(activeContext);
}

function notify() {
    const snapshot = buildSnapshot();
    subscribers.forEach(listener => {
        try {
            listener(snapshot);
        } catch (error) {
            console.error('Runtime context subscriber error:', error);
        }
    });

    window.dispatchEvent(new CustomEvent('st-runtime-context-update', {
        detail: snapshot,
    }));
}

export function setActiveRuntimeContext(partial) {
    activeContext = {
        ...activeContext,
        ...(partial || {}),
        updatedAt: Date.now(),
    };
    notify();
    return buildSnapshot();
}

export function clearActiveRuntimeContext(key) {
    if (!['card', 'preset', 'chat'].includes(String(key || ''))) {
        return buildSnapshot();
    }
    activeContext = {
        ...activeContext,
        [key]: null,
        updatedAt: Date.now(),
    };
    notify();
    return buildSnapshot();
}

export function getActiveRuntimeContext() {
    return buildSnapshot();
}

export function subscribeRuntimeContext(listener, options = {}) {
    if (typeof listener !== 'function') {
        throw new TypeError('subscribeRuntimeContext requires a listener function');
    }

    subscribers.add(listener);
    if (options.emitCurrent !== false) {
        listener(buildSnapshot());
    }

    return () => {
        subscribers.delete(listener);
    };
}
