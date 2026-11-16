import { migrationRequest, uploadMigrationFile } from '../api/system.js';
import { authorizeAndroidDirectories } from '../utils/androidStorage.js';

// 在现有设置容器中显示预览，不引入新的浮层或返回栈。
export default function dataMigration() {
  return {
    migration: null,
    migrationBusy: false,
    migrationConfirmed: false,
    migrationTimer: null,
    get migrationAndroid() { return typeof window !== 'undefined' && window.stmHost?.platform?.() === 'android'; },
    async watchMigration(id) {
      clearTimeout(this.migrationTimer);
      localStorage.setItem('stm-migration-job', id);
      try {
        this.migration = await migrationRequest(`/jobs/${id}`);
        this.migrationBusy = ['queued', 'uploading', 'working', 'restoring', 'saving'].includes(this.migration.state);
        if (this.migrationBusy || (this.migrationAndroid && this.migration.state === 'ready')) {
          this.migrationTimer = setTimeout(() => this.watchMigration(id), 1000);
        }
      } catch (error) {
        this.migrationBusy = false;
        this.migration = {state: 'failed', error: error.message};
      }
    },
    async startMigrationExport() {
      this.migrationBusy = true;
      try {
        if (this.migrationAndroid) {
          const sources = await migrationRequest('/sources');
          await authorizeAndroidDirectories({allowed_abs_resource_roots: sources.authorization});
        }
        const job = await migrationRequest('/export', {method: 'POST'});
        await this.watchMigration(job.id);
      } catch (error) {
        this.migrationBusy = false;
        this.migration = {state: 'failed', error: error.message};
      }
    },
    async saveMigrationZip() {
      const id = this.migration.id;
      if (this.migrationAndroid) {
        await migrationRequest(`/jobs/${id}/save`, {method: 'POST'});
        window.stmHost.backupDocument(id, 'export');
        this.watchMigration(id);
      } else {
        const link = document.createElement('a');
        link.href = `/api/migration/jobs/${id}/download`;
        link.download = this.migration.filename;
        link.click();
        this.migration.phase = '已请求浏览器下载，请在下载列表确认文件保存完成';
      }
    },
    async selectMigrationZip() {
      this.migrationConfirmed = false;
      if (!this.migrationAndroid) { this.$refs.migrationFile.click(); return; }
      try {
        const job = await migrationRequest('/import', {method: 'POST'});
        window.stmHost.backupDocument(job.id, 'import');
        this.watchMigration(job.id);
      } catch (error) { this.migration = {state: 'failed', error: error.message}; }
    },
    async uploadMigrationZip(event) {
      const file = event.target.files?.[0];
      event.target.value = '';
      if (!file) return;
      this.migrationBusy = true;
      try {
        const job = await migrationRequest('/import', {method: 'POST'});
        this.migration = {phase: '正在上传备份文件', state: 'uploading'};
        await uploadMigrationFile(job.id, file);
        await this.watchMigration(job.id);
      } catch (error) {
        this.migrationBusy = false;
        this.migration = {state: 'failed', error: error.message};
      }
    },
    async confirmMigrationRestore() {
      if (!this.migrationConfirmed || this.migrationBusy) return;
      this.migrationBusy = true;
      try {
        await migrationRequest(`/jobs/${this.migration.id}/restore`, {
          method: 'POST', body: JSON.stringify({confirm: true}),
        });
        this.migration.state = 'working';
        this.migrationTimer = setTimeout(() => this.watchMigration(this.migration.id), 500);
      } catch (error) {
        this.migrationBusy = false;
        this.migration = {state: 'failed', error: error.message};
      }
    },
    async importLegacyUi(event) {
      const file = event.target.files?.[0];
      event.target.value = '';
      if (!file || !window.confirm('合并旧备注与标签 JSON？同一资源的附加信息会更新，现有文件将自动留存一份保护副本。')) return;
      try {
        if (file.size > 16 * 1048576) throw new Error('旧 JSON 超过 16 MiB');
        const result = await migrationRequest('/legacy-ui', {method: 'POST', body: await file.text()});
        this.migration = {state: 'complete', phase: `已合并 ${result.imported} 项备注与标签`};
      } catch (error) { this.migration = {state: 'failed', error: error.message}; }
    },
    resumeMigration() {
      const id = localStorage.getItem('stm-migration-job');
      if (id) this.watchMigration(id);
    },
  };
}
