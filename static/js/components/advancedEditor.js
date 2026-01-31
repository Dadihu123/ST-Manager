/**
 * static/js/components/advancedEditor.js
 * 高级编辑器组件 (正则脚本 & 扩展脚本)
 */

import { updateShadowContent } from '../utils/dom.js';

export default function advancedEditor() {
    return {
        // === 本地状态 ===
        showAdvancedModal: false,
        activeTab: 'regex',
        activeRegexIndex: -1,
        showMobileSidebar: false, // 移动端侧边栏显示状态

        regexPreviewMode: 'text', // text | html
        showLargePreview: false,

        // 正则测试
        regexTestInput: "",
        regexTestResult: "",

        // ST脚本扩展
        activeScriptIndex: -1,
        scriptDataJson: "",

        // 数据引用 (从 detailModal 传入)
        editingData: {
            extensions: {
                regex_scripts: [],
                tavern_helper: []
            }
        },

        isFileMode: false,
        currentFilePath: null,
        fileType: null, // 'regex' | 'script'

        updateShadowContent,

        init() {
            // 监听打开事件
            // detailModal 或者 HTML 中的按钮需要触发此事件，并传递 editingData 的引用
            window.addEventListener('open-advanced-editor', (e) => {
                this.activeRegexIndex = -1;
                this.activeScriptIndex = -1;
                this.isFileMode = false;
                this.editingData = e.detail; // 接收引用，实现响应式同步
                this.showAdvancedModal = true;
                this.activeTab = 'regex';
                this.activeRegexIndex = -1;
                this.regexTestInput = "";
                this.regexTestResult = "";
                this.regexPreviewMode = 'text';
                // 确保数据结构完整
                if (!this.editingData.extensions) this.editingData.extensions = {};
                if (!this.editingData.extensions.regex_scripts) this.editingData.extensions.regex_scripts = [];
                // 确保 Helper 脚本也经过清洗
                this.getTavernScripts().forEach(s => this._normalizeScript(s));

                if (this.$store.global.deviceType === 'mobile') {
                    this.showMobileSidebar = false;
                }
            });

            // 监听打开独立文件事件
            window.addEventListener('open-script-file-editor', (e) => {
                const { fileData, filePath, type } = e.detail;
                this.activeRegexIndex = -1;
                this.activeScriptIndex = -1;
                this.isFileMode = true;
                this.currentFilePath = filePath;
                this.fileType = type; // 'regex' or 'script'
                // 立即清洗数据，防止 Alpine 渲染报错
                if (type === 'script') {
                    this._normalizeScript(fileData);
                }
                this.showAdvancedModal = true;

                // 构造一个伪造的 editingData 结构，让现有 UI 能够复用
                // 因为 UI 绑定的是 editingData.extensions.regex_scripts 等
                this.editingData = {
                    extensions: {
                        regex_scripts: type === 'regex' ? [fileData] : [],
                        tavern_helper: type === 'script' ? { scripts: [fileData] } : { scripts: [] }
                    }
                };

                // 自动选中
                if (type === 'regex') {
                    this.activeTab = 'regex';
                    this.activeRegexIndex = 0;
                } else {
                    this.activeTab = 'scripts';
                    this.activeScriptIndex = 0;
                    // 初始化 JSON 编辑器内容
                    this.scriptDataJson = JSON.stringify(fileData.data || {}, null, 2);
                }
            });

            this.$watch('activeScriptIndex', (idx) => {
                if (idx > -1) {
                    const script = this.getTavernScripts()[idx];
                    if (script) {
                        this._normalizeScript(script); // 再次确保安全
                        this.scriptDataJson = JSON.stringify(script.data, null, 2);
                    }
                }
            });
        },

        // 数据标准化辅助函数
        _normalizeScript(script) {
            if (!script) return;
            if (!script.button) script.button = { enabled: true, buttons: [] };
            if (!script.data) script.data = {};
            if (script.enabled === undefined) script.enabled = true; // 默认启用
        },

        // === 通用工具 ===
        _downloadJson(data, filename) {
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        },

        _readJsonFile(file) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = e => {
                    try {
                        resolve(JSON.parse(e.target.result));
                    } catch (err) {
                        reject(err);
                    }
                };
                reader.readAsText(file);
            });
        },

        // === Regex Import/Export ===
        exportRegex(index) {
            const script = this.editingData.extensions.regex_scripts[index];
            if (!script) return;
            const { id, ...data } = script;
            const name = script.scriptName || 'untitled';
            this._downloadJson({ ...data, id: script.id }, `regex-${name}.json`);
        },

        async importRegex(e) {
            const file = e.target.files[0];
            if (!file) return;
            try {
                const data = await this._readJsonFile(file);
                if (!data.findRegex && !data.scriptName) throw new Error("无效的正则脚本格式");
                data.id = crypto.randomUUID();
                if (!this.editingData.extensions.regex_scripts) this.editingData.extensions.regex_scripts = [];
                this.editingData.extensions.regex_scripts.push(data);
                this.activeRegexIndex = this.editingData.extensions.regex_scripts.length - 1;
                this.$store.global.showToast("导入成功");
            } catch (err) {
                alert("导入失败: " + err.message);
            }
            e.target.value = '';
        },

        // === Tavern Script Import/Export ===
        exportScript(index) {
            const scripts = this.getTavernScripts();
            const script = scripts[index];
            if (!script) return;
            this.syncScriptDataJson();
            const name = script.name || 'untitled';
            this._downloadJson(script, `酒馆助手脚本-${name}.json`);
        },

        async importScript(e) {
            const file = e.target.files[0];
            if (!file) return;
            try {
                const data = await this._readJsonFile(file);
                if (data.type !== 'script' && !data.content) throw new Error("无效的 ST 脚本格式");

                data.id = crypto.randomUUID();
                
                // 导入时标准化
                this._normalizeScript(data);

                const helper = this.editingData.extensions.tavern_helper;
                let scriptBlock = null; 
                
                // 兼容逻辑：查找或创建 scripts 数组
                if (Array.isArray(helper)) {
                    scriptBlock = helper.find(item => Array.isArray(item) && item[0] === "scripts");
                    if (!scriptBlock) {
                        scriptBlock = ["scripts", []];
                        helper.push(scriptBlock);
                    }
                    scriptBlock[1].push(data);
                    // 强制刷新
                    this.editingData.extensions.tavern_helper = [...helper];
                    this.activeScriptIndex = scriptBlock[1].length - 1;
                } else {
                    // 字典结构
                    if (!helper.scripts) helper.scripts = [];
                    helper.scripts.push(data);
                    this.activeScriptIndex = helper.scripts.length - 1;
                }

                this.$store.global.showToast("导入成功");
            } catch (err) {
                alert("导入失败: " + err.message);
            }
            e.target.value = '';
        },

        // === Tavern Script Data Sync ===
        // 当 textarea 内容变化时，尝试解析 JSON 并回写到对象
        syncScriptDataJson() {
            if (this.activeScriptIndex === -1) return;
            const scripts = this.getTavernScripts();
            const script = scripts[this.activeScriptIndex];
            if (!script) return;
            try {
                const parsed = JSON.parse(this.scriptDataJson);
                script.data = parsed;
            } catch (e) {
                console.warn("JSON Parse Error in Data field");
            }
        },

        // === Regex Script 管理 ===

        addRegexScript() {
            const newScript = {
                id: crypto.randomUUID(),
                scriptName: "新正则脚本",
                findRegex: "", replaceString: "", trimStrings: [], placement: [2],
                disabled: false, markdownOnly: false, promptOnly: false, runOnEdit: true, substituteRegex: 0,
                minDepth: null, maxDepth: null
            };
            if (!this.editingData.extensions) this.editingData.extensions = {};
            if (!this.editingData.extensions.regex_scripts) this.editingData.extensions.regex_scripts = [];
            this.editingData.extensions.regex_scripts.push(newScript);
            this.activeRegexIndex = this.editingData.extensions.regex_scripts.length - 1;
        },

        removeRegexScript(index) {
            if (confirm("确定删除此正则脚本？")) {
                this.editingData.extensions.regex_scripts.splice(index, 1);
                this.activeRegexIndex = -1;
            }
        },

        moveRegex(index, dir) {
            const list = this.editingData.extensions.regex_scripts;
            const newIdx = index + dir;
            if (newIdx < 0 || newIdx >= list.length) return;
            const temp = list[index];
            list[index] = list[newIdx];
            list[newIdx] = temp;
            if (this.activeRegexIndex === index) this.activeRegexIndex = newIdx;
            else if (this.activeRegexIndex === newIdx) this.activeRegexIndex = index;
            this.editingData.extensions.regex_scripts = [...list];
        },

        // 处理 Placement (SillyTavern 使用整数枚举数组)
        toggleRegexPlacement(script, value) {
            const val = parseInt(value);
            if (!script.placement) script.placement = [];
            const idx = script.placement.indexOf(val);
            if (idx > -1) script.placement.splice(idx, 1);
            else script.placement.push(val);
        },

        // === 正则测试逻辑 ===

        runRegexTest() {
            const script = this.editingData.extensions.regex_scripts[this.activeRegexIndex];
            if (!script) return;
            if (!this.regexTestInput) { this.regexTestResult = ""; return; }
            if (!script.findRegex) { this.regexTestResult = this.regexTestInput; return; }
            try {
                const flags = "g" + (script.caseSensitive ? "" : "i") + "m";
                const regex = new RegExp(script.findRegex, flags);
                let result = this.regexTestInput;
                if (script.trimStrings && Array.isArray(script.trimStrings)) {
                    script.trimStrings.forEach(trimStr => { if (trimStr) result = result.split(trimStr).join(""); });
                }
                result = result.replace(regex, script.replaceString || "");
                this.regexTestResult = result;
            } catch (e) {
                this.regexTestResult = "❌ 正则表达式错误: " + e.message;
            }
        },

        // === Trim Strings 辅助 (Textarea <-> Array) ===

        updateTrimStrings(script, text) {
            // 按换行符分割，去除空行
            script.trimStrings = text.split('\n').filter(line => line.length > 0);
        },

        getTrimStringsText(script) {
            if (Array.isArray(script.trimStrings)) {
                return script.trimStrings.join('\n');
            }
            return "";
        },

        // === Tavern Scripts (Post-History / Slash Commands) ===

        getTavernScripts() {
            if (!this.editingData.extensions) return [];
            const helper = this.editingData.extensions.tavern_helper;

            if (!helper) return [];

            // 1. 新版：字典结构 (Dict)
            if (!Array.isArray(helper) && typeof helper === 'object') {
                // 新版结构通常是 { scripts: [], variables: {} }
                if (!Array.isArray(helper.scripts)) helper.scripts = [];
                return helper.scripts;
            }

            // 2. 旧版：数组结构 (List)
            if (Array.isArray(helper)) {
                // 查找 ["scripts", Array] 结构
                const scriptBlock = helper.find(item => Array.isArray(item) && item[0] === "scripts");
                if (scriptBlock && Array.isArray(scriptBlock[1])) {
                    return scriptBlock[1];
                }
                // 如果是纯旧版且没找到 scripts 块，可能数据还未迁移，返回空
                return [];
            }

            return [];
        },

        addTavernScript() {
            const newScript = {
                name: "新脚本",
                type: "script",
                content: "// Write your JS code here\nconsole.log('Hello World');",
                info: "作者备注信息",
                enabled: false,
                id: crypto.randomUUID(),
                button: { enabled: true, buttons: [] },
                data: {}
            };

            // 确保 extensions 结构
            if (!this.editingData.extensions) this.editingData.extensions = {};
            let helper = this.editingData.extensions.tavern_helper;

            // 智能初始化
            if (!helper) {
                // 默认初始化为新版字典结构
                helper = {
                    scripts: [],
                    variables: {}
                };
                this.editingData.extensions.tavern_helper = helper;
            }

            let scriptsList = null;

            if (Array.isArray(helper)) {
                // 旧版兼容：保持数组结构
                let scriptBlock = helper.find(item => Array.isArray(item) && item[0] === "scripts");
                if (!scriptBlock) {
                    scriptBlock = ["scripts", []];
                    helper.push(scriptBlock);
                }
                scriptsList = scriptBlock[1];
            } else {
                // 新版字典
                if (!helper.scripts) helper.scripts = [];
                scriptsList = helper.scripts;
            }

            scriptsList.push(newScript);
            this.activeScriptIndex = scriptsList.length - 1;
        },

        removeTavernScript(scriptId) {
            const list = this.getTavernScripts();
            const index = list.findIndex(s => s.id === scriptId);
            if (index > -1) {
                list.splice(index, 1);
                this.activeScriptIndex = -1;
            }
        },

        moveTavernScript(scriptId, dir) {
            const list = this.getTavernScripts();
            const index = list.findIndex(s => s.id === scriptId);
            if (index === -1) return;

            const newIdx = index + dir;
            if (newIdx < 0 || newIdx >= list.length) return;

            // 交换
            const temp = list[index];
            list[index] = list[newIdx];
            list[newIdx] = temp;

            // 同步选中索引
            if (this.activeScriptIndex === index) {
                this.activeScriptIndex = newIdx;
            } else if (this.activeScriptIndex === newIdx) {
                this.activeScriptIndex = index;
            }
        },

        // === 按钮管理 (New) ===

        addScriptButton(script) {
            this._normalizeScript(script);
            script.button.buttons.push({ name: "新按钮", visible: true });
        },

        removeScriptButton(script, btnIndex) {
            if (script.button && script.button.buttons) {
                script.button.buttons.splice(btnIndex, 1);
            }
        },

        // 保存独立文件的方法
        saveFileChanges() {
            if (!this.isFileMode || !this.currentFilePath) return;
            let contentToSave = null;
            try {
                if (this.fileType === 'regex') {
                    contentToSave = this.editingData.extensions.regex_scripts[0];
                } else {
                    this.syncScriptDataJson();
                    const scripts = this.getTavernScripts();
                    contentToSave = scripts[0];
                }
                import('../api/resource.js').then(module => {
                    module.saveScriptFile({
                        file_path: this.currentFilePath,
                        content: contentToSave
                    }).then(res => {
                        if (res.success) this.$store.global.showToast("💾 脚本文件已保存");
                        else alert("保存失败: " + res.msg);
                    });
                });
            } catch (e) {
                console.error(e);
                alert("保存前处理数据出错: " + e.message);
            }
        },
    }
}