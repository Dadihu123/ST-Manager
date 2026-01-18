/**
 * static/js/components/resourceManager.js
 * 网页版资源文件管理器组件
 */

import { 
    listResourceFiles, 
    deleteResourceFile, 
    uploadResourceFile 
} from '../api/resource.js';

export default function resourceManager() {
    return {
        visible: false,
        cardId: null,
        charName: '',
        folderName: '',
        files: [],
        isLoading: false,

        init() {
            // 监听打开管理器的事件
            window.addEventListener('open-resource-manager', (e) => {
                this.cardId = e.detail.card_id;
                this.charName = e.detail.char_name || '资源';
                this.open();
            });
        },

        async open() {
            if (!this.cardId) return;
            this.visible = true;
            await this.refresh();
        },

        async refresh() {
            this.isLoading = true;
            try {
                const res = await listResourceFiles(this.cardId);
                if (res.success) {
                    this.files = res.files;
                    this.folderName = res.folder_name;
                } else {
                    alert(res.msg);
                }
            } catch (err) {
                console.error(err);
            } finally {
                this.isLoading = false;
            }
        },

        async handleDelete(filename) {
            if (!confirm(`确定要删除文件 "${filename}" 吗？此操作不可撤销。`)) return;
            
            try {
                const res = await deleteResourceFile(this.cardId, filename);
                if (res.success) {
                    await this.refresh();
                } else {
                    alert(res.msg);
                }
            } catch (err) {
                alert('删除失败');
            }
        },

        async triggerFileUpload() {
            this.$refs.fileInput.click();
        },

        async handleFileUpload(e) {
            const file = e.target.files[0];
            if (!file) return;

            this.isLoading = true;
            try {
                const res = await uploadResourceFile(this.cardId, file);
                if (res.success) {
                    await this.refresh();
                } else {
                    alert(res.msg);
                }
            } catch (err) {
                alert('上传失败');
            } finally {
                this.isLoading = false;
                e.target.value = ''; // 清空选择
            }
        },

        formatSize(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        },

        formatDate(timestamp) {
            const date = new Date(timestamp * 1000);
            return date.toLocaleString();
        },

        isImage(filename) {
            const ext = filename.split('.').pop().toLowerCase();
            return ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'].includes(ext);
        }
    };
}
