/**
 * static/js/components/rollbackModal.js
 * 时光机组件：版本回滚与差异对比
 */

import { 
    listBackups, 
    restoreBackup, 
    readFileContent, 
    normalizeCardData, 
    openPath 
} from '../api/system.js';

import { getCardMetadata } from '../api/card.js';
import { generateSideBySideDiff } from '../utils/diff.js';
import { getCleanedV3Data, toStV3Worldbook } from '../utils/data.js';

export default function rollbackModal() {
    return {
        // === 本地状态 ===
        showRollbackModal: false,
        isLoading: false,
        isDiffLoading: false,
        
        backupList: [],           // 历史备份列表
        rollbackVersions: [],     // 包含 Current 的完整列表
        
        // 目标信息
        rollbackTargetType: '',   // 'card' | 'lorebook'
        rollbackTargetId: '',
        rollbackTargetPath: '',
        rollbackLiveContent: null, // 当前编辑器中的实时内容
        rollbackEmbeddedWiContext: false,
        diffRenderMode: 'raw',     // 'raw' | 'wi_entries'
        
        // Diff 状态
        diffSelection: { left: null, right: null },
        diffData: { left: '', right: '', currentObj: null },

        init() {
            // 监听打开事件 (由 detailModal 或 wiEditor 触发)
            window.addEventListener('open-rollback', (e) => {
                const { type, id, path, editingData, editingWiFile } = e.detail;
                this.openRollback(type, id, path, editingData, editingWiFile);
            });
        },

        // === 打开时光机 ===
        openRollback(type, targetId, targetPath, editingData, editingWiFile) {
            this.rollbackTargetType = type;
            this.rollbackTargetId = targetId;
            this.rollbackTargetPath = targetPath;
            this.rollbackLiveContent = null;
            this.rollbackEmbeddedWiContext = !!(editingWiFile && editingWiFile.type === 'embedded');
            this.diffRenderMode = (type === 'lorebook' || this.rollbackEmbeddedWiContext) ? 'wi_entries' : 'raw';

            // 1. 捕获实时内容 (Live Content)
            if (type === 'card') {
                // 内嵌世界书上下文：只比较世界书
                if (this.rollbackEmbeddedWiContext && editingData && editingData.character_book) {
                    const name = editingData.character_book.name || "World Info";
                    this.rollbackLiveContent = toStV3Worldbook(editingData.character_book, name);
                } else if (editingData && editingData.id === targetId) {
                    // 如果传入了 editingData 且 ID 匹配，说明正在编辑
                    this.rollbackLiveContent = getCleanedV3Data(editingData);
                }
            } else if (type === 'lorebook') {
                // 如果正在编辑该世界书
                let isEditingThis = false;
                if (editingWiFile) {
                    if (editingWiFile.id === targetId) isEditingThis = true;
                }
                
                if (isEditingThis && editingData && editingData.character_book) {
                    const name = editingData.character_book.name || "World Info";
                    this.rollbackLiveContent = toStV3Worldbook(editingData.character_book, name);
                }
            }

            this.isLoading = true;
            listBackups({ id: targetId, type: type, file_path: targetPath })
                .then(async (res) => {
                    if (res.success) {
                        // 构造版本列表
                        const currentVer = {
                            filename: "Current (当前编辑器版本)",
                            path: null, // null 表示需要读取 Live 或 Disk Current
                            mtime: new Date().getTime() / 1000,
                            size: 0,
                            is_current: true,
                            label: "LIVE"
                        };

                        const pruneResult = await this._pruneBackupsRepresentedByCurrent(currentVer, res.backups || []);
                        this.backupList = pruneResult.backups;
                        this.rollbackVersions = [currentVer, ...this.backupList];
                        
                        // 默认选中：左=最近备份，右=当前
                        this.diffSelection = {
                            left: this.backupList.length > 0 ? this.backupList[0] : null,
                            right: currentVer
                        };
                        
                        this.showRollbackModal = true;

                        if (pruneResult.hidden > 0 && this.$store?.global?.showToast) {
                            this.$store.global.showToast(`已折叠 ${pruneResult.hidden} 个与 Current 重合的最新快照`, 2000);
                        }
                        
                        // 立即加载 Diff
                        this.updateDiffView();
                    } else {
                        alert(res.msg);
                    }
                })
                .catch(err => {
                    alert("加载备份失败: " + err);
                })
                .finally(() => {
                    this.isLoading = false;
                });
        },

        // === Diff 逻辑 ===

        setDiffSide(side, version) {
            this.diffSelection[side] = version;
            // 手动切换时不自动跳转，尊重用户选择
            this.updateDiffView(false);
        },

        _isLorebookComparison() {
            return this.rollbackTargetType === 'lorebook' || this.rollbackEmbeddedWiContext;
        },

        _escapeHtml(text) {
            return String(text ?? '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        },

        _stableStringify(value) {
            if (Array.isArray(value)) {
                return `[${value.map(v => this._stableStringify(v)).join(',')}]`;
            }
            if (value && typeof value === 'object') {
                const keys = Object.keys(value).sort();
                return `{${keys.map(k => `${JSON.stringify(k)}:${this._stableStringify(value[k])}`).join(',')}}`;
            }
            return JSON.stringify(value);
        },

        _toArray(val) {
            if (Array.isArray(val)) {
                return val.map(v => String(v ?? '').trim()).filter(Boolean);
            }
            if (typeof val === 'string') {
                return val.split(',').map(s => s.trim()).filter(Boolean);
            }
            return [];
        },

        _extractLorebookEntries(raw) {
            if (!raw) return [];

            let book = raw;
            if (raw?.data?.character_book) {
                book = raw.data.character_book;
            } else if (raw?.character_book) {
                book = raw.character_book;
            }

            if (Array.isArray(book)) {
                return book.filter(e => e && typeof e === 'object');
            }

            if (book && typeof book === 'object') {
                const entries = book.entries;
                if (Array.isArray(entries)) return entries.filter(e => e && typeof e === 'object');
                if (entries && typeof entries === 'object') {
                    return Object.values(entries).filter(e => e && typeof e === 'object');
                }
            }
            return [];
        },

        _normalizeLorebookEntry(entry, index) {
            const raw = entry || {};
            const keys = this._toArray(raw.keys ?? raw.key);
            const secondaryKeys = this._toArray(raw.secondary_keys ?? raw.keysecondary);
            const comment = String(raw.comment ?? '').trim();
            const content = String(raw.content ?? '');
            const uid = String(raw.st_manager_uid ?? '').trim();
            const legacyUid = String(raw.uid ?? '').trim();

            const compareObj = { ...raw };
            delete compareObj.id;
            delete compareObj.uid;
            delete compareObj.displayIndex;
            delete compareObj.st_manager_uid;

            const keySig = keys.map(k => k.toLowerCase()).sort().join('|');
            const secSig = secondaryKeys.map(k => k.toLowerCase()).sort().join('|');
            const quickSig = `${comment.toLowerCase()}|${keySig}|${secSig}`;
            const stableSig = this._stableStringify(compareObj);

            return {
                raw,
                index,
                uid,
                legacyUid,
                comment,
                content,
                keys,
                secondaryKeys,
                compareObj,
                quickSig,
                stableSig,
                title: comment || `(无备注 #${index + 1})`
            };
        },

        _buildLorebookPairs(leftEntries, rightEntries) {
            const left = leftEntries.map((e, i) => this._normalizeLorebookEntry(e, i));
            const right = rightEntries.map((e, i) => this._normalizeLorebookEntry(e, i));

            const rightUsed = new Set();
            const rightUidMap = new Map();
            const rightLegacyUidMap = new Map();
            const rightStableMap = new Map();
            const rightQuickMap = new Map();

            const pushMap = (map, key, idx) => {
                if (!key) return;
                if (!map.has(key)) map.set(key, []);
                map.get(key).push(idx);
            };

            right.forEach((item, idx) => {
                pushMap(rightUidMap, item.uid, idx);
                pushMap(rightLegacyUidMap, item.legacyUid, idx);
                pushMap(rightStableMap, item.stableSig, idx);
                pushMap(rightQuickMap, item.quickSig, idx);
            });

            const pickUnique = (map, key) => {
                const arr = map.get(key);
                if (!arr || arr.length !== 1) return -1;
                const idx = arr[0];
                if (rightUsed.has(idx)) return -1;
                return idx;
            };

            const pairs = [];
            left.forEach((item) => {
                let rightIdx = -1;
                if (item.uid) rightIdx = pickUnique(rightUidMap, item.uid);
                if (rightIdx < 0 && item.legacyUid) rightIdx = pickUnique(rightLegacyUidMap, item.legacyUid);
                if (rightIdx < 0) rightIdx = pickUnique(rightStableMap, item.stableSig);
                if (rightIdx < 0) rightIdx = pickUnique(rightQuickMap, item.quickSig);

                if (rightIdx >= 0) {
                    rightUsed.add(rightIdx);
                    pairs.push({ left: item, right: right[rightIdx] });
                } else {
                    pairs.push({ left: item, right: null, _needsFallback: true });
                }
            });

            // 二次兜底：当 UID/签名无法匹配（常见于旧版本无 UID，且条目内容变化较大），
            // 按剩余顺序配对，避免“修改被误判为删除+新增”造成可读性差和“条目丢失”错觉。
            const fallbackLeftPairs = pairs.filter(p => p._needsFallback);
            const unmatchedRight = [];
            right.forEach((item, idx) => {
                if (!rightUsed.has(idx)) unmatchedRight.push(item);
            });

            const fallbackCount = Math.min(fallbackLeftPairs.length, unmatchedRight.length);
            for (let i = 0; i < fallbackCount; i++) {
                fallbackLeftPairs[i].right = unmatchedRight[i];
                delete fallbackLeftPairs[i]._needsFallback;
            }
            for (let i = fallbackCount; i < fallbackLeftPairs.length; i++) {
                delete fallbackLeftPairs[i]._needsFallback;
            }
            for (let i = fallbackCount; i < unmatchedRight.length; i++) {
                pairs.push({ left: null, right: unmatchedRight[i] });
            }

            // 清理临时标记
            pairs.forEach((p) => {
                if (p._needsFallback) {
                    delete p._needsFallback;
                }
            });

            return pairs;
        },

        _getPairMeta(pair) {
            if (pair.left && pair.right) {
                const leftStr = this._stableStringify(pair.left.compareObj);
                const rightStr = this._stableStringify(pair.right.compareObj);
                const isSame = leftStr === rightStr;
                return {
                    status: isSame ? 'same' : 'changed',
                    changed: {
                        comment: pair.left.comment !== pair.right.comment,
                        keys: pair.left.keys.join('|') !== pair.right.keys.join('|') ||
                            pair.left.secondaryKeys.join('|') !== pair.right.secondaryKeys.join('|'),
                        content: pair.left.content !== pair.right.content
                    }
                };
            }
            if (pair.left && !pair.right) {
                return { status: 'removed', changed: { comment: true, keys: true, content: true } };
            }
            return { status: 'added', changed: { comment: true, keys: true, content: true } };
        },

        _previewContent(text, maxLen = 800) {
            const raw = String(text ?? '');
            if (raw.length <= maxLen) return raw;
            return `${raw.slice(0, maxLen)}\n...(已省略 ${raw.length - maxLen} 字)`;
        },

        _splitLinesWithLimit(text, maxLines = 240, maxChars = 16000) {
            const raw = String(text ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
            let limited = raw;
            let truncatedByChars = false;
            if (limited.length > maxChars) {
                limited = limited.slice(0, maxChars);
                truncatedByChars = true;
            }
            let lines = limited.split('\n');
            let truncatedByLines = false;
            if (lines.length > maxLines) {
                lines = lines.slice(0, maxLines);
                truncatedByLines = true;
            }
            if (truncatedByChars || truncatedByLines) {
                lines.push(`...(内容过长，已截断显示)`);
            }
            return lines;
        },

        _buildLineOps(leftLines, rightLines, maxCells = 70000) {
            const n = leftLines.length;
            const m = rightLines.length;

            // 兜底：内容过大时使用按索引近似对齐，避免 O(n*m) 过重
            if (n * m > maxCells) {
                const approx = [];
                const len = Math.max(n, m);
                for (let i = 0; i < len; i++) {
                    const l = i < n ? leftLines[i] : null;
                    const r = i < m ? rightLines[i] : null;
                    if (l !== null && r !== null) {
                        approx.push({ t: l === r ? 'same' : 'changed', left: l, right: r });
                    } else if (l !== null) {
                        approx.push({ t: 'removed', left: l, right: null });
                    } else {
                        approx.push({ t: 'added', left: null, right: r });
                    }
                }
                return approx;
            }

            const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
            for (let i = n - 1; i >= 0; i--) {
                for (let j = m - 1; j >= 0; j--) {
                    if (leftLines[i] === rightLines[j]) {
                        dp[i][j] = dp[i + 1][j + 1] + 1;
                    } else {
                        dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
                    }
                }
            }

            const rawOps = [];
            let i = 0;
            let j = 0;
            while (i < n && j < m) {
                if (leftLines[i] === rightLines[j]) {
                    rawOps.push({ t: 'same', text: leftLines[i] });
                    i += 1;
                    j += 1;
                } else if (dp[i + 1][j] >= dp[i][j + 1]) {
                    rawOps.push({ t: 'remove', text: leftLines[i] });
                    i += 1;
                } else {
                    rawOps.push({ t: 'add', text: rightLines[j] });
                    j += 1;
                }
            }
            while (i < n) {
                rawOps.push({ t: 'remove', text: leftLines[i] });
                i += 1;
            }
            while (j < m) {
                rawOps.push({ t: 'add', text: rightLines[j] });
                j += 1;
            }

            // 将连续 add/remove 片段折叠为 changed / added / removed 行
            const aligned = [];
            let k = 0;
            while (k < rawOps.length) {
                const op = rawOps[k];
                if (op.t === 'same') {
                    aligned.push({ t: 'same', left: op.text, right: op.text });
                    k += 1;
                    continue;
                }

                const removes = [];
                const adds = [];
                while (k < rawOps.length && rawOps[k].t !== 'same') {
                    if (rawOps[k].t === 'remove') removes.push(rawOps[k].text);
                    if (rawOps[k].t === 'add') adds.push(rawOps[k].text);
                    k += 1;
                }

                const pairCount = Math.min(removes.length, adds.length);
                for (let x = 0; x < pairCount; x++) {
                    aligned.push({ t: 'changed', left: removes[x], right: adds[x] });
                }
                for (let x = pairCount; x < removes.length; x++) {
                    aligned.push({ t: 'removed', left: removes[x], right: null });
                }
                for (let x = pairCount; x < adds.length; x++) {
                    aligned.push({ t: 'added', left: null, right: adds[x] });
                }
            }

            return aligned;
        },

        _lineClassByType(type, side) {
            if (type === 'changed') return 'bg-yellow-500/20 border border-yellow-500/40';
            if (type === 'added' && side === 'right') return 'bg-green-500/20 border border-green-500/40';
            if (type === 'removed' && side === 'left') return 'bg-red-500/20 border border-red-500/40';
            if (type === 'added' && side === 'left') return 'bg-green-500/10 border border-green-500/30';
            if (type === 'removed' && side === 'right') return 'bg-red-500/10 border border-red-500/30';
            return 'bg-black/10 border border-transparent';
        },

        _renderLineDiffHtml(leftText, rightText, side) {
            const leftLines = this._splitLinesWithLimit(leftText);
            const rightLines = this._splitLinesWithLimit(rightText);
            const rows = this._buildLineOps(leftLines, rightLines);

            let leftNo = 0;
            let rightNo = 0;
            let html = '';
            rows.forEach((row) => {
                const isLeft = side === 'left';
                const text = isLeft ? row.left : row.right;
                const cls = this._lineClassByType(row.t, side);

                if (row.left !== null) leftNo += 1;
                if (row.right !== null) rightNo += 1;
                const lineNo = isLeft ? (row.left !== null ? leftNo : '') : (row.right !== null ? rightNo : '');
                const lineText = text === null ? '∅' : this._escapeHtml(text);
                const lineTextClass = text === null ? 'text-[var(--text-dim)] italic' : 'text-[var(--text-main)]';

                html += `
                    <div class="px-2 py-0.5 rounded ${cls}">
                        <span class="inline-block w-8 mr-2 text-[10px] text-[var(--text-dim)] text-right select-none">${lineNo || ' '}</span>
                        <span class="text-[11px] whitespace-pre-wrap break-words ${lineTextClass}">${lineText || ' '}</span>
                    </div>
                `;
            });
            return html;
        },

        _fieldDiffClass(meta, side, fieldChanged) {
            const isLeft = side === 'left';
            const isRight = side === 'right';

            // 整条新增：右侧字段全部绿底
            if (meta.status === 'added' && isRight) {
                return 'bg-green-500/20 border border-green-500/40';
            }
            // 整条删除：左侧字段全部红底
            if (meta.status === 'removed' && isLeft) {
                return 'bg-red-500/20 border border-red-500/40';
            }
            // 双侧都存在时，仅变化字段黄底
            if (meta.status === 'changed' && fieldChanged) {
                return 'bg-yellow-500/20 border border-yellow-500/40';
            }
            return 'bg-black/10 border border-transparent';
        },

        _renderLorebookEntry(entry, oppositeEntry, meta, side, orderNo) {
            if (!entry) {
                return `
                    <div class="m-2 p-3 rounded border border-dashed border-[var(--border-light)] text-[11px] text-[var(--text-dim)] opacity-70">
                        <div>（此侧无对应条目）</div>
                    </div>
                `;
            }

            const isLeft = side === 'left';
            const markClass = (isLeft && (meta.status === 'removed' || meta.status === 'changed'))
                ? 'text-red-300'
                : ((!isLeft && (meta.status === 'added' || meta.status === 'changed')) ? 'text-green-300' : 'text-[var(--text-main)]');
            const comment = this._escapeHtml(entry.title);
            const keys = this._escapeHtml(entry.keys.join(', ') || '(空)');
            const sec = this._escapeHtml(entry.secondaryKeys.join(', ') || '(空)');
            const idx = entry.index + 1;

            const commentCls = meta.changed.comment ? markClass : 'text-[var(--text-main)]';
            const keyCls = meta.changed.keys ? markClass : 'text-[var(--text-main)]';
            const contentCls = meta.changed.content ? markClass : 'text-[var(--text-main)]';

            const commentBgCls = this._fieldDiffClass(meta, side, meta.changed.comment);
            const keysBgCls = this._fieldDiffClass(meta, side, meta.changed.keys);
            const leftContent = side === 'left' ? (entry.content || '') : (oppositeEntry?.content || '');
            const rightContent = side === 'right' ? (entry.content || '') : (oppositeEntry?.content || '');
            const lineDiffHtml = this._renderLineDiffHtml(leftContent, rightContent, side);

            return `
                <div class="m-2 p-3 rounded border bg-[var(--bg-sub)] border-[var(--border-light)]">
                    <div class="text-[10px] uppercase tracking-wide text-[var(--text-dim)]">Entry ${orderNo} · Source #${idx}</div>
                    <div class="mt-1 p-1.5 rounded ${commentBgCls}">
                        <div class="text-sm font-bold ${commentCls}">${comment}</div>
                    </div>
                    <div class="mt-2 p-1.5 rounded ${keysBgCls}">
                        <div class="text-[11px] ${keyCls}">关键词: ${keys}</div>
                        <div class="mt-1 text-[11px] ${keyCls}">次级词: ${sec}</div>
                    </div>
                    <div class="mt-2 p-1.5 rounded bg-black/5 border border-[var(--border-light)]">
                        <div class="text-[11px] text-[var(--text-dim)]">内容预览</div>
                        <div class="mt-1 p-2 rounded bg-black/10 max-h-56 overflow-auto">${lineDiffHtml}</div>
                        <div class="mt-1 text-[10px] ${contentCls}">行级高亮：绿=新增，黄=修改，红=删除</div>
                    </div>
                </div>
            `;
        },

        _renderLorebookDiff(leftData, rightData) {
            const leftEntries = this._extractLorebookEntries(leftData);
            const rightEntries = this._extractLorebookEntries(rightData);
            const pairs = this._buildLorebookPairs(leftEntries, rightEntries);
            const withMeta = pairs.map(pair => ({ pair, meta: this._getPairMeta(pair) }));

            const changed = withMeta.filter(x => x.meta.status !== 'same');
            const hiddenCount = withMeta.length - changed.length;
            const displayList = changed.length > 0 ? changed : withMeta.slice(0, 20);

            const counts = { added: 0, removed: 0, changed: 0, same: 0 };
            withMeta.forEach(x => { counts[x.meta.status] += 1; });

            const summary = `
                <div class="sticky top-0 z-10 px-3 py-2 border-b border-[var(--border-light)] bg-[var(--bg-panel)] text-[11px]">
                    <span class="text-green-400 mr-3">新增 ${counts.added}</span>
                    <span class="text-red-400 mr-3">删除 ${counts.removed}</span>
                    <span class="text-orange-400 mr-3">修改 ${counts.changed}</span>
                    <span class="text-[var(--text-dim)]">未变化 ${counts.same}</span>
                    <span class="ml-3 text-[var(--text-dim)]">行级底色: <span class="text-green-400">绿=新增</span> / <span class="text-yellow-300">黄=修改</span> / <span class="text-red-400">红=删除</span></span>
                    ${hiddenCount > 0 ? `<span class="ml-3 text-[var(--text-dim)]">（已隐藏 ${hiddenCount} 条未变化）</span>` : ''}
                </div>
            `;

            let leftHtml = summary;
            let rightHtml = summary;
            displayList.forEach((item, idx) => {
                leftHtml += this._renderLorebookEntry(item.pair.left, item.pair.right, item.meta, 'left', idx + 1);
                rightHtml += this._renderLorebookEntry(item.pair.right, item.pair.left, item.meta, 'right', idx + 1);
            });

            if (displayList.length === 0) {
                leftHtml += '<div class="p-6 text-center text-[var(--text-dim)] text-xs">无可展示条目</div>';
                rightHtml += '<div class="p-6 text-center text-[var(--text-dim)] text-xs">无可展示条目</div>';
            }

            return { left: leftHtml, right: rightHtml };
        },

        _isDataEqual(a, b) {
            try {
                return this._stableStringify(a) === this._stableStringify(b);
            } catch (e) {
                try {
                    return JSON.stringify(a) === JSON.stringify(b);
                } catch {
                    return false;
                }
            }
        },

        _hasLorebookDiff(leftData, rightData) {
            const leftEntries = this._extractLorebookEntries(leftData);
            const rightEntries = this._extractLorebookEntries(rightData);
            const pairs = this._buildLorebookPairs(leftEntries, rightEntries);
            if (!pairs.length) return false;
            for (const pair of pairs) {
                const meta = this._getPairMeta(pair);
                if (meta.status !== 'same') return true;
            }
            return false;
        },

        _hasLorebookVisibleDiff(leftData, rightData) {
            const leftEntries = this._extractLorebookEntries(leftData);
            const rightEntries = this._extractLorebookEntries(rightData);
            const pairs = this._buildLorebookPairs(leftEntries, rightEntries);
            if (!pairs.length) return false;

            for (const pair of pairs) {
                // 一侧有一侧无：可视上一定是新增/删除
                if (!pair.left || !pair.right) return true;

                // 按当前 UI 真正展示的字段判定可视差异
                if (pair.left.comment !== pair.right.comment) return true;
                if (pair.left.content !== pair.right.content) return true;

                const leftKeys = pair.left.keys.join('|');
                const rightKeys = pair.right.keys.join('|');
                if (leftKeys !== rightKeys) return true;

                const leftSec = pair.left.secondaryKeys.join('|');
                const rightSec = pair.right.secondaryKeys.join('|');
                if (leftSec !== rightSec) return true;
            }
            return false;
        },

        _isSameForAutoPick(leftData, rightData) {
            if (this._isLorebookComparison()) {
                return !this._hasLorebookVisibleDiff(leftData, rightData);
            }
            return this._isDataEqual(leftData, rightData);
        },

        async _pruneBackupsRepresentedByCurrent(currentVer, backups) {
            const ordered = Array.isArray(backups) ? backups : [];
            if (!ordered.length) {
                return { backups: [], hidden: 0 };
            }

            let currentData;
            try {
                currentData = await this._loadVersionData(currentVer);
            } catch (e) {
                console.warn('Load current version for backup pruning failed:', e);
                return { backups: ordered, hidden: 0 };
            }

            let hidden = 0;
            for (const backup of ordered) {
                try {
                    const backupData = await this._loadVersionData(backup);
                    if (this._isSameForAutoPick(backupData, currentData)) {
                        hidden += 1;
                    } else {
                        break;
                    }
                } catch (e) {
                    console.warn('Load backup for pruning failed:', e);
                    break;
                }
            }

            return {
                backups: ordered.slice(hidden),
                hidden
            };
        },

        async _loadVersionData(ver) {
            let data;

            // 场景 A: 当前版本 (Current)
            if (ver.is_current) {
                let rawContent = this.rollbackLiveContent;

                // 如果没有实时内容，从 API 读取
                if (!rawContent) {
                    if (this.rollbackTargetType === 'card') {
                        // 读取角色卡元数据
                        const res = await getCardMetadata(this.rollbackTargetId);
                        rawContent = (res.success === true && res.data) ? res.data : res;
                    } else if (this.rollbackTargetType === 'lorebook') {
                        // 读取世界书
                        if (this.rollbackTargetId.startsWith('embedded::')) {
                            // 内嵌：读取宿主卡片
                            const realId = this.rollbackTargetId.replace('embedded::', '');
                            const res = await getCardMetadata(realId);
                            rawContent = (res.success === true && res.data) ? res.data : res;
                        } else {
                            // 独立文件
                            const res = await readFileContent({ path: this.rollbackTargetPath });
                            rawContent = res.data;
                        }
                    }
                }

                // 角色卡走标准化，世界书保持原结构以做条目级匹配
                if (this._isLorebookComparison()) {
                    data = rawContent;
                } else {
                    const cleanRes = await normalizeCardData(rawContent);
                    if (cleanRes.success) {
                        data = cleanRes.data;
                    } else {
                        console.warn("清洗失败，使用原始数据", cleanRes.msg);
                        data = rawContent;
                    }
                }
            }
            // 场景 B: 历史备份 (Backup)
            else {
                const res = await readFileContent({ path: ver.path });
                data = res.data;
            }

            // 世界书对比模式：统一提取 character_book
            if (this._isLorebookComparison()) {
                if (data?.data?.character_book) {
                    data = data.data.character_book;
                } else if (data?.character_book) {
                    data = data.character_book;
                }
            }

            return data;
        },

        async updateDiffView(autoAdjustLeft = true) {
            const leftVer = this.diffSelection.left;
            const rightVer = this.diffSelection.right;

            if (!leftVer || !rightVer) {
                this.diffData = { left: '<div class="p-8 text-center text-gray-500">请在左侧列表选择版本进行比对</div>', right: '' };
                return;
            }

            this.isDiffLoading = true;
            try {
                const [leftData, rightData] = await Promise.all([
                    this._loadVersionData(leftVer),
                    this._loadVersionData(rightVer)
                ]);

                // 默认打开时：若“最新快照”与 Current 完全一致，自动切到下一个有差异的版本
                if (autoAdjustLeft && rightVer.is_current && leftVer && !leftVer.is_current) {
                    const isSameAsCurrent = this._isSameForAutoPick(leftData, rightData);
                    if (isSameAsCurrent && this.backupList.length > 1) {
                        const currentIdx = this.backupList.findIndex(b => b.path === leftVer.path);
                        for (let i = currentIdx + 1; i < this.backupList.length; i++) {
                            const candidate = this.backupList[i];
                            const candidateData = await this._loadVersionData(candidate);
                            if (!this._isSameForAutoPick(candidateData, rightData)) {
                                this.diffSelection.left = candidate;
                                await this.updateDiffView(false);
                                return;
                            }
                        }
                    }
                }

                const result = this._isLorebookComparison()
                    ? this._renderLorebookDiff(leftData, rightData)
                    : generateSideBySideDiff(leftData, rightData);
                this.diffData.left = result.left;
                this.diffData.right = result.right;
            } catch (e) {
                console.error(e);
                this.diffData.left = `<div class="p-4 text-red-500">Error: ${e.message}</div>`;
                this.diffData.right = '';
            } finally {
                this.isDiffLoading = false;
            }
        },

        // === 恢复逻辑 ===

        performRestore() {
            const targetVer = this.diffSelection.left;
            
            if (!targetVer || targetVer.is_current) {
                alert("请在左侧选择一个历史备份版本进行恢复");
                return;
            }
            if (!confirm(`确定回滚到 ${new Date(targetVer.mtime*1000).toLocaleString()} 的版本吗？`)) return;
            
            this.isLoading = true;
            restoreBackup({
                backup_path: targetVer.path,
                target_id: this.rollbackTargetId,
                type: this.rollbackTargetType,
                target_file_path: this.rollbackTargetPath
            }).then(res => {
                this.isLoading = false;
                if(res.success) {
                    alert("回滚成功！页面将刷新数据。");
                    this.showRollbackModal = false;

                    window.dispatchEvent(new CustomEvent('wi-restore-applied', {
                        detail: {
                            targetType: this.rollbackTargetType,
                            targetId: this.rollbackTargetId,
                            targetFilePath: this.rollbackTargetPath,
                            restoredBackupPath: targetVer.path,
                            restoredBackupLabel: targetVer.label || '',
                            restoredBackupMtime: targetVer.mtime || 0
                        }
                    }));
                    
                    // 刷新父级数据
                    if (this.rollbackTargetType === 'card') {
                        // 通知详情页刷新
                        // 注意：这里需要 Card ID，如果是内嵌WI，ID需要处理
                        let refreshId = this.rollbackTargetId;
                        if (refreshId.startsWith('embedded::')) refreshId = refreshId.replace('embedded::', '');
                        
                        // 由于 detailModal 可能不在作用域内，通过事件通知
                        // detailModal 需要监听 'refresh-card-detail'
                        // 但在原 app.js 逻辑中，是直接调用 refreshActiveCardDetail
                        // 这里我们派发通用刷新事件
                        window.dispatchEvent(new CustomEvent('card-updated', { detail: { id: refreshId } })); // 触发重载
                        window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    } 
                    else if (this.rollbackTargetType === 'lorebook') {
                        window.dispatchEvent(new CustomEvent('refresh-wi-list'));
                        // 如果在编辑器中，也应该刷新编辑器，这里简单处理为刷新列表
                    }
                } else {
                    alert("回滚失败: " + res.msg);
                }
            });
        },

        // 打开备份文件夹
        openBackupFolder() {
            const type = this.rollbackTargetType; // 'card' | 'lorebook'
            const id = this.rollbackTargetId;     // e.g. "group/name.png" or "embedded::group/name.png"
            const path = this.rollbackTargetPath; // e.g. "data/..." (only for standalone WI)

            // 1. 预判逻辑
            let isEmbedded = false;
            let targetName = "";

            // 辅助：从 ID 或路径中提取纯文件名 (无后缀)
            const extractName = (str) => {
                if (!str) return "";
                // 取文件名部分 -> 去后缀 -> 替换非法字符
                return str.split('/').pop().replace(/\.[^/.]+$/, "").replace(/[\\/:*?"<>|]/g, '_').trim();
            };

            if (type === 'lorebook') {
                if (id && id.startsWith('embedded::')) {
                    isEmbedded = true;
                    // embedded::card_id -> 提取 card_id 部分
                    const realCardId = id.replace('embedded::', '');
                    targetName = extractName(realCardId);
                } else {
                    // 独立世界书，使用文件路径提取名字
                    targetName = extractName(path);
                }
            } else {
                // 角色卡
                targetName = extractName(id);
            }

            // 2. 构造路径
            let base = "";
            if (isEmbedded || type === 'card') {
                base = `data/system/backups/cards`;
            } else {
                base = `data/system/backups/lorebooks`;
            }

            let specific = "";
            if (targetName) {
                specific = `${base}/${targetName}`;
            } else {
                specific = base;
            }

            // 3. 执行打开请求
            openPath({ 
                path: specific, 
                relative_to_base: true 
            }).then(res => {
                if(!res.success) {
                    // 如果特定目录不存在 (比如还没备份过)，尝试打开上一级基础目录
                    openPath({ path: base, relative_to_base: true });
                }
            });
        }
    }
}
