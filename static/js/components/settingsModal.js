/**
 * static/js/components/settingsModal.js
 * 系统设置组件
 */

import { uploadBackground } from '../api/resource.js';
import { openTrash, emptyTrash, performSystemAction, triggerScan } from '../api/system.js';
import { updateCssVariable, applyFont as applyFontDom } from '../utils/dom.js';

export default function settingsModal() {
    return {
        // === 本地状态 ===
        activeSettingTab: 'general',
        showDiscordHelper: false,

        get settingsForm() { return this.$store.global.settingsForm; },
        get showSettingsModal() { 
            return this.$store.global.showSettingsModal; 
        },
        set showSettingsModal(val) { 
            this.$store.global.showSettingsModal = val; 
        },

        updateCssVariable,

        applyFont(type) {
            // 1. 更新全局状态 (这会让按钮的高亮 :class 重新计算)
            this.$store.global.settingsForm.font_style = type;
            
            // 2. 应用 CSS 样式 (改变视觉字体)
            applyFontDom(type);
        },

        // 1. 应用主题 (调用全局 Store 的 action)
        applyTheme(color) {
            this.$store.global.applyTheme(color);
        },

        // 2. 切换深色模式 (调用全局 Store)
        toggleDarkMode() {
            this.$store.global.toggleDarkMode();
        },

        // 3. 立即扫描 (scanNow)
        scanNow() {
            if (!confirm("立即触发一次全量扫描同步磁盘与数据库？\n（适用于 watchdog 未安装或你手动改动过文件）")) return;
            
            this.$store.global.isLoading = true;
            triggerScan()
                .then(res => {
                    if (!res.success) alert("触发扫描失败: " + (res.msg || 'unknown'));
                    else alert("已触发扫描任务（后台进行中）。稍后可点刷新查看结果。");
                })
                .catch(err => alert("网络错误: " + err))
                .finally(() => { 
                    this.$store.global.isLoading = false; 
                });
        },

        // 4. 系统操作 (systemAction: 打开文件夹、备份等)
        systemAction(action) {
            performSystemAction(action)
                .then(res => {
                    if (!res.success && res.msg) alert(res.msg);
                    else if (res.msg) alert(res.msg);
                })
                .catch(err => alert("请求失败: " + err));
        },

        // === 初始化 ===
        init() {
            // 设置数据直接绑定到 $store.global.settingsForm
            // 无需本地 duplicate
        },

        openSettings() {
            this.showSettingsModal = true;
        },

        saveSettings(closeModal = true) {
            // 调用 Store 的 Action
            this.$store.global.saveSettings(closeModal)
                .then(res => {
                    if (res && res.success && closeModal) {
                        this.showSettingsModal = false; // 手动关闭
                    }
                });
        },

        // === 背景图上传 ===
        
        triggerBackgroundUpload() {
            this.$refs.bgUploadInput.click();
        },

        handleBackgroundUpload(e) {
            const file = e.target.files[0];
            if (!file) return;
            
            if (file.size > 10 * 1024 * 1024) {
                alert("图片太大，请上传 10MB 以内的图片");
                return;
            }

            const formData = new FormData();
            formData.append('file', file);

            const btn = e.target.previousElementSibling; 
            const originalText = btn ? btn.innerText : '';
            if(btn) btn.innerText = '⏳...';

            uploadBackground(formData)
                .then(res => {
                    if (res.success) {
                        // 更新 Store
                        this.$store.global.settingsForm.bg_url = res.url;
                        this.$store.global.updateBackgroundImage(res.url);
                    } else {
                        alert("上传失败: " + res.msg);
                    }
                })
                .catch(err => {
                    alert("网络错误: " + err);
                })
                .finally(() => {
                    if(btn) btn.innerText = originalText;
                    e.target.value = ''; 
                });
        },

        // === 回收站操作 ===

        openTrashFolder() {
            openTrash().then(res => {
                if(!res.success) alert("打开失败: " + res.msg);
            });
        },

        emptyTrash() {
            if(!confirm("确定要彻底清空回收站吗？此操作无法撤销！")) return;
            emptyTrash().then(res => {
                if(res.success) alert(res.msg);
                else alert("清空失败: " + res.msg);
            });
        }
    }
}