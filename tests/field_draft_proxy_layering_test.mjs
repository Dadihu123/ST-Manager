import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../static/js/utils/fieldDraft.js', import.meta.url), 'utf8');
const { createFieldDraft } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

// 用最小的 Alpine 替身：同样的缓存语义 + 读取时递归包代理 + Alpine.raw 解包。
// 详情页真正的组合就是「草稿追踪代理」和「Alpine 响应式代理」互相读取，
// 这里把那一层关系固定下来，防止追踪代理再次套娃。
const cache = new WeakMap();
const rawOfProxy = new WeakMap();
const reactive = value => {
    if (!value || typeof value !== 'object') return value;
    if (cache.has(value)) return cache.get(value);
    const proxy = new Proxy(value, {
        get(target, key) {
            return reactive(Reflect.get(target, key, proxy));
        },
        set(target, key, next) {
            return Reflect.set(target, key, next, proxy);
        },
    });
    cache.set(value, proxy);
    rawOfProxy.set(proxy, value);
    return proxy;
};
globalThis.Alpine = { raw: value => (value && rawOfProxy.get(value)) || value };

const makeCard = () => reactive({
    description: 'hello',
    tags: ['a'],
    alternate_greetings: ['greet'],
    extensions: { regex_scripts: [] },
    character_book: { entries: [{ content: 'lore' }] },
});

// 1. 反复把响应式代理写回数据：旧实现每轮都多套一层代理，读取最终爆栈。
{
    const draft = createFieldDraft(makeCard());
    for (let i = 0; i < 400; i += 1) {
        draft.data.character_book = reactive({ entries: [{ content: `lore-${i}` }] });
        assert.equal(draft.data.character_book.entries[0].content, `lore-${i}`);
    }
    assert.equal(draft.dirtyFields().includes('character_book'), true, '深层写入必须记脏');
}

// 2. 同一个原始对象只有一个追踪代理；反复读同一个嵌套字段身份稳定。
{
    const card = makeCard();
    const first = createFieldDraft(card);
    const firstBook = first.data.character_book;
    for (let i = 0; i < 200; i += 1) {
        assert.equal(first.data.character_book, firstBook, '追踪代理必须复用同一实例');
    }
    const second = createFieldDraft(card);
    assert.equal(second.data, first.data, '同一对象只能有一个追踪代理');
}

// 3. 代理不会被当成数据值存进去：写进去的响应式对象仍是同一个底层对象。
{
    const draft = createFieldDraft(makeCard());
    const extensions = reactive({ regex_scripts: [] });
    draft.data.extensions = extensions;
    extensions.regex_scripts.push({ id: 'r1' });
    assert.equal(draft.data.extensions.regex_scripts.length, 1, '写入代理必须解包为原始对象');
}

// 4. 字段边界语义不变：顶层、深层、数组就地修改都要记脏，改回原值要洗白。
{
    const draft = createFieldDraft(makeCard());
    assert.deepEqual(draft.dirtyFields(), []);
    draft.data.description = 'hello X';
    assert.deepEqual(draft.dirtyFields(), ['description']);
    draft.data.description = 'hello';
    assert.deepEqual(draft.dirtyFields(), []);
    draft.data.character_book.entries[0].content = 'lore Y';
    assert.deepEqual(draft.dirtyFields(), ['character_book']);
    draft.data.character_book.entries[0].content = 'lore';
    assert.deepEqual(draft.dirtyFields(), []);
    draft.data.tags.push('b');
    assert.deepEqual(draft.dirtyFields(), ['tags']);
    draft.data.tags.pop();
    assert.deepEqual(draft.dirtyFields(), []);
}

// 5. versions 仍然按字段累加，供 refresh/capture/accept 比较用。
{
    const draft = createFieldDraft(makeCard());
    draft.data.description = 'one';
    draft.data.description = 'two';
    assert.equal(draft.versions.description, 2);
    assert.equal(draft.versions.tags, undefined);
}

console.log('field_draft_proxy_layering_test: ok');
