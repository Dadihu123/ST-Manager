import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');

function readProjectFile(relativePath) {
  return readFileSync(path.join(root, relativePath), 'utf8');
}

function extractJsFunctionBlock(source, signature) {
  const start = source.indexOf(signature);
  if (start === -1) {
    throw new Error(`Missing signature: ${signature}`);
  }
  const braceStart = source.indexOf('{', start);
  let depth = 1;
  let index = braceStart + 1;
  while (depth > 0 && index < source.length) {
    const char = source[index];
    if (char === '{') depth += 1;
    if (char === '}') depth -= 1;
    index += 1;
  }
  return source.slice(start, index);
}

function createWindowStub() {
  const listeners = new Map();
  return {
    addEventListener(name, handler) {
      if (!listeners.has(name)) listeners.set(name, []);
      listeners.get(name).push(handler);
    },
    dispatchEvent(event) {
      const handlers = listeners.get(event.type) || [];
      for (const handler of handlers) {
        handler(event);
      }
      return true;
    },
  };
}

globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};

function testDetailSendSyncsGridWithoutReload() {
  const detailSource = readProjectFile('static/js/components/wiDetailPopup.js');
  const gridSource = readProjectFile('static/js/components/wiGrid.js');

  const detailInitBlock = extractJsFunctionBlock(detailSource, 'init() {');
  const gridInitBlock = extractJsFunctionBlock(gridSource, 'init() {');
  const canSendBlock = extractJsFunctionBlock(
    detailSource,
    'canSendActiveWorldInfoToST() {',
  );
  const titleBlock = extractJsFunctionBlock(
    detailSource,
    'getActiveWorldInfoSendToSTTitle() {',
  );
  const sendBlock = extractJsFunctionBlock(
    detailSource,
    'async sendActiveWorldInfoToST() {',
  );
  const applyGridSentStateBlock = extractJsFunctionBlock(
    gridSource,
    'applyWorldInfoSentState(detail) {',
  );

  const windowStub = createWindowStub();
  globalThis.window = windowStub;
  globalThis.document = {
    getElementById(id) {
      if (id !== 'wi-scroll-area') return null;
      return {
        addEventListener() {},
        removeEventListener() {},
      };
    },
  };
  const apiCalls = [];
  const sendWorldInfoToSillyTavern = async (payload) => {
    apiCalls.push(payload);
    return {
      success: true,
      last_sent_to_st: 1712345678,
    };
  };

  const toasts = [];
  const detailComponent = {
    activeWiDetail: {
      id: 'wi-1',
      type: 'global',
      path: 'books/test.json',
      name: 'Test Book',
      last_sent_to_st: 0,
    },
    isSendingWorldInfoToST: false,
    $store: {
      global: {
        showToast(message) {
          toasts.push(message);
        },
      },
    },
    $watch() {},
    loadContent() {},
    formatDate(timestamp) {
      return String(timestamp);
    },
  };

  const gridComponent = {
    wiList: [
      {
        id: 'wi-1',
        source_type: 'global',
        path: 'books/test.json',
        last_sent_to_st: 0,
      },
      {
        id: 'embedded-1',
        source_type: 'embedded',
        last_sent_to_st: 0,
      },
    ],
    $store: {
      global: {},
    },
    $watch() {},
    $nextTick(callback) {
      if (typeof callback === 'function') callback();
    },
    initMarqueeSelection() {},
    scheduleFetchWorldInfoList() {},
    syncWorldInfoUiState() {},
    syncWiWindowRange() {},
    fetchWorldInfoList() {},
    createNewWorldInfo() {},
    deleteSelectedWorldInfo() {},
    moveSelectedWorldInfo() {},
  };

  Object.assign(
    detailComponent,
    eval(`(({ ${detailInitBlock}, ${canSendBlock}, ${titleBlock}, ${sendBlock} }))`),
  );
  Object.assign(
    gridComponent,
    eval(`(({ ${gridInitBlock}, ${applyGridSentStateBlock} }))`),
  );

  detailComponent.init();
  gridComponent.init();

  assert.equal(detailComponent.canSendActiveWorldInfoToST(), true);
  assert.equal(detailComponent.getActiveWorldInfoSendToSTTitle(), '发送到 ST');

  return detailComponent.sendActiveWorldInfoToST().then(() => {
    assert.deepEqual(apiCalls, [
      {
        id: detailComponent.activeWiDetail.id,
        source_type:
          detailComponent.activeWiDetail.source_type ||
          detailComponent.activeWiDetail.type,
        file_path: detailComponent.activeWiDetail.path,
      },
    ]);
    assert.equal(detailComponent.isSendingWorldInfoToST, false);
    assert.equal(detailComponent.activeWiDetail.last_sent_to_st, 1712345678);
    assert.equal(gridComponent.wiList[0].last_sent_to_st, 1712345678);
    assert.equal(gridComponent.wiList[1].last_sent_to_st, 0);
    assert.equal(toasts.includes('已发送到 ST'), true);
  });
}

