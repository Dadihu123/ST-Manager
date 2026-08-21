/**
 * 类脑搜索站帖子只读预览弹层
 */

import { fetchForumThreadPreview } from '../api/forum.js';

function _pad(n) {
  return String(n).padStart(2, '0');
}

/** ISO 时间 → 紧凑本地时间 */
function formatForumTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return `${d.getFullYear()}-${_pad(d.getMonth() + 1)}-${_pad(d.getDate())} ${_pad(d.getHours())}:${_pad(d.getMinutes())}`;
}

export default function forumThreadPreview() {
  return {
    visible: false,
    loading: false,
    error: '',
    thread: null,
    sourceLink: '',
    cardId: '',
    coverIndex: 0,

    init() {
      window.addEventListener('open-forum-thread-preview', (e) => {
        const detail = e.detail || {};
        this.open(detail);
      });

      window.addEventListener('keydown', (e) => {
        if (!this.visible) return;
        if (e.key === 'Escape') {
          e.preventDefault();
          this.close();
          return;
        }
        // 多图时左右键切换
        if (this.hasMultipleCovers()) {
          if (e.key === 'ArrowLeft') {
            e.preventDefault();
            this.prevCover();
          } else if (e.key === 'ArrowRight') {
            e.preventDefault();
            this.nextCover();
          }
        }
      });
    },

    async open({ source_link = '', card_id = '', card = null } = {}) {
      this.sourceLink = source_link || card?.source_link || '';
      this.cardId = card_id || card?.id || '';
      this.visible = true;
      this.loading = true;
      this.error = '';
      this.thread = null;
      this.coverIndex = 0;

      try {
        const res = await fetchForumThreadPreview({
          source_link: this.sourceLink,
          card_id: this.cardId,
        });
        if (!res?.success) {
          this.error = res?.msg || '加载失败';
          return;
        }
        this.thread = res.data || null;
        this.coverIndex = 0;
        if (!this.thread) this.error = '无帖子数据';
      } catch (err) {
        this.error = err?.message || '加载失败';
      } finally {
        this.loading = false;
      }
    },

    close() {
      this.visible = false;
      this.loading = false;
      this.error = '';
      this.thread = null;
      this.coverIndex = 0;
    },

    formatTime(iso) {
      return formatForumTime(iso);
    },

    authorName() {
      const a = this.thread?.author;
      if (!a) return '未知作者';
      return a.display_name || a.global_name || a.name || '未知作者';
    },

    authorAvatar() {
      return this.thread?.author?.avatar_url || '';
    },

    /** 过滤后的封面列表 */
    coverUrls() {
      const urls = this.thread?.thumbnail_urls;
      if (!Array.isArray(urls)) return [];
      return urls.map((u) => String(u || '').trim()).filter(Boolean);
    },

    hasMultipleCovers() {
      return this.coverUrls().length > 1;
    },

    coverUrl() {
      const urls = this.coverUrls();
      if (!urls.length) return '';
      const idx = Math.min(Math.max(this.coverIndex, 0), urls.length - 1);
      return urls[idx];
    },

    prevCover() {
      const n = this.coverUrls().length;
      if (n <= 1) return;
      this.coverIndex = (this.coverIndex - 1 + n) % n;
    },

    nextCover() {
      const n = this.coverUrls().length;
      if (n <= 1) return;
      this.coverIndex = (this.coverIndex + 1) % n;
    },

    goCover(idx) {
      const n = this.coverUrls().length;
      if (n <= 0) return;
      this.coverIndex = Math.min(Math.max(Number(idx) || 0, 0), n - 1);
    },

    /** 简介：优先 Markdown 渲染，失败则纯文本转义 */
    excerptHtml() {
      const raw = this.thread?.first_message_excerpt || '';
      if (!raw) return '<p class="forum-preview-empty">暂无简介</p>';
      try {
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
          const html = marked.parse(raw, { breaks: true });
          return DOMPurify.sanitize(html);
        }
      } catch (_) {
        /* fallback below */
      }
      const escaped = raw
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
      return `<pre class="forum-preview-excerpt-plain">${escaped}</pre>`;
    },
  };
}
