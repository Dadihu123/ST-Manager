// Track mutations at field boundaries. Reading dirty state never walks untouched fields.
export const CARD_UI_FIELDS = ['ui_summary', 'source_link', 'resource_folder'];
export const CARD_FILE_FIELDS = ['char_name', 'description', 'first_mes', 'mes_example',
    'creator_notes', 'personality', 'scenario', 'system_prompt', 'post_history_instructions',
    'creator', 'character_version', 'tags', 'alternate_greetings', 'character_book', 'extensions', 'filename'];
const fields = new Set([...CARD_UI_FIELDS, ...CARD_FILE_FIELDS]);
const clone = value => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
const signature = value => value && typeof value === 'object' ? JSON.stringify(value) : value;

// 草稿追踪代理必须保持「一层、且只包原始对象」。
//
// 编辑数据同时活在两个 Proxy 体系里：Alpine 的响应式代理负责渲染，这里的
// 追踪代理负责字段边界。两边若互相包裹，每次读取都会再套一层，代理链随
// 交互无限加深——详情页打开时就是在这个链条上走到 V8 爆栈（RangeError:
// Maximum call stack size exceeded），主线程被一条几十秒的长任务占死。
//
// 因此这里守三条：
// 1. trackers 以原始对象为键，同一对象永远只有一个追踪代理；
// 2. 入参是代理（Alpine 响应式或别的追踪代理）时先解包到原始对象；
// 3. 写入时也解包，代理不会作为「数据值」被存进编辑数据。
// 任何一条被破坏，层数就会重新开始累积。
const trackers = new WeakMap();   // 原始对象 -> { proxy, root }
const sources = new WeakMap();    // 追踪代理 -> 原始对象
const owners = new WeakMap();     // 原始对象 -> 当前生效的草稿上下文

const unwrap = value => {
    let current = value;
    for (let i = 0; i < 8; i += 1) {
        if (!current || typeof current !== 'object') return current;
        if (sources.has(current)) { current = sources.get(current); continue; }
        if (typeof Alpine !== 'undefined' && typeof Alpine.raw === 'function') {
            const raw = Alpine.raw(current);
            if (raw !== current) { current = raw; continue; }
        }
        return current;
    }
    return current;
};

const fieldOf = (root, key) => root || (typeof key === 'string' && key ? key : null);

const markTouched = (raw, root) => {
    if (!raw || !root || !fields.has(root)) return;
    const ctx = owners.get(raw);
    if (!ctx || ctx.muted()) return;
    ctx.mark(root);
};

const wrap = (value, root, ctx) => {
    if (!value || typeof value !== 'object') return value;
    const target = unwrap(value);
    if (!target || typeof target !== 'object') return target;
    if (ctx) owners.set(target, ctx);

    const existing = trackers.get(target);
    if (existing) {
        if (root && !existing.root) existing.root = root;
        return existing.proxy;
    }

    const entry = { proxy: null, root: root || null };
    entry.proxy = new Proxy(target, {
        get(object, key) {
            const own = trackers.get(object);
            const childRoot = fieldOf(own && own.root, key);
            return wrap(Reflect.get(object, key), childRoot, owners.get(object));
        },
        set(object, key, nextValue) {
            const next = unwrap(nextValue);
            if (Reflect.get(object, key) === next) return true;
            const own = trackers.get(object);
            Reflect.set(object, key, next);
            markTouched(object, fieldOf(own && own.root, key));
            return true;
        },
        deleteProperty(object, key) {
            const own = trackers.get(object);
            const removed = Reflect.deleteProperty(object, key);
            markTouched(object, fieldOf(own && own.root, key));
            return removed;
        },
    });
    trackers.set(target, entry);
    sources.set(entry.proxy, target);
    return entry.proxy;
};

export function createFieldDraft(source, notify = () => {}) {
    const baseline = {};
    const versions = {};
    const pending = new Set();
    const dirty = new Set();
    let muted = false;
    const ctx = {
        versions,
        muted: () => muted,
        mark: field => {
            versions[field] = (versions[field] || 0) + 1;
            pending.add(field);
            notify();
        },
    };
    const data = wrap(source, null, ctx);
    for (const field of fields) baseline[field] = clone(data[field]);
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
                if (!fields.has(field)) continue;
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
            // 从与 x-model 相同的响应式入口写回，才能让 x-for 里的条目引用一起更新。
            const editor = typeof Alpine !== 'undefined' && Alpine.reactive ? Alpine.reactive(data) : data;
            muted = true;
            try {
                const accepted = new Set([...Object.keys(snapshot.values),
                    ...Object.keys(canonical).filter(field => fields.has(field))]);
                for (const field of accepted) {
                    const value = Object.hasOwn(canonical, field) ? canonical[field] : snapshot.values[field];
                    // New input is retained; the submitted value remains the disk baseline.
                    if ((versions[field] || 0) === (snapshot.versions[field] || 0)
                        && Object.hasOwn(canonical, field)) editor[field] = clone(value);
                    baseline[field] = clone(value);
                    pending.add(field);
                }
            } finally { muted = false; }
            notify();
        },
    };
    return draft;
}
