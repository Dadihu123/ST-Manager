const runtimeStore = new Map();
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

function normalizeRuntimeSnapshot(snapshot, existing = null) {
    const runtimeId = String(snapshot?.runtimeId || existing?.runtimeId || '');
    if (!runtimeId) {
        throw new Error('Runtime snapshot requires runtimeId');
    }

    return {
        runtimeId,
        kind: String(snapshot?.kind || existing?.kind || 'unknown'),
        ownerId: String(snapshot?.ownerId || existing?.ownerId || ''),
        label: String(snapshot?.label || existing?.label || runtimeId),
        status: String(snapshot?.status || existing?.status || 'idle'),
        startedAt: Number(snapshot?.startedAt || existing?.startedAt || Date.now()),
        updatedAt: Date.now(),
        metrics: cloneValue(snapshot?.metrics || existing?.metrics || {}),
        meta: cloneValue(snapshot?.meta || existing?.meta || {}),
    };
}

function buildManagerState() {
    const items = [...runtimeStore.values()]
        .map(item => cloneValue(item))
        .sort((a, b) => Number(b.updatedAt || 0) - Number(a.updatedAt || 0));

    const byKind = {};
    const byStatus = {};

    items.forEach(item => {
        byKind[item.kind] = (byKind[item.kind] || 0) + 1;
        byStatus[item.status] = (byStatus[item.status] || 0) + 1;
    });

    return {
        total: items.length,
        byKind,
        byStatus,
        items,
    };
}

function notifySubscribers() {
    const snapshot = buildManagerState();
    subscribers.forEach(listener => {
        try {
            listener(snapshot);
        } catch (error) {
            console.error('Runtime manager subscriber error:', error);
        }
    });

    window.dispatchEvent(new CustomEvent('st-runtime-manager-update', {
        detail: snapshot,
    }));
}

export function upsertRuntime(snapshot) {
    const existing = runtimeStore.get(String(snapshot?.runtimeId || '')) || null;
    const normalized = normalizeRuntimeSnapshot(snapshot, existing);
    runtimeStore.set(normalized.runtimeId, normalized);
    notifySubscribers();
    return cloneValue(normalized);
}

export function patchRuntime(runtimeId, patch) {
    const existing = runtimeStore.get(String(runtimeId || '')) || null;
    const normalized = normalizeRuntimeSnapshot({
        ...(existing || {}),
        ...(patch || {}),
        runtimeId: String(runtimeId || existing?.runtimeId || ''),
    }, existing);
    runtimeStore.set(normalized.runtimeId, normalized);
    notifySubscribers();
    return cloneValue(normalized);
}

export function removeRuntime(runtimeId) {
    if (!runtimeStore.delete(String(runtimeId || ''))) {
        return false;
    }
    notifySubscribers();
    return true;
}

export function getRuntime(runtimeId) {
    const runtime = runtimeStore.get(String(runtimeId || ''));
    return runtime ? cloneValue(runtime) : null;
}

export function listRuntimes(filter = {}) {
    const kind = filter?.kind ? String(filter.kind) : '';
    const status = filter?.status ? String(filter.status) : '';

    return [...runtimeStore.values()]
        .filter(item => (!kind || item.kind === kind) && (!status || item.status === status))
        .sort((a, b) => Number(b.updatedAt || 0) - Number(a.updatedAt || 0))
        .map(item => cloneValue(item));
}

export function getRuntimeManagerState() {
    return buildManagerState();
}

export function subscribeRuntimeManager(listener, options = {}) {
    if (typeof listener !== 'function') {
        throw new TypeError('subscribeRuntimeManager requires a listener function');
    }

    subscribers.add(listener);
    if (options.emitCurrent !== false) {
        listener(buildManagerState());
    }

    return () => {
        subscribers.delete(listener);
    };
}
