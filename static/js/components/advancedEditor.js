/**
 * static/js/components/advancedEditor.js
 * 高级编辑器组件 (正则脚本 & 扩展脚本)
 */

import { updateShadowContent } from '../utils/dom.js';

export default function advancedEditor() {
    return {
        // === 本地状态 ===
        showAdvancedModal: false,
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

        updateShadowContent,

        init() {
            // 监听打开事件
            // detailModal 或者 HTML 中的按钮需要触发此事件，并传递 editingData 的引用
            window.addEventListener('open-advanced-editor', (e) => {
                this.editingData = e.detail; // 接收引用，实现响应式同步
                this.showAdvancedModal = true;
                this.activeRegexIndex = -1;
                this.regexTestInput = "";
                this.regexTestResult = "";
                this.regexPreviewMode = 'text';
                // 移动端默认关闭侧边栏
                if (this.$store.global.deviceType === 'mobile') {
                    this.showMobileSidebar = false;
                }
            });

            this.$watch('activeScriptIndex', (idx) => {
                if (idx > -1) {
                    const script = this.getTavernScripts()[idx];
                    if (script) {
                        // 确保结构完整
                        if (!script.button) script.button = { enabled: true, buttons: [] };
                        if (!script.data) script.data = {};
                        // 格式化 JSON 以便编辑
                        this.scriptDataJson = JSON.stringify(script.data, null, 2);
                    }
                }
            });
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
            // 清理内部 ID，导出纯净数据
            const { id, ...data } = script; 
            const name = script.scriptName || 'untitled';
            this._downloadJson({ ...data, id: script.id }, `regex-${name}.json`);
        },

        async importRegex(e) {
            const file = e.target.files[0];
            if (!file) return;
            try {
                const data = await this._readJsonFile(file);
                // 简单的格式校验
                if (!data.findRegex && !data.scriptName) throw new Error("无效的正则脚本格式");
                
                // 赋予新 ID，防止冲突
                data.id = crypto.randomUUID();
                
                if (!this.editingData.extensions.regex_scripts) this.editingData.extensions.regex_scripts = [];
                this.editingData.extensions.regex_scripts.push(data);
                this.activeRegexIndex = this.editingData.extensions.regex_scripts.length - 1;
                alert("导入成功");
            } catch (err) {
                alert("导入失败: " + err.message);
            }
            e.target.value = ''; // 重置 input
        },

        // === Tavern Script Import/Export ===
        exportScript(index) {
            const scripts = this.getTavernScripts();
            const script = scripts[index];
            if (!script) return;
            // 确保 data 字段是最新的（从 textarea 的字符串同步回对象）
            this.syncScriptDataJson(); 
            const name = script.name || 'untitled';
            this._downloadJson(script, `酒馆助手脚本-${name}.json`);
        },

        async importScript(e) {
            const file = e.target.files[0];
            if (!file) return;
            try {
                const data = await this._readJsonFile(file);
                // 校验
                if (data.type !== 'script' && !data.content) throw new Error("无效的 ST 脚本格式");
                
                data.id = crypto.randomUUID();
                // 确保默认字段
                if (!data.button) data.button = { enabled: true, buttons: [] };
                if (!data.data) data.data = {};

                // 获取 scripts 数组并推入
                const helper = this.editingData.extensions.tavern_helper;
                let scriptBlock = helper.find(item => Array.isArray(item) && item[0] === "scripts");
                if (!scriptBlock) {
                    scriptBlock = ["scripts", []];
                    helper.push(scriptBlock);
                }
                scriptBlock[1].push(data);
                
                // 强制更新视图
                this.editingData.extensions.tavern_helper = [...helper];
                this.activeScriptIndex = scriptBlock[1].length - 1;
                alert("导入成功");
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
                // 尝试解析 JSON
                const parsed = JSON.parse(this.scriptDataJson);
                script.data = parsed;
            } catch (e) {
                // 解析失败时不更新原对象，保持 UI 显示错误状态（可选：加个边框变红逻辑）
                console.warn("JSON Parse Error in Data field");
            }
        },

        // === Regex Script 管理 ===

        addRegexScript() {
            const newScript = {
                id: crypto.randomUUID(),
                scriptName: "新正则脚本",
                findRegex: "",
                replaceString: "",
                trimStrings: [],          // 剔除字符串数组
                placement: [2],           // 默认生效位置：2 (AI Output)
                disabled: false,
                markdownOnly: false,      // 仅影响显示
                promptOnly: false,        // 仅影响提示词
                runOnEdit: true,          // 编辑时运行
                substituteRegex: 0,       // 宏替换模式
                minDepth: null,
                maxDepth: null
            };

            // 确保结构存在
            if (!this.editingData.extensions) this.editingData.extensions = {};
            if (!this.editingData.extensions.regex_scripts) {
                this.editingData.extensions.regex_scripts = [];
            }

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

            // 交换
            const temp = list[index];
            list[index] = list[newIdx];
            list[newIdx] = temp;

            // 保持选中状态跟随
            if (this.activeRegexIndex === index) this.activeRegexIndex = newIdx;
            else if (this.activeRegexIndex === newIdx) this.activeRegexIndex = index;
            
            // 强制更新数组以触发 Alpine 响应式
            this.editingData.extensions.regex_scripts = [...list];
        },

        // 处理 Placement (SillyTavern 使用整数枚举数组)
        toggleRegexPlacement(script, value) {
            const val = parseInt(value);
            if (!script.placement) script.placement = [];

            const idx = script.placement.indexOf(val);
            if (idx > -1) {
                script.placement.splice(idx, 1);
            } else {
                script.placement.push(val);
            }
        },

        // === 正则测试逻辑 ===

        runRegexTest() {
            const script = this.editingData.extensions.regex_scripts[this.activeRegexIndex];
            if (!script) return;

            if (!this.regexTestInput) {
                this.regexTestResult = "";
                return;
            }
            if (!script.findRegex) {
                this.regexTestResult = this.regexTestInput;
                return;
            }

            try {
                const flags = "g" + (script.caseSensitive ? "" : "i") + "m";
                const regex = new RegExp(script.findRegex, flags);

                let result = this.regexTestInput;

                // 1. Trim Strings (预处理剔除)
                if (script.trimStrings && Array.isArray(script.trimStrings)) {
                    script.trimStrings.forEach(trimStr => {
                        if (trimStr) result = result.split(trimStr).join("");
                    });
                }

                // 2. Replace (正则替换)
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

            // 1. 新版：字典结构
            if (!Array.isArray(helper) && typeof helper === 'object') {
                if (!Array.isArray(helper.scripts)) helper.scripts = [];
                return helper.scripts;
            }

            // 2. 旧版：数组结构
            if (Array.isArray(helper)) {
                // 查找 ["scripts", Array] 结构
                const scriptBlock = helper.find(item => Array.isArray(item) && item[0] === "scripts");
                return (scriptBlock && Array.isArray(scriptBlock[1])) ? scriptBlock[1] : [];
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
            
            // 如果不存在，初始化为【新版字典结构】
            if (!helper) {
                helper = {
                    scripts: [],
                    variables: {}
                };
                this.editingData.extensions.tavern_helper = helper;
            }

            // 获取引用并推入
            let scriptsList = null;

            if (Array.isArray(helper)) {
                // 旧版兼容逻辑：如果已经是数组，保持数组结构
                let scriptBlock = helper.find(item => Array.isArray(item) && item[0] === "scripts");
                if (!scriptBlock) {
                    scriptBlock = ["scripts", []];
                    helper.push(scriptBlock);
                    // 补齐 variables 块
                    if (!helper.find(item => Array.isArray(item) && item[0] === "variables")) {
                        helper.push(["variables", {}]);
                    }
                }
                scriptsList = scriptBlock[1];
            } else {
                // 新版字典逻辑
                if (!helper.scripts) helper.scripts = [];
                scriptsList = helper.scripts;
            }

            scriptsList.push(newScript);

            // 自动选中新建的脚本
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
            if (!script.button) script.button = { enabled: true, buttons: [] };
            if (!script.button.buttons) script.button.buttons = [];
            
            script.button.buttons.push({
                name: "新按钮",
                visible: true // 默认可见
            });
        },

        removeScriptButton(script, btnIndex) {
            if (script.button && script.button.buttons) {
                script.button.buttons.splice(btnIndex, 1);
            }
        },
    }
}