import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { File } from "node:buffer";

const moduleUrl = (relative) => `data:text/javascript;base64,${Buffer.from(readFileSync(new URL(relative, import.meta.url), "utf8")).toString("base64")}`;
const apiUrl = moduleUrl("../static/js/api/wi.js");
const diffUrl = moduleUrl("../static/js/utils/worldbookDiff.js");
const componentSource = readFileSync(new URL("../static/js/components/worldbookUpdate.js", import.meta.url), "utf8").replace('"../api/wi.js"', JSON.stringify(apiUrl)).replace('"../utils/worldbookDiff.js"', JSON.stringify(diffUrl));
const { default: worldbookUpdate } = await import(`data:text/javascript;base64,${Buffer.from(componentSource).toString("base64")}`);
const { readableWorldbook } = await import(diffUrl);

const listeners = new Map();
const events = [];
globalThis.window = {
  addEventListener(name, callback) { listeners.set(name, callback); },
  dispatchEvent(event) { events.push(event); listeners.get(event.type)?.(event); },
};
globalThis.CustomEvent = class {
  constructor(type, options) { this.type = type; this.detail = options?.detail; }
};
globalThis.document = { activeElement: { focus() {} } };
const calls = [];
const replies = [];
globalThis.fetch = async (url, options) => {
  calls.push({ url, options });
  return { json: async () => replies.shift() };
};
const app = worldbookUpdate();
app.$refs = { close: { focus() {} } };
app.$nextTick = async (callback) => callback?.();
app.$store = { global: { showToast() {} } };
app.renderDiff = async () => { app.previewReady = true; };
app.init();
const open = (type = "global") => window.dispatchEvent(new CustomEvent("open-worldbook-update", { detail: { type, name: "目标", path: "data/lorebooks/target.json" } }));

open("embedded");
assert.equal(app.show, false, "Embedded must never enter the independent update flow");
open();
await app.preview();
assert.match(app.error, /请选择/);
assert.equal(calls.length, 0);

const sourceText = '{"entries":{"0":{"key":["测试"],"content":"完整正文","custom":900719925474099312345}}}';
app.source = "url";
app.url = "https://example.test/raw";
replies.push({ success: true, current_text: '{"entries":{}}', source_text: sourceText, source_revision: "hash-before" });
await app.preview();
assert.equal(app.step, "preview");
assert.equal(app.sourceText, sourceText);
assert.deepEqual(JSON.parse(calls[0].options.body), { file_path: "data/lorebooks/target.json", source_type: "global", url: app.url });
assert.match(readableWorldbook(sourceText), /完整正文/);

replies.push({ success: false, code: "source_changed", msg: "源文件已改变" });
await app.commit();
assert.equal(app.stale, true);
assert.equal(app.show, true);
assert.equal(JSON.parse(calls[1].options.body).source_text, sourceText, "Never serialize parsed JSON when committing large integer or unknown fields");
await app.commit();
assert.equal(calls.length, 2, "Stale preview cannot be committed again");
replies.push({ success: true, current_text: '{"entries":{"1":{"content":"新本地内容"}}}', source_text: sourceText, source_revision: "hash-after" });
await app.preview(true);
assert.equal(app.stale, false);
assert.equal(app.revision, "hash-after");
assert.equal(JSON.parse(calls[2].options.body).source_text, sourceText);
assert.equal(JSON.parse(calls[2].options.body).url, undefined, "Recompare retained bytes, without redownloading a changed remote URL");

replies.push({ success: true, backup_path: "backup.json" });
await app.commit();
assert.equal(app.show, false);
assert.equal(JSON.parse(calls[3].options.body).source_revision, "hash-after");
assert.ok(events.some((event) => event.type === "wi-content-updated"));
assert.ok(events.some((event) => event.type === "refresh-wi-list"));

open("resource");
app.file = new File([sourceText], "incoming.json", { type: "application/json" });
replies.push({ success: true, current_text: '{"entries":{}}', source_text: sourceText, source_revision: "resource-hash" });
await app.preview();
assert.ok(calls[4].options.body instanceof FormData);
assert.equal(calls[4].options.body.get("source_type"), "resource");
assert.equal(calls[4].options.headers, undefined, "Browser chooses the multipart boundary");
const count = calls.length;
app.busy = true;
app.close();
await app.commit();
assert.equal(app.show, true);
assert.equal(calls.length, count);
app.busy = false;
app.close();
assert.equal(calls.length, count, "Cancel is a local operation");
assert.equal(app.sourceText, "");

open();
app.step = "preview";
app.previewReady = false;
await app.commit();
assert.equal(calls.length, count, "Diff loading failure cannot enable replacement");
console.log("Worldbook update runtime checks passed: URL/file, source identity, raw integer preservation, stale recompare, cancellation and busy guards.");