function testEmbeddedDetailCannotSendOrCallApi() {
  const detailSource = readProjectFile('static/js/components/wiDetailPopup.js');
  const canSendBlock = extractJsFunctionBlock(
    detailSource,
    'canSendActiveWorldInfoToST() {',
  );
  const sendBlock = extractJsFunctionBlock(
    detailSource,
    'async sendActiveWorldInfoToST() {',
  );

  const apiCalls = [];
  const sendWorldInfoToSillyTavern = async (payload) => {
    apiCalls.push(payload);
    return {
      success: true,
      last_sent_to_st: 1712345678,
    };
  };

  const detailComponent = {
    activeWiDetail: {
      id: 'embedded-1',
      type: 'embedded',
      source_type: 'embedded',
      path: 'cards/hero.png',
      name: 'Embedded Book',
      last_sent_to_st: 0,
    },
    isSendingWorldInfoToST: false,
    $store: {
      global: {
        showToast() {},
      },
    },
  };

  Object.assign(
    detailComponent,
    eval(`(({ ${canSendBlock}, ${sendBlock} }))`),
  );

  assert.equal(detailComponent.canSendActiveWorldInfoToST(), false);

  return detailComponent.sendActiveWorldInfoToST().then(() => {
    assert.deepEqual(apiCalls, []);
    assert.equal(detailComponent.isSendingWorldInfoToST, false);
    assert.equal(detailComponent.activeWiDetail.last_sent_to_st, 0);
  });
}

function testGridSendSyncsOpenDetailWithoutReload() {
  const detailSource = readProjectFile('static/js/components/wiDetailPopup.js');
  const gridSource = readProjectFile('static/js/components/wiGrid.js');

  const detailInitBlock = extractJsFunctionBlock(detailSource, 'init() {');
  const sendGridBlock = extractJsFunctionBlock(
    gridSource,
    'async sendWorldInfoToST(item) {',
  );
  const canSendGridBlock = extractJsFunctionBlock(
    gridSource,
    'canSendWorldInfoToST(item) {',
  );
  const isSendingGridBlock = extractJsFunctionBlock(
    gridSource,
    'isSendingWorldInfoToST(itemId) {',
  );
  const applyGridSentStateBlock = extractJsFunctionBlock(
    gridSource,
    'applyWorldInfoSentState(detail) {',
  );

  const windowStub = createWindowStub();
  globalThis.window = windowStub;
  const apiCalls = [];
  const sendWorldInfoToSillyTavern = async (payload) => {
    apiCalls.push(payload);
    return {
      success: true,
      last_sent_to_st: 1812345678,
    };
  };

  const detailComponent = {
    activeWiDetail: {
      id: 'wi-1',
      type: 'global',
      path: 'books/test.json',
      name: 'Test Book',
      last_sent_to_st: 0,
    },
    loadContentCalls: 0,
    $watch() {},
    loadContent() {
      this.loadContentCalls += 1;
    },
  };

  const toasts = [];
  const gridComponent = {
    wiList: [
      {
        id: 'wi-1',
        source_type: 'global',
        path: 'books/test.json',
        last_sent_to_st: 0,
      },
    ],
    sendingWorldInfoToStIds: {},
    $store: {
      global: {
        showToast(message) {
          toasts.push(message);
        },
      },
    },
  };

  Object.assign(detailComponent, eval(`(({ ${detailInitBlock} }))`));
  Object.assign(
    gridComponent,
    eval(
      `(({ ${canSendGridBlock}, ${isSendingGridBlock}, ${applyGridSentStateBlock}, ${sendGridBlock} }))`,
    ),
  );

  detailComponent.init();

  return gridComponent.sendWorldInfoToST(gridComponent.wiList[0]).then(() => {
    assert.deepEqual(apiCalls, [
      {
        id: 'wi-1',
        source_type: 'global',
        file_path: 'books/test.json',
      },
    ]);
    assert.equal(gridComponent.wiList[0].last_sent_to_st, 1812345678);
    assert.equal(detailComponent.activeWiDetail.last_sent_to_st, 1812345678);
    assert.equal(detailComponent.loadContentCalls, 0);
    assert.equal(toasts.includes('已发送到 ST'), true);
  });
}

