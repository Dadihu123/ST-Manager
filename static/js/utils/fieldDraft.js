// Track mutations at field boundaries. Reading dirty state never walks untouched fields.
export const CARD_UI_FIELDS = ['ui_summary', 'source_link', 'resource_folder'];
export const CARD_FILE_FIELDS = ['char_name', 'description', 'first_mes', 'mes_example',
    'creator_notes', 'personality', 'scenario', 'system_prompt', 'post_history_instructions',
    'creator', 'character_version', 'tags', 'alternate_greetings', 'character_book', 'extensions', 'filename'];
const fields = new Set([...CARD_UI_FIELDS, ...CARD_FILE_FIELDS]);
const clone = value => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
const signature = value => value && typeof value === 'object' ? JSON.stringify(value) : value;

export function createFieldDraft(source, notify = () => {}) {
    const baseline = {};
    const versions = {};
    const pending = new Set();
    const dirty = new Set();
    const proxies = new WeakMap();
    let muted = false;
    const touch = field => {
        if (muted || !fields.has(field)) return;
        versions[field] = (versions[field] || 0) + 1;
        pending.add(field);
        notify();
    };
    const wrap = (object, root) => {
        if (!object || typeof object !== 'object') return object;
        if (proxies.has(object)) return proxies.get(object);
        const proxy = new Proxy(object, {
            get(target, key, receiver) {
                return wrap(Reflect.get(target, key, receiver), root || key);
            },
            set(target, key, value) {
                if (target[key] === value) return true;
                Reflect.set(target, key, value);
                touch(root || key);
                return true;
            },
            deleteProperty(target, key) {
                Reflect.deleteProperty(target, key);
                touch(root || key);
                return true;
            },
        });
        proxies.set(object, proxy);
        return proxy;
    };
    const data = wrap(source);
    for (const field of fields) baseline[field] = clone(source[field]);
    const draft = {
        data, versions,
        dirtyFields() {
            for (const field of pending) {
                if (signature(data[field]) === signature(baseline[field])) dirty.delete(field);
                else dirty.add(field);
            }
            pending.clear();
            return [...dirty];
        },
        baseline() { return clone(baseline); },
        rebase(names, values) {
            for (const field of names) {
                baseline[field] = clone(values[field]);
                pending.add(field);
            }
            notify();
        },
        capture(names) {
            return { values: Object.fromEntries(names.map(field => [field, clone(data[field])])),
                versions: { ...versions } };
        },
        accept(snapshot, canonical = {}) {
            muted = true;
            try {
                const accepted = new Set([...Object.keys(snapshot.values),
                    ...Object.keys(canonical).filter(field => fields.has(field))]);
                for (const field of accepted) {
                    const value = Object.hasOwn(canonical, field) ? canonical[field] : snapshot.values[field];
                    // New input is retained; the submitted value remains the disk baseline.
                    if ((versions[field] || 0) === (snapshot.versions[field] || 0)) data[field] = clone(value);
                    baseline[field] = clone(value);
                    pending.add(field);
                }
            } finally { muted = false; }
            notify();
        },
    };
    return draft;
}
