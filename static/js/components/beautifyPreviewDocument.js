import { buildVendorFirstPreviewShell } from '../../vendor/sillytavern/preview-shell.js';
import {
  CHARACTER_DRAWER_VENDOR_MARKUP,
  FORMATTING_DRAWER_VENDOR_MARKUP,
  SETTINGS_DRAWER_VENDOR_MARKUP,
} from '../../vendor/sillytavern/preview-drawers.js';
import {
  buildCharacterDrawerPreviewMarkupFromVendor,
  buildFormattingDrawerPreviewMarkupFromVendor,
  buildSettingsDrawerPreviewMarkupFromVendor,
} from './beautifyPreviewDrawerAdapters.js';
import { getBeautifyPreviewColorTokens } from '../runtime/previewColorTokens.js';

export const DEFAULT_PREVIEW_SCENE_ID = 'daily';

export const PREVIEW_SCENE_OPTIONS = [
  {
    id: 'daily',
    label: '日常陪伴',
    description: '更自然的日常多轮聊天',
  },
  {
    id: 'flirty',
    label: '暧昧互动',
    description: '更柔和的情绪和停顿',
  },
  {
    id: 'lore',
    label: '设定说明',
    description: '长段落和说明性文本',
  },
  {
    id: 'story',
    label: '剧情推进',
    description: '连续叙事与状态推进',
  },
  {
    id: 'style-demo',
    label: '样式演示',
    description: '用于校验富文本、系统提示和代码块等样式表现',
  },
];

const PREVIEW_SCENE_CONTEXT_STORY_STRINGS = {
  daily: '日常陪伴场景：输出轻松自然的多轮对话，语气温和，重视承接与停顿。',
  flirty: '暧昧互动场景：输出克制、柔和、留有余白的短轮对话。',
  lore: '设定说明场景：输出信息清晰、段落完整、便于阅读的长文本说明。',
  story: '剧情推进场景：输出包含动作、观察与状态变化的连续叙事。',
  'style-demo': '样式演示专用：集中展示粗体、斜体、引用、列表、链接、行内代码、代码块和系统提示样式。',
};

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeCssText(value) {
  return String(value ?? "").replace(/<\/style/gi, "<\\/style");
}

