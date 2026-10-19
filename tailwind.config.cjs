module.exports = {
  content: [
    './templates/**/*.html',
    './static/js/**/*.js',
    './static/js/**/*.mjs',
    './core/**/*.py',
  ],
  theme: {
    extend: {
      /*
       * Tailwind 默认值此前构成「第二套标尺」，与项目自己的令牌并行生效、
       * 互不约束（阴影 288 个值里有相当一部分来自这里）。
       *
       * 这里只做**零视觉变化**的对齐：把 Tailwind 的默认产出映射到
       * `static/css/modules/ui-refresh.css` 里定义的同一组值。圆角本来
       * 就是 4 / 8 / 12 / 16，与项目标尺一致，无需覆盖 —— 覆盖它反而会
       * 改动既有界面。阴影则收回项目唯一的五档 elevation。
       *
       * 注意：`fontSize` 不动。Tailwind 的 xs/sm/base 分别是 12 / 14 / 16，
       * 与本项目 `--text-xs` / `--text-sm` / `--text-md` 完全一致。
       */
      boxShadow: {
        sm: 'var(--elevation-1)',
        DEFAULT: 'var(--elevation-2)',
        md: 'var(--elevation-2)',
        lg: 'var(--elevation-3)',
        xl: 'var(--elevation-4)',
        '2xl': 'var(--elevation-5)',
        none: 'none',
      },
      borderRadius: {
        /* 与 --radius-sm / -md / -lg / -xl 同值，保持单一圆角标尺。 */
        DEFAULT: 'var(--radius-sm)',
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-md)',
        xl: 'var(--radius-lg)',
        '2xl': 'var(--radius-xl)',
        full: 'var(--radius-pill)',
      },
    },
  },
  plugins: [],
};
