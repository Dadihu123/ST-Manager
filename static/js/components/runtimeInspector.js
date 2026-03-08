import { getRuntimeManagerState, subscribeRuntimeManager } from '../runtime/runtimeManager.js';

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

export default function runtimeInspector() {
    return {
        showRuntimeInspector: false,
        runtimeFilterKind: 'all',
        runtimeFilterStatus: 'all',
        runtimeSearch: '',
        runtimeOverview: getRuntimeManagerState(),
        selectedRuntimeId: '',
        runtimeActionStatus: '',
        _unsubscribeRuntimeManager: null,

        init() {
            this._unsubscribeRuntimeManager = subscribeRuntimeManager((snapshot) => {
                this.runtimeOverview = snapshot;
                const items = this.filteredRuntimes();
                if (!items.find(item => item.runtimeId === this.selectedRuntimeId)) {
                    this.selectedRuntimeId = items[0]?.runtimeId || '';
                }
            });

            window.addEventListener('open-runtime-inspector', () => {
                this.open();
            });

            window.addEventListener('keydown', (event) => {
                if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'r') {
                    event.preventDefault();
                    this.open();
                }
            });
        },

        destroy() {
            if (this._unsubscribeRuntimeManager) {
                this._unsubscribeRuntimeManager();
                this._unsubscribeRuntimeManager = null;
            }
        },

        open() {
            this.showRuntimeInspector = true;
            const firstItem = this.filteredRuntimes()[0];
            if (firstItem && !this.selectedRuntimeId) {
                this.selectedRuntimeId = firstItem.runtimeId;
            }
        },

        close() {
            this.showRuntimeInspector = false;
        },

        filteredRuntimes() {
            const search = this.runtimeSearch.trim().toLowerCase();
            return (this.runtimeOverview.items || []).filter(item => {
                if (this.runtimeFilterKind !== 'all' && item.kind !== this.runtimeFilterKind) {
                    return false;
                }
                if (this.runtimeFilterStatus !== 'all' && item.status !== this.runtimeFilterStatus) {
                    return false;
                }
                if (!search) {
                    return true;
                }
                return [item.runtimeId, item.label, item.ownerId, item.kind, item.status]
                    .filter(Boolean)
                    .some(part => String(part).toLowerCase().includes(search));
            });
        },

        selectedRuntime() {
            const list = this.filteredRuntimes();
            return list.find(item => item.runtimeId === this.selectedRuntimeId) || list[0] || null;
        },

        selectRuntime(runtimeId) {
            this.selectedRuntimeId = runtimeId;
        },

        formatTime(timestamp) {
            if (!timestamp) return '-';
            return new Date(timestamp).toLocaleString();
        },

        runtimeDetailJson() {
            const runtime = this.selectedRuntime();
            if (!runtime) return '{}';
            return JSON.stringify(cloneValue(runtime), null, 2);
        },

        copyRuntimeJson() {
            const text = this.runtimeDetailJson();
            navigator.clipboard.writeText(text)
                .then(() => this.$store.global.showToast('运行时快照已复制'))
                .catch(() => this.$store.global.showToast('复制失败', 1800));
        },

        dispatchRuntimeControl(action) {
            const runtime = this.selectedRuntime();
            if (!runtime || runtime.kind !== 'script') {
                return;
            }

            this.runtimeActionStatus = action === 'stop' ? '正在停止...' : '正在重载...';
            window.dispatchEvent(new CustomEvent('runtime-inspector-control', {
                detail: {
                    runtimeId: runtime.runtimeId,
                    action,
                },
            }));

            window.setTimeout(() => {
                this.runtimeActionStatus = action === 'stop' ? '已发送停止请求' : '已发送重载请求';
            }, 60);
        },

        openScriptFromRuntime() {
            const runtime = this.selectedRuntime();
            if (!runtime || runtime.kind !== 'script' || !runtime.ownerId) {
                return;
            }

            window.dispatchEvent(new CustomEvent('focus-script-runtime-owner', {
                detail: { scriptId: runtime.ownerId },
            }));
            this.$store.global.showToast('已尝试定位对应脚本', 1500);
        },
    };
}
