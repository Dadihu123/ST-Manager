import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const apiSource = readFileSync(new URL('../static/js/api/chat.js', import.meta.url), 'utf8');
const { listChats } = await import(`data:text/javascript;base64,${Buffer.from(apiSource).toString('base64')}`);
const source = readFileSync(new URL('../static/js/components/chatGrid.js', import.meta.url), 'utf8');
const method = source.slice(source.indexOf('    fetchChats() {'), source.indexOf('    changeChatPage(page) {'));
const component = Function('listChats', `return ({${method}})`)(listChats);
const requests = [];
globalThis.fetch = (url, options) => new Promise((resolve, reject) => {
    requests.push({ url, options, resolve: data => resolve({ json: async () => data }), reject });
});
component.$store = { global: { serverStatus: { status: 'ready' }, settingsForm: {}, isLoading: false } };
component.chatCurrentPage = 1;
const first = component.fetchChats();
component.chatCurrentPage = 2;
component.chatSearchQuery = 'latest';
const second = component.fetchChats();
assert.equal(requests[0].options.signal.aborted, true);
assert.match(requests[1].url, /page=2/);
assert.match(requests[1].url, /search=latest/);
requests[0].resolve({ success: true, items: [{ id: 'old' }], total: 1, page_size: 20 });
await first;
assert.equal(component.$store.global.isLoading, true, 'old completion cannot stop the new spinner');
assert.equal(component.chatList, undefined, 'old response cannot populate another page');
requests[1].resolve({ success: true, items: [{ id: 'new' }], total: 22, page_size: 20 });
await second;
assert.equal(component.chatList[0].id, 'new');
assert.equal(component.chatTotalPages, 2);
assert.equal(component.$store.global.isLoading, false);
const third = component.fetchChats();
const fourth = component.fetchChats();
requests[2].reject(new DOMException('aborted', 'AbortError'));
await third;
assert.equal(component.$store.global.isLoading, true);
requests[3].resolve({ success: true, items: [], total: 0, page_size: 20 });
await fourth;
assert.equal(component.$store.global.isLoading, false);
console.log('chat request ordering, cancellation and loading ownership passed');

// Real snapshot scheduler: the baseline must represent the submitted snapshot while
// input typed during the request remains eligible for the next snapshot.
const systemStub = 'export const smartAutoSnapshot = payload => globalThis.__snapshot(payload);';
const systemUrl = `data:text/javascript;base64,${Buffer.from(systemStub).toString('base64')}`;
const autoSaveSource = readFileSync(new URL('../static/js/utils/autoSave.js', import.meta.url), 'utf8')
    .replace('"../api/system.js"', JSON.stringify(systemUrl));
const { createAutoSaver } = await import(`data:text/javascript;base64,${Buffer.from(autoSaveSource).toString('base64')}`);
let tick;
globalThis.setInterval = callback => { tick = callback; return 1; };
globalThis.clearInterval = () => {};
globalThis.Alpine = { store: () => ({ settingsForm: { auto_save_enabled: true }, showToast() {} }) };
let finishSnapshot;
globalThis.__snapshot = () => new Promise(resolve => { finishSnapshot = resolve; });
const saver = createAutoSaver();
const data = { description: 'disk', ui_summary: 'note', resource_folder: 'old' };
saver.initBaseline(data);
saver.start(() => data, () => ({ content: data.description }));
data.description = 'submitted';
const snapshot = tick();
data.description = 'new input';
finishSnapshot({ success: true, status: 'created' });
await snapshot;
assert.equal(JSON.parse(saver.originalJson).description, 'submitted');
data.resource_folder = 'persisted';
saver.rebaseBaseline(data, ['resource_folder']);
assert.equal(JSON.parse(saver.originalJson).resource_folder, 'persisted');
assert.equal(JSON.parse(saver.originalJson).description, 'submitted', 'rebase cannot absorb newer unsaved input');
saver.stop();
console.log('snapshot request baseline and direct persistence rebase passed');