function sanitizePreviewCustomCss(value) {
  return String(value ?? "")
    .replace(
      /@import\s+url\((['"]?)(?:https?:)?\/\/[^)]+\1\)(?:\s+[^;]+)?\s*;?/gi,
      "",
    )
    .replace(/@import\s+(['"])(?:https?:)?\/\/[^;]+\1(?:\s+[^;]+)?\s*;?/gi, "");
}

function buildPreviewContentSecurityPolicy() {
  const localResourceOrigins = [
    "'self'",
    "data:",
    "blob:",
    "http://127.0.0.1:5000",
    "https://127.0.0.1:5000",
  ];
  const imageOrigins = [...localResourceOrigins, "http:", "https:"];

  return [
    "default-src 'none'",
    "script-src 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline' http://127.0.0.1:5000 https://127.0.0.1:5000",
    `font-src ${localResourceOrigins.join(" ")}`,
    `img-src ${imageOrigins.join(" ")}`,
  ].join("; ");
}

function escapeCssUrl(value) {
  return String(value ?? "")
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"')
    .replace(/[\r\n\f]/g, " ");
}

function normalizeNumber(value, fallback) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function clampMin(value, minimum) {
  return Math.max(value, minimum);
}

function clampRange(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
}

function buildPreviewBodyClasses(theme = {}) {
  const classes = [];

  if (theme.timer_enabled === false) {
    classes.push("no-timer");
  }

  if (theme.timestamps_enabled === false) {
    classes.push("no-timestamps");
  }

  if (theme.message_token_count_enabled === false) {
    classes.push("no-tokenCount");
  }

  if (theme.mesIDDisplay_enabled === false) {
    classes.push("no-mesIDDisplay");
  }

  if (theme.hideChatAvatars_enabled) {
    classes.push("hideChatAvatars");
  }

  if (Number(theme.avatar_style) === 2) {
    classes.push("square-avatars");
  }

  if (Number(theme.avatar_style) === 3) {
    classes.push("rounded-avatars");
  }

  if (Number(theme.chat_display) === 1) {
    classes.push("bubblechat");
  }

  if (Number(theme.chat_display) === 2) {
    classes.push("documentstyle");
  }

  return classes;
}

const PREVIEW_IDENTITY_ASSET_PATHS = {
  character: "/static/images/beautify-preview/sumian.png",
  user: "/static/images/beautify-preview/lingyan.png",
};

function buildInlineAvatarDataUri({
  label,
  size = 96,
  radius = 24,
  background,
  foreground,
  themeMode = 'dark',
}) {
  const fallbackColors = getBeautifyPreviewColorTokens(themeMode);
  const safeBackground = background || fallbackColors.avatarSurface;
  const safeForeground = foreground || fallbackColors.avatarText;
  const fontSize = Math.max(Math.round(size * 0.3125), 16);
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='${size}' height='${size}' viewBox='0 0 ${size} ${size}'%3E%3Crect width='${size}' height='${size}' rx='${radius}' fill='${encodeURIComponent(safeBackground)}'/%3E%3Ctext x='50%25' y='55%25' font-size='${fontSize}' text-anchor='middle' fill='${encodeURIComponent(safeForeground)}' font-family='Arial'%3E${encodeURIComponent(label)}%3C/text%3E%3C/svg%3E`;
}

function resolvePreviewAvatarSrc({
  avatarSrc = "",
  avatarLabel = "",
  size = 96,
  themeMode = 'dark',
}) {
  if (avatarSrc) {
    return avatarSrc;
  }

  return buildInlineAvatarDataUri({
    label: avatarLabel,
    size,
    radius: Math.round(size / 4),
    themeMode,
  });
}

function buildPreviewIdentities(identities = {}) {
  const character = identities.character || {};
  const user = identities.user || {};

  return {
    system: {
      name: "SillyTavern System",
      avatarLabel: "ST",
    },
    character: {
      name: character.name || "苏眠",
      avatarSrc: character.avatarSrc || PREVIEW_IDENTITY_ASSET_PATHS.character,
    },
    user: {
      name: user.name || "凌砚",
      avatarSrc: user.avatarSrc || PREVIEW_IDENTITY_ASSET_PATHS.user,
    },
  };
}

function serializeCssVars(vars) {
  return Object.entries(vars)
    .filter(
      ([, value]) => value !== "" && value !== null && value !== undefined,
    )
    .map(([key, value]) => `${key}:${escapeCssText(value)}`)
    .join(";");
}

function buildMessageActions() {
  return `
    <div class="mes_buttons">
      <div class="mes_button extraMesButtonsHint fa-solid fa-ellipsis" data-icon-fallback="⋯" title="Message Actions"></div>
      <div class="extraMesButtons">
        <div class="mes_button mes_translate fa-solid fa-language" data-icon-fallback="文" title="Translate message"></div>
        <div class="mes_button sd_message_gen fa-solid fa-paintbrush" data-icon-fallback="刷" title="Generate Image"></div>
        <div class="mes_button mes_narrate fa-solid fa-bullhorn" data-icon-fallback="📣" title="Narrate"></div>
        <div class="mes_button mes_prompt fa-solid fa-square-poll-horizontal" data-icon-fallback="≣" title="Prompt" style="display: none;"></div>
        <div class="mes_button mes_hide fa-solid fa-eye" data-icon-fallback="◐" title="Exclude message from prompts"></div>
        <div class="mes_button mes_unhide fa-solid fa-eye-slash" data-icon-fallback="◑" title="Include message in prompts"></div>
        <div class="mes_button mes_media_gallery fa-solid fa-photo-film" data-icon-fallback="▦" title="Toggle media display style"></div>
        <div class="mes_button mes_media_list fa-solid fa-table-cells-large" data-icon-fallback="☷" title="Toggle media display style"></div>
        <div class="mes_button mes_embed fa-solid fa-paperclip" data-icon-fallback="📎" title="Embed file or image"></div>
        <div class="mes_button mes_swipe_picker fa-solid fa-bookmark" data-icon-fallback="🔖" title="Jump to swipe history" style="display: none;"></div>
        <div class="mes_button mes_create_bookmark fa-regular fa-solid fa-flag-checkered" data-icon-fallback="⚑" title="Create checkpoint"></div>
        <div class="mes_button mes_create_branch fa-regular fa-code-branch" data-icon-fallback="⑂" title="Create branch"></div>
        <div class="mes_button mes_copy fa-solid fa-copy" data-icon-fallback="⧉" title="Copy"></div>
      </div>
      <div class="mes_button mes_bookmark fa-solid fa-flag" data-icon-fallback="⚑" title="Bookmark"></div>
      <div class="mes_button mes_edit fa-solid fa-pencil" data-icon-fallback="✎" title="Edit"></div>
    </div>
    <div class="mes_edit_buttons">
      <div class="mes_edit_done menu_button fa-solid fa-check" data-icon-fallback="✓" title="Confirm"></div>
      <div class="mes_edit_copy menu_button fa-solid fa-copy" data-icon-fallback="⧉" title="Copy this message"></div>
      <div class="mes_edit_add_reasoning menu_button fa-solid fa-lightbulb" data-icon-fallback="💡" title="Add a reasoning block"></div>
      <div class="mes_edit_delete menu_button fa-solid fa-trash-can" data-icon-fallback="🗑" title="Delete this message"></div>
      <div class="mes_edit_up menu_button fa-solid fa-chevron-up" data-icon-fallback="↑" title="Move message up"></div>
      <div class="mes_edit_down menu_button fa-solid fa-chevron-down" data-icon-fallback="↓" title="Move message down"></div>
      <div class="mes_edit_cancel menu_button fa-solid fa-xmark" data-icon-fallback="×" title="Cancel"></div>
    </div>
  `;
}

function buildReasoningBlock() {
  return `
    <details class="mes_reasoning_details">
      <summary class="mes_reasoning_summary">
        <div class="mes_reasoning_header_block flex-container">
          <div class="mes_reasoning_header flex-container">
            <span class="mes_reasoning_header_title">Thought for some time</span>
            <div class="mes_reasoning_arrow">^</div>
          </div>
        </div>
        <div class="mes_reasoning_actions flex-container">
          <div class="mes_reasoning_edit_done menu_button edit_button fa-solid fa-check" data-icon-fallback="✓" aria-label="Confirm Edit"></div>
          <div class="mes_reasoning_delete menu_button edit_button fa-solid fa-trash-can" data-icon-fallback="🗑" aria-label="Remove reasoning"></div>
          <div class="mes_reasoning_edit_cancel menu_button edit_button fa-solid fa-xmark" data-icon-fallback="×" aria-label="Cancel edit"></div>
          <div class="mes_reasoning_close_all mes_button fa-solid fa-minimize" data-icon-fallback="▁" aria-label="Collapse all reasoning blocks"></div>
          <div class="mes_reasoning_copy mes_button fa-solid fa-copy" data-icon-fallback="⧉" aria-label="Copy reasoning"></div>
          <div class="mes_reasoning_edit mes_button fa-solid fa-pencil" data-icon-fallback="✎" aria-label="Edit reasoning"></div>
        </div>
      </summary>
      <div class="mes_reasoning">${escapeHtml("🌿 梧桐絮语：这条预览消息保留了思维链容器，便于主题命中相关选择器。")}</div>
    </details>
  `;
}

function buildMessage({
  mesId,
  name,
  avatarLabel,
  avatarSrc = "",
  messageHtml,
  timestamp,
  timer = "",
  tokenCounter,
  isUser = false,
  isSystem = false,
  includeReasoning = false,
  extraClass = "",
  themeMode = 'dark',
}) {
  const classes = ["mes"];
  if (extraClass) {
    classes.push(extraClass);
  }

  const resolvedAvatarSrc = resolvePreviewAvatarSrc({
    avatarSrc,
    avatarLabel,
    themeMode,
  });

  return `
    <div class="${classes.join(" ")}" mesid="${escapeHtml(mesId)}" ch_name="${escapeHtml(name)}" is_user="${isUser ? "true" : "false"}" is_system="${isSystem ? "true" : "false"}" bookmark_link="">
      <div class="for_checkbox"></div><input type="checkbox" class="del_checkbox">
      <div class="mesAvatarWrapper">
        <div class="avatar">
          <img alt="${escapeHtml(name)}" src="${escapeHtml(resolvedAvatarSrc)}">
        </div>
        <div class="mesIDDisplay">#${escapeHtml(mesId)}</div>
        <div class="mes_timer">${escapeHtml(timer)}</div>
        <div class="tokenCounterDisplay">${escapeHtml(tokenCounter)}</div>
      </div>
      <div class="swipe_left">&lt;</div>
      <div class="mes_block">
        <div class="ch_name flex-container justifySpaceBetween">
          <div class="flex-container flex1 alignitemscenter">
            <div class="flex-container alignItemsBaseline">
              <span class="name_text">${escapeHtml(name)}</span>
              <i class="mes_ghost fa-solid fa-ghost" data-icon-fallback="👻" title="Ghost"></i>
              <small class="timestamp">${escapeHtml(timestamp)}</small>
            </div>
          </div>
          ${buildMessageActions()}
        </div>
        ${includeReasoning ? buildReasoningBlock() : ""}
        <div class="mes_text">${messageHtml}</div>
        <div class="mes_media_wrapper"></div>
        <div class="mes_file_wrapper"></div>
        <div class="mes_bias"></div>
      </div>
      <div class="flex-container swipeRightBlock flexFlowColumn flexNoGap">
        <div class="swipe_right">></div>
        <div class="swipes-counter">1/1</div>
      </div>
    </div>
  `;
}

function buildPreviewScenes(normalizedPlatform = "pc") {
  return PREVIEW_SCENE_OPTIONS.map((scene) => {
    if (scene.id === 'daily') {
      return {
        ...scene,
        messages: [
          {
            role: 'system',
            mesId: '1',
            timestamp: 'System',
            tokenCounter: 'meta',
            extraClass: 'smallSysMes',
            messageHtml:
              '<p>日常陪伴预览：观察更自然的多轮来回节奏。</p><hr>',
          },
          {
            role: 'character',
            mesId: '2',
            timestamp: '2026年4月27日 20:11',
            timer: '',
            tokenCounter: '148 tok',
            messageHtml:
              '<p>你终于忙完了？我刚刚还在想，要不要再等你五分钟就去泡茶。</p>',
          },
          {
            role: 'user',
            mesId: '3',
            timestamp: '2026年4月27日 20:12',
            timer: '',
            tokenCounter: '42 tok',
            messageHtml: '<p>差一点就要加班到更晚了，现在总算能喘口气。</p>',
          },
          {
            role: 'character',
            mesId: '4',
            timestamp: '2026年4月27日 20:12',
            timer: '',
            tokenCounter: '173 tok',
            messageHtml:
              '<p>那先别急着想别的，坐下来，肩膀放松一点。你说一句今天最想听的话，我负责顺着你往下接。</p>',
          },
          {
            role: 'user',
            mesId: '5',
            timestamp: '2026年4月27日 20:13',
            timer: '',
            tokenCounter: '36 tok',
            extraClass: 'last_mes',
            messageHtml: '<p>那你先说，欢迎回来。</p>',
          },
        ],
      };
    }

    if (scene.id === 'flirty') {
      return {
        ...scene,
        messages: [
          {
            role: 'character',
            mesId: '1',
            timestamp: '2026年4月27日 22:06',
            timer: '',
            tokenCounter: '124 tok',
            messageHtml:
              '<p>你刚刚那句“只看一眼消息”听起来，可不像真的只看一眼。</p>',
          },
          {
            role: 'user',
            mesId: '2',
            timestamp: '2026年4月27日 22:06',
            timer: '',
            tokenCounter: '72 tok',
            messageHtml: '<p>被你发现了。我本来只是想确认你睡了没。</p>',
          },
          {
            role: 'character',
            mesId: '3',
            timestamp: '2026年4月27日 22:07',
            timer: '',
            tokenCounter: '136 tok',
            messageHtml:
              '<p>如果我说还没睡，你是不是就会顺理成章地多陪我几分钟？</p>',
          },
          {
            role: 'user',
            mesId: '4',
            timestamp: '2026年4月27日 22:08',
            timer: '',
            tokenCounter: '48 tok',
            extraClass: 'last_mes',
            messageHtml: '<p>几分钟可能不够，要看你接下来打算怎么留我。</p>',
          },
        ],
      };
    }

    if (scene.id === 'lore') {
      return {
        ...scene,
        messages: [
          {
            role: 'user',
            mesId: '1',
            timestamp: '2026年4月27日 19:24',
            timer: '',
            tokenCounter: '104 tok',
            messageHtml: '<p>你之前提过“潮灯湾”，那地方到底是什么样？</p>',
          },
          {
            role: 'character',
            mesId: '2',
            timestamp: '2026年4月27日 19:25',
            timer: '',
            tokenCounter: '220 tok',
            messageHtml:
              '<p>港口白天看着安静，到了夜里，栈桥边会亮起成串的冷色灯。海面不算平，风一吹，光带就碎成一片一片的，像有人把玻璃撒进水里。</p>',
          },
          {
            role: 'user',
            mesId: '3',
            timestamp: '2026年4月27日 19:26',
            timer: '',
            tokenCounter: '81 tok',
            messageHtml: '<p>听起来不像旅游港，更像某种会藏秘密的地方。</p>',
          },
          {
            role: 'character',
            mesId: '4',
            timestamp: '2026年4月27日 19:27',
            timer: '',
            tokenCounter: '268 tok',
            extraClass: 'last_mes',
            messageHtml:
              '<p>确实。那里的旧仓库区白天封着，晚上却有人出入。很多走私传闻都和那边有关，所以本地人提起潮灯湾时，总会把声音压低一点。</p>',
          },
        ],
      };
    }

    if (scene.id === 'story') {
      return {
        ...scene,
        messages: [
          {
            role: 'system',
            mesId: '1',
            timestamp: 'System',
            tokenCounter: 'meta',
            extraClass: 'smallSysMes',
            messageHtml:
              '<p>场景预览：轻量剧情推进，用于观察多轮叙事节奏。</p><hr>',
          },
          {
            role: 'character',
            mesId: '2',
            timestamp: '2026年4月27日 23:11',
            timer: '',
            tokenCounter: '180 tok',
            messageHtml:
              '<p>巷口的风把纸灯吹得一晃一晃的，我抬手替你挡了下火，指尖顺势擦过你袖口上沾着的灰。</p>',
          },
          {
            role: 'user',
            mesId: '3',
            timestamp: '2026年4月27日 23:12',
            timer: '',
            tokenCounter: '74 tok',
            messageHtml: '<p>前面那扇门里真的有人？我刚才明明听见里面拖动椅子的声音了。</p>',
          },
          {
            role: 'character',
            mesId: '4',
            timestamp: '2026年4月27日 23:13',
            timer: '',
            tokenCounter: '196 tok',
            messageHtml:
              '<p>有人，而且不止一个。你先站我身后，等我数到三，我们一起进去。要是灯灭了，就沿着右手边的墙走，别回头。</p>',
          },
          {
            role: 'user',
            mesId: '5',
            timestamp: '2026年4月27日 23:13',
            timer: '',
            tokenCounter: '55 tok',
            extraClass: 'last_mes',
            messageHtml: '<p>好，你数吧。我会跟紧你。</p>',
          },
        ],
      };
    }

    return {
      ...scene,
      messages: [
        {
          role: 'system',
          mesId: '1',
          timestamp: 'System',
          tokenCounter: 'meta',
          extraClass: 'smallSysMes',
          messageHtml:
            '<p>样式演示场景：集中观察富文本、系统提示和代码样式。</p><hr>',
        },
        {
          role: 'character',
          mesId: '2',
          timestamp: '2026年4月27日 21:40',
          timer: '',
          tokenCounter: '188 tok',
          includeReasoning: true,
          messageHtml:
            '<p><strong>粗体</strong>、<em>斜体</em>、<u>下划线</u> 和 <code>inline code</code>。</p><blockquote>Welcome back. Theme variables now drive this isolated preview.</blockquote>',
        },
        {
          role: 'user',
          mesId: '3',
          timestamp: '2026年4月27日 21:41',
          timer: '',
          tokenCounter: '120 tok',
          extraClass: 'last_mes',
          messageHtml: `<p>这里还要检查列表、链接和代码块。</p><ul><li>Example item A</li><li>Example item B</li></ul><p><a href="#" data-preview-link="disabled">Example link</a></p><pre><code>const preview = buildBeautifyPreviewDocument({ platform: '${escapeHtml(normalizedPlatform)}' });</code></pre>`,
        },
      ],
    };
  });
}

function getPreviewSceneContextStoryString(sceneId) {
  return PREVIEW_SCENE_CONTEXT_STORY_STRINGS[sceneId] || PREVIEW_SCENE_CONTEXT_STORY_STRINGS[DEFAULT_PREVIEW_SCENE_ID];
}

function buildPreviewSceneMessage(message, previewIdentities, themeMode = 'dark') {
  if (message.role === "system") {
    return buildMessage({
      ...message,
      name: previewIdentities.system.name,
      avatarLabel: previewIdentities.system.avatarLabel,
      themeMode,
      isSystem: true,
    });
  }

  if (message.role === "user") {
    return buildMessage({
      ...message,
      name: previewIdentities.user.name,
      avatarLabel: "CL",
      avatarSrc: previewIdentities.user.avatarSrc,
      isUser: true,
      themeMode,
    });
  }

  return buildMessage({
    ...message,
    name: previewIdentities.character.name,
    avatarLabel: "QW",
    avatarSrc: previewIdentities.character.avatarSrc,
    themeMode,
  });
}

function buildPreviewSceneMessages(scene, previewIdentities, themeMode = 'dark') {
  return scene.messages
    .map((message) => buildPreviewSceneMessage(message, previewIdentities, themeMode))
    .join("");
}

const VENDORED_ST_STYLESHEETS = [
  "/static/vendor/sillytavern/css/fontawesome.min.css",
  "/static/vendor/sillytavern/css/solid.min.css",
  "/static/vendor/sillytavern/css/brands.min.css",
  "/static/vendor/sillytavern/style.css",
];

function buildVendoredStylesheetMarkup(platform = "pc") {
  const hrefs = [...VENDORED_ST_STYLESHEETS];
  if (platform === "mobile") {
    hrefs.push("/static/vendor/sillytavern/css/mobile-styles.css");
  }

  return hrefs
    .map((href) => `    <link rel="stylesheet" href="${href}" />`)
    .join("\n");
}

function buildPreviewBehaviorScript() {
  return `
    (() => {
      const root = document.querySelector('.st-preview-root');
      if (!root) return;
      const buttons = Array.from(document.querySelectorAll('[data-panel-target]'));
      const panels = Array.from(document.querySelectorAll('.drawer-content[data-panel-surface]'));
      const drawers = Array.from(document.querySelectorAll('.inline-drawer'));

      const toggleInlineDrawer = (drawer, expand = true) => {
        const icon = drawer.querySelector(':scope > .inline-drawer-header .inline-drawer-icon');
        const content = drawer.querySelector(':scope > .inline-drawer-content');

        if (!icon || !content) {
          return;
        }

        if (expand) {
          icon.classList.remove('down', 'fa-circle-chevron-down');
          icon.classList.add('up', 'fa-circle-chevron-up');
          content.style.display = 'block';
        } else {
          icon.classList.remove('up', 'fa-circle-chevron-up');
          icon.classList.add('down', 'fa-circle-chevron-down');
          content.style.display = 'none';
        }

        drawer.dispatchEvent(new CustomEvent('inline-drawer-toggle', { bubbles: true }));
      };

      const sync = (activePanel) => {
        root.dataset.activePanel = activePanel;
        buttons.forEach((button) => {
          const active = button.dataset.panelTarget === activePanel;
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
          button.classList.toggle('is-active', active);
          button.classList.toggle('openIcon', active);
          button.classList.toggle('closedIcon', !active);
        });
        panels.forEach((panel) => {
          const isActive = panel.dataset.panelSurface === activePanel;
          panel.classList.toggle('openDrawer', isActive);
          panel.classList.toggle('closedDrawer', !isActive);
          panel.classList.toggle('open', isActive);
          const drawer = panel.closest('.drawer');
          if (drawer) {
            drawer.classList.toggle('openDrawer', isActive);
            drawer.classList.toggle('closedDrawer', !isActive);
            drawer.classList.toggle('open', isActive);
          }
        });
        drawers.forEach((drawer) => {
          const isActive = activePanel === 'settings';
          drawer.classList.toggle('open', isActive);
          drawer.classList.toggle('closed', !isActive);
          toggleInlineDrawer(drawer, isActive);
        });
      };

      const bindPreviewLinks = () => {
        document.querySelectorAll('[data-preview-link="disabled"]').forEach((link) => {
          if (link.__stPreviewLinkBound) {
            return;
          }
          link.__stPreviewLinkBound = true;
          link.addEventListener('click', (event) => {
            event.preventDefault();
          });
        });
      };

      const bindPreviewDisabledActions = () => {
        document.querySelectorAll('[data-preview-disabled="true"]').forEach((node) => {
          if (node.__stPreviewDisabledBound) {
            return;
          }
          node.__stPreviewDisabledBound = true;
          node.addEventListener('click', (event) => {
            event.preventDefault();
            if (typeof event.stopPropagation === 'function') {
              event.stopPropagation();
            }
          });
        });
      };

      const bindCharacterDrawerControls = () => {
        const searchForm = document.querySelector('#form_character_search_form');

        document.querySelectorAll('[data-preview-action="toggle-search"]').forEach((node) => {
          if (node.__stPreviewToggleSearchBound) {
            return;
          }
          node.__stPreviewToggleSearchBound = true;
          node.addEventListener('click', (event) => {
            event.preventDefault();
            if (!searchForm || !searchForm.style) {
              return;
            }
            searchForm.style.display = searchForm.style.display === 'none' ? 'block' : 'none';
          });
        });

        document.querySelectorAll('[data-preview-action="toggle-grid"]').forEach((node) => {
          if (node.__stPreviewToggleGridBound) {
            return;
          }
          node.__stPreviewToggleGridBound = true;
          node.addEventListener('click', (event) => {
            event.preventDefault();
            if (!document.body || !document.body.classList) {
              return;
            }
            document.body.classList.toggle('charListGrid');
          });
        });
      };

      const scrollChatToBottom = () => {
        const chat = document.querySelector('#chat');
        if (!chat) {
          return;
        }
        chat.scrollTop = chat.scrollHeight;
      };

      buttons.forEach((button) => {
        button.addEventListener('click', () => {
          const nextPanel = button.dataset.panelTarget || 'none';
          sync(root.dataset.activePanel === nextPanel ? 'none' : nextPanel);
        });
      });

      drawers.forEach((drawer) => {
        const toggle = drawer.querySelector(':scope > .inline-drawer-toggle');
        if (!toggle) return;
        toggle.addEventListener('click', () => {
          const isOpen = drawer.classList.contains('open');
          drawer.classList.toggle('open', !isOpen);
          drawer.classList.toggle('closed', isOpen);
          toggleInlineDrawer(drawer, !isOpen);
        });
      });

      sync(root.dataset.activePanel || 'none');
      bindPreviewLinks();
      bindPreviewDisabledActions();
      bindCharacterDrawerControls();
      window.requestAnimationFrame(scrollChatToBottom);
      window.addEventListener('load', scrollChatToBottom);
    })();
  `;
}

export function buildBeautifyPreviewThemeVars(
  theme = {},
  wallpaperUrl = "",
  platform = 'pc',
  themeMode = 'dark',
) {
  const fallbackColors = getBeautifyPreviewColorTokens(themeMode);
  const fontScale = (() => {
    const normalized = normalizeNumber(theme.font_scale, 1);
    return normalized > 0 ? normalized : 1;
  })();
  const blurStrength = clampMin(normalizeNumber(theme.blur_strength, 10), 0);
  const shadowWidth = clampMin(normalizeNumber(theme.shadow_width, 2), 0);
  const previewShellWidth = platform === 'mobile'
    ? '100%'
    : `${clampRange(normalizeNumber(theme.chat_width, 100), 25, 100)}vw`;
  const safeWallpaperUrl = wallpaperUrl
    ? `url("${escapeCssUrl(wallpaperUrl)}")`
    : "none";

  return {
    "--SmartThemeBodyColor": theme.main_text_color || fallbackColors.contentPrimary,
    "--SmartThemeEmColor":
      theme.italics_text_color || theme.main_text_color || fallbackColors.contentSecondary,
    "--SmartThemeUnderlineColor":
      theme.underline_text_color || theme.quote_text_color || fallbackColors.contentLink,
    "--SmartThemeQuoteColor": theme.quote_text_color || fallbackColors.contentQuote,
    "--SmartThemeBlurTintColor":
      theme.blur_tint_color || fallbackColors.blurTint,
    "--SmartThemeChatTintColor":
      theme.chat_tint_color || fallbackColors.chatTint,
    "--SmartThemeUserMesBlurTintColor":
      theme.user_mes_blur_tint_color || fallbackColors.userMessageTint,
    "--SmartThemeBotMesBlurTintColor":
      theme.bot_mes_blur_tint_color || fallbackColors.botMessageTint,
    "--SmartThemeShadowColor": theme.shadow_color || fallbackColors.shadow,
    "--SmartThemeBorderColor":
      theme.border_color || fallbackColors.border,
    "--fontScale": String(fontScale),
    "--blurStrength": `${blurStrength}px`,
    "--shadowWidth": `${shadowWidth}px`,
    "--SmartThemeBlurStrength": "var(--blurStrength)",
    "--mainFontSize": "calc(var(--fontScale) * 16px)",
    "--stPreviewShellWidth": previewShellWidth,
    "--wallpaperUrl": safeWallpaperUrl,
  };
}

export function buildBeautifyPreviewSampleMarkup(
  platform = "pc",
  theme = {},
  identities = {},
  activeScene = "",
  detail = {},
  themeMode = 'dark',
) {
  const normalizedPlatform = platform === "mobile" ? "mobile" : "pc";
  const previewIdentities = buildPreviewIdentities(identities);
  const vendorDrawerMarkup = {
    settings: SETTINGS_DRAWER_VENDOR_MARKUP,
    formatting: FORMATTING_DRAWER_VENDOR_MARKUP,
    character: CHARACTER_DRAWER_VENDOR_MARKUP,
  };
  const previewScenes = buildPreviewScenes(normalizedPlatform);
  const selectedScene =
    previewScenes.find((scene) => scene.id === activeScene) ||
    previewScenes.find((scene) => scene.id === DEFAULT_PREVIEW_SCENE_ID) ||
    previewScenes[0];
  const sendFormClasses = ["no-connection"];

  if (theme.compact_input_area) {
    sendFormClasses.push("compact");
  }

  const settingsDrawerContentMarkup = buildSettingsDrawerPreviewMarkupFromVendor({
    theme,
    vendorMarkup: vendorDrawerMarkup.settings,
  });
  const formattingDrawerContentMarkup = buildFormattingDrawerPreviewMarkupFromVendor({
    scenePromptContent: getPreviewSceneContextStoryString(selectedScene.id),
    vendorMarkup: vendorDrawerMarkup.formatting,
  });
  const characterDrawerContentMarkup = buildCharacterDrawerPreviewMarkupFromVendor({
    identities: previewIdentities,
    detail,
    vendorMarkup: vendorDrawerMarkup.character,
  });
  const chatMarkup = buildPreviewSceneMessages(
    selectedScene,
    previewIdentities,
    themeMode,
  );

  return buildVendorFirstPreviewShell({
    activeSceneId: escapeHtml(selectedScene.id),
    settingsDrawerContentMarkup,
    formattingDrawerContentMarkup,
    characterDrawerContentMarkup,
    chatMarkup,
    sendFormClassNames: sendFormClasses.join(' '),
  });
}

export function buildBeautifyPreviewDocument({
  theme = {},
  wallpaperUrl = "",
  platform = "pc",
  themeMode = 'dark',
  identities = {},
  activeScene = "",
  detail = {},
} = {}) {
  const normalizedPlatform = platform === "mobile" ? "mobile" : "pc";
  const themeVars = buildBeautifyPreviewThemeVars(
    theme,
    wallpaperUrl,
    normalizedPlatform,
    themeMode,
  );
  const bodyClasses = buildPreviewBodyClasses(theme);
  const bodyClassAttr = bodyClasses.length
    ? ` class="${escapeHtml(bodyClasses.join(" "))}"`
    : "";
  const serializedVars = serializeCssVars(themeVars);
  const customCss = escapeCssText(
    sanitizePreviewCustomCss(theme.custom_css || ""),
  );
  const markup = buildBeautifyPreviewSampleMarkup(
    normalizedPlatform,
    theme,
    identities,
    activeScene,
    detail,
    themeMode,
  );
  const behaviorScript = buildPreviewBehaviorScript();
  const contentSecurityPolicy = escapeHtml(buildPreviewContentSecurityPolicy());
  const stylesheetMarkup = buildVendoredStylesheetMarkup(normalizedPlatform);

  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, viewport-fit=cover, initial-scale=1" />
    <meta http-equiv="Content-Security-Policy" content="${contentSecurityPolicy}" />
    <title>Beautify Native ST Preview</title>
${stylesheetMarkup}
    <style>:root{color-scheme:${themeMode === 'light' ? 'light' : 'dark'};${serializedVars}}</style>
    <style>
      html, body {
        margin: 0;
        width: 100%;
        height: 100%;
        min-height: 0;
      }

      body {
        position: relative;
        overflow: hidden;
        color: var(--SmartThemeBodyColor);
      }

      .st-preview-root {
        display: flex;
        flex-direction: column;
        width: 100%;
        height: 100%;
        min-height: 0;
        position: relative;
      }

      #bg1 {
        position: absolute;
        inset: 0;
        pointer-events: none;
        background-image: var(--wallpaperUrl);
        background-size: cover;
        background-position: center;
        filter: saturate(0.92);
      }

      .st-preview-shell {
        position: relative;
        z-index: 1;
        flex: 1 1 auto;
        min-height: 0;
        display: flex;
        flex-direction: column;
        padding: 0 20px 20px;
      }

      #top-bar {
        display: block;
      }

      body[data-st-preview-platform='mobile'] #top-settings-holder,
      body[data-st-preview-platform='mobile'] #top-bar {
        left: 0;
        right: 0;
      }

      .drawer-toggle {
        pointer-events: auto;
      }

      .st-preview-panel-body {
        display: none;
        min-width: 0;
        pointer-events: auto;
        max-height: min(680px, calc(100vh - 160px));
        overflow: auto;
      }

      .st-preview-root[data-active-panel='settings'] [data-panel-surface='settings'],
      .st-preview-root[data-active-panel='formatting'] [data-panel-surface='formatting'],
      .st-preview-root[data-active-panel='character'] [data-panel-surface='character'] {
        display: block;
        pointer-events: auto;
      }

    </style>
    <style>${customCss}</style><style>:root{--sheldWidth:var(--stPreviewShellWidth);}</style>
  </head>
  <body data-st-preview-platform="${escapeHtml(normalizedPlatform)}"${bodyClassAttr}>
    ${markup}
    <script>${behaviorScript.replace(/<\/script/gi, "<\\/script")}</script>
  </body>
</html>`;
}