async function testLoadContentHydratesLastSentToStFromDetailResponse() {
  const detailSource = readProjectFile('static/js/components/wiDetailPopup.js');
  const loadContentBlock = extractJsFunctionBlock(
    detailSource,
    'async loadContent(targetId) {',
  );

  const getWorldInfoDetail = async () => ({
    success: true,
    data: {
      entries: [{ key: ['hello'], content: 'world' }],
      description: 'Lore description',
    },
    source_revision: 'rev-2',
    ui_summary: 'summary from server',
    last_sent_to_st: 1912345678,
    truncated: false,
    truncated_content: false,
  });
  const getCardDetail = async () => {
    throw new Error('embedded branch should not run');
  };
  const normalizeWiBook = (rawData, name) => ({
    name,
    description: rawData.description,
    entries: rawData.entries,
  });

  const detailComponent = {
    activeWiDetail: {
      id: 'wi-2',
      type: 'global',
      path: 'books/second.json',
      name: 'Second Book',
      ui_summary: '',
      last_sent_to_st: 0,
    },
    loadRequestToken: 0,
    isLoading: false,
    description: '',
    activeWiNoteDraft: '',
    isTruncated: false,
    totalEntries: 0,
    previewLimit: 0,
    isContentTruncated: false,
    previewContentLimit: 0,
    wiData: null,
    wiEntries: [],
    searchMatchedEntryIds: null,
    resetEntryRenderLimits() {},
    runDetailSearch() {
      return Promise.resolve();
    },
    _applyPreviewLimits(data) {
      return { data, truncated: false, totalEntries: 0, previewLimit: 0, truncatedContent: false, previewContentLimit: 0 };
    },
  };

  Object.assign(detailComponent, eval(`(({ ${loadContentBlock} }))`));

  await detailComponent.loadContent();

  assert.equal(detailComponent.activeWiDetail.source_revision, 'rev-2');
  assert.equal(detailComponent.activeWiDetail.ui_summary, 'summary from server');
  assert.equal(detailComponent.activeWiDetail.last_sent_to_st, 1912345678);
  assert.equal(detailComponent.activeWiNoteDraft, 'summary from server');
  assert.equal(detailComponent.description, 'Lore description');
  assert.equal(detailComponent.wiEntries.length, 1);
}

await testDetailSendSyncsGridWithoutReload();
await testEmbeddedDetailCannotSendOrCallApi();
await testGridSendSyncsOpenDetailWithoutReload();
await testLoadContentHydratesLastSentToStFromDetailResponse();

console.log('worldinfo_send_to_st_runtime_test: ok');
