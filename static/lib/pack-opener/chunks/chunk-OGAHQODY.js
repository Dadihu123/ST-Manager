// src/core/index.ts
import { Application, Assets, Texture as Texture10 } from "pixi.js";

// src/core/variants/shared/defaultPedestal.js
var DEFAULT_PEDESTAL_URI = "data:image/webp;base64,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";

// src/core/config/protocol.ts
var MESSAGES = {
  READY: "ready",
  INTERACTION_START: "interactionStart",
  TICK: "tick",
  COMMITTED: "committed",
  OPENED: "opened",
  /** Card reveal finished — the host may move on to its result screen. */
  REVEALED: "revealed",
  RETRACTED: "retracted",
  /**
   * The card has turned over and landed face up (`slice`) — the moment for
   * a heavy haptic or an impact sound. The React Native wrapper turns it into
   * `onHaptic('heavy')` by itself.
   */
  IMPACT: "impact",
  /**
   * A phase of the ceremony has begun; `name` is the scene's own word for it
   * (slice: autoSlice, runOut, open, charge, chargeHold — the card held at
   * its peak while its artwork is still on its way, announced once for the
   * whole wait — flip, land, hold, retract;
   * burst: autoCharge, release, beat, swarm, assemble, snap, settle) and
   * `durationMs` how long it will run. For a host that scores the ceremony —
   * a sound on the lid coming off, a rising tone under the charge, a swish on
   * the turn — where `opened` and `revealed` are too coarse.
   *
   * Slice also announces 0.4's names beside its own, for hosts scored by
   * them: `spin` with `open`, `unveil` with `charge` (or once late artwork
   * arrives), `spinHold` with `chargeHold`, `beam` with `flip`. The card
   * lands as `beam` ends, as it did in 0.4. Deprecated, gone in 0.6.
   */
  PHASE: "phase",
  /**
   * How long each phase of the ceremony will run, in ms, after `motion.speed`
   * — for slice `chargeMs`, `flipMs`, `landMs`, `holdMs` (and, deprecated,
   * 0.4's `spinMs`, `unveilMs`, `beamMs`); for burst
   * `chargeHoldMs`, `releaseMs`, `beatMs`, `swarmMs`, `assembleMs`,
   * `snapMs`. Posted with `ready` and again after every retune, so a host
   * that cues a sound ahead of a phase (an impact that has to land as the
   * card does) can count from the real numbers. Web only: the scene bundle
   * does not post it.
   */
  TIMELINE: "timeline",
  /** The stage changed size — a rotated phone, a resized window — and the pack
   * was re-derived for the new box; `rect` is where it is now. */
  LAYOUT: "layout",
  ERROR: "error"
};

// src/core/variants/burst/presets.ts
var PRESETS = {
  charged: {
    theme: {
      background: "transparent",
      glow: "#9a6bff",
      rim: "#ffffff",
      bloom: "#ffffff",
      beam: "#ffffff",
      spark: "#ffffff",
      // The cut's light — there is no cut here, kept so the theme is whole
      seam: "#ffcf8a",
      hint: "#ffffff",
      // Plain: the carousel flips this back into view, and it is designed blank
      cardBack: {
        top: "#ffffff",
        mid: "#f4f6ff",
        bottom: "#e9edf8",
        sheen: "rgba(255,255,255,0.85)",
        line: "transparent",
        emblem: "transparent"
      },
      // The artwork's own corners: a graded slab is barely rounded
      cornerRadius: 6
    },
    motion: {
      speed: 1,
      introMs: 320,
      // Both belong to the cut and are unused here; kept at the shared
      // defaults so a host switching variants sees no surprise in `motion`
      finishMs: 170,
      autoSliceMs: 430,
      retractMs: 220,
      open: {
        ms: 1e3,
        lid: 0.52,
        cardFrom: 0.34,
        sink: 0.5,
        gone: 0.8,
        clipFrom: 0.45,
        lidThrowX: 0.5,
        lidThrowY: 0.62,
        lidSpin: 0.5,
        lidFadeFrom: 0.15,
        lidFadeSpan: 0.45,
        uncutFade: 0.18
      },
      // This mechanic assembles the card instead of turning it over, so only
      // `holdMs`, the three glow opacities and the card's geometry are read
      // from here — the beam belongs to the cut, the spin to the carousel
      reveal: {
        /** The stand comes in behind the card, ahead of the host's own UI. */
        pedestalMs: 260,
        holdMs: 900,
        beamTail: 0.32,
        spinFlatness: 0.06,
        spinShade: 0.05,
        spinBloom: 0.85,
        bloomAlpha: 0.95,
        rimAlpha: 0.9,
        haloAlpha: 0.95,
        beamWidth: 3,
        beamAlpha: 0.9,
        beamGlowWidth: 11,
        beamGlowAlpha: 0.34,
        beamTipRadius: 8,
        beamSteps: 24,
        beamStyle: "segments",
        outlineDetail: 9,
        artWaitSpinMs: 600,
        // The card's own moment: its outline swells and a highlight runs
        // across the artwork. Both belong to the card, so a loud landing
        // still reads as the card arriving rather than as another blast
        pulseRim: 0.9,
        pulseHalo: 0.7,
        pulseSpread: 0.07,
        sheenMs: 850,
        sheenAlpha: 0.95,
        sheenWidth: 0.6,
        sheenTilt: 0.35
      }
    },
    charge: {
      holdMs: 1100,
      releaseMs: 260,
      shake: 9e-3,
      shakeHz: 22,
      squeeze: 0.05,
      heatAlpha: 0.7,
      haloAlpha: 0.85,
      bloomAlpha: 0.9,
      arcWidth: 4,
      arcAlpha: 0.95,
      sparks: 24,
      sparkReach: 0.85,
      sparkSize: 4,
      tickStep: 0.08,
      breathe: 0.012,
      breatheMs: 2600
    },
    burst: {
      flashMs: 260,
      flashScale: 2.8,
      // Long enough to read as a held breath. The first pass at this was 180ms
      // and the card started gathering while the eye was still on the debris.
      beatMs: 420,
      // Straight to small pieces: 13 × 22 shards of the pack. Two stages — big
      // pieces breaking up mid-flight — read as the debris jumping and were
      // dropped.
      cols: 13,
      rows: 22,
      // The cut is a mosaic, so these three decide how uneven it looks and
      // never whether the pieces meet: nodes pushed a third of a cell off
      // true, three segments an edge, tears a tenth of a cell deep
      shapeJitter: 0.32,
      shapeSegments: 3,
      shapeRagged: 0.1,
      scatter: 0.45,
      lifeScatter: 0.5,
      shardMs: 1400,
      spread: 1.15,
      lift: 0.5,
      gravity: 2.6,
      spin: 3.4,
      fadeFrom: 0.5,
      glowFrom: 0.45,
      glowSwell: 1.4,
      spikes: 14,
      spikeMs: 520,
      spikeLength: 1.5,
      spikeWidth: 7,
      spikeAlpha: 0.9,
      // The front, not an outline: three waves a stagger apart, each a thick
      // soft band with a hot white edge riding it, flattened so it reads as
      // travelling across a floor rather than drawn on the glass
      rings: 3,
      ringMs: 760,
      ringStagger: 0.28,
      ringThickness: 0.16,
      ringRagged: 0.1,
      ringSquash: 0.22,
      ringAlpha: 0.55,
      ringCoreAlpha: 0.7,
      ringReach: 1.6,
      // The flare struck at the middle of the blast
      flareMs: 700,
      flareSpread: 1,
      flareReach: 1.6,
      flareAlpha: 0.8,
      flareSpin: 0.4,
      // The stage itself takes the hit: thrown off centre and shaken back,
      // in pack widths
      kickMs: 420,
      kickAmp: 0.035,
      kickHz: 13,
      // And goes white for a moment — the cheapest thing in the scene and the
      // one that carries the blast past the glass
      screenFlashMs: 220,
      screenFlashAlpha: 0.85,
      debris: 90,
      debrisMs: 1400,
      debrisSpread: 1.5,
      debrisSize: 2.6,
      debrisTrail: 1.4,
      debrisAlpha: 0.9,
      debrisGravity: 0.5,
      glitter: 70,
      glitterMs: 2600,
      glitterSize: 2.4,
      glitterAlpha: 0.75,
      glitterFall: 0.5,
      // Short on purpose: the cloud used to run its full length after the
      // shreds had gone, which left half a second of empty screen between the
      // blast and the card. It now starts while the foil is still burning out
      swarmMs: 520,
      dustMotes: 130,
      dustSize: 2.6,
      dustAlpha: 0.85,
      dustBloomAlpha: 0.75,
      assembleMs: 1400,
      assembleCols: 10,
      assembleRows: 14,
      assembleSpread: 1,
      assembleStagger: 0.35,
      assembleSpin: 2.6,
      assembleScaleFrom: 0.62,
      // Where the rarity tint starts draining out of a piece, as a share of
      // its approach, and where the finished card starts coming up underneath
      // the assembly, as a share of `assembleMs`
      tintFrom: 0.55,
      handoverFrom: 0.6,
      snapMs: 420,
      // Share of the snap over which the pieces dissolve off the card
      dissolveSpan: 0.55,
      snapOvershoot: 0.1
      // Nothing is thrown at the card when it lands: the blast had its moment,
      // and a second one two seconds later fights the artwork instead of
      // presenting it
    },
    layout: {
      // Nothing is kept back by default: a host that draws over the stage says
      // how much of it it needs
      stage: {
        reserveTop: 0,
        reserveBottom: 0
      },
      pack: {
        widthRatio: 0.86,
        heightRatio: 0.66,
        offsetY: 0.07,
        anchor: "stage"
      },
      card: {
        heightRatio: 0.95,
        packWidthRatio: 0.64,
        aspect: 0.66,
        // The artwork's own shape, landscape too: past this its sides are cut
        maxRatio: 2,
        spinAt: "rest"
      },
      pedestal: {
        widthRatio: 1.15,
        aspect: 0.335,
        gapRatio: 0.077,
        clearanceRatio: 0.1
      },
      glow: {
        bloomScaleX: 3,
        bloomScaleY: 2.2,
        rimSpread: 40,
        rimPadding: 80,
        haloSpread: 56,
        haloPadding: 112
      }
    },
    performance: {
      maxFps: 60,
      idleFps: 30,
      sleepFps: 1,
      resolutionCap: 2,
      antialias: true
    }
  }
};

// src/core/variants/burst/scene.js
import { Container as Container6 } from "pixi.js";

// src/core/runtime/color.js
var clamp255 = (value) => Math.max(0, Math.min(255, Math.round(value)));
function parseColor(value) {
  if (typeof value !== "string") {
    return null;
  }
  const text = value.trim();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(text);
  if (hex) {
    const digits = hex[1];
    const full = digits.length === 3 ? digits.split("").map((c) => c + c).join("") : digits;
    const n = parseInt(full, 16);
    return { r: n >> 16 & 255, g: n >> 8 & 255, b: n & 255, a: 1 };
  }
  const rgb = /^rgba?\(([^)]+)\)$/i.exec(text);
  if (rgb) {
    const parts = rgb[1].split(",").map((p) => parseFloat(p));
    if (parts.length < 3 || parts.some((p) => Number.isNaN(p))) {
      return null;
    }
    return {
      r: clamp255(parts[0]),
      g: clamp255(parts[1]),
      b: clamp255(parts[2]),
      a: parts.length > 3 ? Math.max(0, Math.min(1, parts[3])) : 1
    };
  }
  return null;
}
function toNumber(value, fallback = 16777215) {
  const c = parseColor(value);
  return c ? c.r << 16 | c.g << 8 | c.b : fallback;
}
function mixNumbers(from, to, t) {
  const k = Math.max(0, Math.min(1, t));
  const r = (from >> 16 & 255) + ((to >> 16 & 255) - (from >> 16 & 255)) * k;
  const g = (from >> 8 & 255) + ((to >> 8 & 255) - (from >> 8 & 255)) * k;
  const b = (from & 255) + ((to & 255) - (from & 255)) * k;
  return Math.round(r) << 16 | Math.round(g) << 8 | Math.round(b);
}
function withAlpha(value, alpha) {
  const c = parseColor(value) || { r: 255, g: 255, b: 255, a: 1 };
  return `rgba(${c.r},${c.g},${c.b},${Math.max(0, Math.min(1, alpha))})`;
}
function alphaOf(value, fallback = 1) {
  const c = parseColor(value);
  return c ? c.a : fallback;
}

// src/core/variants/shared/pedestal.js
import { Sprite, Texture } from "pixi.js";
var CardPedestal = class {
  /** `sceneRoot` is the variant's own container. */
  constructor(sceneRoot, options) {
    this.sceneRoot = sceneRoot;
    this.o = options;
    this.texture = null;
    this.node = null;
    this.progress = 0;
    this.revealing = false;
  }
  setOptions(options) {
    this.o = options;
  }
  get built() {
    return !!this.node;
  }
  setTexture(texture) {
    this.texture = texture;
    if (this.node && texture) {
      this.node.texture = texture;
      this.fit();
    }
  }
  /**
   * Placed under where the card comes to rest, not under where it starts:
   * `centreX` is the card's column, `cardBottom` the lower edge of the card in
   * its final position, `cardWidth` what the stand is measured against.
   */
  build(centreX, cardBottom, cardWidth) {
    this.centreX = centreX;
    this.cardBottom = cardBottom;
    this.cardWidth = cardWidth;
    if (!this.node) {
      this.node = new Sprite(this.texture || Texture.EMPTY);
      this.node.anchor.set(0.5, 0);
      this.node.alpha = 0;
      this.sceneRoot.addChildAt(this.node, 0);
    }
    this.fit();
  }
  fit() {
    if (!this.node) {
      return;
    }
    const { widthRatio, aspect, gapRatio } = this.o.layout.pedestal;
    const given = this.o.rest?.pedestal;
    if (given) {
      const own2 = this.texture && this.texture.width > 0 ? this.texture.height / this.texture.width : aspect;
      const height = given.width * own2;
      this.node.width = given.width;
      this.node.height = height;
      this.node.position.set(given.left + given.width / 2, given.bottom - height);
      return;
    }
    const width = this.cardWidth * widthRatio;
    this.node.width = width;
    this.node.height = width * aspect;
    this.node.position.set(
      this.centreX,
      this.cardBottom + this.cardWidth * gapRatio
    );
  }
  /**
   * Starts the stand's own arrival. Called once the card has landed: it comes
   * in behind the card and ahead of whatever the host hangs under it, so the
   * eye goes card → stand → price.
   */
  reveal() {
    this.revealing = true;
  }
  update(deltaMS) {
    if (!this.node || !this.revealing || this.progress >= 1) {
      return;
    }
    this.progress = Math.min(
      1,
      this.progress + deltaMS / this.o.motion.reveal.pedestalMs
    );
    this.node.alpha = this.progress;
  }
  /** Where it ended up, so the host can lay its own UI out below it. */
  bounds() {
    if (!this.node) {
      return null;
    }
    const { width, height } = this.node;
    return {
      left: this.node.x - width / 2,
      right: this.node.x + width / 2,
      top: this.node.y,
      bottom: this.node.y + height,
      width,
      height
    };
  }
  rewind() {
    this.revealing = false;
    this.progress = 0;
    if (this.node) {
      this.node.alpha = 0;
    }
  }
  destroy() {
    this.node?.destroy();
    this.node = null;
  }
};

// src/core/variants/shared/card.js
import {
  Container,
  Graphics,
  MeshRope,
  PerspectiveMesh,
  Point,
  RenderTexture,
  Sprite as Sprite2,
  Texture as Texture3
} from "pixi.js";

// src/core/variants/shared/geometry.js
var clamp = (value, min, max) => value < min ? min : value > max ? max : value;
var jitterAt = (index, phase) => Math.sin(index * 1.73 + phase) * 0.6 + Math.sin(index * 4.31 + phase * 2.1) * 0.4;
var easeOut = (t) => 1 - Math.pow(1 - t, 3);
var easeInOut = (t) => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
function outlinePath(w, h, radius, perCorner = 8) {
  const r = Math.max(0, Math.min(radius, Math.min(w, h) / 2));
  const points = [];
  const corners = [
    { cx: w - r, cy: r, start: -Math.PI / 2 },
    { cx: w - r, cy: h - r, start: 0 },
    { cx: r, cy: h - r, start: Math.PI / 2 },
    { cx: r, cy: r, start: Math.PI }
  ];
  const straights = [
    [{ x: r, y: 0 }, { x: w - r, y: 0 }],
    [{ x: w, y: r }, { x: w, y: h - r }],
    [{ x: w - r, y: h }, { x: r, y: h }],
    [{ x: 0, y: h - r }, { x: 0, y: r }]
  ];
  for (let side = 0; side < 4; side++) {
    points.push(straights[side][0], straights[side][1]);
    const { cx, cy, start } = corners[side];
    for (let i = 1; i < perCorner; i++) {
      const angle = start + Math.PI / 2 * (i / perCorner);
      points.push({ x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) });
    }
  }
  const lengths = [0];
  let total = 0;
  for (let i = 1; i < points.length; i++) {
    total += Math.hypot(
      points[i].x - points[i - 1].x,
      points[i].y - points[i - 1].y
    );
    lengths.push(total);
  }
  const closing = Math.hypot(
    points[0].x - points[points.length - 1].x,
    points[0].y - points[points.length - 1].y
  );
  return { points, lengths, total: total + closing };
}
function pointAt(path, distance) {
  const { points, lengths, total } = path;
  let d = distance % total;
  if (d < 0) {
    d += total;
  }
  const lastLength = lengths[lengths.length - 1];
  if (d >= lastLength) {
    const last = points[points.length - 1];
    const first = points[0];
    const t2 = (d - lastLength) / (total - lastLength || 1);
    return { x: last.x + (first.x - last.x) * t2, y: last.y + (first.y - last.y) * t2 };
  }
  let lo = 0;
  let hi = lengths.length - 1;
  while (lo < hi - 1) {
    const mid = lo + hi >> 1;
    if (lengths[mid] <= d) {
      lo = mid;
    } else {
      hi = mid;
    }
  }
  const t = (d - lengths[lo]) / (lengths[hi] - lengths[lo] || 1);
  return {
    x: points[lo].x + (points[hi].x - points[lo].x) * t,
    y: points[lo].y + (points[hi].y - points[lo].y) * t
  };
}
function projectPoint(x, y, yaw, pitch, focal) {
  const x1 = x * Math.cos(yaw);
  const z1 = x * Math.sin(yaw);
  const y2 = y * Math.cos(pitch) - z1 * Math.sin(pitch);
  const z2 = y * Math.sin(pitch) + z1 * Math.cos(pitch);
  const k = focal / Math.max(focal * 0.2, focal + z2);
  return { x: x1 * k, y: y2 * k };
}
function computePackRect(width, height, aspect, pack, stage, anchorY) {
  const reservedTop = stage?.reserveTop ?? 0;
  const reservedBottom = stage?.reserveBottom ?? 0;
  const free = Math.max(1, height - reservedTop - reservedBottom);
  const maxWidth = width * pack.widthRatio;
  const maxHeight = free * pack.heightRatio;
  let w = maxWidth;
  let h = w / aspect;
  if (h > maxHeight) {
    h = maxHeight;
    w = h * aspect;
  }
  const left = (width - w) / 2;
  const centredInFree = reservedTop + (free - h) / 2 + free * pack.offsetY;
  const centredOnStage = (height - h) / 2 + height * pack.offsetY;
  const centred = clamp(
    Math.min(centredInFree, centredOnStage),
    reservedTop,
    reservedTop + free - h
  );
  const top = anchorY === void 0 ? centred : anchorY - h / 2;
  return {
    left,
    top,
    right: left + w,
    bottom: top + h,
    width: w,
    height: h
  };
}

// src/core/variants/shared/textures.js
import { Texture as Texture2 } from "pixi.js";
function makeCanvas(w, h) {
  const canvas = document.createElement("canvas");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.max(1, Math.ceil(w * dpr));
  canvas.height = Math.max(1, Math.ceil(h * dpr));
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  return { canvas, ctx };
}
var WHOLE = { left: 0, top: 0, right: 1, bottom: 1 };
function contentBoundsOf(texture) {
  try {
    const source = texture?.source?.resource;
    if (!source || !source.width) return WHOLE;
    const w = 128;
    const h = 256;
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(source, 0, 0, w, h);
    const data = ctx.getImageData(0, 0, w, h).data;
    let left = w;
    let right = -1;
    let top = h;
    let bottom = -1;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        if (data[(y * w + x) * 4 + 3] <= 24) continue;
        if (x < left) left = x;
        if (x > right) right = x;
        if (y < top) top = y;
        if (y > bottom) bottom = y;
      }
    }
    if (right < 0) return WHOLE;
    return { left: left / w, top: top / h, right: (right + 1) / w, bottom: (bottom + 1) / h };
  } catch {
    return WHOLE;
  }
}
var shows = (color) => alphaOf(color, 0) > 0;
function starPath(ctx, cx, cy, outer, inner, points = 4) {
  ctx.beginPath();
  for (let i = 0; i < points * 2; i++) {
    const angle = -Math.PI / 2 + i * Math.PI / points;
    const r = i % 2 === 0 ? outer : inner;
    const x = cx + Math.cos(angle) * r;
    const y = cy + Math.sin(angle) * r;
    if (i === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  }
  ctx.closePath();
}
function makeCometTexture(width) {
  const length = 256;
  const canvas = document.createElement("canvas");
  canvas.width = length;
  canvas.height = Math.max(2, Math.ceil(width));
  const ctx = canvas.getContext("2d");
  const image = ctx.createImageData(canvas.width, canvas.height);
  const data = image.data;
  const half = canvas.height / 2;
  const sigma = canvas.height / 4.5;
  for (let y = 0; y < canvas.height; y++) {
    const d = (y + 0.5 - half) / sigma;
    const across = Math.exp(-d * d * 0.5);
    for (let x = 0; x < length; x++) {
      const t = (x + 0.5) / length;
      const rise = t * t;
      const nose = t > 0.94 ? 1 - Math.pow((t - 0.94) / 0.06, 2) : 1;
      const alpha = Math.max(0, Math.min(1, rise * nose * across));
      const i = (y * length + x) * 4;
      data[i] = 255;
      data[i + 1] = 255;
      data[i + 2] = 255;
      data[i + 3] = Math.round(alpha * 255);
    }
  }
  ctx.putImageData(image, 0, 0);
  return Texture2.from(canvas);
}
function roundRectPath(ctx, x, y, w, h, r) {
  const radius = Math.max(0, Math.min(r, Math.min(w, h) / 2));
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + w, y, x + w, y + h, radius);
  ctx.arcTo(x + w, y + h, x, y + h, radius);
  ctx.arcTo(x, y + h, x, y, radius);
  ctx.arcTo(x, y, x + w, y, radius);
  ctx.closePath();
}
function drawBackPrint(ctx, w, h, radius, back) {
  if (!shows(back.line) && !shows(back.emblem)) {
    return;
  }
  if (shows(back.line)) {
    ctx.save();
    ctx.strokeStyle = back.line;
    ctx.lineWidth = 0.6;
    const step = Math.max(4, w / 30);
    ctx.beginPath();
    for (let d = -h; d < w + h; d += step) {
      ctx.moveTo(d, 0);
      ctx.lineTo(d + h, h);
      ctx.moveTo(d + h, 0);
      ctx.lineTo(d, h);
    }
    ctx.stroke();
    ctx.restore();
  }
  const vignette = ctx.createRadialGradient(
    w / 2,
    h / 2,
    Math.min(w, h) * 0.2,
    w / 2,
    h / 2,
    Math.max(w, h) * 0.7
  );
  vignette.addColorStop(0, "rgba(0,0,0,0)");
  vignette.addColorStop(1, "rgba(0,0,0,0.45)");
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, w, h);
  if (!shows(back.emblem)) {
    return;
  }
  const emblem = alphaOf(back.emblem, 1);
  ctx.save();
  ctx.strokeStyle = back.emblem;
  for (const [inset, width, alpha] of [
    [0.055, 1.2, 0.5],
    [0.085, 0.7, 0.25]
  ]) {
    const d = w * inset;
    ctx.globalAlpha = alpha;
    ctx.lineWidth = width;
    roundRectPath(ctx, d, d, w - d * 2, h - d * 2, Math.max(2, radius - d * 0.6));
    ctx.stroke();
  }
  const cx = w / 2;
  const cy = h / 2;
  ctx.globalAlpha = 0.28;
  ctx.lineWidth = 0.8;
  ctx.beginPath();
  ctx.arc(cx, cy, w * 0.27, 0, Math.PI * 2);
  ctx.stroke();
  ctx.globalAlpha = 0.6;
  ctx.lineWidth = 1.3;
  starPath(ctx, cx, cy, w * 0.21, w * 0.21 * 0.7, 4);
  ctx.stroke();
  const fill = ctx.createLinearGradient(0, cy - w * 0.16, 0, cy + w * 0.16);
  fill.addColorStop(0, withAlpha(back.emblem, emblem));
  fill.addColorStop(1, withAlpha(back.emblem, emblem * 0.45));
  ctx.globalAlpha = 1;
  ctx.fillStyle = fill;
  starPath(ctx, cx, cy, w * 0.16, w * 0.045, 4);
  ctx.fill();
  ctx.restore();
}
function makeCardBackTexture(w, h, theme) {
  const { canvas, ctx } = makeCanvas(w, h);
  roundRectPath(ctx, 0, 0, w, h, theme.cornerRadius);
  ctx.clip();
  const back = theme.cardBack;
  const base2 = ctx.createLinearGradient(0, 0, w, h);
  base2.addColorStop(0, back.top);
  base2.addColorStop(0.5, back.mid);
  base2.addColorStop(1, back.bottom);
  ctx.fillStyle = base2;
  ctx.fillRect(0, 0, w, h);
  drawBackPrint(ctx, w, h, theme.cornerRadius, back);
  const sheen = ctx.createLinearGradient(0, h, w, 0);
  sheen.addColorStop(0, withAlpha(back.sheen, 0));
  sheen.addColorStop(0.5, back.sheen);
  sheen.addColorStop(1, withAlpha(back.sheen, 0));
  ctx.fillStyle = sheen;
  ctx.fillRect(0, 0, w, h);
  return Texture2.from(canvas);
}
function makeBloomTexture(size, color) {
  const { canvas, ctx } = makeCanvas(size, size);
  const half = size / 2;
  const gradient = ctx.createRadialGradient(half, half, 0, half, half, half);
  gradient.addColorStop(0, withAlpha(color, 0.95));
  gradient.addColorStop(0.42, withAlpha(color, 0.3));
  gradient.addColorStop(1, withAlpha(color, 0));
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  return Texture2.from(canvas);
}
function makeShockwaveTexture(size, thickness, ragged) {
  const { canvas, ctx } = makeCanvas(size, size);
  const c = size / 2;
  const outer = c * 0.97;
  const inner = outer * (1 - Math.min(0.9, thickness));
  ctx.save();
  ctx.beginPath();
  const steps = 128;
  for (let i = 0; i <= steps; i++) {
    const angle = i / steps * Math.PI * 2;
    const wobble = Math.sin(angle * 5 + 0.7) * 0.6 + Math.sin(angle * 11 + 2.3) * 0.4;
    const r = outer * (1 - ragged * (0.5 + 0.5 * wobble));
    const x = c + Math.cos(angle) * r;
    const y = c + Math.sin(angle) * r;
    if (i === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  }
  ctx.closePath();
  ctx.clip();
  const gradient = ctx.createRadialGradient(c, c, inner * 0.9, c, c, outer);
  gradient.addColorStop(0, "rgba(255,255,255,0)");
  gradient.addColorStop(0.6, "rgba(255,255,255,0.06)");
  gradient.addColorStop(0.88, "rgba(255,255,255,0.9)");
  gradient.addColorStop(0.96, "rgba(255,255,255,0.4)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  ctx.restore();
  return Texture2.from(canvas);
}
function makeStarburstTexture(size, spread) {
  const { canvas, ctx } = makeCanvas(size, size);
  const c = size / 2;
  const rays = [
    { angle: 0, length: 1, width: 0.05 },
    { angle: Math.PI / 2, length: 0.62, width: 0.04 },
    { angle: Math.PI / 4, length: 0.3, width: 0.02 },
    { angle: -Math.PI / 4, length: 0.3, width: 0.02 }
  ];
  for (const ray of rays) {
    for (const direction of [1, -1]) {
      const length = c * ray.length * spread * direction;
      const width = c * ray.width;
      const dx = Math.cos(ray.angle) * length;
      const dy = Math.sin(ray.angle) * length;
      const nx = -Math.sin(ray.angle) * width;
      const ny = Math.cos(ray.angle) * width;
      const gradient = ctx.createLinearGradient(c, c, c + dx, c + dy);
      gradient.addColorStop(0, "rgba(255,255,255,0.95)");
      gradient.addColorStop(0.35, "rgba(255,255,255,0.35)");
      gradient.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.moveTo(c, c);
      ctx.lineTo(c + dx * 0.18 + nx, c + dy * 0.18 + ny);
      ctx.lineTo(c + dx, c + dy);
      ctx.lineTo(c + dx * 0.18 - nx, c + dy * 0.18 - ny);
      ctx.closePath();
      ctx.fill();
    }
  }
  const core = ctx.createRadialGradient(c, c, 0, c, c, c * 0.22);
  core.addColorStop(0, "rgba(255,255,255,1)");
  core.addColorStop(0.35, "rgba(255,255,255,0.6)");
  core.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = core;
  ctx.fillRect(0, 0, size, size);
  return Texture2.from(canvas);
}
function makeSheenTexture(w, h) {
  const { canvas, ctx } = makeCanvas(w, h);
  const gradient = ctx.createLinearGradient(0, 0, w, 0);
  gradient.addColorStop(0, "rgba(255,255,255,0)");
  gradient.addColorStop(0.38, "rgba(255,255,255,0.35)");
  gradient.addColorStop(0.5, "rgba(255,255,255,0.95)");
  gradient.addColorStop(0.62, "rgba(255,255,255,0.35)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, w, h);
  return Texture2.from(canvas);
}
function makeHaloTexture(w, h, color, spread, radius) {
  const { canvas, ctx } = makeCanvas(w + spread * 2, h + spread * 2);
  ctx.shadowColor = color;
  ctx.fillStyle = color;
  for (let i = 0; i < 3; i++) {
    ctx.shadowBlur = spread * (0.45 + i * 0.35);
    roundRectPath(ctx, spread, spread, w, h, radius);
    ctx.fill();
  }
  return Texture2.from(canvas);
}
function makeSilhouetteGlowTexture(texture, width, height, spread) {
  const source = texture?.source?.resource;
  if (!source || !source.width) {
    return null;
  }
  try {
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.ceil(width + spread * 2));
    canvas.height = Math.max(1, Math.ceil(height + spread * 2));
    const ctx = canvas.getContext("2d");
    const away = canvas.width * 2;
    ctx.shadowColor = "#ffffff";
    ctx.shadowOffsetX = away;
    for (let i = 0; i < 3; i++) {
      ctx.shadowBlur = spread * (0.3 + i * 0.35);
      ctx.drawImage(source, spread - away, spread, width, height);
    }
    ctx.shadowColor = "transparent";
    ctx.shadowBlur = 0;
    ctx.shadowOffsetX = 0;
    ctx.globalCompositeOperation = "destination-out";
    ctx.drawImage(source, spread, spread, width, height);
    return Texture2.from(canvas);
  } catch {
    return null;
  }
}
function makeSoftDotTexture(size) {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  const c = size / 2;
  const gradient = ctx.createRadialGradient(c, c, 0, c, c, c);
  gradient.addColorStop(0, "rgba(255,255,255,1)");
  gradient.addColorStop(0.25, "rgba(255,255,255,0.75)");
  gradient.addColorStop(0.6, "rgba(255,255,255,0.18)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  return Texture2.from(canvas);
}
function makeTwinkleTexture(size) {
  const { canvas, ctx } = makeCanvas(size, size);
  const c = size / 2;
  const rays = [
    { angle: 0, length: 1, width: 0.045 },
    { angle: Math.PI / 2, length: 1, width: 0.045 },
    { angle: Math.PI / 4, length: 0.38, width: 0.03 },
    { angle: -Math.PI / 4, length: 0.38, width: 0.03 }
  ];
  for (const ray of rays) {
    for (const direction of [1, -1]) {
      const length = c * ray.length * direction;
      const width = c * ray.width;
      const dx = Math.cos(ray.angle) * length;
      const dy = Math.sin(ray.angle) * length;
      const nx = -Math.sin(ray.angle) * width;
      const ny = Math.cos(ray.angle) * width;
      const gradient = ctx.createLinearGradient(c, c, c + dx, c + dy);
      gradient.addColorStop(0, "rgba(255,255,255,1)");
      gradient.addColorStop(0.4, "rgba(255,255,255,0.4)");
      gradient.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.moveTo(c, c);
      ctx.lineTo(c + dx * 0.12 + nx, c + dy * 0.12 + ny);
      ctx.lineTo(c + dx, c + dy);
      ctx.lineTo(c + dx * 0.12 - nx, c + dy * 0.12 - ny);
      ctx.closePath();
      ctx.fill();
    }
  }
  const core = ctx.createRadialGradient(c, c, 0, c, c, c * 0.16);
  core.addColorStop(0, "rgba(255,255,255,1)");
  core.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = core;
  ctx.fillRect(0, 0, size, size);
  return Texture2.from(canvas);
}
var EMBLEM_GLOW_SPAN = 0.7;
function makeEmblemGlowTexture(size) {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  const c = size / 2;
  const unit = size / EMBLEM_GLOW_SPAN;
  ctx.shadowColor = "#ffffff";
  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = "#ffffff";
  for (let i = 0; i < 3; i++) {
    ctx.shadowBlur = unit * (0.02 + i * 0.035);
    starPath(ctx, c, c, unit * 0.16, unit * 0.045, 4);
    ctx.fill();
    ctx.lineWidth = unit * 0.012;
    starPath(ctx, c, c, unit * 0.21, unit * 0.21 * 0.7, 4);
    ctx.stroke();
  }
  return Texture2.from(canvas);
}

// src/core/variants/shared/card.js
var MESH_GRID = 10;
var RIBBON_POINTS = 96;
function tailBelow(width, o) {
  const pedestal = o.layout.pedestal;
  return pedestal ? width * pedestal.gapRatio + width * pedestal.widthRatio * pedestal.aspect + width * (pedestal.clearanceRatio ?? 0) : 0;
}
function restFor(width, screen, o) {
  const stage = o.layout.stage;
  const tail = tailBelow(width, o);
  const top = stage?.reserveTop ?? 0;
  const available = screen.height - top - (stage?.reserveBottom ?? 0);
  const centred = top + available / 2 - tail / 2;
  return Math.min(centred, screen.height / 2 - tail / 2);
}
function cardLayoutFor(rect, screen, aspect, o) {
  const ratio = Math.min(aspect, o.layout.card.maxRatio);
  const box = o.rest?.card;
  if (box) {
    const fitByHeight = ratio <= box.width / box.height;
    const height2 = fitByHeight ? box.height : box.width / ratio;
    const width2 = fitByHeight ? height2 * ratio : box.width;
    return { width: width2, height: height2, restY: box.top + box.height - height2 / 2 };
  }
  let height = rect.height * o.layout.card.heightRatio;
  let width = height * ratio;
  const maxWidth = rect.width * o.layout.card.packWidthRatio;
  if (width > maxWidth) {
    width = maxWidth;
    height = width / ratio;
  }
  const stage = o.layout.stage;
  const reservedTop = stage?.reserveTop ?? 0;
  const available = screen.height - reservedTop - (stage?.reserveBottom ?? 0);
  const tailRatio = tailBelow(width, o) / height;
  const room = Math.min(available, screen.height - 2 * reservedTop);
  const maxHeight = room / (1 + tailRatio);
  if (height > maxHeight && maxHeight > 0) {
    const fit = maxHeight / height;
    width *= fit;
    height *= fit;
  }
  return { width, height, restY: restFor(width, screen, o) };
}
var RevealCard = class {
  /** `sceneRoot` is the variant's own container, `screen` the renderer's size. */
  constructor(sceneRoot, screen, options, colors) {
    this.sceneRoot = sceneRoot;
    this.screen = screen;
    this.o = options;
    this.colors = colors;
    this.texture = null;
    this.node = null;
    this.renderer = null;
  }
  setOptions(options, colors) {
    this.o = options;
    this.colors = colors;
    if (this.halo) {
      this.halo.tint = colors.glow;
    }
  }
  /**
   * Turn the card in perspective rather than squeezing it: its two sides
   * become meshes whose corners are projected every frame, so the edge
   * turning away gets shorter as it would on a real card. Needs the renderer
   * — the artwork's rounded face is baked into a texture a mesh can carry.
   * Called once, before the first `build`.
   */
  useDepth(renderer) {
    this.renderer = renderer;
  }
  /** Built once — a replay reuses the same card and just rewinds it. */
  get built() {
    return !!this.node;
  }
  get hasArt() {
    return !!this.texture;
  }
  get height() {
    return this.size.height;
  }
  /**
   * The artwork, whenever it arrives. A card built before it did was sized to
   * a guess at its shape (`layout.card.aspect`), and artwork of another shape
   * was cover-fitted into the guess — a slab lost the top and bottom of its
   * frame. So a card whose face has not been shown yet is built again to the
   * artwork's own shape. True when it was: the scene lays out again what it
   * placed against the card.
   *
   * `defer`: the card is on show face down, and built again in front of the
   * player it would jump from one size to the other. It waits instead for
   * the moment it turns edge-on in `flipOver`, where it has no width to be
   * seen by and the face is about to show for the first time.
   */
  setTexture(texture, { defer = false } = {}) {
    this.texture = texture;
    if (!this.face || !texture) {
      return false;
    }
    if (this.face.alpha === 0 && !this.landed && !this.turnedOver && this.misfits(texture)) {
      if (defer) {
        this.refitDue = true;
        return false;
      }
      this.refit();
      return true;
    }
    this.face.texture = texture;
    this.fitFace();
    this.bakeFace();
    return false;
  }
  /** Whether the card was built to a shape the artwork does not have. */
  misfits(texture) {
    if (!texture.width || !texture.height) {
      return false;
    }
    const { width, height } = cardLayoutFor(
      this.rect,
      this.screen,
      texture.width / texture.height,
      this.o
    );
    return Math.abs(width - this.size.width) > 0.5 || Math.abs(height - this.size.height) > 0.5;
  }
  /**
   * Built again to the artwork's shape, from where the card is now: its
   * place, its presence, its layer and the clip at the lip — and where it
   * comes to rest, which moves with its size. The phase that is playing
   * draws the rest on its next frame.
   */
  refit() {
    const { x, y } = this.node;
    const alpha = this.node.alpha;
    const scale = this.node.scale.x;
    const layer = this.sceneRoot.getChildIndex(this.node);
    const clipped = this.turn.mask === this.clipG;
    const { clipBottom, fromY, spinY } = this;
    const turnsAtPack = this.lifts;
    const focalRatio = this.focal ? this.focal / this.size.height : null;
    this.destroy();
    this.build(this.rect);
    if (focalRatio) {
      this.focal = focalRatio * this.size.height;
    }
    this.sceneRoot.setChildIndex(
      this.node,
      Math.min(layer, this.sceneRoot.children.length - 1)
    );
    this.node.position.set(x, y);
    this.node.alpha = alpha;
    this.node.scale.set(scale);
    if (clipped) {
      this.turn.mask = this.clipG;
      this.clip(clipBottom);
    }
    if (this.placed) {
      this.fromY = fromY;
      this.toY = this.restingY();
      this.spinY = turnsAtPack ? spinY : this.toY;
    }
  }
  /** Whether the card has been put somewhere to come out from (`park` or `place`). */
  get placed() {
    return this.fromY !== void 0;
  }
  /**
   * The artwork as the mesh shows it while the card turns: cover-fitted and
   * rounded exactly like the flat face, rendered once into a texture of its
   * own. Multisampled, because the corners are cut by a mask, and a mask
   * rendered off screen without it leaves them stepped.
   */
  bakeFace() {
    if (!this.renderer || !this.faceMesh) {
      return;
    }
    const { width, height } = this.size;
    const holder = new Container();
    const art = new Sprite2(this.texture || Texture3.WHITE);
    art.anchor.set(0.5);
    art.position.set(width / 2, height / 2);
    if (this.texture && this.texture.width) {
      art.scale.set(
        Math.max(width / this.texture.width, height / this.texture.height)
      );
    } else {
      art.width = width;
      art.height = height;
    }
    const corners = new Graphics().roundRect(0, 0, width, height, this.o.theme.cornerRadius).fill(16777215);
    art.mask = corners;
    holder.addChild(art, corners);
    const target = RenderTexture.create({
      width,
      height,
      resolution: this.renderer.resolution,
      antialias: true
    });
    this.renderer.render({ container: holder, target, clear: true });
    holder.destroy({ children: true });
    this.faceBaked?.destroy(true);
    this.faceBaked = target;
    this.faceMesh.texture = target;
  }
  /** Cover-fits the artwork into the card frame. */
  fitFace() {
    const texture = this.face?.texture;
    if (!texture || !texture.width) {
      return;
    }
    const { width, height } = this.size;
    const scale = Math.max(width / texture.width, height / texture.height);
    this.face.width = texture.width * scale;
    this.face.height = texture.height * scale;
    this.face.position.set(0, 0);
  }
  /** Where the card would come to rest for `rect`, before any card is built. */
  static restingCentre(screen, rect, options) {
    return cardLayoutFor(rect, screen, options.layout.card.aspect, options).restY;
  }
  build(rect) {
    this.rect = rect;
    const aspect = this.texture ? this.texture.width / this.texture.height : this.o.layout.card.aspect;
    const { width, height } = cardLayoutFor(rect, this.screen, aspect, this.o);
    this.size = { width, height };
    this.node = new Container();
    const box = this.o.rest?.card;
    this.node.position.set(
      box ? box.left + box.width / 2 : rect.left + rect.width / 2,
      rect.top + rect.height / 2
    );
    this.node.alpha = 0;
    this.sceneRoot.addChildAt(this.node, 0);
    const glow = this.o.layout.glow;
    this.bloom = new Sprite2(makeBloomTexture(512, this.o.theme.bloom));
    this.bloom.anchor.set(0.5);
    this.bloom.width = width * glow.bloomScaleX;
    this.bloom.height = height * glow.bloomScaleY;
    this.bloom.blendMode = "add";
    this.bloom.alpha = 0;
    this.rim = new Sprite2(
      makeHaloTexture(
        width,
        height,
        this.o.theme.rim,
        glow.rimSpread,
        this.o.theme.cornerRadius
      )
    );
    this.rim.anchor.set(0.5);
    this.rim.width = width + glow.rimPadding;
    this.rim.height = height + glow.rimPadding;
    this.rim.blendMode = "add";
    this.rim.alpha = 0;
    this.halo = new Sprite2(
      makeHaloTexture(
        width,
        height,
        "#ffffff",
        glow.haloSpread,
        this.o.theme.cornerRadius
      )
    );
    this.halo.tint = this.colors.glow;
    this.halo.anchor.set(0.5);
    this.halo.width = width + glow.haloPadding;
    this.halo.height = height + glow.haloPadding;
    this.halo.blendMode = "add";
    this.halo.alpha = 0;
    this.turn = new Container();
    this.face = new Sprite2(this.texture || Texture3.WHITE);
    this.face.anchor.set(0.5);
    const faceMask = new Graphics().roundRect(-width / 2, -height / 2, width, height, this.o.theme.cornerRadius).fill(16777215);
    this.face.mask = faceMask;
    this.back = new Sprite2(makeCardBackTexture(width, height, this.o.theme));
    this.back.anchor.set(0.5);
    this.back.width = width;
    this.back.height = height;
    this.backMask = new Graphics();
    this.back.mask = this.backMask;
    const reveal = this.o.motion.reveal;
    this.sheen = new Sprite2(
      makeSheenTexture(Math.round(width * reveal.sheenWidth), Math.round(height * 2))
    );
    this.sheen.anchor.set(0.5);
    this.sheen.width = width * reveal.sheenWidth;
    this.sheen.height = height * 2.2;
    this.sheen.blendMode = "add";
    this.sheen.alpha = 0;
    this.sheen.visible = false;
    this.sheen.rotation = reveal.sheenTilt;
    const sheenMask = new Graphics().roundRect(-width / 2, -height / 2, width, height, this.o.theme.cornerRadius).fill(16777215);
    this.sheen.mask = sheenMask;
    this.beam = new Graphics();
    this.beamPath = outlinePath(
      width,
      height,
      this.o.theme.cornerRadius,
      this.o.motion.reveal.outlineDetail
    );
    this.turn.addChild(
      this.face,
      faceMask,
      this.back,
      this.backMask,
      this.sheen,
      sheenMask,
      this.beam
    );
    this.node.addChild(this.bloom, this.rim, this.halo, this.turn);
    this.clipG = new Graphics();
    this.sceneRoot.addChild(this.clipG);
    this.restX = this.node.x;
    this.rim.baseScaleX = this.rim.scale.x;
    this.glowBase = {
      rim: { x: this.rim.scale.x, y: this.rim.scale.y },
      halo: { x: this.halo.scale.x, y: this.halo.scale.y }
    };
    this.bloomBase = { x: this.bloom.scale.x, y: this.bloom.scale.y };
    this.face.alpha = 0;
    this.drawBackMask(1);
    this.fitFace();
    if (this.renderer) {
      this.buildDepth(width);
    }
  }
  /**
   * The two sides as meshes, the printed star's light over the back and the
   * glints that catch on the artwork once it lands. The flat back stays in
   * the tree for the mechanics that flip flat, but is not shown.
   */
  buildDepth(width) {
    this.backMesh = new PerspectiveMesh({
      texture: this.back.texture,
      verticesX: MESH_GRID,
      verticesY: MESH_GRID
    });
    this.faceMesh = new PerspectiveMesh({
      texture: Texture3.WHITE,
      verticesX: MESH_GRID,
      verticesY: MESH_GRID
    });
    this.faceMesh.visible = false;
    this.emblem = new Sprite2(makeEmblemGlowTexture(128));
    this.emblem.anchor.set(0.5);
    this.emblem.width = width * EMBLEM_GLOW_SPAN;
    this.emblem.height = width * EMBLEM_GLOW_SPAN;
    this.emblem.blendMode = "add";
    this.emblem.alpha = 0;
    this.emblemBase = this.emblem.scale.x;
    this.twinkleTexture = makeTwinkleTexture(64);
    this.twinkles = [];
    this.back.visible = false;
    const at = this.turn.getChildIndex(this.backMask) + 1;
    this.turn.addChildAt(this.backMesh, at);
    this.turn.addChildAt(this.faceMesh, at + 1);
    this.turn.addChildAt(this.emblem, at + 2);
    this.bakeFace();
    this.pose(0, 0, 1);
  }
  /**
   * Stands the card at `yaw` / `pitch`, `lift` times its size: the side that
   * faces the eye shown as a mesh in perspective, the other hidden, and the
   * rim and halo stretched over the box the turned card covers — glows that
   * stay square while the card turns read as belonging to something else.
   * The projection is kept, so the beam can follow the same outline
   * (`viewPoint`).
   */
  pose(yaw, pitch, lift) {
    const { width, height } = this.size;
    const focal = this.focal ?? height * 3;
    const hw = width / 2 * lift;
    const hh = height / 2 * lift;
    const tl = projectPoint(-hw, -hh, yaw, pitch, focal);
    const tr = projectPoint(hw, -hh, yaw, pitch, focal);
    const br = projectPoint(hw, hh, yaw, pitch, focal);
    const bl = projectPoint(-hw, hh, yaw, pitch, focal);
    const facing = Math.cos(yaw) >= 0;
    this.backMesh.visible = facing;
    this.faceMesh.visible = !facing;
    if (facing) {
      this.backMesh.setCorners(tl.x, tl.y, tr.x, tr.y, br.x, br.y, bl.x, bl.y);
    } else {
      this.faceMesh.setCorners(tr.x, tr.y, tl.x, tl.y, bl.x, bl.y, br.x, br.y);
    }
    const minX = Math.min(tl.x, tr.x, br.x, bl.x);
    const maxX = Math.max(tl.x, tr.x, br.x, bl.x);
    const minY = Math.min(tl.y, tr.y, br.y, bl.y);
    const maxY = Math.max(tl.y, tr.y, br.y, bl.y);
    const sx = Math.max((maxX - minX) / width, 0.04);
    const sy = (maxY - minY) / height;
    for (const [glow, base2] of [
      [this.rim, this.glowBase.rim],
      [this.halo, this.glowBase.halo]
    ]) {
      glow.scale.set(base2.x * sx, base2.y * sy);
      glow.position.set((minX + maxX) / 2, (minY + maxY) / 2);
    }
    this.emblem.visible = facing;
    this.emblem.scale.set(
      this.emblemBase * lift * Math.abs(Math.cos(yaw)),
      this.emblemBase * lift
    );
    this.projection = { yaw, pitch, lift, focal };
  }
  /**
   * A point of the card's outline — in the card's own box, `0..width` across —
   * where it is drawn: through the pose while the card is turned, straight
   * about the centre otherwise.
   */
  viewPoint(x, y) {
    const { width, height } = this.size;
    const view = this.projection;
    if (!view) {
      return { x: x - width / 2, y: y - height / 2 };
    }
    return projectPoint(
      (x - width / 2) * view.lift,
      (y - height / 2) * view.lift,
      view.yaw,
      view.pitch,
      view.focal
    );
  }
  /** Everything above `bottomY` is visible; the rest is still in the wrapper. */
  clip(bottomY) {
    this.clipBottom = bottomY;
    const { width, height } = this.screen;
    this.clipG.clear().rect(-width, -height, width * 3, height + bottomY).fill(16777215);
  }
  /** `visible` is the share of the back still covering the card, top-down. */
  drawBackMask(visible) {
    const { width, height } = this.size;
    const covered = height * visible;
    this.backMask.clear();
    if (covered <= 0) {
      return;
    }
    this.backMask.rect(-width / 2 - 4, height / 2 - covered, width + 8, covered).fill(16777215);
  }
  /**
   * `progress` runs the beam around the outline, `settled` fades the rim in.
   * Every point goes through `viewPoint`, so on a card turned in perspective the
   * beam runs the outline the eye sees rather than the square one.
   */
  drawBeam(progress, settled) {
    const { width, height } = this.size;
    const path = this.beamPath;
    const color = this.colors.glow;
    const reveal = this.o.motion.reveal;
    this.beam.clear();
    if (settled > 0) {
      if (this.projection) {
        const outline = path.points.map((p) => this.viewPoint(p.x, p.y));
        this.beam.poly(outline.flatMap((p) => [p.x, p.y]), true);
      } else {
        this.beam.roundRect(
          -width / 2,
          -height / 2,
          width,
          height,
          this.o.theme.cornerRadius
        );
      }
      this.beam.stroke({
        width: reveal.beamWidth,
        color,
        alpha: reveal.beamAlpha * settled,
        join: "round",
        alignment: 0
      });
    }
    if (progress <= 0 || progress >= 1) {
      this.hideRibbon();
      return;
    }
    const head = progress * path.total;
    const tail = path.total * reveal.beamTail;
    if (reveal.beamStyle === "ribbon") {
      this.drawRibbon(head, tail);
      return;
    }
    this.hideRibbon();
    const steps = reveal.beamSteps;
    for (let i = 0; i < steps; i++) {
      const t0 = i / steps;
      const t1 = (i + 1) / steps;
      const a = pointAt(path, head - tail * (1 - t0));
      const b = pointAt(path, head - tail * (1 - t1));
      const p0 = this.viewPoint(a.x, a.y);
      const p1 = this.viewPoint(b.x, b.y);
      const alpha = t1 * t1;
      this.beam.moveTo(p0.x, p0.y).lineTo(p1.x, p1.y).stroke({
        width: reveal.beamGlowWidth,
        color,
        alpha: alpha * reveal.beamGlowAlpha,
        cap: "round"
      }).moveTo(p0.x, p0.y).lineTo(p1.x, p1.y).stroke({
        width: reveal.beamWidth,
        color: this.colors.beam,
        alpha,
        cap: "round"
      });
    }
    const end = pointAt(path, head);
    const tip = this.viewPoint(end.x, end.y);
    this.beam.circle(tip.x, tip.y, reveal.beamTipRadius).fill({ color: this.colors.beam, alpha: reveal.beamAlpha });
  }
  /**
   * The beam in one piece. Each short stroke above is drawn on its own, and
   * once the card is big — a desktop stage — the round caps stop overlapping
   * and the trail reads as a row of dots. A rope lays one soft gradient along
   * the outline instead, continuous at any size: the wide glow in the rarity
   * colour, the bright core over it, the head rounded off by the texture so
   * no tip has to be drawn. Built the first time it is asked for, so a scene
   * that never draws it never carries it.
   */
  drawRibbon(head, tail) {
    const reveal = this.o.motion.reveal;
    if (!this.ribbon) {
      const points2 = [];
      for (let i = 0; i < RIBBON_POINTS; i++) {
        points2.push(new Point(0, 0));
      }
      const glow2 = new MeshRope({
        texture: makeCometTexture(reveal.beamGlowWidth * 3),
        points: points2
      });
      glow2.blendMode = "add";
      const core2 = new MeshRope({
        texture: makeCometTexture(reveal.beamWidth * 3),
        points: points2
      });
      this.turn.addChild(glow2, core2);
      this.ribbon = { points: points2, glow: glow2, core: core2 };
    }
    const { points, glow, core } = this.ribbon;
    const last = points.length - 1;
    for (let i = 0; i <= last; i++) {
      const p = pointAt(this.beamPath, head - tail * (1 - i / last));
      const at = this.viewPoint(p.x, p.y);
      points[i].set(at.x, at.y);
    }
    glow.tint = this.colors.glow;
    glow.alpha = Math.min(1, reveal.beamGlowAlpha * 2);
    core.tint = this.colors.beam;
    core.alpha = reveal.beamAlpha;
    glow.visible = true;
    core.visible = true;
  }
  hideRibbon() {
    if (this.ribbon) {
      this.ribbon.glow.visible = false;
      this.ribbon.core.visible = false;
    }
  }
  /** Where the card settles — see `restFor`; on the host's box's bottom edge when it gave one. */
  restingY() {
    const box = this.o.rest?.card;
    if (box) return box.top + box.height - this.size.height / 2;
    return restFor(this.size.width, this.screen, this.o);
  }
  /** Where the card came to rest, so React Native can build its UI around it. */
  bounds() {
    const { width, height } = this.size;
    const x = this.node.x;
    return {
      left: x - width / 2,
      right: x + width / 2,
      top: this.toY - height / 2,
      bottom: this.toY + height / 2,
      width,
      height
    };
  }
  /**
   * The card and its glow. `t` is the whole open timeline: the glow leads, so by
   * the time the card clears the lip it is already lit — catching up afterwards
   * looked like the card switched its light on late. `bloomLevel` and
   * `bloomTint` let a mechanic keep that light low and warm, for a card whose
   * own colour is still to come.
   */
  slide(t, bloomLevel = 1, bloomTint = 16777215) {
    const glow = clamp(t / this.o.motion.open.cardFrom, 0, 1);
    this.bloom.alpha = glow * bloomLevel;
    this.bloom.tint = bloomTint;
    this.rim.alpha = glow * this.o.motion.reveal.rimAlpha;
    const p = clamp((t - this.o.motion.open.cardFrom) / (1 - this.o.motion.open.cardFrom), 0, 1);
    const eased = easeOut(p);
    const target = this.spinY ?? this.toY;
    this.node.y = this.fromY + (target - this.fromY) * eased;
  }
  /**
   * The flat phases other mechanics build their reveal from: `spinHold` — the
   * card turning on at one steady speed while its artwork is on its way, a
   * whole turn per hold so it can run on for as many as it takes; `flip` —
   * half a turn from the back to the artwork; `hold` — the finished card with
   * its halo and lit outline.
   */
  reveal(kind, t) {
    const reveal = this.o.motion.reveal;
    if (kind === "spinHold") {
      const cos = Math.cos(Math.PI * 2 * t);
      const flat = Math.max(Math.abs(cos), reveal.spinFlatness);
      this.turn.scale.x = flat;
      const shade = 1 - reveal.spinShade + reveal.spinShade * Math.abs(cos);
      const tint = Math.round(255 * shade);
      this.back.tint = tint << 16 | tint << 8 | tint;
      this.bloom.alpha = reveal.spinBloom + (1 - reveal.spinBloom) * Math.abs(cos);
      this.rim.alpha = reveal.rimAlpha;
      this.rim.scale.x = this.rim.baseScaleX * flat;
      return;
    }
    if (kind === "flip") {
      const eased = easeInOut(t);
      const angle = Math.PI * eased;
      const cos = Math.cos(angle);
      const flat = Math.max(Math.abs(cos), reveal.spinFlatness);
      this.node.y = this.toY;
      this.turn.scale.x = flat;
      this.turn.mask = null;
      const past = cos < 0;
      this.face.alpha = past ? 1 : 0;
      this.drawBackMask(past ? 0 : 1);
      const shade = 1 - reveal.spinShade + reveal.spinShade * Math.abs(cos);
      const tint = Math.round(255 * shade);
      this.back.tint = tint << 16 | tint << 8 | tint;
      this.rim.alpha = reveal.rimAlpha;
      this.rim.scale.x = this.rim.baseScaleX * flat;
      const landing = clamp((t - 0.5) * 2, 0, 1);
      this.halo.alpha = reveal.haloAlpha * landing;
      this.bloom.alpha = reveal.bloomAlpha * (1 - eased);
      this.pulse(Math.sin(Math.PI * landing) * 0.6);
      return;
    }
    if (kind === "hold") {
      this.drawBeam(1, 1);
      this.halo.alpha = reveal.haloAlpha;
    }
  }
  /**
   * Face down at rest, gathering itself before it turns — a card built with
   * `useDepth`. It sways a little in perspective, a beam in its colour runs
   * the edge faster and faster, the printed star and the halo fill with that
   * colour, and towards the end it trembles. `level` runs 0..1 over the
   * build-up and stays at 1 while the artwork is late; `clock` is ms since it
   * began, so the sway and the beam carry on unbroken through the wait. `fx`
   * is the mechanic's own numbers (`slice`).
   */
  charge(level, clock, fx, colors) {
    const reveal = this.o.motion.reveal;
    const energy = level * level;
    this.focal = fx.focal * this.size.height;
    const tilt = fx.tiltDeg * Math.PI / 180;
    const sway = 2 * Math.PI * clock / fx.tiltMs;
    const yaw = tilt * Math.sin(sway);
    const pitch = tilt * 0.45 * Math.cos(sway * 0.77);
    this.turnedFrom = { yaw, pitch };
    this.pose(yaw, pitch, 1 + 0.02 * energy);
    const shake = fx.tremble * clamp((level - 0.55) / 0.45, 0, 1);
    this.node.x = this.restX + shake * Math.sin(clock * 0.083);
    this.node.y = this.spinY + shake * Math.cos(clock * 0.107);
    const flicker = 1 + 0.12 * energy * Math.sin(clock * 0.021);
    this.bloom.tint = mixNumbers(colors.seam, colors.glow, energy);
    this.bloom.alpha = reveal.bloomAlpha * (0.3 + 0.45 * energy) * flicker;
    this.rim.alpha = reveal.rimAlpha * (0.45 + 0.55 * energy);
    this.halo.alpha = Math.min(
      1,
      reveal.haloAlpha * fx.chargeHalo * energy * flicker
    );
    this.emblem.tint = colors.glow;
    this.emblem.alpha = Math.min(1, fx.emblemAlpha * (0.2 + 0.8 * energy) * flicker);
    const laps = fx.chargeLaps * Math.pow(clock / fx.chargeMs, 1.5);
    this.drawBeam(laps % 1, 0.2 + 0.8 * energy);
  }
  /** The turn starts from wherever the sway left the card, so it never jumps. */
  beginFlip() {
    this.flipFrom = this.turnedFrom ?? { yaw: 0, pitch: 0 };
  }
  /**
   * Half a turn in perspective, the card coming up towards the eye as it goes
   * and settling back as the artwork squares up. Its own light flares as the
   * edge passes — the moment the colour is the whole card — and the beam
   * hands its light over to the turn.
   *
   * A card still waiting to be built to its artwork's shape (`setTexture`
   * with `defer`) is built again on the frame it passes edge-on. True then:
   * the scene lays out again what it placed against the card.
   */
  flipOver(t, fx, colors) {
    const reveal = this.o.motion.reveal;
    const from = this.flipFrom ?? { yaw: 0, pitch: 0 };
    const eased = easeInOut(t);
    const arc = Math.sin(Math.PI * t);
    const yaw = from.yaw + (Math.PI - from.yaw) * eased;
    const edgeOnPassed = Math.cos(yaw) <= 0;
    const refitted = edgeOnPassed && this.refitDue;
    if (refitted) {
      this.refitDue = false;
      this.refit();
    }
    this.turnedOver = edgeOnPassed;
    this.pose(yaw, from.pitch * (1 - eased), 1 + fx.flipLift * arc);
    this.node.x = this.restX;
    this.node.y = this.spinY - this.size.height * fx.flipRise * arc;
    const edge = Math.exp(-Math.pow((t - 0.5) / 0.2, 2));
    this.bloom.tint = colors.glow;
    this.bloom.alpha = Math.min(
      1,
      reveal.bloomAlpha * (0.75 + fx.flipFlare * edge)
    );
    this.bloom.scale.set(
      this.bloomBase.x * (1 + 0.18 * edge),
      this.bloomBase.y * (1 + 0.18 * edge)
    );
    this.rim.alpha = reveal.rimAlpha * (0.3 + 0.7 * Math.abs(Math.cos(yaw)));
    this.halo.alpha = Math.min(
      1,
      reveal.haloAlpha * (fx.chargeHalo + (1 - fx.chargeHalo) * eased)
    );
    this.emblem.alpha = fx.emblemAlpha * clamp(1 - eased * 2.2, 0, 1);
    this.drawBeam(0, clamp(1 - t * 2.5, 0, 1));
    return refitted;
  }
  /**
   * The artwork squared up, landing: a push out and back, its outline
   * swelling, the highlight crossing it and glints catching on it one after
   * another. `elapsed` is ms since it landed. The meshes hand over to the flat
   * face at the first frame — the same pixels, square — so the card at rest
   * is the one every mechanic ends on.
   */
  land(t, elapsed, fx) {
    const reveal = this.o.motion.reveal;
    if (!this.landed) {
      this.squareUp();
    }
    const push = clamp(t / 0.5, 0, 1);
    this.setScale(1 + fx.landPunch * Math.sin(Math.PI * push) * (1 - push * 0.4));
    if (this.lifts) {
      this.node.y = this.spinY + (this.toY - this.spinY) * easeInOut(t);
    }
    this.pulse(Math.sin(Math.PI * clamp(t / 0.75, 0, 1)));
    this.sweepSheen(clamp((elapsed - 60) / reveal.sheenMs, 0, 1));
    this.twinkle(elapsed, fx);
    this.bloom.alpha = reveal.bloomAlpha * (0.2 + 0.8 * Math.pow(1 - t, 2));
    this.bloom.scale.set(this.bloomBase.x, this.bloomBase.y);
    this.drawBeam(0, clamp(t * 2, 0, 1));
  }
  /** From the meshes to the flat card: artwork up, glows square, no projection. */
  squareUp() {
    this.landed = true;
    this.projection = null;
    this.backMesh.visible = false;
    this.faceMesh.visible = false;
    this.emblem.visible = false;
    this.face.alpha = 1;
    this.node.x = this.restX;
    this.rim.position.set(0, 0);
    this.halo.position.set(0, 0);
    this.rim.scale.set(this.glowBase.rim.x, this.glowBase.rim.y);
    this.halo.scale.set(this.glowBase.halo.x, this.glowBase.halo.y);
  }
  /**
   * Glints on the artwork: four-pointed stars that flash up and go, one after
   * another, all of them over within the landing. Scattered by a fixed noise,
   * so the same card catches the light in the same places every time.
   */
  twinkle(elapsed, fx) {
    const count = Math.max(0, Math.round(fx.twinkles));
    while (this.twinkles.length < count) {
      const glint = new Sprite2(this.twinkleTexture);
      glint.anchor.set(0.5);
      glint.blendMode = "add";
      glint.visible = false;
      this.turn.addChild(glint);
      this.twinkles.push(glint);
    }
    const { width, height } = this.size;
    const span = Math.max(0, fx.landMs - fx.twinkleMs - 80);
    this.twinkles.forEach((glint, i) => {
      const start = 60 + (count > 1 ? span * i / (count - 1) : 0);
      const u = (elapsed - start) / fx.twinkleMs;
      if (i >= count || u <= 0 || u >= 1) {
        glint.visible = false;
        return;
      }
      const flash = Math.sin(Math.PI * u);
      const size = fx.twinkleSize * (0.7 + 0.5 * Math.abs(jitterAt(i, 7.7))) * flash;
      glint.visible = true;
      glint.position.set(
        width * 0.4 * jitterAt(i, 2.3),
        height * 0.42 * jitterAt(i, 5.1)
      );
      glint.width = size;
      glint.height = size;
      glint.rotation = i + u * 0.6;
      glint.alpha = flash;
      glint.tint = this.colors.spark;
    });
  }
  hideTwinkles() {
    for (const glint of this.twinkles ?? []) {
      glint.visible = false;
    }
  }
  /** Puts the revealed card back inside the pack so a replay starts clean. */
  rewind(rect) {
    if (!this.node) {
      return;
    }
    if (this.refitDue) {
      this.refitDue = false;
      this.refit();
    }
    this.turnedOver = false;
    this.node.alpha = 0;
    this.node.x = this.restX;
    this.node.y = rect.top + rect.height / 2;
    this.node.scale.set(1);
    this.bloom.alpha = 0;
    this.bloom.tint = 16777215;
    this.bloom.scale.set(this.bloomBase.x, this.bloomBase.y);
    this.rim.alpha = 0;
    this.rim.position.set(0, 0);
    this.rim.scale.set(this.glowBase.rim.x, this.glowBase.rim.y);
    this.halo.alpha = 0;
    this.halo.position.set(0, 0);
    this.halo.scale.set(this.glowBase.halo.x, this.glowBase.halo.y);
    this.sheen.visible = false;
    this.turn.scale.x = 1;
    this.back.tint = 16777215;
    this.beam.clear();
    this.hideRibbon();
    this.face.alpha = 0;
    this.drawBackMask(1);
    if (this.backMesh) {
      this.landed = false;
      this.turnedFrom = null;
      this.emblem.alpha = 0;
      this.hideTwinkles();
      this.pose(0, 0, 1);
    }
  }
  /**
   * Parked just below the lip, so the card starts out of sight inside the
   * wrapper and the clip alone decides how much of it shows.
   */
  park(cutY, rect) {
    this.fromY = cutY + this.size.height / 2;
    this.node.y = this.fromY;
    this.node.alpha = 1;
    this.toY = this.restingY();
    this.spinY = this.o.layout.card.spinAt === "pack" && rect ? rect.top + rect.height / 2 : this.toY;
    this.turn.mask = this.clipG;
    this.clip(cutY);
  }
  /** Whether the card still has to rise onto its stand after it turns. */
  get lifts() {
    return this.spinY !== void 0 && this.spinY !== this.toY;
  }
  /**
   * Sat where the pack was, invisible, with nothing clipping it. A mechanic
   * that blows the wrapper apart has no lip for the card to slide past — the
   * card is simply not there until the blast puts it there.
   */
  place(rect) {
    this.fromY = rect.top + rect.height / 2;
    this.toY = this.restingY();
    this.node.y = this.fromY;
    this.node.alpha = 0;
    this.node.scale.set(1);
    this.turn.mask = null;
  }
  /**
   * The finished card, with no reveal played into it: face up, square, at rest
   * where it will stay. A mechanic that reveals the card some other way — by
   * assembling it out of particles, say — draws its own build-up and then hands
   * over to this.
   */
  revealInstant() {
    this.node.alpha = 1;
    this.node.scale.set(1);
    this.node.y = this.toY;
    this.turn.scale.x = 1;
    this.turn.mask = null;
    this.back.tint = 16777215;
    this.face.alpha = 1;
    this.drawBackMask(0);
    this.beam.clear();
    this.hideRibbon();
  }
  /**
   * How present the finished card is. A mechanic that hands over to it from
   * something else — pieces flying into place, say — brings it up underneath
   * rather than swapping it in, so the eye never catches the change.
   */
  setAlpha(alpha) {
    this.node.alpha = alpha;
  }
  /** The rarity halo on its own, for a finish that has no beam to run. */
  setHalo(alpha) {
    this.halo.alpha = alpha * this.o.motion.reveal.haloAlpha;
  }
  /**
   * A swell of light around the card's own outline — `p` runs 0..1 and back.
   * It is the card's silhouette that flares, not a ring drawn near it, which
   * is what keeps a loud moment from reading as a second explosion.
   */
  pulse(p) {
    const reveal = this.o.motion.reveal;
    this.rim.alpha = Math.min(1, reveal.rimAlpha * (1 + p * reveal.pulseRim));
    this.halo.alpha = Math.min(1, reveal.haloAlpha * (1 + p * reveal.pulseHalo));
    const grow = 1 + p * reveal.pulseSpread;
    this.rim.scale.set(this.glowBase.rim.x * grow, this.glowBase.rim.y * grow);
    this.halo.scale.set(this.glowBase.halo.x * grow, this.glowBase.halo.y * grow);
  }
  /**
   * The highlight crossing the artwork. `t` runs 0..1 over `reveal.sheenMs`;
   * masked by the card, so it reads as light on the card rather than as light
   * thrown at it.
   */
  sweepSheen(t) {
    if (t <= 0 || t >= 1) {
      this.sheen.visible = false;
      return;
    }
    const travel = this.size.width * 1.9;
    this.sheen.visible = true;
    this.sheen.position.set(
      (t - 0.5) * travel,
      -(t - 0.5) * travel * Math.tan(this.sheen.rotation) * 0.5
    );
    this.sheen.alpha = Math.sin(Math.PI * t) * this.o.motion.reveal.sheenAlpha;
  }
  /** A short push out and back, so the card lands rather than appears. */
  setScale(value) {
    this.node.scale.set(value);
  }
  /**
   * Dropped whole before a rebuild bakes the options into new textures. The
   * ribbon's textures are ours to free, but only once the ropes are gone — a
   * destroyed mesh has let go of its texture, so the references are taken
   * first and released last.
   */
  destroy() {
    const textures = this.ribbon ? [this.ribbon.glow.texture, this.ribbon.core.texture] : [];
    this.ribbon = null;
    this.node?.destroy({ children: true });
    this.clipG?.destroy();
    for (const texture of textures) {
      texture?.destroy(true);
    }
    this.faceBaked?.destroy(true);
    this.twinkleTexture?.destroy(true);
    this.faceBaked = null;
    this.backMesh = null;
    this.faceMesh = null;
    this.twinkles = [];
    this.node = null;
  }
};

// src/core/variants/shared/blast.js
import { Container as Container2, Sprite as Sprite3, Texture as Texture4 } from "pixi.js";
var TEXTURE_SIZE = 512;
var ShockFront = class {
  constructor(root, count, shape) {
    this.node = new Container2();
    root.addChild(this.node);
    this.waves = [];
    this.setShape(count, shape);
  }
  /**
   * The band and the ragged edge are baked into the texture, so changing them
   * — or the number of waves — is a rebuild. Done in place rather than by
   * replacing the node, or the front would end up drawn over the card.
   */
  setShape(count, shape) {
    this.dispose();
    this.glowTexture = makeShockwaveTexture(
      TEXTURE_SIZE,
      shape.thickness,
      shape.ragged
    );
    this.coreTexture = makeShockwaveTexture(
      TEXTURE_SIZE,
      shape.thickness * 0.38,
      shape.ragged * 0.55
    );
    for (let i = 0; i < count; i++) {
      const glow = new Sprite3(this.glowTexture);
      const core = new Sprite3(this.coreTexture);
      for (const sprite of [glow, core]) {
        sprite.anchor.set(0.5);
        sprite.blendMode = "add";
        sprite.visible = false;
        this.node.addChild(sprite);
      }
      this.waves.push({ glow, core });
    }
    if (this.center) {
      this.layout(this.center, this.size);
    }
  }
  dispose() {
    this.node.removeChildren().forEach((child) => child.destroy());
    this.waves = [];
    this.glowTexture?.destroy(true);
    this.coreTexture?.destroy(true);
  }
  /** `size` is the radius the front is measured against. */
  layout(center, size) {
    this.center = center;
    this.size = size;
    for (const wave of this.waves) {
      wave.glow.position.set(center.x, center.y);
      wave.core.position.set(center.x, center.y);
    }
  }
  /**
   * `elapsed` is time since the blast, in ms. Waves start a stagger apart —
   * one circle growing is a circle growing, three are a shockwave.
   */
  play(elapsed, options, colors) {
    this.waves.forEach((wave, i) => {
      const delay = options.ringMs * options.ringStagger * i;
      const t = (elapsed - delay) / options.ringMs;
      if (t <= 0 || t >= 1) {
        wave.glow.visible = false;
        wave.core.visible = false;
        return;
      }
      const eased = easeOut(t);
      const radius = options.ringInward ? this.size * (options.ringReach - (options.ringReach - 0.62) * eased) : this.size * (0.2 + options.ringReach * eased);
      const squash = 1 - options.ringSquash;
      const scale = radius * 2 / TEXTURE_SIZE;
      const presence = options.ringInward ? Math.pow(t, 0.7) : Math.pow(1 - t, 1.4);
      wave.glow.visible = true;
      wave.glow.scale.set(scale, scale * squash);
      wave.glow.tint = i % 2 === 0 ? colors.glow : colors.beam;
      wave.glow.alpha = options.ringAlpha * presence;
      wave.core.visible = true;
      wave.core.scale.set(scale * 1.01, scale * squash * 1.01);
      wave.core.tint = colors.rim;
      wave.core.alpha = options.ringCoreAlpha * (options.ringInward ? Math.pow(t, 1.6) : Math.pow(1 - t, 2.6));
    });
  }
  clear() {
    for (const wave of this.waves) {
      wave.glow.visible = false;
      wave.core.visible = false;
    }
  }
};
var Starflare = class {
  constructor(root, spread) {
    this.sprite = new Sprite3(makeStarburstTexture(TEXTURE_SIZE, spread));
    this.sprite.anchor.set(0.5);
    this.sprite.blendMode = "add";
    this.sprite.visible = false;
    root.addChild(this.sprite);
  }
  /** The spindles are baked in, so their spread is a new texture. */
  setSpread(spread) {
    const before = this.sprite.texture;
    this.sprite.texture = makeStarburstTexture(TEXTURE_SIZE, spread);
    before.destroy(true);
  }
  layout(center, size) {
    this.center = center;
    this.size = size;
    this.sprite.position.set(center.x, center.y);
  }
  /** `elapsed` is time since the flare was lit, in ms. */
  play(elapsed, ms, options, colors) {
    const t = elapsed / ms;
    if (t <= 0 || t >= 1) {
      this.sprite.visible = false;
      return;
    }
    const rise = clamp(t / 0.08, 0, 1);
    const decay = Math.pow(1 - clamp((t - 0.08) / 0.92, 0, 1), 1.8);
    const reach = this.size * options.flareReach * (0.45 + 0.75 * easeOut(t));
    this.sprite.visible = true;
    this.sprite.alpha = options.flareAlpha * rise * decay;
    this.sprite.scale.set(reach * 2 / TEXTURE_SIZE);
    this.sprite.rotation = options.flareSpin * t;
    this.sprite.tint = colors.rim;
  }
  clear() {
    this.sprite.visible = false;
  }
};
var ScreenFlash = class {
  constructor(root) {
    this.sprite = new Sprite3(Texture4.WHITE);
    this.sprite.anchor.set(0.5);
    this.sprite.blendMode = "add";
    this.sprite.alpha = 0;
    this.sprite.visible = false;
    root.addChild(this.sprite);
  }
  layout(screen) {
    this.sprite.position.set(screen.width / 2, screen.height / 2);
    this.sprite.width = screen.width * 1.3;
    this.sprite.height = screen.height * 1.3;
  }
  /** `elapsed` is time since the flash was struck, in ms. */
  play(elapsed, ms, alpha, colors) {
    const t = elapsed / ms;
    if (t <= 0 || t >= 1) {
      this.clear();
      return;
    }
    this.sprite.alpha = alpha * Math.pow(1 - t, 2.2);
    this.sprite.visible = this.sprite.alpha > 0.01;
    this.sprite.tint = colors.rim;
  }
  clear() {
    this.sprite.alpha = 0;
    this.sprite.visible = false;
  }
};

// src/core/variants/burst/assemble.js
import { Container as Container3, Graphics as Graphics2, Rectangle as Rectangle2, Sprite as Sprite4, Texture as Texture6 } from "pixi.js";

// src/core/variants/shared/shardAtlas.js
import { Rectangle, Texture as Texture5 } from "pixi.js";
var MAX_ATLAS = 2048;
function sourceImage(texture) {
  const source = texture?.source;
  return source?.resource ?? source?.source ?? null;
}
function gridNode(c, r, g) {
  const insideX = c > 0 && c < g.cols;
  const insideY = r > 0 && r < g.rows;
  return {
    x: g.srcW * c + (insideX ? jitterAt(c * 31 + r * 7, 0.7) * g.srcW * g.jitter : 0),
    y: g.srcH * r + (insideY ? jitterAt(c * 17 + r * 3, 2.3) * g.srcH * g.jitter : 0)
  };
}
function edgeTear(a, b, id, g, straight) {
  const points = [];
  if (straight) {
    return points;
  }
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = Math.hypot(dx, dy) || 1;
  const nx = -dy / length;
  const ny = dx / length;
  for (let k = 1; k < g.segments; k++) {
    const t = k / g.segments;
    const push = jitterAt(id * 13 + k, 1.9) * g.amp;
    points.push({ x: a.x + dx * t + nx * push, y: a.y + dy * t + ny * push });
  }
  return points;
}
var horizontalId = (c, r, g) => (r * (g.cols + 1) + c) * 2;
var verticalId = (c, r, g) => (r * (g.cols + 1) + c) * 2 + 1;
function cellOutline(c, r, g) {
  const a = gridNode(c, r, g);
  const b = gridNode(c + 1, r, g);
  const d = gridNode(c + 1, r + 1, g);
  const e = gridNode(c, r + 1, g);
  return [
    a,
    ...edgeTear(a, b, horizontalId(c, r, g), g, r === 0),
    b,
    ...edgeTear(b, d, verticalId(c + 1, r, g), g, c + 1 === g.cols),
    d,
    // Walked backwards, so the points match the cell below and to the left
    ...edgeTear(e, d, horizontalId(c, r + 1, g), g, r + 1 === g.rows).reverse(),
    e,
    ...edgeTear(a, e, verticalId(c, r, g), g, c === 0).reverse()
  ];
}
function cutShardAtlas(texture, shape) {
  const image = sourceImage(texture);
  if (!image) {
    return null;
  }
  const { cols, rows } = shape;
  const frame = texture.frame;
  const srcW = frame.width / cols;
  const srcH = frame.height / rows;
  const pad = shape.shapeJitter + shape.shapeRagged + 0.05;
  const g = {
    cols,
    rows,
    srcW,
    srcH,
    jitter: shape.shapeJitter,
    segments: Math.max(1, Math.round(shape.shapeSegments)),
    amp: Math.min(srcW, srcH) * shape.shapeRagged
  };
  const cellW = srcW * (1 + pad * 2);
  const cellH = srcH * (1 + pad * 2);
  const scale = Math.min(
    1,
    MAX_ATLAS / (cellW * cols),
    MAX_ATLAS / (cellH * rows)
  );
  const outW = Math.max(1, Math.floor(cellW * scale));
  const outH = Math.max(1, Math.floor(cellH * scale));
  const canvas = document.createElement("canvas");
  canvas.width = outW * cols;
  canvas.height = outH * rows;
  const ctx = canvas.getContext("2d");
  const frames = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const dx = c * outW;
      const dy = r * outH;
      const sx = srcW * c - srcW * pad;
      const sy = srcH * r - srcH * pad;
      const kx = outW / cellW;
      const ky = outH / cellH;
      ctx.save();
      ctx.beginPath();
      cellOutline(c, r, g).forEach((point, index) => {
        const x = dx + (point.x - sx) * kx;
        const y = dy + (point.y - sy) * ky;
        if (index === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      });
      ctx.closePath();
      ctx.clip();
      ctx.drawImage(
        image,
        frame.x + sx,
        frame.y + sy,
        cellW,
        cellH,
        dx,
        dy,
        outW,
        outH
      );
      ctx.restore();
      frames.push(new Rectangle(dx, dy, outW, outH));
    }
  }
  return { source: Texture5.from(canvas).source, frames, pad };
}

// src/core/variants/burst/assemble.js
var SWARM_SPIN = 0.6;
var CardAssembly = class {
  constructor(root, theme) {
    this.node = new Container3();
    this.node.visible = false;
    this.bloom = new Sprite4(makeBloomTexture(512, theme.bloom));
    this.bloom.anchor.set(0.5);
    this.bloom.blendMode = "add";
    this.bloom.alpha = 0;
    this.dust = new Graphics2();
    this.dust.blendMode = "add";
    this.pieces = [];
    this.node.addChild(this.bloom, this.dust);
    root.addChild(this.node);
  }
  /**
   * Where the pieces will end up, and where they start from. Called once the
   * card rect is known — the pieces are cut from the artwork, so this needs the
   * texture too; without one only the dust cloud can be drawn.
   */
  build(rect, texture, options) {
    this.rect = rect;
    this.center = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    this.node.pivot.set(this.center.x, this.center.y);
    this.node.position.set(this.center.x, this.center.y);
    this.bloom.position.set(this.center.x, this.center.y);
    this.bloom.width = rect.width * 2.4;
    this.bloom.height = rect.height * 1.8;
    for (const piece of this.pieces) {
      piece.sprite.destroy();
    }
    this.pieces = [];
    if (!texture) {
      return;
    }
    const { assembleCols: cols, assembleRows: rows } = options;
    const base2 = texture.frame;
    const source = texture.source;
    const tileW = rect.width / cols;
    const tileH = rect.height / rows;
    const atlas = cutShardAtlas(texture, { ...options, cols, rows });
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const index = r * cols + c;
        const frame = atlas ? atlas.frames[index] : new Rectangle2(
          base2.x + base2.width / cols * c,
          base2.y + base2.height / rows * r,
          base2.width / cols,
          base2.height / rows
        );
        const sprite = new Sprite4(
          new Texture6({ source: atlas ? atlas.source : source, frame })
        );
        sprite.anchor.set(0.5);
        sprite.width = atlas ? tileW * (1 + atlas.pad * 2) : tileW + 1;
        sprite.height = atlas ? tileH * (1 + atlas.pad * 2) : tileH + 1;
        const baseScale = { x: sprite.scale.x, y: sprite.scale.y };
        const toX = rect.left + tileW * (c + 0.5);
        const toY = rect.top + tileH * (r + 0.5);
        const angle = jitterAt(index, 0.4) * Math.PI;
        const reach = rect.height * options.assembleSpread * (0.55 + Math.abs(jitterAt(index, 3.1)) * 0.6);
        const distance = Math.hypot(toX - this.center.x, toY - this.center.y);
        const reference = Math.hypot(rect.width, rect.height) / 2;
        this.pieces.push({
          sprite,
          toX,
          toY,
          fromX: toX + Math.cos(angle) * reach,
          fromY: toY + Math.sin(angle) * reach * 0.7,
          spin: jitterAt(index, 1.7) * options.assembleSpin,
          delay: distance / reference * options.assembleStagger,
          scaleFrom: options.assembleScaleFrom,
          baseScale
        });
        this.node.addChild(sprite);
      }
    }
    this.park();
  }
  get built() {
    return this.pieces.length > 0;
  }
  /** Pieces back at their launch points, invisible. */
  park() {
    for (const piece of this.pieces) {
      piece.sprite.position.set(piece.fromX, piece.fromY);
      piece.sprite.rotation = piece.spin;
      this.scalePiece(piece, piece.scaleFrom);
      piece.sprite.alpha = 0;
    }
  }
  scalePiece(piece, factor) {
    piece.sprite.scale.set(
      piece.baseScale.x * factor,
      piece.baseScale.y * factor
    );
  }
  /**
   * The waiting cloud: motes turning slowly where the card will be. This is
   * what the artwork's download hides behind, and it is also the reason the
   * assembly reads as inevitable — the dust is already card-shaped.
   */
  swarm(t, clock, options, colors) {
    this.node.visible = true;
    const { rect, center } = this;
    const presence = Math.min(1, t * 3);
    this.bloom.alpha = options.dustBloomAlpha * presence;
    this.dust.clear();
    const turn = clock / 1e3 * SWARM_SPIN;
    for (let i = 0; i < options.dustMotes; i++) {
      const angle = i / options.dustMotes * Math.PI * 2 + turn + jitterAt(i, 0.9);
      const radius = 0.35 + 0.45 * Math.abs(jitterAt(i, 2.3));
      const x = center.x + Math.cos(angle) * rect.width * radius;
      const y = center.y + Math.sin(angle) * rect.height * radius;
      const size = options.dustSize * (0.6 + 0.4 * Math.abs(jitterAt(i, 4.7)));
      this.dust.circle(x, y, size).fill({ color: colors.spark, alpha: presence * options.dustAlpha });
    }
  }
  /**
   * The assembly itself. `t` runs 0..1 over `burst.assembleMs`; each piece has
   * its own slice of that, so the card fills in rather than snapping together.
   */
  play(t, options, colors) {
    this.node.visible = true;
    const fade = 1 - clamp(t / 0.35, 0, 1);
    this.dust.alpha = fade;
    this.bloom.alpha = options.dustBloomAlpha * (0.4 + 0.6 * t);
    for (const piece of this.pieces) {
      const span = 1 - piece.delay;
      const local = clamp((t - piece.delay) / (span || 1), 0, 1);
      const eased = easeOut(local);
      piece.sprite.x = piece.fromX + (piece.toX - piece.fromX) * eased;
      piece.sprite.y = piece.fromY + (piece.toY - piece.fromY) * eased;
      piece.sprite.rotation = piece.spin * (1 - eased);
      this.scalePiece(piece, piece.scaleFrom + (1 - piece.scaleFrom) * eased);
      piece.sprite.alpha = Math.min(1, local * 2.6);
      piece.sprite.tint = mixNumbers(
        colors.glow,
        16777215,
        clamp((local - options.tintFrom) / (1 - options.tintFrom), 0, 1)
      );
    }
  }
  /**
   * The hand-over: the card is already up underneath, so the pieces dissolve
   * off it rather than being swapped out, and they take the same push the card
   * is given so nothing doubles.
   */
  settle(alpha, scale) {
    this.node.alpha = alpha;
    this.node.scale.set(scale);
  }
  /** The whole card has taken over — nothing here should still be visible. */
  hide() {
    this.node.visible = false;
    this.node.alpha = 1;
    this.node.scale.set(1);
    this.dust.clear();
    this.bloom.alpha = 0;
  }
  reset() {
    this.node.visible = false;
    this.node.alpha = 1;
    this.node.scale.set(1);
    this.dust.clear();
    this.dust.alpha = 1;
    this.bloom.alpha = 0;
    if (this.rect) {
      this.park();
    }
  }
};

// src/core/variants/burst/effects.js
import { Graphics as Graphics3 } from "pixi.js";
var BlastEffects = class {
  constructor(root, options) {
    this.front = new ShockFront(root, options.rings, {
      thickness: options.ringThickness,
      ragged: options.ringRagged
    });
    this.flare = new Starflare(root, options.flareSpread);
    this.spikes = new Graphics3();
    this.motes = new Graphics3();
    for (const layer of [this.spikes, this.motes]) {
      layer.blendMode = "add";
      root.addChild(layer);
    }
  }
  /** The baked half of the blast: wave count, band, ragged edge, spindles. */
  setShape(options) {
    this.front.setShape(options.rings, {
      thickness: options.ringThickness,
      ragged: options.ringRagged
    });
    this.flare.setSpread(options.flareSpread);
  }
  layout(rect) {
    this.center = {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2
    };
    this.size = Math.hypot(rect.width, rect.height) / 2;
    this.rect = rect;
    this.front.layout(this.center, this.size);
    this.flare.layout(this.center, this.size);
  }
  /** `elapsed` is time since the pack went off, in ms. */
  play(elapsed, options, colors) {
    this.flare.play(elapsed, options.flareMs, options, colors);
    this.front.play(elapsed, options, colors);
    this.drawSpikes(elapsed, options, colors);
    this.drawMotes(elapsed, options, colors);
  }
  /**
   * Spikes of light out of the middle. Uneven lengths on purpose — a rosette of
   * equal rays reads as a decoration, a ragged one reads as something bursting.
   */
  drawSpikes(elapsed, options, colors) {
    const t = elapsed / options.spikeMs;
    this.spikes.clear();
    if (t >= 1) {
      return;
    }
    const eased = easeOut(t);
    const fade = 1 - t * t;
    const { center } = this;
    for (let i = 0; i < options.spikes; i++) {
      const angle = i / options.spikes * Math.PI * 2 + jitterAt(i, 5.3) * 0.4;
      const length = this.size * options.spikeLength * (0.45 + Math.abs(jitterAt(i, 1.9)) * 0.85);
      const inner = this.size * 0.12 * eased;
      const outer = inner + length * eased;
      this.spikes.moveTo(center.x + Math.cos(angle) * inner, center.y + Math.sin(angle) * inner).lineTo(center.x + Math.cos(angle) * outer, center.y + Math.sin(angle) * outer).stroke({
        width: options.spikeWidth * (1 - eased * 0.75),
        color: i % 3 === 0 ? colors.beam : colors.glow,
        alpha: options.spikeAlpha * fade,
        cap: "round"
      });
    }
  }
  /**
   * Debris and glitter, drawn together because they are the same kind of thing
   * at different speeds: the debris is thrown hard and falls, the glitter is
   * barely thrown at all and drifts down long after.
   *
   * Debris is drawn as short streaks rather than dots — a dot travelling
   * hundreds of pixels between frames reads as a stutter, a streak along its
   * own direction reads as speed.
   */
  drawMotes(elapsed, options, colors) {
    this.motes.clear();
    const { center } = this;
    const debrisT = elapsed / options.debrisMs;
    if (debrisT < 1) {
      const eased = easeOut(debrisT);
      const fade = 1 - clamp((debrisT - 0.35) / 0.65, 0, 1);
      for (let i = 0; i < options.debris; i++) {
        const angle = jitterAt(i, 0.31) * Math.PI;
        const speed = 0.35 + Math.abs(jitterAt(i, 2.13)) * 0.9;
        const reach = this.size * options.debrisSpread * speed;
        const drop = this.rect.height * options.debrisGravity * debrisT * debrisT * speed;
        const x = center.x + Math.cos(angle) * reach * eased;
        const y = center.y + Math.sin(angle) * reach * eased * 0.8 + drop;
        const trail = options.debrisTrail * reach * (1 - debrisT) * 0.12;
        const size = options.debrisSize * (0.5 + Math.abs(jitterAt(i, 3.7)) * 0.9);
        this.motes.moveTo(x, y).lineTo(
          x - Math.cos(angle) * trail,
          y - Math.sin(angle) * trail * 0.8
        ).stroke({
          width: size,
          color: i % 4 === 0 ? colors.glow : colors.spark,
          alpha: options.debrisAlpha * fade,
          cap: "round"
        });
      }
    }
    const glitterT = elapsed / options.glitterMs;
    if (glitterT >= 1) {
      return;
    }
    const presence = Math.min(1, glitterT * 6) * (1 - glitterT * glitterT);
    for (let i = 0; i < options.glitter; i++) {
      const angle = jitterAt(i, 4.21) * Math.PI;
      const spread = 0.2 + Math.abs(jitterAt(i, 1.13)) * 0.8;
      const sway = Math.sin(glitterT * Math.PI * 2 + i) * this.rect.width * 0.03;
      const x = center.x + Math.cos(angle) * this.size * spread + sway;
      const y = center.y + Math.sin(angle) * this.size * spread * 0.7 + this.rect.height * options.glitterFall * glitterT;
      const size = options.glitterSize * (0.4 + Math.abs(jitterAt(i, 6.7)) * 0.9);
      this.motes.circle(x, y, size).fill({
        color: i % 3 === 0 ? colors.glow : colors.spark,
        alpha: options.glitterAlpha * presence
      });
    }
  }
  clear() {
    this.front.clear();
    this.flare.clear();
    this.spikes.clear();
    this.motes.clear();
  }
};

// src/core/variants/burst/pack.js
import { Container as Container4, Graphics as Graphics4, Sprite as Sprite5 } from "pixi.js";
var SPARK_LOOP_MS = 900;
var HALO_SPREAD = 46;
var ARC_RADIUS = 18;
var ARC_STEPS = 96;
var ChargingPack = class {
  constructor(root, texture, rect, theme) {
    this.theme = theme;
    this.root = root;
    this.bloom = new Sprite5(makeBloomTexture(512, theme.bloom));
    this.bloom.anchor.set(0.5);
    this.bloom.blendMode = "add";
    this.bloom.alpha = 0;
    root.addChild(this.bloom);
    this.halo = null;
    this.node = new Container4();
    this.sprite = new Sprite5(texture);
    this.heat = new Sprite5(texture);
    this.heat.blendMode = "add";
    this.heat.tint = 16777215;
    this.heat.alpha = 0;
    this.node.addChild(this.sprite, this.heat);
    this.arc = new Graphics4();
    this.node.addChild(this.arc);
    this.sparks = new Graphics4();
    this.sparks.blendMode = "add";
    root.addChild(this.node, this.sparks);
    this.layout(rect);
  }
  /** Called again whenever the pack rect changes — a resize or a retune. */
  layout(rect) {
    this.rect = rect;
    this.center = {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2
    };
    for (const part of [this.sprite, this.heat]) {
      part.position.set(rect.left, rect.top);
      part.width = rect.width;
      part.height = rect.height;
    }
    this.path = outlinePath(rect.width, rect.height, ARC_RADIUS, 8);
    this.halo?.destroy();
    this.halo = new Sprite5(
      makeHaloTexture(rect.width, rect.height, this.theme.glow, HALO_SPREAD, 18)
    );
    this.halo.anchor.set(0.5);
    this.halo.position.set(this.center.x, this.center.y);
    this.halo.width = rect.width + HALO_SPREAD * 2;
    this.halo.height = rect.height + HALO_SPREAD * 2;
    this.halo.blendMode = "add";
    this.halo.alpha = 0;
    this.root.addChildAt(this.halo, this.root.getChildIndex(this.node));
    this.node.pivot.set(this.center.x, this.center.y);
    this.node.position.set(this.center.x, this.center.y);
    this.bloom.position.set(this.center.x, this.center.y);
    this.bloom.width = rect.width * 2.1;
    this.bloom.height = rect.height * 1.5;
  }
  /**
   * `charge` is the pressure, `clock` the scene's running time. An untouched
   * pack breathes; a charged one shakes, squeezes and glows from the inside.
   */
  apply(charge, clock, options, colors) {
    const { rect, center } = this;
    const eased = charge * charge;
    const breath = Math.sin(clock / options.breatheMs * Math.PI * 2) * options.breathe * (1 - charge);
    const squeeze = options.squeeze * eased;
    this.node.scale.set(1 + breath - squeeze, 1 + breath + squeeze * 0.6);
    const wobbleX = Math.sin(clock * options.shakeHz * 1e-3 * Math.PI * 2);
    const wobbleY = Math.sin(clock * options.shakeHz * 17e-4 * Math.PI * 2);
    const amp = rect.height * options.shake * eased;
    this.node.position.set(center.x + wobbleX * amp, center.y + wobbleY * amp);
    this.node.rotation = wobbleY * eased * 0.012;
    this.heat.tint = colors.glow;
    this.heat.alpha = options.heatAlpha * Math.pow(charge, 1.6);
    this.halo.alpha = options.haloAlpha * Math.pow(charge, 1.3);
    this.bloom.alpha = options.bloomAlpha * eased;
    this.drawArc(charge, options, colors);
    this.drawSparks(eased, clock, options, colors);
  }
  /**
   * The charge, drawn as a line closing around the pack. It starts at the top
   * middle and runs both ways at once, so the two ends meet at the bottom
   * exactly when the pack goes off — a single head running one lap read as a
   * loading spinner instead of something filling up.
   */
  drawArc(charge, options, colors) {
    const { rect, path } = this;
    this.arc.clear();
    if (charge <= 0.01) {
      return;
    }
    const half = path.total / 2;
    const reach = half * charge;
    const left = rect.left;
    const top = rect.top;
    for (const side of [1, -1]) {
      for (let i = 0; i < ARC_STEPS; i++) {
        const from = reach * i / ARC_STEPS;
        const to = reach * (i + 1) / ARC_STEPS;
        const p0 = pointAt(path, side * from);
        const p1 = pointAt(path, side * to);
        this.arc.moveTo(left + p0.x, top + p0.y).lineTo(left + p1.x, top + p1.y).stroke({
          width: options.arcWidth,
          color: colors.glow,
          alpha: options.arcAlpha,
          cap: "round"
        });
      }
    }
  }
  /**
   * Sparks falling inwards. Each runs its own loop, offset by its index, so the
   * stream never pulses as one — and they travel on an ellipse around the pack
   * rather than a circle, or the ones above and below arrive visibly early.
   */
  drawSparks(strength, clock, options, colors) {
    const { rect, center } = this;
    this.sparks.clear();
    if (strength <= 0.02) {
      return;
    }
    for (let i = 0; i < options.sparks; i++) {
      const angle = i / options.sparks * Math.PI * 2 + jitterAt(i, 1.3);
      const phase = (clock / SPARK_LOOP_MS + i / options.sparks) % 1;
      const reach = 1 + options.sparkReach * (1 - phase);
      const x = center.x + Math.cos(angle) * (rect.width / 2) * reach;
      const y = center.y + Math.sin(angle) * (rect.height / 2) * reach;
      this.sparks.circle(x, y, options.sparkSize * (0.5 + 0.5 * phase)).fill({ color: colors.spark, alpha: phase * strength });
    }
  }
  /** The wrapper is gone — the shreds carry the artwork from here on. */
  hide() {
    this.node.visible = false;
    this.arc.clear();
    this.sparks.clear();
    this.heat.alpha = 0;
    this.halo.alpha = 0;
    this.bloom.alpha = 0;
  }
  /** Whole and unlit again, for a replay. */
  reset() {
    this.node.visible = true;
    this.node.scale.set(1);
    this.node.rotation = 0;
    this.node.position.set(this.center.x, this.center.y);
    this.arc.clear();
    this.sparks.clear();
    this.heat.alpha = 0;
    this.halo.alpha = 0;
    this.bloom.alpha = 0;
  }
};

// src/core/variants/burst/shards.js
import { Container as Container5, Sprite as Sprite6, Texture as Texture7 } from "pixi.js";
var BurstShards = class {
  constructor(root, texture, rect, options) {
    this.texture = texture;
    this.node = new Container5();
    this.node.visible = false;
    this.pieces = [];
    root.addChild(this.node);
    this.build(rect, options);
  }
  /**
   * Cuts the shards and works out where each one is thrown. Done once per
   * layout rather than per frame: the atlas costs a few hundred canvas clips,
   * and a burst is not the moment to be rasterising anything.
   */
  build(rect, options) {
    this.node.removeChildren().forEach((child) => child.destroy());
    this.pieces = [];
    const atlas = cutShardAtlas(this.texture, options);
    if (!atlas) {
      return;
    }
    const { cols, rows } = options;
    const stepW = rect.width / cols;
    const stepH = rect.height / rows;
    const drawW = stepW * (1 + atlas.pad * 2);
    const drawH = stepH * (1 + atlas.pad * 2);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const index = r * cols + c;
        const sprite = new Sprite6(
          new Texture7({ source: atlas.source, frame: atlas.frames[index] })
        );
        sprite.anchor.set(0.5);
        sprite.width = drawW;
        sprite.height = drawH;
        const baseScale = { x: sprite.scale.x, y: sprite.scale.y };
        const x0 = rect.left + stepW * (c + 0.5);
        const y0 = rect.top + stepH * (r + 0.5);
        const nx = (c + 0.5) / cols - 0.5 + jitterAt(index, 0.7) * 0.22;
        const ny = (r + 0.5) / rows - 0.5 + jitterAt(index, 2.9) * 0.22;
        const scatter = 1 + jitterAt(index, 3.3) * options.scatter;
        this.pieces.push({
          sprite,
          x0,
          y0,
          baseScale,
          // Travel over the whole phase, so `play` takes a plain 0..1
          vx: nx * options.spread * rect.width * scatter,
          vy: (ny * options.spread * rect.height - options.lift * rect.height) * scatter,
          gravity: options.gravity * rect.height,
          spin: jitterAt(index, 2.1) * options.spin,
          // Uneven, so they do not all wink out together — but measured
          // against the phase's own clock, not the shard's. A shard fading on
          // its own schedule is still half there when the blast ends, and
          // cutting it off at that point is what makes the burst look clipped
          fadeAt: clamp(
            options.fadeFrom * (1 + jitterAt(index, 5.1) * options.lifeScatter),
            0.1,
            0.92
          ),
          // Same treatment for the burn: all of them flaring on the same
          // frame is a click the eye hears
          glowAt: clamp(
            options.glowFrom * (1 + jitterAt(index, 2.7) * options.lifeScatter),
            0.1,
            0.95
          ),
          glowing: false
        });
        this.node.addChild(sprite);
      }
    }
    this.reset();
  }
  /** `t` runs 0..1 over `burst.shardMs`. */
  play(t, options, colors) {
    this.node.visible = true;
    const local = clamp(t, 0, 1);
    for (const piece of this.pieces) {
      const fade = clamp((local - piece.fadeAt) / (1 - piece.fadeAt), 0, 1);
      piece.sprite.x = piece.x0 + piece.vx * local;
      piece.sprite.y = piece.y0 + piece.vy * local + 0.5 * piece.gravity * local * local;
      piece.sprite.rotation = piece.spin * local;
      piece.sprite.alpha = (1 - fade) * (1 - fade);
      piece.sprite.visible = piece.sprite.alpha > 0.01;
      const glowing = local >= piece.glowAt;
      if (glowing !== piece.glowing) {
        piece.glowing = glowing;
        piece.sprite.blendMode = glowing ? "add" : "normal";
        piece.sprite.tint = glowing ? colors.glow : 16777215;
      }
      if (glowing) {
        const burn = 1 + (local - piece.glowAt) / (1 - piece.glowAt) * options.glowSwell;
        piece.sprite.scale.set(
          piece.baseScale.x * burn,
          piece.baseScale.y * burn
        );
      }
    }
  }
  /** The flight is over — stop handing the GPU a hundred invisible sprites. */
  hide() {
    this.node.visible = false;
  }
  /** Back inside the pack shape and out of sight, for a replay. */
  reset() {
    this.node.visible = false;
    for (const piece of this.pieces) {
      piece.sprite.position.set(piece.x0, piece.y0);
      piece.sprite.rotation = 0;
      piece.sprite.alpha = 1;
      piece.sprite.visible = true;
      piece.sprite.blendMode = "normal";
      piece.sprite.tint = 16777215;
      piece.sprite.scale.set(piece.baseScale.x, piece.baseScale.y);
      piece.glowing = false;
    }
  }
};
var BurstFlash = class {
  constructor(root, rect, theme, options) {
    this.sprite = new Sprite6(makeBloomTexture(512, theme.bloom));
    this.sprite.anchor.set(0.5);
    this.sprite.blendMode = "add";
    this.sprite.alpha = 0;
    root.addChild(this.sprite);
    this.layout(rect, options);
  }
  layout(rect, options) {
    this.sprite.position.set(
      rect.left + rect.width / 2,
      rect.top + rect.height / 2
    );
    this.sprite.width = rect.width * options.flashScale;
    this.sprite.height = rect.height * options.flashScale;
    this.base = { x: this.sprite.scale.x, y: this.sprite.scale.y };
  }
  /**
   * `t` runs 0..1 over `burst.flashMs`. The curve peaks early and falls off
   * slowly — a symmetric fade reads as a lamp being turned up rather than
   * something going off.
   */
  play(t) {
    this.sprite.alpha = Math.sin(Math.PI * Math.pow(clamp(t, 0, 1), 0.55));
    const grow = 0.6 + 0.5 * t;
    this.sprite.scale.set(this.base.x * grow, this.base.y * grow);
  }
  reset() {
    this.sprite.alpha = 0;
    this.sprite.scale.set(this.base.x, this.base.y);
  }
};

// src/core/variants/burst/scene.js
var TOUCH_SLOP = 16;
var sceneColors = (theme) => ({
  glow: toNumber(theme.glow),
  beam: toNumber(theme.beam),
  spark: toNumber(theme.spark)
});
var BurstScene = class {
  constructor(app, texture, options, emit) {
    this.app = app;
    this.texture = texture;
    this.emit = emit || (() => {
    });
    this.o = options;
    this.colors = sceneColors(options.theme);
    this.clock = 0;
    this.intro = 0;
    this.charge = 0;
    this.lastTick = 0;
    this.tracking = false;
    this.locked = false;
    this.blasted = false;
    this.enabled = true;
    this.ignoring = false;
    this.artWaitStart = 0;
    this.handed = false;
    this.sheenAt = null;
    this.root = new Container6();
    this.root.alpha = 0;
    app.stage.addChild(this.root);
    this.rect = this.layoutRect(
      app.screen.width,
      app.screen.height,
      texture.width / texture.height
    );
    this.pack = new ChargingPack(this.root, texture, this.rect, this.o.theme);
    this.shards = new BurstShards(this.root, texture, this.rect, this.o.burst);
    this.flash = new BurstFlash(this.root, this.rect, this.o.theme, this.o.burst);
    this.effects = new BlastEffects(this.root, this.o.burst);
    this.effects.layout(this.rect);
    this.card = new RevealCard(this.root, app.screen, this.o, this.colors);
    this.pedestal = new CardPedestal(this.root, this.o);
    this.assembly = new CardAssembly(this.root, this.o.theme);
    this.screenFlash = new ScreenFlash(this.root);
    this.screenFlash.layout(app.screen);
    this.kick = 0;
    this.kickMs = 1;
    this.kickAmp = 0;
    this.blastClock = null;
  }
  /**
   * Drives the engine's frame cap. A finger on the glass counts as busy even
   * before the charge starts moving — the shudder is redrawn every frame, and a
   * sleeping ticker turns it into a stutter exactly when the tension peaks.
   */
  get activity() {
    if (this.anim || this.tracking || this.charge > 0 || this.intro < 1 || this.blastClock !== null) {
      return "busy";
    }
    return this.blasted ? "idle" : "hint";
  }
  /* ── gesture ── */
  onDown(x, y) {
    if (!this.enabled || this.locked) {
      this.ignoring = true;
      return;
    }
    const { rect } = this;
    const inside = x >= rect.left - TOUCH_SLOP && x <= rect.right + TOUCH_SLOP && y >= rect.top - TOUCH_SLOP && y <= rect.bottom + TOUCH_SLOP;
    this.ignoring = !inside;
    if (this.ignoring) {
      return;
    }
    this.tracking = true;
    this.emit(MESSAGES.INTERACTION_START);
  }
  /**
   * The charge is a clock, not a distance: a finger that wanders — and one
   * pressing hard on glass always does — must not change what is being asked
   * of it. Nothing to read from a move.
   */
  onMove() {
  }
  onUp() {
    this.tracking = false;
    if (this.ignoring || this.locked) {
      return;
    }
    if (this.charge > 0) {
      this.releaseCharge();
    }
  }
  /* ── phases ── */
  /** Pressure bleeding back out of a pack that was let go too early. */
  releaseCharge() {
    this.releaseFrom = this.charge;
    this.animate("release", this.o.charge.releaseMs, () => {
      this.charge = 0;
      this.lastTick = 0;
      this.emit(MESSAGES.RETRACTED);
    });
  }
  /**
   * Full charge. The wrapper stops existing inside the flash: the pack is
   * hidden and the shreds take over in the same frame, which is only allowed
   * because the flash is over both of them.
   */
  commit() {
    if (this.blasted) {
      return;
    }
    this.locked = true;
    this.blasted = true;
    this.charge = 1;
    this.emit(MESSAGES.COMMITTED);
    this.prepareCard();
    this.pack.hide();
    this.emit(MESSAGES.OPENED);
    this.blastClock = 0;
    this.strike(this.o.burst.kickMs, this.o.burst.kickAmp);
    this.animate("beat", this.o.burst.beatMs, () => this.startSwarm());
  }
  /**
   * Everything the finish needs, resolved before the timeline starts. The card
   * is built but never shown: the assembly draws the pieces, and the card
   * itself only appears once they have all landed.
   */
  prepareCard() {
    if (!this.card.built) {
      this.card.build(this.rect);
    }
    this.card.place(this.rect);
    this.standCard();
  }
  /** Where the card comes to rest, and its stand under it. */
  standCard() {
    this.cardRect = this.card.bounds();
    this.pedestal.build(
      this.cardRect.left + this.cardRect.width / 2,
      this.cardRect.bottom,
      this.cardRect.width
    );
  }
  setPedestalTexture(texture) {
    this.pedestal.setTexture(texture);
  }
  setCardTexture(texture) {
    if (this.card.setTexture(texture) && this.cardRect) {
      this.standCard();
    }
    if (!this.anim || this.anim.kind !== "assemble") {
      this.buildAssembly();
    }
  }
  buildAssembly() {
    if (!this.cardRect) {
      return;
    }
    this.assembly.build(this.cardRect, this.card.texture, this.o.burst);
  }
  /**
   * The dust cloud. It is where the artwork's download hides: the cloud is
   * already card-shaped, so waiting reads as the card gathering rather than as
   * a spinner. A card that is already in hand still gets one short pass of it,
   * because the pieces have to come from somewhere.
   */
  startSwarm(again = false) {
    if (!this.artWaitStart) {
      this.artWaitStart = Date.now();
    }
    this.buildAssembly();
    this.animate(
      "swarm",
      this.o.burst.swarmMs,
      () => {
        const waited = Date.now() - this.artWaitStart;
        if (!this.assembly.built && waited < this.o.assets.card.timeoutMs) {
          this.startSwarm(true);
          return;
        }
        this.startAssemble();
      },
      again
    );
  }
  /**
   * A hit the hand feels: the whole stage thrown off centre and shaken back.
   * Costs one position write a frame and does more for a blast than any number
   * of particles.
   */
  strike(ms, amp) {
    this.kick = ms;
    this.kickMs = ms;
    this.kickAmp = amp * this.rect.width;
  }
  updateKick(deltaMS) {
    if (this.kick <= 0) {
      if (this.root.x !== 0 || this.root.y !== 0) {
        this.root.position.set(0, 0);
      }
      return;
    }
    this.kick = Math.max(0, this.kick - deltaMS);
    const left = this.kick / this.kickMs;
    const amp = this.kickAmp * left * left;
    const phase = this.clock / 1e3 * this.o.burst.kickHz * Math.PI * 2;
    this.root.position.set(
      Math.sin(phase) * amp,
      Math.cos(phase * 1.37) * amp * 0.6
    );
  }
  /**
   * The pieces flying in, the light that marks them landing, and the finished
   * card. `snap` is where the assembly hands over to the card itself: one push
   * out and back, so it lands instead of appearing.
   */
  startAssemble() {
    this.handed = false;
    this.animate("assemble", this.o.burst.assembleMs, () => {
      this.animate("snap", this.o.burst.snapMs, () => {
        this.assembly.hide();
        this.animate(
          "settle",
          this.o.motion.reveal.holdMs,
          () => this.emit(MESSAGES.REVEALED, {
            card: this.card.bounds(),
            pedestal: this.pedestal.bounds()
          })
        );
      });
    });
  }
  /**
   * The card coming up underneath the pieces over the last of the assembly.
   * It is what closes the hairlines between them — and it means the finished
   * artwork is already there when they dissolve, instead of replacing them.
   */
  handOver(alpha) {
    if (!this.handed) {
      this.handed = true;
      this.card.revealInstant();
    }
    this.card.setAlpha(alpha);
    this.pedestal.reveal();
  }
  /** Charge it without a finger — the host's tap-to-open fallback. */
  autoSlice() {
    if (this.locked) {
      return;
    }
    this.locked = true;
    this.emit(MESSAGES.INTERACTION_START);
    this.animate("autoCharge", this.o.charge.holdMs, () => this.commit());
  }
  setEnabled(value) {
    this.enabled = !!value;
  }
  /* ── frame ── */
  animate(kind, duration, onDone, quiet = false) {
    this.anim = { kind, duration, elapsed: 0, onDone };
    if (!quiet) {
      this.emit(MESSAGES.PHASE, { name: kind, durationMs: duration });
    }
  }
  update(deltaMS) {
    this.clock += deltaMS;
    this.updateIntro(deltaMS);
    this.updateCharge(deltaMS);
    this.pedestal.update(deltaMS);
    const anim = this.anim;
    if (anim) {
      anim.elapsed += deltaMS;
      const t = clamp(anim.elapsed / anim.duration, 0, 1);
      if (anim.kind === "autoCharge") {
        this.charge = t;
        this.reportCharge();
      } else if (anim.kind === "release") {
        this.charge = this.releaseFrom * (1 - t);
      } else if (anim.kind === "swarm") {
        this.assembly.swarm(t, this.clock, this.o.burst, this.colors);
      } else if (anim.kind === "assemble") {
        this.assembly.play(t, this.o.burst, this.colors);
        this.card.setHalo(t);
        const from = this.o.burst.handoverFrom;
        if (t >= from) {
          this.handOver(clamp((t - from) / (1 - from), 0, 1));
        }
      } else if (anim.kind === "snap") {
        const push = Math.sin(Math.PI * t) * this.o.burst.snapOvershoot;
        this.handOver(1);
        this.card.setScale(1 + push);
        this.card.pulse(Math.sin(Math.PI * Math.pow(t, 0.7)));
        if (this.sheenAt === null) {
          this.sheenAt = this.clock;
        }
        this.assembly.settle(
          1 - clamp(t / this.o.burst.dissolveSpan, 0, 1),
          1 + push
        );
      } else if (anim.kind === "settle") {
        this.card.setScale(1);
        this.card.pulse(0);
      }
      if (t >= 1) {
        this.anim = null;
        anim.onDone?.();
      }
    }
    this.updateKick(deltaMS);
    if (this.sheenAt !== null) {
      this.card.sweepSheen(
        (this.clock - this.sheenAt) / this.o.motion.reveal.sheenMs
      );
    }
    if (!this.blasted) {
      this.pack.apply(this.charge, this.clock, this.o.charge, this.colors);
    }
    if (this.blastClock !== null) {
      this.updateBlast(deltaMS);
    }
  }
  /**
   * Everything the blast throws off, on one clock and each on its own duration:
   * flash, shreds, spikes, rings, debris, glitter. They deliberately outlast
   * the phase that started them — a blast that stops dead the moment the next
   * phase begins is what made this read as two animations glued together.
   */
  updateBlast(deltaMS) {
    const burst2 = this.o.burst;
    this.blastClock += deltaMS;
    const elapsed = this.blastClock;
    this.flash.play(elapsed / burst2.flashMs);
    this.screenFlash.play(
      elapsed,
      burst2.screenFlashMs,
      burst2.screenFlashAlpha,
      this.colors
    );
    if (elapsed <= burst2.shardMs) {
      this.shards.play(clamp(elapsed / burst2.shardMs, 0, 1), burst2, this.colors);
    } else if (this.shards.node.visible) {
      this.shards.hide();
    }
    this.effects.play(elapsed, burst2, this.colors);
    const spent = Math.max(
      burst2.flashMs,
      burst2.shardMs,
      burst2.spikeMs,
      burst2.ringMs * (1 + burst2.ringStagger * burst2.rings),
      burst2.debrisMs,
      burst2.glitterMs
    );
    if (elapsed > spent) {
      this.effects.clear();
      this.blastClock = null;
    }
  }
  updateIntro(deltaMS) {
    if (this.intro >= 1) {
      return;
    }
    this.intro = clamp(this.intro + deltaMS / this.o.motion.introMs, 0, 1);
    this.root.alpha = this.intro;
  }
  /** A finger held down is the only thing that builds pressure. */
  updateCharge(deltaMS) {
    if (this.locked || !this.tracking) {
      return;
    }
    this.charge = clamp(this.charge + deltaMS / this.o.charge.holdMs, 0, 1);
    this.reportCharge();
    if (this.charge >= 1) {
      this.commit();
    }
  }
  reportCharge() {
    if (this.charge - this.lastTick < this.o.charge.tickStep) {
      return;
    }
    this.lastTick = this.charge;
    this.emit(MESSAGES.TICK, { progress: this.charge });
  }
  /* ── options and layout ── */
  /**
   * Applies new options to a live scene. Numbers and colours land immediately;
   * anything baked into a texture, the shred grid or the pack rect waits for
   * the next `reset()`, because rebuilding mid-burst would replace the shreds
   * in flight with a fresh, motionless grid.
   */
  setOptions(next) {
    const before = this.o;
    this.o = next;
    this.colors = sceneColors(next.theme);
    this.card.setOptions(next, this.colors);
    this.pedestal.setOptions(next);
    const baked = JSON.stringify(before.theme) !== JSON.stringify(next.theme) || JSON.stringify(before.layout) !== JSON.stringify(next.layout) || JSON.stringify(before.rest) !== JSON.stringify(next.rest) || before.burst.cols !== next.burst.cols || before.burst.rows !== next.burst.rows || before.burst.flashScale !== next.burst.flashScale || before.burst.rings !== next.burst.rings || before.burst.ringThickness !== next.burst.ringThickness || before.burst.ringRagged !== next.burst.ringRagged || before.burst.flareSpread !== next.burst.flareSpread || before.burst.shapeJitter !== next.burst.shapeJitter || before.burst.shapeSegments !== next.burst.shapeSegments || before.burst.shapeRagged !== next.burst.shapeRagged || before.burst.assembleCols !== next.burst.assembleCols || before.burst.assembleRows !== next.burst.assembleRows || before.burst.assembleSpread !== next.burst.assembleSpread;
    if (!baked) {
      return true;
    }
    if (this.anim || this.charge > 0) {
      this.pendingRebuild = true;
      return false;
    }
    this.rebuild();
    return true;
  }
  /**
   * The stage changed size. A ceremony in flight keeps the pack it started
   * with — restarting the burst halfway through it would read as a glitch —
   * and the new geometry rides on the next `reset()`.
   */
  resize() {
    if (this.anim || this.charge > 0) {
      this.pendingRebuild = true;
      return;
    }
    this.rebuild();
  }
  /**
   * The pack's box. With `layout.pack.anchor: 'card'` the pack is placed so
   * its centre is where the card will come to rest — sized on a first pass,
   * then moved — so the blast does not leave the card somewhere else. The
   * default keeps it centred on the stage, nudged by `offsetY`.
   */
  layoutRect(width, height, aspect) {
    const { pack, stage } = this.o.layout;
    const sized = computePackRect(width, height, aspect, pack, stage);
    if (pack.anchor !== "card") {
      return sized;
    }
    const anchorY = RevealCard.restingCentre({ width, height }, sized, this.o);
    return computePackRect(width, height, aspect, pack, stage, anchorY);
  }
  rebuild() {
    this.pendingRebuild = false;
    this.rect = this.layoutRect(
      this.app.screen.width,
      this.app.screen.height,
      this.texture.width / this.texture.height
    );
    this.pack.layout(this.rect);
    this.shards.build(this.rect, this.o.burst);
    this.shards.reset();
    this.flash.layout(this.rect, this.o.burst);
    this.effects.setShape(this.o.burst);
    this.effects.layout(this.rect);
    this.screenFlash.layout(this.app.screen);
    if (this.card.built) {
      this.card.destroy();
      this.card.build(this.rect);
      this.card.rewind(this.rect);
      this.pedestal.rewind();
      this.cardRect = this.card.bounds();
      this.buildAssembly();
    }
    this.emit(MESSAGES.LAYOUT, { rect: this.rect });
  }
  reset() {
    if (this.pendingRebuild) {
      this.rebuild();
    }
    this.anim = null;
    this.charge = 0;
    this.lastTick = 0;
    this.locked = false;
    this.blasted = false;
    this.tracking = false;
    this.ignoring = false;
    this.artWaitStart = 0;
    this.handed = false;
    this.sheenAt = null;
    this.blastClock = null;
    this.pack.reset();
    this.shards.reset();
    this.flash.reset();
    this.effects.clear();
    this.assembly.reset();
    this.screenFlash.clear();
    this.kick = 0;
    this.root.position.set(0, 0);
    this.card.rewind(this.rect);
    this.pedestal.rewind();
  }
  /**
   * Only the scene graph — the renderer belongs to the host, which tears it
   * down itself. Keeps the variant safe to swap out without dropping the app.
   */
  destroy() {
    this.root.destroy({ children: true });
  }
};

// src/core/variants/burst/index.ts
var burst = {
  id: "burst",
  presets: PRESETS,
  defaultPreset: "charged",
  create({ app, texture, options, emit }) {
    return new BurstScene(app, texture, options, emit);
  }
};

// src/core/variants/carousel/presets.ts
var base = PRESETS.charged;
var PRESETS2 = {
  showcase: {
    theme: {
      ...base.theme,
      // The turntable is a stage under lights: the pull's colour is the only
      // colour on it until the banner
      glow: "#f5d000"
    },
    motion: {
      ...base.motion,
      reveal: {
        ...base.motion.reveal,
        // The flip is its own phase; the spin/unveil/beam of the cut are unused
        holdMs: 900
      }
    },
    layout: {
      ...base.layout,
      pack: {
        // The front copy is the measure: the turntable is laid out around it
        // on the whole stage — half the width of a phone, as the reference
        // has it — and sits a little above the middle
        widthRatio: 0.5,
        heightRatio: 0.45,
        offsetY: -0.04,
        anchor: "stage"
      },
      card: {
        ...base.layout.card,
        // Read against the risen pack, which is bigger than the front copy
        packWidthRatio: 0.92
      }
    },
    performance: base.performance,
    carousel: {
      copies: 5,
      // In front-copy widths: the copies stand this far from the axis, so
      // the two beside the front one sit a little apart from it
      // Tuned by eye against the reference in the console: a tight ring,
      // the neighbours gathered a little toward the front and turned just
      // short of tangent, the two behind seen from the back between them
      radius: 1.05,
      gather: 0.21,
      turn: 0.92,
      // A medium lens and the eye half a pack above the floor: the two
      // behind come out smaller and their feet climb the stage
      focal: 2.6,
      eye: 0.34,
      fade: 0.08,
      // The ring sits in the dark away from the front
      shade: 0.78,
      // The copies hover on the spot: slow and slight, each on its own beat
      hoverAmp: 0.012,
      hoverMs: 8700,
      // Still until touched: the shuffle and the finger turn it
      driftDps: 0,
      // Two whole turns and the settle: long enough to lose track, and the
      // copy it stops on is the one chosen
      shuffleTurns: 2,
      shuffleMs: 2600,
      // A drag across one pack width turns the ring about a fifth: the next copy
      dragTurn: 0.2,
      settleMs: 520,
      dropMs: 220,
      riseMs: 320,
      riseScale: 1.15,
      floatAmp: 0.012,
      floatMs: 2600,
      dissolveMs: 380,
      factMs: 320,
      factGapMs: 700,
      bannerMs: 900,
      bannerHoldMs: 1500,
      bannerTilt: -12,
      flipMs: 520,
      reflectionAlpha: 0.32,
      reflectionHeight: 0.7,
      // A sliver of floor between the pack and its reflection
      reflectionGap: 0.04
    }
  }
};

// src/core/variants/carousel/scene.js
import { Container as Container9, Sprite as Sprite8 } from "pixi.js";

// src/core/variants/carousel/story.js
import { Container as Container7, Graphics as Graphics5, Text, TextStyle } from "pixi.js";
var FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
var BANNER_REPEATS_MAX = 40;
var Story = class {
  constructor(root, options) {
    this.root = root;
    this.o = options;
    this.node = new Container7();
    this.node.alpha = 0;
    root.addChild(this.node);
    this.facts = [];
    this.pill = null;
    this.banner = null;
    this.screen = { width: 1, height: 1 };
  }
  setOptions(options) {
    this.o = options;
  }
  /** Font sizes follow the stage, so a phone and a desktop read the same. */
  metrics(rect) {
    const unit = clamp(rect.width / 6, 16, 44);
    return {
      label: unit * 0.42,
      value: unit * 0.78,
      pill: unit * 0.5,
      banner: unit * 1.5,
      line: unit * 1.7,
      gap: unit * 0.35
    };
  }
  /**
   * Builds the facts and the pill for this pull, laid out around the centre
   * of the stage. Facts arrive late as a rule — read here, at the moment
   * they are needed, not when the scene was built.
   */
  build(rect, screen) {
    this.clear();
    this.screen = screen;
    const facts = this.o.assets.card.facts;
    const badge = this.o.assets.card.badge;
    const m = this.metrics(rect);
    this.rise = m.gap;
    const centreX = rect.left + rect.width / 2;
    const total = facts.length * m.line + (badge ? m.line : 0);
    let y = rect.top + rect.height / 2 - total / 2;
    for (const fact of facts) {
      const group = new Container7();
      const label = new Text({
        text: String(fact.label).toUpperCase(),
        style: new TextStyle({
          fontFamily: FONT,
          fontSize: m.label,
          fill: 16777215,
          letterSpacing: m.label * 0.18
        })
      });
      label.alpha = 0.6;
      label.anchor.set(0.5, 0);
      const value = new Text({
        text: String(fact.value),
        style: new TextStyle({
          fontFamily: FONT,
          fontSize: m.value,
          fontWeight: "700",
          fill: 16777215
        })
      });
      value.anchor.set(0.5, 0);
      value.y = m.label * 1.35;
      group.addChild(label, value);
      group.position.set(centreX, y);
      group.baseY = y;
      group.alpha = 0;
      this.node.addChild(group);
      this.facts.push(group);
      y += m.line;
    }
    if (badge) {
      const pill = new Container7();
      const color = toNumber(badge.color);
      const text = new Text({
        text: String(badge.label).toUpperCase(),
        style: new TextStyle({
          fontFamily: FONT,
          fontSize: m.pill,
          fontWeight: "800",
          fill: 1118481,
          letterSpacing: m.pill * 0.08
        })
      });
      text.anchor.set(0.5);
      const padX = m.pill * 0.9;
      const padY = m.pill * 0.45;
      const w = text.width + padX * 2;
      const h = text.height + padY * 2;
      const back = new Graphics5();
      back.roundRect(-w / 2 - 6, -h / 2 - 6, w + 12, h + 12, h / 2 + 6).fill({ color, alpha: 0.35 });
      back.roundRect(-w / 2, -h / 2, w, h, h / 2).fill({ color });
      pill.addChild(back, text);
      pill.position.set(centreX, y + h / 2 + m.gap);
      pill.baseY = pill.y;
      pill.alpha = 0;
      this.node.addChild(pill);
      this.pill = pill;
    }
  }
  /** How many moments the story has: one per fact, one for the pill. */
  get beats() {
    return this.facts.length + (this.pill ? 1 : 0);
  }
  /** Moment `index` (a fact, or the pill last) at progress `t`. */
  showBeat(index, t) {
    const target = index < this.facts.length ? this.facts[index] : this.pill;
    if (!target) return;
    const eased = easeOut(clamp(t, 0, 1));
    target.alpha = eased;
    target.y = target.baseY + (1 - eased) * (this.rise ?? 0);
  }
  setAlpha(alpha) {
    this.node.alpha = alpha;
  }
  /**
   * The banner: a strip in the tier's colour across the stage, tilted, with
   * the tier's name repeated along it and running. Built for the stage as
   * a whole, so the strip runs off both edges.
   */
  buildBanner(rect, screen) {
    this.destroyBanner();
    const badge = this.o.assets.card.badge;
    if (!badge) return;
    const m = this.metrics(rect);
    const c = this.o.carousel;
    const strip = new Container7();
    const height = m.banner * 1.4;
    const width = Math.hypot(screen.width, screen.height) * 1.4;
    const color = toNumber(badge.color);
    const back = new Graphics5();
    back.rect(-width / 2, -height / 2, width, height).fill({ color });
    strip.addChild(back);
    const style = new TextStyle({
      fontFamily: FONT,
      fontSize: m.banner,
      fontWeight: "900",
      fontStyle: "italic",
      fill: 16777215,
      letterSpacing: m.banner * 0.04
    });
    const word = `${String(badge.label).toUpperCase()}!`;
    const run = new Container7();
    let x = 0;
    let period = 0;
    do {
      const t = new Text({ text: word, style });
      t.anchor.set(0, 0.5);
      t.x = x;
      run.addChild(t);
      period = t.width + m.banner * 1.1;
      x += period;
    } while (x < width + period && run.children.length < BANNER_REPEATS_MAX);
    this.period = period;
    run.x = -width / 2;
    strip.addChild(run);
    this.bannerRun = run;
    strip.rotation = c.bannerTilt * Math.PI / 180;
    strip.position.set(screen.width / 2, rect.top + rect.height / 2);
    strip.alpha = 0;
    this.root.addChild(strip);
    this.banner = strip;
    this.bannerWidth = width;
  }
  /**
   * The banner crossing: it slides in from the left over `t` in 0..1 while
   * the text runs along it, and keeps running while it holds.
   */
  showBanner(t, runMs) {
    if (!this.banner) return;
    const eased = easeInOut(clamp(t, 0, 1));
    this.banner.alpha = clamp(t * 4, 0, 1);
    const slide = (1 - eased) * -this.bannerWidth * 0.35;
    this.banner.x = this.screen.width / 2 + slide;
    const run = this.bannerRun;
    if (run && this.period) {
      run.x = -this.bannerWidth / 2 - runMs * 0.12 % this.period;
    }
  }
  hideBanner(t) {
    if (!this.banner) return;
    this.banner.alpha = clamp(1 - t, 0, 1);
  }
  destroyBanner() {
    if (this.banner) {
      this.banner.destroy({ children: true });
      this.banner = null;
      this.bannerRun = null;
    }
  }
  clear() {
    this.node.removeChildren().forEach((child) => child.destroy({ children: true }));
    this.facts = [];
    this.pill = null;
    this.node.alpha = 0;
    this.destroyBanner();
  }
  destroy() {
    this.clear();
    this.node.destroy({ children: true });
  }
};

// src/core/variants/carousel/turntable.js
import { Container as Container8, PerspectiveMesh as PerspectiveMesh2, Sprite as Sprite7, Texture as Texture8 } from "pixi.js";
var TWO_PI = Math.PI * 2;
var MESH_GRID2 = 8;
function wrap(angle) {
  let a = angle % TWO_PI;
  if (a > Math.PI) a -= TWO_PI;
  if (a <= -Math.PI) a += TWO_PI;
  return a;
}
function makeFadeTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = 2;
  canvas.height = 256;
  const ctx = canvas.getContext("2d");
  const gradient = ctx.createLinearGradient(0, 0, 0, 256);
  gradient.addColorStop(0, "rgba(255,255,255,1)");
  gradient.addColorStop(0.4, "rgba(255,255,255,1)");
  gradient.addColorStop(0.7, "rgba(255,255,255,0.35)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 2, 256);
  return Texture8.from(canvas);
}
function inQuad(p, q) {
  let sign = 0;
  for (let i = 0; i < 4; i++) {
    const a = q[i];
    const b = q[(i + 1) % 4];
    const cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x);
    if (cross === 0) continue;
    const s = cross > 0 ? 1 : -1;
    if (sign === 0) sign = s;
    else if (s !== sign) return false;
  }
  return sign !== 0;
}
var Turntable = class {
  constructor(root, texture, options) {
    this.root = root;
    this.texture = texture;
    this.o = options;
    this.node = new Container8();
    this.mirrors = new Container8();
    this.fade = new Sprite7(makeFadeTexture());
    this.mirrors.mask = this.fade;
    this.node.addChild(this.mirrors, this.fade);
    this.faces = new Container8();
    this.node.addChild(this.faces);
    root.addChild(this.node);
    this.copies = [];
    this.angle = 0;
    this.chosen = -1;
    this.hoverClock = 0;
    this.contentBottom = contentBoundsOf(texture).bottom;
    this.build();
  }
  /** Time passing: the copies hover, so they are laid out again. */
  tick(deltaMS) {
    if (this.o.carousel.hoverAmp <= 0) return;
    this.hoverClock += deltaMS;
    this.place();
  }
  setOptions(options) {
    this.o = options;
    if (this.copies.length !== Math.max(1, Math.round(this.o.carousel.copies))) {
      this.build();
    }
  }
  build() {
    for (const copy of this.copies) {
      copy.mesh.destroy();
      copy.mirror.destroy();
    }
    this.copies = [];
    this.faces.removeChildren();
    this.mirrors.removeChildren();
    const count = Math.max(1, Math.round(this.o.carousel.copies));
    for (let i = 0; i < count; i++) {
      const mesh = new PerspectiveMesh2({
        texture: this.texture,
        verticesX: MESH_GRID2,
        verticesY: MESH_GRID2
      });
      const mirror = new PerspectiveMesh2({
        texture: this.texture,
        verticesX: MESH_GRID2,
        verticesY: MESH_GRID2
      });
      this.faces.addChild(mesh);
      this.mirrors.addChild(mirror);
      this.copies.push({ mesh, mirror, index: i, fade: 1, drop: 0, quad: null, depth: 0, facing: 0 });
    }
    this.place();
  }
  /**
   * The front copy's box on the stage: everything else is placed against it.
   * `floorY` is where the copies stand — the front copy's bottom edge.
   */
  layout(rect) {
    this.rect = rect;
    this.floorY = rect.bottom;
    this.centreX = rect.left + rect.width / 2;
    this.place();
  }
  /** The ring's own angle for copy `index`, in (-π, π]: 0 is squarely at the front. */
  angleOf(index) {
    const count = this.copies.length;
    return wrap(this.angle + index / count * TWO_PI);
  }
  /** The ring angle that brings copy `index` squarely to the front. */
  angleFor(index) {
    const count = this.copies.length;
    return wrap(-(index / count) * TWO_PI);
  }
  /** The ring angle nearest `angle` that has some copy squarely at the front. */
  nearestRest(angle) {
    const step = TWO_PI / this.copies.length;
    return Math.round(angle / step) * step;
  }
  /** Which copy is nearest the front right now. */
  get nearest() {
    let best = 0;
    let bestCos = -2;
    for (let i = 0; i < this.copies.length; i++) {
      const cos = Math.cos(this.angleOf(i));
      if (cos > bestCos) {
        bestCos = cos;
        best = i;
      }
    }
    return best;
  }
  /**
   * Where round the ring copy `index` stands, once the copies have gathered
   * toward the front: an even ring's angle bent by `gather`, smoothly and
   * periodically, so a turn is still a turn.
   */
  bentAngleOf(index) {
    const a = this.angleOf(index);
    return a - this.o.carousel.gather * Math.sin(a);
  }
  /** Copy `index`'s box on the stage, for the scene to lift it from. */
  boundsOf(index) {
    const copy = this.copies[index];
    if (!copy || !copy.quad) return null;
    const xs = copy.quad.map((p) => p.x);
    const ys = copy.quad.map((p) => p.y);
    const left = Math.min(...xs);
    const right = Math.max(...xs);
    const top = Math.min(...ys);
    const bottom = Math.max(...ys);
    return { left, right, top, bottom, width: right - left, height: bottom - top };
  }
  /** The copy under a point, or -1. Nearer copies win where they overlap. */
  hit(x, y) {
    let found = -1;
    let foundDepth = Infinity;
    for (const copy of this.copies) {
      if (copy.fade <= 0 || copy.facing <= 0 || !copy.quad) continue;
      if (inQuad({ x, y }, copy.quad) && copy.depth < foundDepth) {
        found = copy.index;
        foundDepth = copy.depth;
      }
    }
    return found;
  }
  /** Lays every copy out for the current angle, fades and drops. */
  place() {
    if (!this.rect) return;
    const { rect } = this;
    const c = this.o.carousel;
    const w = rect.width;
    const h = rect.height;
    const F = w * c.focal;
    const R = w * c.radius;
    const eyeY = h * c.eye;
    const horizonY = this.floorY - eyeY;
    const D = F + R;
    const project = (x, y, z) => ({
      x: this.centreX + F * x / z,
      y: horizonY - F * (y - eyeY) / z
    });
    const order = [];
    for (const copy of this.copies) {
      const a = this.bentAngleOf(copy.index);
      const cx = R * Math.sin(a);
      const cz = D - R * Math.cos(a);
      const facingAngle = a * c.turn;
      const tx = w / 2 * Math.cos(facingAngle);
      const tz = w / 2 * Math.sin(facingAngle);
      const drop = copy.drop * h * 1.6;
      const lift = c.hoverAmp > 0 ? c.hoverAmp * h * Math.sin(TWO_PI * this.hoverClock / c.hoverMs + copy.index * 1.9) : 0;
      const lx = cx - tx;
      const lz = cz - tz;
      const rx = cx + tx;
      const rz = cz + tz;
      const tl = project(lx, h + lift, lz);
      const tr = project(rx, h + lift, rz);
      const br = project(rx, lift, rz);
      const bl = project(lx, lift, lz);
      const facing = clamp((tr.x - tl.x) / (F * w / cz), -1, 1);
      copy.facing = facing;
      copy.depth = cz;
      copy.quad = [tl, tr, br, bl].map((p) => ({ x: p.x, y: p.y + drop }));
      const { mesh, mirror } = copy;
      mesh.setCorners(tl.x, tl.y + drop, tr.x, tr.y + drop, br.x, br.y + drop, bl.x, bl.y + drop);
      const meet = 2 * (1 - this.contentBottom) * h - c.reflectionGap * h;
      const mtl = project(lx, -h - lift + meet, lz);
      const mtr = project(rx, -h - lift + meet, rz);
      const mbr = project(rx, -lift + meet, rz);
      const mbl = project(lx, -lift + meet, lz);
      mirror.setCorners(
        mtl.x,
        mtl.y - drop,
        mtr.x,
        mtr.y - drop,
        mbr.x,
        mbr.y - drop,
        mbl.x,
        mbl.y - drop
      );
      const visible = clamp(Math.abs(facing) / c.fade, 0, 1) * copy.fade;
      const lit = 1 - c.shade * ((1 - facing) / 2);
      const grey = Math.round(255 * lit);
      mesh.alpha = visible;
      mesh.tint = grey << 16 | grey << 8 | grey;
      mirror.alpha = visible * c.reflectionAlpha;
      mirror.tint = mesh.tint;
      order.push({ copy, depth: cz });
    }
    order.sort((p, q) => q.depth - p.depth);
    for (const { copy } of order) {
      this.faces.addChild(copy.mesh);
      this.mirrors.addChild(copy.mirror);
    }
    const whole = this.floorY - horizonY;
    const height = Math.max(1, whole / 0.4);
    this.fade.position.set(rect.left - rect.width * 4, horizonY);
    this.fade.width = rect.width * 9;
    this.fade.height = Math.max(height, whole + h * c.reflectionHeight);
  }
  setAngle(angle) {
    this.angle = wrap(angle);
    this.place();
  }
  /** Neighbours of the chosen copy fading out, and the chosen one dropping. */
  setDrop(t) {
    for (const copy of this.copies) {
      if (copy.index === this.chosen) {
        copy.drop = t;
      } else {
        copy.fade = clamp(1 - t, 0, 1);
      }
    }
    this.place();
  }
  setAlpha(alpha) {
    this.node.alpha = alpha;
  }
  reset() {
    this.chosen = -1;
    for (const copy of this.copies) {
      copy.fade = 1;
      copy.drop = 0;
    }
    this.node.alpha = 1;
    this.place();
  }
  destroy() {
    this.fade.texture.destroy(true);
    this.node.destroy({ children: true });
  }
};

// src/core/variants/carousel/scene.js
var TOUCH_SLOP2 = 12;
var TAP_SLOP = 14;
var STORY_SWAP_MS = 300;
var HELD_MAX_SHARE = 0.7;
var COAST_MS = 220;
var VELOCITY_WINDOW_MS = 80;
var sceneColors2 = (theme) => ({
  glow: toNumber(theme.glow),
  beam: toNumber(theme.beam),
  spark: toNumber(theme.spark)
});
var CarouselScene = class {
  constructor(app, texture, options, emit) {
    this.app = app;
    this.texture = texture;
    this.emit = emit || (() => {
    });
    this.o = options;
    this.colors = sceneColors2(options.theme);
    this.clock = 0;
    this.intro = 0;
    this.enabled = true;
    this.locked = false;
    this.ignoring = false;
    this.tracking = false;
    this.down = null;
    this.moved = null;
    this.drag = null;
    this.artWaitStart = 0;
    this.floatClock = 0;
    this.bannerClock = 0;
    this.stage = "ring";
    this.anim = null;
    this.cardIn = false;
    this.frontIndex = 0;
    this.root = new Container9();
    this.root.alpha = 0;
    app.stage.addChild(this.root);
    this.content = contentBoundsOf(texture);
    this.rect = this.layoutRect(
      app.screen.width,
      app.screen.height,
      texture.width / texture.height
    );
    this.turntable = new Turntable(this.root, texture, this.o);
    this.turntable.layout(this.rect);
    this.frontIndex = this.turntable.nearest;
    this.held = new Sprite8(texture);
    this.held.anchor.set(0.5);
    this.held.visible = false;
    this.root.addChild(this.held);
    this.card = new RevealCard(this.root, app.screen, this.o, this.colors);
    this.pedestal = new CardPedestal(this.root, this.o);
    this.story = new Story(this.root, this.o);
  }
  get activity() {
    if (this.anim || this.tracking || this.intro < 1) return "busy";
    return this.stage === "done" ? "idle" : "hint";
  }
  /* ── layout ── */
  /**
   * The front copy's box. The ring has the whole stage: the bands the host
   * keeps back are for the winner's chrome around the card, which is not on
   * the stage while the ring is, and a ring squeezed into the band between
   * them comes out a toy on a phone. So it is sized and centred on the stage
   * itself, nudged by `offsetY`. With `layout.pack.anchor: 'card'` it is
   * placed so the held pack, which grows from it, is centred where the card
   * will rest.
   */
  layoutRect(width, height, aspect) {
    const { pack } = this.o.layout;
    const c = this.content;
    const fw = c.right - c.left;
    const fh = c.bottom - c.top;
    const seenAspect = aspect * fw / fh;
    let seen = computePackRect(width, height, seenAspect, pack, void 0);
    if (pack.anchor === "card") {
      const anchorY = RevealCard.restingCentre({ width, height }, seen, this.o);
      seen = computePackRect(width, height, seenAspect, pack, void 0, anchorY);
    }
    const w = seen.width / fw;
    const h = seen.height / fh;
    const left = seen.left - c.left * w;
    const top = seen.top - c.top * h;
    return { left, top, right: left + w, bottom: top + h, width: w, height: h };
  }
  /**
   * The held pack's box at full rise: the front copy grown by `riseScale`,
   * but never past most of the stage. The card is built from this box and
   * fitted into the band the host left free on its own (see
   * `cardLayoutFor`); the pack dissolves before the card is seen, so the
   * two need not be the same size.
   */
  heldRect() {
    const { rect } = this;
    const grow = Math.min(
      this.o.carousel.riseScale,
      this.app.screen.height * HELD_MAX_SHARE / rect.height
    );
    const w = rect.width * grow;
    const h = rect.height * grow;
    const cx = rect.left + rect.width / 2;
    const cy = RevealCard.restingCentre(this.app.screen, { ...rect, width: w, height: h }, this.o);
    return { left: cx - w / 2, top: cy - h / 2, right: cx + w / 2, bottom: cy + h / 2, width: w, height: h };
  }
  heldBounds() {
    if (!this.held.visible) return null;
    const s = this.held;
    return {
      left: s.x - s.width / 2,
      right: s.x + s.width / 2,
      top: s.y - s.height / 2,
      bottom: s.y + s.height / 2,
      width: s.width,
      height: s.height
    };
  }
  /* ── gesture ── */
  /**
   * Whether a gesture can be read: nothing in flight except the float, which
   * is a wait, and the ring settling after a turn, which a finger may catch.
   */
  get idle() {
    return !this.anim || this.anim.kind === "float" || this.anim.kind === "settle";
  }
  onDown(x, y) {
    if (!this.enabled || this.locked || !this.idle) {
      this.ignoring = true;
      return;
    }
    this.ignoring = false;
    this.tracking = true;
    this.down = { x, y };
    this.moved = { x, y };
    if (this.stage === "ring") {
      if (this.anim?.kind === "settle") this.anim = null;
      this.drag = {
        turning: false,
        fromAngle: this.turntable.angle,
        samples: [{ t: this.clock, angle: this.turntable.angle }]
      };
    }
    this.emit(MESSAGES.INTERACTION_START);
  }
  onMove(x, y) {
    if (!this.tracking) return;
    this.moved = { x, y };
    const drag = this.drag;
    if (!drag || !this.down) return;
    const dx = x - this.down.x;
    if (!drag.turning && Math.hypot(dx, y - this.down.y) <= TAP_SLOP) return;
    drag.turning = true;
    const angle = drag.fromAngle + dx / this.rect.width * this.o.carousel.dragTurn * Math.PI * 2;
    this.turntable.angle = angle;
    this.turntable.place();
    this.noteStep();
    drag.samples.push({ t: this.clock, angle });
    while (drag.samples.length > 2 && this.clock - drag.samples[1].t > VELOCITY_WINDOW_MS) {
      drag.samples.shift();
    }
  }
  onUp() {
    if (!this.tracking) return;
    this.tracking = false;
    if (this.ignoring || !this.down) return;
    const { x, y } = this.down;
    const moved = this.moved ?? this.down;
    const drag = this.drag;
    this.down = null;
    this.drag = null;
    if (drag?.turning) {
      const first = drag.samples[0];
      const last = drag.samples[drag.samples.length - 1];
      const dt = Math.max(1, last.t - first.t);
      const velocity = drag.samples.length > 1 ? (last.angle - first.angle) / dt : 0;
      this.emit(MESSAGES.RETRACTED);
      this.settle(this.turntable.angle + velocity * COAST_MS);
      return;
    }
    if (Math.hypot(moved.x - x, moved.y - y) > TAP_SLOP) {
      this.emit(MESSAGES.RETRACTED);
      if (this.stage === "ring") this.settle(this.turntable.angle);
      return;
    }
    if (this.stage === "ring") {
      const index = this.turntable.hit(x, y);
      if (index < 0) {
        this.emit(MESSAGES.RETRACTED);
        this.settle(this.turntable.angle);
        return;
      }
      this.choose(index);
      return;
    }
    if (this.stage === "held") {
      const b = this.heldBounds();
      const inside = b && x >= b.left - TOUCH_SLOP2 && x <= b.right + TOUCH_SLOP2 && y >= b.top - TOUCH_SLOP2 && y <= b.bottom + TOUCH_SLOP2;
      if (!inside) {
        this.emit(MESSAGES.RETRACTED);
        return;
      }
      this.open();
    }
  }
  /**
   * The host's shuffle: the ring turns on, `shuffleTurns` whole times plus
   * whatever brings some other copy to the front, and settles there — and
   * the copy it settles on is the choice: it drops and rises as if tapped,
   * so the shuffle is a way of choosing, not a prelude to it. A whole turn
   * is every copy passing through every place, which is the point: after
   * it nobody can say which copy was where.
   */
  shuffle() {
    if (this.locked || this.stage !== "ring" || this.tracking) return;
    if (this.anim && this.anim.kind !== "settle") return;
    const c = this.o.carousel;
    const count = this.turntable.copies.length;
    const from = this.turntable.angle;
    const current = this.turntable.nearest;
    const next = (current + 1 + Math.floor(Math.random() * Math.max(1, count - 1))) % count;
    let delta = this.turntable.angleFor(next) - from;
    while (delta <= 0) delta += Math.PI * 2;
    const sign = Math.random() < 0.5 ? 1 : -1;
    this.shuffleFrom = from;
    this.shuffleDelta = sign * (delta + c.shuffleTurns * Math.PI * 2);
    if (sign < 0) this.shuffleDelta = -(Math.PI * 2 - delta + c.shuffleTurns * Math.PI * 2);
    this.animate("shuffle", c.shuffleMs, () => {
      this.turntable.setAngle(this.turntable.angleFor(next));
      this.noteStep();
      this.choose(next);
    });
  }
  /**
   * A copy has come to the front, or the ring has turned past one: a step,
   * for the host to click on. Read after every turn of the ring.
   */
  noteStep() {
    const nearest = this.turntable.nearest;
    if (nearest === this.frontIndex) return;
    this.frontIndex = nearest;
    this.emit(MESSAGES.PHASE, { name: "step", durationMs: 0 });
  }
  /**
   * The ring turning on its own to rest with a copy squarely in front: the
   * nearest rest to `angle`, which a flung ring may have overshot by turns.
   * Nothing to settle is nothing done.
   */
  settle(angle) {
    const from = this.turntable.angle;
    const to = this.turntable.nearestRest(angle);
    let delta = to - from;
    if (Math.abs(angle - from) < Math.PI) delta = wrap(delta);
    if (Math.abs(delta) < 1e-4) return;
    this.settleFrom = from;
    this.settleDelta = delta;
    const c = this.o.carousel;
    const ms = Math.round(c.settleMs * clamp(0.5 + Math.abs(delta) / Math.PI, 0.5, 2));
    this.animate("settle", ms, () => {
    }, true);
  }
  /**
   * Copy `index` tapped: it drops off the ring as its neighbours fade, then
   * rises alone to centre stage and floats there for the second tap. The
   * host hears `committed` here — this is the choice.
   */
  choose(index) {
    if (this.stage !== "ring") return;
    this.turntable.chosen = index;
    this.stage = "held";
    this.locked = true;
    this.emit(MESSAGES.COMMITTED);
    const c = this.o.carousel;
    this.animate("drop", c.dropMs, () => {
      const from = this.turntable.boundsOf(index) ?? this.rect;
      this.riseFrom = {
        x: from.left + from.width / 2,
        y: from.top + from.height / 2,
        w: from.width,
        h: from.height
      };
      this.turntable.setAlpha(0);
      this.held.position.set(this.riseFrom.x, this.riseFrom.y);
      this.held.width = this.riseFrom.w;
      this.held.height = this.riseFrom.h;
      this.held.alpha = 1;
      this.held.visible = true;
      this.animate("rise", c.riseMs, () => {
        this.locked = false;
        this.floatClock = 0;
        this.animate("float", 0, null, false);
      });
    });
  }
  /**
   * The second tap: the pack goes, the pull is told, then shown. The host
   * hears `opened` when the pack has dissolved — its cue to fetch the card
   * if it has not already — and the facts and the banner are read from the
   * options when their moment comes, so ones that arrive during the
   * dissolve are still told.
   */
  open() {
    if (this.stage !== "held") return;
    this.stage = "opening";
    this.locked = true;
    this.anim = null;
    this.prepareCard();
    const c = this.o.carousel;
    this.animate("dissolve", c.dissolveMs, () => {
      this.held.visible = false;
      this.emit(MESSAGES.OPENED);
      this.startStory();
    });
  }
  /** The facts, one after another, then the pill; nothing to tell skips straight on. */
  startStory() {
    this.story.build(this.heldRect(), this.app.screen);
    this.story.setAlpha(1);
    if (this.story.beats === 0) {
      this.startBanner();
      return;
    }
    this.animate("facts", this.storyLength(), () => this.startBanner());
  }
  storyLength() {
    const c = this.o.carousel;
    const beats = this.story.beats;
    return beats * c.factMs + Math.max(0, beats - 1) * c.factGapMs + c.factGapMs;
  }
  /** The banner, for a tier that has one; otherwise straight to the flip. */
  startBanner() {
    if (!this.o.assets.card.badge) {
      this.startFlip();
      return;
    }
    const c = this.o.carousel;
    this.story.buildBanner(this.heldRect(), this.app.screen);
    this.bannerClock = 0;
    this.animate("banner", c.bannerMs + c.bannerHoldMs, () => this.startFlip());
  }
  /**
   * The flip: the story fades, the blank card turns over into the artwork
   * and the stand comes in under it. Artwork still on its way holds the
   * card face-down, turning on, until it comes — announced once.
   */
  startFlip() {
    const firstHold = !this.card.hasArt && !this.artWaitStart;
    if (firstHold) this.artWaitStart = Date.now();
    const waited = this.artWaitStart ? Date.now() - this.artWaitStart : 0;
    if (!this.card.hasArt && waited < this.o.assets.card.timeoutMs) {
      this.animate("spinHold", this.o.motion.reveal.artWaitSpinMs, () => this.startFlip(), !firstHold);
      return;
    }
    const c = this.o.carousel;
    this.animate("flip", c.flipMs, () => {
      this.story.destroyBanner();
      this.story.clear();
      this.pedestal.reveal();
      this.animate("hold", this.o.motion.reveal.holdMs, () => {
        this.stage = "done";
        this.emit(MESSAGES.REVEALED, {
          card: this.card.bounds(),
          pedestal: this.pedestal.bounds()
        });
      });
    });
  }
  /** The card, built where the held pack is, so the flip happens in its place. */
  prepareCard() {
    const rect = this.heldRect();
    if (!this.card.built) {
      this.card.build(rect);
    }
    this.card.place(rect);
    this.standCard();
  }
  /** Where the card comes to rest, and its stand under it. */
  standCard() {
    this.cardRect = this.card.bounds();
    this.pedestal.build(
      this.cardRect.left + this.cardRect.width / 2,
      this.cardRect.bottom,
      this.cardRect.width
    );
  }
  setCardTexture(texture) {
    if (this.card.setTexture(texture) && this.cardRect) {
      this.standCard();
    }
  }
  setPedestalTexture(texture) {
    this.pedestal.setTexture(texture);
  }
  /**
   * Open it without a finger — the host's tap-to-open. On the ring it
   * chooses the front copy; holding the pack, it opens it.
   */
  autoSlice() {
    if (this.tracking) return;
    if (this.anim && this.anim.kind !== "float" && this.anim.kind !== "settle") return;
    if (this.stage === "ring") {
      this.anim = null;
      this.emit(MESSAGES.INTERACTION_START);
      this.choose(this.turntable.nearest);
      this.autoOpen = true;
      return;
    }
    if (this.stage === "held") {
      this.emit(MESSAGES.INTERACTION_START);
      this.open();
    }
  }
  setEnabled(value) {
    this.enabled = !!value;
  }
  /* ── frame ── */
  animate(kind, duration, onDone, quiet = false) {
    this.anim = { kind, duration, elapsed: 0, onDone };
    if (!quiet) {
      this.emit(MESSAGES.PHASE, { name: kind, durationMs: duration });
    }
  }
  update(deltaMS) {
    this.clock += deltaMS;
    if (this.intro < 1) {
      this.intro = clamp(this.intro + deltaMS / this.o.motion.introMs, 0, 1);
      this.root.alpha = easeOut(this.intro);
    }
    this.pedestal.update(deltaMS);
    const c = this.o.carousel;
    const anim = this.anim;
    if (this.stage === "ring" || anim?.kind === "drop") {
      this.turntable.tick(deltaMS);
    }
    if (this.stage === "ring" && !anim && !this.tracking && c.driftDps) {
      this.turntable.setAngle(this.turntable.angle + c.driftDps * Math.PI / 180 * (deltaMS / 1e3));
      this.noteStep();
    }
    if (!anim) return;
    anim.elapsed += deltaMS;
    const t = anim.duration > 0 ? clamp(anim.elapsed / anim.duration, 0, 1) : 0;
    switch (anim.kind) {
      case "shuffle": {
        const eased = easeInOut(t);
        this.turntable.setAngle(this.shuffleFrom + this.shuffleDelta * eased);
        this.noteStep();
        break;
      }
      case "settle": {
        this.turntable.setAngle(this.settleFrom + this.settleDelta * easeOut(t));
        this.noteStep();
        break;
      }
      case "drop": {
        this.turntable.setDrop(easeInOut(t));
        break;
      }
      case "rise": {
        const eased = easeOut(t);
        const to = this.heldRect();
        const from = this.riseFrom;
        const cx = to.left + to.width / 2;
        const cy = to.top + to.height / 2;
        this.held.x = from.x + (cx - from.x) * eased;
        this.held.y = from.y + (cy - from.y) * eased;
        this.held.width = from.w + (to.width - from.w) * eased;
        this.held.height = from.h + (to.height - from.h) * eased;
        this.held.alpha = 1;
        break;
      }
      case "float": {
        this.floatClock += deltaMS;
        const to = this.heldRect();
        const bob = Math.sin(this.floatClock / c.floatMs * Math.PI * 2) * to.height * c.floatAmp;
        this.held.x = to.left + to.width / 2;
        this.held.y = to.top + to.height / 2 + bob;
        this.held.width = to.width;
        this.held.height = to.height;
        if (this.autoOpen) {
          this.autoOpen = false;
          this.open();
        }
        return;
      }
      case "dissolve": {
        const eased = easeInOut(t);
        this.held.alpha = 1 - eased;
        const to = this.heldRect();
        const grow = 1 + eased * 0.08;
        this.held.width = to.width * grow;
        this.held.height = to.height * grow;
        this.card.setAlpha(0);
        break;
      }
      case "facts": {
        const beats = this.story.beats;
        const step = c.factMs + c.factGapMs;
        for (let i = 0; i < beats; i++) {
          const local = (anim.elapsed - i * step) / c.factMs;
          this.story.showBeat(i, local);
        }
        break;
      }
      case "banner": {
        this.bannerClock += deltaMS;
        const swap = clamp(anim.elapsed / STORY_SWAP_MS, 0, 1);
        this.story.setAlpha(1 - swap);
        this.card.setAlpha(swap);
        this.card.reveal("flip", 0);
        this.cardIn = true;
        const slide = clamp(anim.elapsed / c.bannerMs, 0, 1);
        this.story.showBanner(slide, this.bannerClock);
        const tail = (anim.elapsed - c.bannerMs) / c.bannerHoldMs;
        if (tail > 0.75) this.story.hideBanner((tail - 0.75) / 0.25);
        break;
      }
      case "spinHold": {
        this.card.setAlpha(1);
        this.cardIn = true;
        this.card.reveal("spinHold", t);
        this.story.setAlpha(1 - clamp(anim.elapsed / STORY_SWAP_MS, 0, 1));
        break;
      }
      case "flip": {
        this.story.setAlpha(1 - clamp(anim.elapsed / (c.flipMs * 0.5), 0, 1));
        if (!this.cardIn) {
          this.card.setAlpha(clamp(anim.elapsed / (c.flipMs * 0.25), 0, 1));
        }
        this.card.reveal("flip", t);
        break;
      }
      case "hold": {
        this.card.reveal("hold", t);
        break;
      }
      default:
        break;
    }
    if (anim.duration > 0 && t >= 1) {
      this.anim = null;
      anim.onDone?.();
    }
  }
  /* ── options / layout / lifecycle ── */
  setOptions(next) {
    const before = this.o;
    this.o = next;
    this.colors = sceneColors2(next.theme);
    this.card.setOptions(next, this.colors);
    this.pedestal.setOptions(next);
    this.story.setOptions(next);
    this.turntable.setOptions(next);
    const baked = JSON.stringify(before.theme) !== JSON.stringify(next.theme) || JSON.stringify(before.layout) !== JSON.stringify(next.layout) || JSON.stringify(before.rest) !== JSON.stringify(next.rest) || before.carousel.copies !== next.carousel.copies || before.carousel.riseScale !== next.carousel.riseScale;
    if (!baked) {
      this.turntable.place();
      return true;
    }
    if (this.anim || this.stage !== "ring") {
      this.pendingRebuild = true;
      return false;
    }
    this.rebuild();
    return true;
  }
  resize() {
    if (this.anim || this.stage !== "ring") {
      this.pendingRebuild = true;
      return;
    }
    this.rebuild();
  }
  rebuild() {
    this.pendingRebuild = false;
    this.rect = this.layoutRect(
      this.app.screen.width,
      this.app.screen.height,
      this.texture.width / this.texture.height
    );
    this.turntable.layout(this.rect);
    if (this.card.built) {
      this.card.destroy();
      this.card.build(this.heldRect());
      this.card.rewind(this.heldRect());
      this.pedestal.rewind();
    }
    this.emit(MESSAGES.LAYOUT, { rect: this.rect });
  }
  reset() {
    if (this.pendingRebuild) {
      this.rebuild();
    }
    this.anim = null;
    this.stage = "ring";
    this.locked = false;
    this.tracking = false;
    this.ignoring = false;
    this.down = null;
    this.moved = null;
    this.drag = null;
    this.autoOpen = false;
    this.artWaitStart = 0;
    this.floatClock = 0;
    this.bannerClock = 0;
    this.cardIn = false;
    this.turntable.reset();
    this.frontIndex = this.turntable.nearest;
    this.held.visible = false;
    this.held.alpha = 1;
    this.story.clear();
    this.card.rewind(this.heldRect());
    this.pedestal.rewind();
  }
  destroy() {
    this.story.destroy();
    this.turntable.destroy();
    this.root.destroy({ children: true });
  }
};

// src/core/variants/carousel/index.ts
var carousel = {
  id: "carousel",
  presets: PRESETS2,
  defaultPreset: "showcase",
  create({ app, texture, options, emit }) {
    return new CarouselScene(app, texture, options, emit);
  }
};

// src/core/variants/slice/presets.ts
var PRESETS3 = {
  classic: {
    theme: {
      background: "transparent",
      glow: "#9a6bff",
      rim: "#ffffff",
      bloom: "#ffffff",
      beam: "#ffffff",
      spark: "#ffffff",
      // Warm, like metal cut hot — the pull's own colour is kept for the card
      seam: "#ffcf8a",
      hint: "#ffffff",
      // A plain card of white light: nothing printed on it, the pull's colour
      // is the beam round its edge and the halo behind it
      cardBack: {
        top: "#ffffff",
        mid: "#f4f6ff",
        bottom: "#e9edf8",
        sheen: "rgba(255,255,255,0.85)",
        line: "transparent",
        emblem: "transparent"
      },
      // The artwork's own corners: a graded slab is barely rounded, and cut
      // any rounder its frame loses its corners while the glow runs round a
      // shape the card does not have
      cornerRadius: 6
    },
    motion: {
      speed: 1,
      introMs: 320,
      finishMs: 170,
      autoSliceMs: 430,
      retractMs: 220,
      open: {
        ms: 1e3,
        lid: 0.52,
        cardFrom: 0.34,
        sink: 0.5,
        gone: 0.8,
        clipFrom: 0.45,
        lidThrowX: 0.55,
        lidThrowY: 0.85,
        lidSpin: 0.9,
        // The lid is seen flying off, not fading where it was cut
        lidFadeFrom: 0.4,
        lidFadeSpan: 0.55,
        uncutFade: 0.18
      },
      reveal: {
        /** The stand comes in behind the card, ahead of the host's own UI. */
        pedestalMs: 260,
        holdMs: 600,
        beamTail: 0.38,
        spinFlatness: 0.06,
        spinShade: 0.05,
        spinBloom: 0.85,
        bloomAlpha: 0.95,
        // Low, so the white edge never outshines the pull's own colour
        rimAlpha: 0.55,
        haloAlpha: 0.95,
        beamWidth: 3,
        beamAlpha: 0.9,
        beamGlowWidth: 14,
        beamGlowAlpha: 0.45,
        beamTipRadius: 8,
        beamSteps: 24,
        // One piece: the charge runs it round a card several hundred pixels tall
        beamStyle: "ribbon",
        outlineDetail: 9,
        artWaitSpinMs: 600,
        // The card is shared, so it carries these even where the mechanic
        // never runs them
        pulseRim: 0.9,
        pulseHalo: 0.7,
        pulseSpread: 0.07,
        sheenMs: 620,
        sheenAlpha: 0.85,
        sheenWidth: 0.55,
        sheenTilt: 0.35
      }
    },
    interaction: {
      activation: 12,
      completeFraction: 0.62,
      trailStep: 8,
      trailMaxPoints: 40,
      rampPoints: 6,
      // A fine, clean slit: the pack cut through, and the lid is what flies
      gapRatio: 0.012,
      edgeJitter: 0.2,
      overshoot: 48,
      band: { top: 0.05, bottom: 0.62 },
      finishOvershoot: 0.03,
      finishSlopeLimit: 0.8,
      tickStep: 0.07,
      autoArc: { inset: 0.06, fromY: 0.23, toY: 0.17, controlY: 0.1 }
    },
    layout: {
      // Nothing is kept back by default: a host that draws over the stage says
      // how much of it it needs
      stage: {
        reserveTop: 0,
        reserveBottom: 0
      },
      // Measured by the pack itself rather than its image, and a good third
      // wider than the card it holds — the card is sized off it below
      pack: {
        widthRatio: 0.6,
        heightRatio: 0.58,
        offsetY: 0.02,
        anchor: "stage"
      },
      card: {
        heightRatio: 0.95,
        packWidthRatio: 0.76,
        aspect: 0.66,
        // The artwork's own shape, landscape too: past this its sides are cut
        maxRatio: 2,
        spinAt: "rest"
      },
      pedestal: {
        widthRatio: 1.15,
        aspect: 0.335,
        gapRatio: 0.077,
        clearanceRatio: 0.1
      },
      glow: {
        bloomScaleX: 3,
        bloomScaleY: 2.2,
        rimSpread: 40,
        rimPadding: 80,
        haloSpread: 56,
        haloPadding: 112
      }
    },
    hint: {
      // Just under the seal a foil pack is torn open at. The pack is measured
      // by the pack itself, so this is on the foil, not in the image's empty
      // margin above it
      lineRatio: 0.12,
      // Edge to edge: the cut it mimes runs the whole width of the pack
      sweep: 1,
      headRadius: 8,
      tail: 0.34,
      segments: 80,
      tailAlpha: 0.75,
      tailFalloff: 1.6,
      loopMs: 1700,
      idleMs: 700,
      fadeMs: 200
    },
    slice: {
      floatAmp: 8e-3,
      floatMs: 3600,
      foilEveryMs: 3400,
      foilMs: 1100,
      foilAlpha: 0.5,
      foilWidth: 0.5,
      foilTilt: 0.42,
      backlightAlpha: 0.22,
      backlightSpread: 28,
      bladeGlow: 16,
      bladeSparks: 0.4,
      sparkSpeed: 380,
      sparkLifeMs: 560,
      sparkSize: 2.6,
      sparkGravity: 1300,
      burstSparks: 90,
      joltScale: 0.035,
      pourAlpha: 0.75,
      riseBloom: 0.5,
      chargeMs: 1150,
      chargeWaitMs: 700,
      chargeLaps: 1.8,
      chargeHalo: 0.75,
      // No star printed on the back for its light to fill
      emblemAlpha: 0,
      tiltDeg: 8,
      tiltMs: 2300,
      tremble: 1.6,
      flipMs: 560,
      flipLift: 0.12,
      flipRise: 0.04,
      flipFlare: 0.75,
      focal: 3.2,
      landMs: 780,
      landPunch: 0.07,
      landShake: 5,
      twinkles: 7,
      twinkleSize: 52,
      twinkleMs: 360,
      embers: 26,
      emberMs: 2600,
      emberSize: 2.2,
      emberRise: 0.9,
      emberAlpha: 0.85
    },
    performance: {
      maxFps: 60,
      idleFps: 30,
      sleepFps: 1,
      resolutionCap: 2,
      antialias: true
    }
  }
};

// src/core/variants/slice/scene.js
import { Container as Container11 } from "pixi.js";

// src/core/variants/slice/geometry.js
var WHOLE2 = { left: 0, top: 0, right: 1, bottom: 1 };
function computeSliceRect(width, height, aspect, interaction, pack, stage, anchorY, bounds = WHOLE2) {
  const share = {
    x: Math.max(0.05, bounds.right - bounds.left),
    y: Math.max(0.05, bounds.bottom - bounds.top)
  };
  const rect = computePackRect(
    width,
    height,
    aspect * share.x / share.y,
    pack,
    stage,
    anchorY
  );
  const imageWidth = rect.width / share.x;
  const imageHeight = rect.height / share.y;
  return {
    ...rect,
    image: {
      left: rect.left - bounds.left * imageWidth,
      top: rect.top - bounds.top * imageHeight,
      width: imageWidth,
      height: imageHeight
    },
    cutTop: rect.top + rect.height * interaction.band.top,
    cutBottom: rect.top + rect.height * interaction.band.bottom,
    gap: rect.height * interaction.gapRatio
  };
}

// src/core/variants/slice/effects.js
import { Graphics as Graphics6, Sprite as Sprite9 } from "pixi.js";
function seeded(seed) {
  let s = seed >>> 0;
  return () => {
    s = s + 1831565813 >>> 0;
    let t = s;
    t = Math.imul(t ^ t >>> 15, t | 1);
    t ^= t + Math.imul(t ^ t >>> 7, t | 61);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
var SEED = 24301;
var STREAK_S = 0.028;
var MAX_SPARKS = 240;
var SliceEffects = class {
  /** `pack` is the wrapper that carries the cut's light, `stage` the scene's root. */
  constructor(pack, stage) {
    this.pour = new Sprite9(makeBloomTexture(256, "#ffffff"));
    this.pour.anchor.set(0.5);
    this.pour.blendMode = "add";
    this.pour.visible = false;
    this.blade = new Sprite9(makeSoftDotTexture(64));
    this.blade.anchor.set(0.5);
    this.blade.blendMode = "add";
    this.blade.visible = false;
    pack.carry(this.pour);
    pack.carry(this.blade);
    this.sparkLayer = new Graphics6();
    this.sparkLayer.blendMode = "add";
    this.emberLayer = new Graphics6();
    this.emberLayer.blendMode = "add";
    stage.addChild(this.emberLayer, this.sparkLayer);
    this.reset();
  }
  reset() {
    this.sparks = [];
    this.embers = [];
    this.emberClock = -1;
    this.owed = 0;
    this.random = seeded(SEED);
    this.sparkLayer.clear();
    this.emberLayer.clear();
    this.blade.visible = false;
    this.pour.visible = false;
  }
  /** Whether anything is still in flight — the scene keeps its frame rate up for it. */
  get busy() {
    return this.sparks.length > 0 || this.emberClock >= 0;
  }
  spawn(x, y, vx, vy, life, size, color) {
    if (this.sparks.length >= MAX_SPARKS) {
      return;
    }
    this.sparks.push({ x, y, vx, vy, life, size, color, age: 0 });
  }
  /**
   * Sparks for the distance the blade just covered, thrown back along the cut
   * and out of it the way a grinder throws them. `y` is on the stage.
   */
  bladeSparks(x, y, travel, dir, fx, colors) {
    this.owed += travel * fx.bladeSparks;
    const count = Math.floor(this.owed);
    this.owed -= count;
    const back = dir > 0 ? Math.PI : 0;
    for (let i = 0; i < count; i++) {
      const angle = back + (this.random() - 0.5) * 2.4;
      const speed = fx.sparkSpeed * (0.35 + this.random() * 0.9);
      this.spawn(
        x,
        y,
        Math.cos(angle) * speed,
        Math.sin(angle) * speed - speed * 0.35,
        fx.sparkLifeMs * (0.5 + this.random() * 0.8),
        fx.sparkSize * (0.6 + this.random() * 0.8),
        this.random() < 0.35 ? colors.spark : colors.seam
      );
    }
  }
  /**
   * The seal gives: sparks leave the whole length of the cut, most of them up
   * and out of the pack. `offsetY` puts the trail, which is in the pack's
   * space, on the stage.
   */
  burst(trail, fx, colors, offsetY = 0) {
    if (!trail.length) {
      return;
    }
    for (let i = 0; i < fx.burstSparks; i++) {
      const point = trail[Math.floor(this.random() * trail.length)];
      const up = this.random() < 0.72;
      const angle = (up ? -Math.PI / 2 : Math.PI / 2) + (this.random() - 0.5) * (up ? 2.3 : 1.5);
      const speed = fx.sparkSpeed * (0.55 + this.random() * 1.15);
      this.spawn(
        point.x,
        point.y + offsetY,
        Math.cos(angle) * speed,
        Math.sin(angle) * speed,
        fx.sparkLifeMs * (0.8 + this.random() * 0.9),
        fx.sparkSize * (0.7 + this.random()),
        this.random() < 0.45 ? colors.spark : colors.seam
      );
    }
  }
  /** The point of light under the blade, or none. `at` is in the pack's space. */
  showBlade(at, fx, colors) {
    if (!at || fx.bladeGlow <= 0) {
      this.blade.visible = false;
      return;
    }
    this.blade.visible = true;
    this.blade.position.set(at.x, at.y);
    this.blade.width = fx.bladeGlow;
    this.blade.height = fx.bladeGlow;
    this.blade.tint = colors.spark;
    this.blade.alpha = 0.9;
  }
  /**
   * Light pouring out of the opened pack, `level` 0..1, spread along the lip
   * at `y` — wide and low, the way light leaves a slot, not a beam.
   */
  pourAt(rect, y, level, fx, colors) {
    const sprite = this.pour;
    if (level <= 5e-3 || fx.pourAlpha <= 0) {
      sprite.visible = false;
      return;
    }
    sprite.visible = true;
    sprite.position.set(rect.left + rect.width / 2, y);
    sprite.width = rect.width * 1.35;
    sprite.height = rect.height * (0.26 + 0.22 * level);
    sprite.tint = colors.seam;
    sprite.alpha = fx.pourAlpha * level;
  }
  /**
   * Embers rising past the card once it is down. `card` is its box on the
   * stage; they start round its lower half and drift up and out of sight.
   */
  startEmbers(card, fx) {
    this.emberClock = 0;
    this.embers = [];
    for (let i = 0; i < fx.embers; i++) {
      this.embers.push({
        x: card.left + card.width * (-0.12 + this.random() * 1.24),
        y: card.top + card.height * (0.3 + this.random() * 0.8),
        delay: this.random() * fx.emberMs * 0.45,
        life: fx.emberMs * (0.35 + this.random() * 0.45),
        rise: card.height * fx.emberRise * (0.4 + this.random() * 0.8),
        sway: (this.random() - 0.5) * card.width * 0.2,
        phase: this.random() * Math.PI * 2,
        size: fx.emberSize * (0.5 + this.random() * 0.9),
        white: this.random() < 0.3
      });
    }
  }
  update(deltaMS, fx, colors) {
    this.updateSparks(deltaMS, fx);
    this.updateEmbers(deltaMS, fx, colors);
  }
  updateSparks(deltaMS, fx) {
    const g = this.sparkLayer;
    g.clear();
    const dt = deltaMS / 1e3;
    const drag = Math.max(0, 1 - 1.4 * dt);
    let alive = 0;
    for (const s of this.sparks) {
      s.age += deltaMS;
      if (s.age >= s.life) {
        continue;
      }
      s.vx *= drag;
      s.vy = s.vy * drag + fx.sparkGravity * dt;
      s.x += s.vx * dt;
      s.y += s.vy * dt;
      const u = s.age / s.life;
      g.moveTo(s.x, s.y).lineTo(s.x - s.vx * STREAK_S, s.y - s.vy * STREAK_S).stroke({
        width: s.size * (1 - u * 0.5),
        color: s.color,
        alpha: Math.pow(1 - u, 1.3),
        cap: "round"
      });
      this.sparks[alive++] = s;
    }
    this.sparks.length = alive;
  }
  updateEmbers(deltaMS, fx, colors) {
    const g = this.emberLayer;
    g.clear();
    if (this.emberClock < 0) {
      return;
    }
    this.emberClock += deltaMS;
    let left = 0;
    for (const e of this.embers) {
      const u = (this.emberClock - e.delay) / e.life;
      if (u >= 1) {
        continue;
      }
      left++;
      if (u <= 0) {
        continue;
      }
      const presence = Math.min(1, u * 5) * Math.pow(1 - u, 1.2);
      const x = e.x + e.sway * Math.sin(u * Math.PI * 2 + e.phase);
      const y = e.y - e.rise * easeOut(u);
      const color = e.white ? colors.spark : colors.glow;
      const alpha = clamp(fx.emberAlpha * presence, 0, 1);
      g.circle(x, y, e.size * 2.6).fill({ color, alpha: alpha * 0.18 });
      g.circle(x, y, e.size).fill({ color, alpha });
    }
    if (!left) {
      this.emberClock = -1;
    }
  }
};

// src/core/variants/slice/hint.js
import { Graphics as Graphics7 } from "pixi.js";
function drawHint(g, rect, head, hint, color) {
  g.clear();
  const presence = Math.min(1, 3 * Math.sin(Math.PI * clamp(head, 0, 1)));
  if (presence <= 0.01) {
    return;
  }
  const y = rect.top + rect.height * hint.lineRatio;
  const inner = rect.width - hint.headRadius * 2;
  const span = inner * hint.sweep;
  const from = rect.left + hint.headRadius + (inner - span) / 2;
  const x = from + span * head;
  const tail = rect.width * hint.tail;
  for (let i = 0; i < hint.segments; i++) {
    const t = (i + 1) / hint.segments;
    const px = x - tail * (1 - t);
    if (px < from) {
      continue;
    }
    g.circle(px, y, hint.headRadius * t).fill({
      color,
      alpha: hint.tailAlpha * Math.pow(t, hint.tailFalloff) * presence
    });
  }
  g.circle(x, y, hint.headRadius).fill({ color, alpha: presence });
}
var SliceHint = class {
  constructor(color) {
    this.view = new Graphics7();
    this.color = color;
    this.alpha = 1;
    this.clock = 0;
  }
  setColor(color) {
    this.color = color;
  }
  /** `hidden` is the moment the pack is touched — the comet fades out for good. */
  update(deltaMS, rect, options, hidden) {
    const wanted = hidden ? 0 : 1;
    if (this.alpha !== wanted) {
      const step = deltaMS / options.fadeMs;
      this.alpha = clamp(
        wanted > this.alpha ? this.alpha + step : this.alpha - step,
        0,
        1
      );
    }
    this.view.alpha = this.alpha;
    if (this.alpha <= 0) {
      return;
    }
    const cycle = options.loopMs + options.idleMs;
    this.clock = (this.clock + deltaMS) % cycle;
    const sweep = clamp(this.clock / options.loopMs, 0, 1);
    drawHint(this.view, rect, easeInOut(sweep), options, this.color);
  }
};

// src/core/variants/slice/wrapper.js
import { Container as Container10, Graphics as Graphics8, Sprite as Sprite10, Texture as Texture9 } from "pixi.js";
function outerBox(rect) {
  const image = rect.image ?? rect;
  return {
    left: Math.min(rect.left, image.left),
    right: Math.max(rect.right, image.left + image.width),
    top: Math.min(rect.top, image.top),
    bottom: Math.max(rect.bottom, image.top + image.height)
  };
}
function tearEdge(points, rect, dir, sign, openness, interaction) {
  const n = points.length;
  if (n < 2 || dir === 0) {
    return null;
  }
  const { overshoot, rampPoints, edgeJitter } = interaction;
  const box = outerBox(rect);
  const gapScale = rect.gap * openness;
  const phase = sign < 0 ? 0 : 2.7;
  const edge = points.map((point, index) => {
    const ramp = Math.min((n - 1 - index) / rampPoints, 1);
    const gap = gapScale * ramp;
    return {
      x: point.x,
      y: point.y + sign * (gap + jitterAt(index, phase) * gap * edgeJitter)
    };
  });
  const first = points[0];
  const backDx = points[1].x - first.x;
  const backSlope = backDx !== 0 ? clamp((points[1].y - first.y) / backDx, -1.1, 1.1) : 0;
  const backAt = (x) => ({ x, y: edge[0].y + backSlope * (x - first.x) });
  return {
    edge,
    back: backAt(dir > 0 ? box.left - overshoot : box.right + overshoot),
    // The blade itself carries no gap — that is what hides the seam ahead of it
    blade: points[n - 1],
    before: points[n - 2]
  };
}
function traceEdge(g, tear) {
  const { edge } = tear;
  for (let i = 0; i < edge.length - 1; i++) {
    const a = edge[i];
    const b = edge[i + 1];
    g.quadraticCurveTo(a.x, a.y, (a.x + b.x) / 2, (a.y + b.y) / 2);
  }
  g.lineTo(tear.blade.x, tear.blade.y);
}
function drawTearMask(g, tear, rect, dir, sign, interaction) {
  g.clear();
  if (!tear) {
    return;
  }
  const { overshoot } = interaction;
  const box = outerBox(rect);
  const frontX = dir > 0 ? box.right + overshoot : box.left - overshoot;
  const cornerY = sign < 0 ? box.top - overshoot : box.bottom + overshoot;
  const { back, blade, before } = tear;
  const frontDx = blade.x - before.x;
  const frontSlope = frontDx !== 0 ? clamp((blade.y - before.y) / frontDx, -1.1, 1.1) : 0;
  g.moveTo(back.x, cornerY);
  g.lineTo(back.x, back.y);
  g.lineTo(tear.edge[0].x, tear.edge[0].y);
  traceEdge(g, tear);
  g.lineTo(frontX, blade.y + frontSlope * (frontX - blade.x));
  g.lineTo(frontX, cornerY);
  g.closePath();
  g.fill(16777215);
}
function drawUncutMask(g, points, rect, dir, OVERSHOOT) {
  const n = points.length;
  const box = outerBox(rect);
  const top = box.top - OVERSHOOT;
  const height = box.bottom - box.top + OVERSHOOT * 2;
  g.clear();
  if (n < 2 || dir === 0) {
    g.rect(box.left - OVERSHOOT, top, box.right - box.left + OVERSHOOT * 2, height);
    g.fill(16777215);
    return;
  }
  const bladeX = points[n - 1].x;
  const left = dir > 0 ? bladeX - 0.5 : box.left - OVERSHOOT;
  const right = dir > 0 ? box.right + OVERSHOOT : bladeX + 0.5;
  if (right - left <= 0) {
    return;
  }
  g.rect(left, top, right - left, height);
  g.fill(16777215);
}
var PackWrapper = class {
  constructor(root, texture, rect, options) {
    this.texture = texture;
    this.o = options;
    this.node = new Container10();
    root.addChild(this.node);
    this.backlight = new Sprite10(Texture9.EMPTY);
    this.backlight.blendMode = "add";
    this.backlight.alpha = 0;
    this.uncut = new Sprite10(texture);
    this.bottom = new Sprite10(texture);
    this.top = new Sprite10(texture);
    this.uncutMask = new Graphics8();
    this.bottomMask = new Graphics8();
    this.topMask = new Graphics8();
    this.foilMask = new Sprite10(texture);
    this.foil = new Sprite10(Texture9.EMPTY);
    this.foil.anchor.set(0.5);
    this.foil.blendMode = "add";
    this.foil.visible = false;
    this.node.addChild(
      this.backlight,
      this.uncutMask,
      this.bottomMask,
      this.topMask,
      this.bottom,
      this.top,
      this.uncut,
      this.foilMask,
      this.foil
    );
    this.uncut.mask = this.uncutMask;
    this.bottom.mask = this.bottomMask;
    this.top.mask = this.topMask;
    this.foil.mask = this.foilMask;
    this.clock = 0;
    this.calm = 1;
    this.lit = 1;
    this.offsetY = 0;
    this.jolt = 0;
    this.layout(rect);
  }
  setOptions(options) {
    this.o = options;
  }
  /** Something the scene hangs on the pack: it floats and jolts with it. */
  carry(view) {
    this.node.addChild(view);
  }
  /** Called again whenever the pack rect changes — a resize or a rebuild. */
  layout(rect) {
    this.rect = rect;
    const image = rect.image ?? rect;
    for (const part of [this.uncut, this.bottom, this.top, this.foilMask]) {
      part.position.set(image.left, image.top);
      part.width = image.width;
      part.height = image.height;
    }
    const fx = this.o.slice;
    this.replaceTexture(
      this.foil,
      makeSheenTexture(
        Math.max(1, Math.round(rect.width * fx.foilWidth)),
        Math.max(1, Math.round(rect.height * 1.8))
      )
    );
    this.foil.width = rect.width * fx.foilWidth;
    this.foil.height = rect.height * 1.8;
    this.foil.rotation = fx.foilTilt;
    const spread = fx.backlightSpread;
    const silhouette = makeSilhouetteGlowTexture(
      this.texture,
      image.width,
      image.height,
      spread
    );
    const box = silhouette ? image : rect;
    this.replaceTexture(
      this.backlight,
      silhouette ?? makeHaloTexture(
        rect.width,
        rect.height,
        "#ffffff",
        spread,
        Math.min(rect.width, rect.height) * 0.04
      )
    );
    this.backlight.position.set(box.left - spread, box.top - spread);
    this.backlight.width = box.width + spread * 2;
    this.backlight.height = box.height + spread * 2;
    this.applyTransform();
  }
  replaceTexture(sprite, texture) {
    const before = sprite.texture;
    sprite.texture = texture;
    if (before && before !== Texture9.EMPTY && before !== texture) {
      before.destroy(true);
    }
  }
  /**
   * The float and the jolt, about the pack's own middle. The pack is where
   * the layout put it whenever both are at rest, so the cut and the card are
   * measured in the same space as the stage.
   */
  applyTransform() {
    const { rect } = this;
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    this.node.pivot.set(cx, cy);
    this.node.position.set(cx, cy + this.offsetY);
    this.node.scale.set(1 + this.jolt);
  }
  /**
   * Life of the waiting pack: it floats, light crosses its foil, its outline
   * glows. `touched` settles all of it away — the cut needs the pack still,
   * and a pack drifting under the blade would pull the seam off the finger.
   * `opened` puts the outline's light out: the silhouette it follows is gone
   * with the lid.
   */
  update(deltaMS, { touched, opened }, colors) {
    const fx = this.o.slice;
    const { rect } = this;
    this.clock += deltaMS;
    this.calm += ((touched ? 0 : 1) - this.calm) * Math.min(1, deltaMS / 140);
    this.lit += ((opened ? 0 : 1) - this.lit) * Math.min(1, deltaMS / 200);
    this.offsetY = fx.floatAmp * rect.height * Math.sin(2 * Math.PI * this.clock / fx.floatMs) * this.calm;
    this.applyTransform();
    const pass = this.clock % fx.foilEveryMs / fx.foilMs;
    if (pass < 1 && fx.foilAlpha > 0 && this.calm > 0.02) {
      const travel = rect.width + this.foil.width;
      this.foil.visible = true;
      this.foil.position.set(
        rect.left - this.foil.width / 2 + travel * easeInOut(pass),
        rect.top + rect.height / 2
      );
      this.foil.alpha = fx.foilAlpha * Math.sin(Math.PI * pass) * this.calm;
    } else {
      this.foil.visible = false;
    }
    const breath = 0.8 + 0.2 * Math.sin(2 * Math.PI * this.clock / (fx.floatMs * 0.73));
    this.backlight.alpha = fx.backlightAlpha * breath * this.lit;
    this.backlight.tint = colors.rim;
    this.backlight.visible = this.backlight.alpha > 5e-3;
  }
  /** The pack giving at the moment the seal goes: a push out and back, `t` over the run-out. */
  setJolt(t) {
    this.jolt = this.o.slice.joltScale * Math.sin(Math.PI * clamp(t, 0, 1));
    this.applyTransform();
  }
  redraw(trail, dir, openness, interaction) {
    const { rect } = this;
    drawUncutMask(this.uncutMask, trail, rect, dir, interaction.overshoot);
    drawTearMask(
      this.topMask,
      tearEdge(trail, rect, dir, -1, openness, interaction),
      rect,
      dir,
      -1,
      interaction
    );
    drawTearMask(
      this.bottomMask,
      tearEdge(trail, rect, dir, 1, openness, interaction),
      rect,
      dir,
      1,
      interaction
    );
  }
  /** Both halves home and opaque again, for a replay. */
  reset() {
    this.top.alpha = 1;
    this.bottom.alpha = 1;
    this.uncut.alpha = 1;
    this.jolt = 0;
    this.moveHalf(this.top, this.topMask, 0, 0);
    this.moveHalf(this.bottom, this.bottomMask, 0, 0);
    this.applyTransform();
  }
  /**
   * Moves one half of the wrapper together with its mask. The mask paths are
   * built in the pack's space, so a sprite that moves on its own slides out
   * from under its own cut — and the half starts showing the wrong part of the
   * artwork, which reads as an uncut pack.
   */
  moveHalf(sprite, mask, dx, dy, rotation = 0) {
    const image = this.rect.image ?? this.rect;
    sprite.position.set(image.left + dx, image.top + dy);
    sprite.rotation = rotation;
    mask.pivot.set(image.left, image.top);
    mask.position.set(image.left + dx, image.top + dy);
    mask.rotation = rotation;
  }
  /** The lid flying off. Owns nothing but the top half. */
  applyLid(release, dir, open) {
    const { rect } = this;
    this.moveHalf(
      this.top,
      this.topMask,
      dir * release * rect.width * open.lidThrowX,
      -release * rect.height * open.lidThrowY,
      dir * release * open.lidSpin
    );
    this.top.alpha = 1 - clamp((release - open.lidFadeFrom) / open.lidFadeSpan, 0, 1);
  }
  /**
   * The emptied wrapper: how far it has sunk and how far it has faded. Returns
   * the drop, because the card clip is cut at the sunken lip — computing that
   * twice let the two disagree for a frame and the wrapper visibly jumped.
   */
  sink(t, open) {
    const { rect } = this;
    const drop = rect.height * open.sink * easeOut(t);
    this.moveHalf(this.bottom, this.bottomMask, 0, drop);
    const gone = clamp(t / open.gone, 0, 1);
    this.bottom.alpha = 1 - gone;
    this.uncut.alpha = 1 - clamp(t / open.uncutFade, 0, 1);
    return drop;
  }
};

// src/core/variants/slice/scene.js
var sceneColors3 = (theme) => ({
  glow: toNumber(theme.glow),
  beam: toNumber(theme.beam),
  spark: toNumber(theme.spark),
  seam: toNumber(theme.seam),
  rim: toNumber(theme.rim)
});
var BAKED_SLICE = ["foilWidth", "backlightSpread"];
var PackScene = class {
  /**
   * `options` arrives already resolved — filling defaults in is the variant
   * registry's job, not the scene's. `emit(type, payload)` is how the scene
   * talks back: a plain callback, so the host is free to turn it into a bridge
   * message or a DOM event.
   */
  constructor(app, texture, options, emit) {
    this.app = app;
    this.texture = texture;
    this.emit = emit || (() => {
    });
    this.o = options;
    this.colors = sceneColors3(options.theme);
    this.trail = [];
    this.dir = 0;
    this.progress = 0;
    this.openness = 0;
    this.release = 0;
    this.locked = false;
    this.enabled = true;
    this.tracking = false;
    this.startX = 0;
    this.startY = 0;
    this.maxAdvance = 0;
    this.needAdvance = 1;
    this.lastTick = 0;
    this.dirty = true;
    this.chargeClock = 0;
    this.landClock = 0;
    this.legacyUnveiled = false;
    this.intro = 0;
    this.root = new Container11();
    this.root.alpha = 0;
    app.stage.addChild(this.root);
    this.bounds = contentBoundsOf(texture);
    this.rect = this.layoutRect(
      app.screen.width,
      app.screen.height,
      texture.width / texture.height
    );
    this.wrapper = new PackWrapper(this.root, texture, this.rect, this.o);
    this.effects = new SliceEffects(this.wrapper, this.root);
    this.hint = new SliceHint(toNumber(this.o.theme.hint));
    this.wrapper.carry(this.hint.view);
    this.card = new RevealCard(this.root, app.screen, this.o, this.colors);
    this.card.useDepth(app.renderer);
    this.pedestal = new CardPedestal(this.root, this.o);
    this.redraw();
  }
  get points() {
    return this.trail;
  }
  /**
   * Drives the engine's frame cap. `dirty` counts as busy: the masks are one
   * redraw behind, and dropping to a sleeping frame rate before that lands
   * would leave the pack half-cut on screen. A finger on the glass counts too —
   * the cut is redrawn between moves, and a sleeping ticker turns a smooth
   * slice into a slideshow. So do sparks and embers still in the air. The
   * untouched pack floats and catches the light, which is slow but alive.
   */
  get activity() {
    if (this.anim || this.dirty || this.tracking || this.intro < 1 || this.effects.busy) {
      return "busy";
    }
    if (!this.started && !this.locked) {
      return "hint";
    }
    return this.hint.alpha > 0 ? "hint" : "idle";
  }
  redraw() {
    this.wrapper.redraw(this.trail, this.dir, this.openness, this.o.interaction);
    this.dirty = false;
  }
  /* ── gesture ── */
  /** The finger on the stage, in the pack's own space — the pack may be floating. */
  local(y) {
    return y - this.wrapper.offsetY;
  }
  /** Whether a point on the stage is on the pack, give or take a fingertip. */
  over(x, y) {
    const { rect } = this;
    const ly = this.local(y);
    return x >= rect.left - 16 && x <= rect.right + 16 && ly >= rect.top - 16 && ly <= rect.bottom + 16;
  }
  /** The finger is on the pack: the cut starts from here once it moves. */
  arm(x, y) {
    const { rect } = this;
    this.armed = true;
    this.tracking = true;
    this.startX = x;
    this.startY = clamp(this.local(y), rect.cutTop, rect.cutBottom);
  }
  onDown(x, y) {
    if (!this.enabled || this.locked) {
      this.ignoring = true;
      return;
    }
    this.ignoring = false;
    this.started = false;
    this.armed = false;
    if (this.over(x, y)) {
      this.arm(x, y);
    }
  }
  onMove(x, y) {
    if (this.ignoring || this.locked) {
      return;
    }
    if (!this.armed) {
      if (!this.over(x, y)) {
        return;
      }
      this.arm(x, y);
    }
    const { rect } = this;
    if (!this.started) {
      if (Math.abs(x - this.startX) < this.o.interaction.activation) {
        return;
      }
      this.started = true;
      this.dir = x >= this.startX ? 1 : -1;
      this.trail = [{ x: this.startX, y: this.startY }];
      this.bladeX = this.startX;
      this.bladeY = this.startY;
      const reach = this.dir > 0 ? rect.right - this.startX : this.startX - rect.left;
      this.needAdvance = Math.max(
        Math.min(rect.width * this.o.interaction.completeFraction, reach * 0.85),
        rect.width * 0.28
      );
      this.emit(MESSAGES.INTERACTION_START);
    }
    const px = clamp(x, rect.left - 12, rect.right + 12);
    const py = clamp(this.local(y), rect.cutTop, rect.cutBottom);
    if ((px - this.bladeX) * this.dir <= 0) {
      return;
    }
    this.moveBlade(px, py);
    this.maxAdvance = Math.max(
      this.maxAdvance,
      (px - this.startX) * this.dir
    );
    this.progress = clamp(this.maxAdvance / this.needAdvance, 0, 1);
    this.openness = this.progress;
    this.dirty = true;
    if (this.progress - this.lastTick >= this.o.interaction.tickStep) {
      this.lastTick = this.progress;
      this.emit(MESSAGES.TICK, { progress: this.progress });
    }
    if (this.progress >= 1) {
      this.commit();
    }
  }
  onUp() {
    this.tracking = false;
    this.armed = false;
    if (this.ignoring || this.locked) {
      return;
    }
    if (this.progress > 0) {
      this.retract();
    }
  }
  /**
   * The blade to a new point of the cut, recorded into the trail at its
   * sampling step, throwing sparks for the way it came.
   */
  moveBlade(x, y) {
    const travel = Math.abs(x - this.bladeX);
    const last = this.trail[this.trail.length - 1];
    if (this.trail.length < this.o.interaction.trailMaxPoints && last && (x - last.x) * this.dir >= this.o.interaction.trailStep) {
      this.trail.push({ x, y });
    }
    this.bladeX = x;
    this.bladeY = y;
    this.effects.bladeSparks(
      x,
      y + this.wrapper.offsetY,
      travel,
      this.dir,
      this.o.slice,
      this.colors
    );
  }
  /* ── phases ── */
  commit() {
    if (this.locked) {
      return;
    }
    this.locked = true;
    this.progress = 1;
    this.emit(MESSAGES.COMMITTED);
    this.effects.burst(this.trail, this.o.slice, this.colors, this.wrapper.offsetY);
    this.animate("runOut", this.o.motion.finishMs, () => this.openLid());
  }
  openLid() {
    this.prepareCard();
    this.openedPosted = false;
    this.animate("open", this.o.motion.open.ms, () => this.startCharge());
  }
  setCardTexture(texture) {
    this.card.setTexture(texture, { defer: this.card.placed });
    const anim = this.anim;
    if (this.card.hasArt && anim && (anim.kind === "charge" || anim.kind === "chargeHold")) {
      this.announceLegacyUnveil(anim.duration - anim.elapsed);
    }
  }
  setPedestalTexture(texture) {
    this.pedestal.setTexture(texture);
  }
  /**
   * The stand goes under where the card comes to rest — the middle of the
   * stage — not under where it starts, so it stays put while the card slides
   * out past the lip.
   */
  buildPedestal() {
    const rect = this.card.bounds();
    this.pedestal.build(rect.left + rect.width / 2, rect.bottom, rect.width);
  }
  /** Everything the slide-out needs, resolved before the timeline starts. */
  prepareCard() {
    if (!this.card.built) {
      this.card.build(this.rect);
    }
    const trail = this.trail;
    this.cutY = trail.length ? trail.reduce((sum, point) => sum + point.y, 0) / trail.length : this.rect.top + this.rect.height * this.o.interaction.band.top;
    this.card.park(this.cutY, this.rect);
    this.buildPedestal();
  }
  /** The card is out, face down: it gathers itself before it turns. */
  startCharge() {
    this.chargeClock = 0;
    this.animate("charge", this.o.slice.chargeMs, () => this.afterCharge());
  }
  /**
   * The artwork may still be downloading — wait for it, but not forever. The
   * wait is the charge held at its peak, one loop per hold, so however many
   * holds it takes read as one unbroken build-up; the host hears `chargeHold`
   * once, when the wait begins, and nothing for the holds after.
   */
  afterCharge() {
    const firstHold = !this.card.hasArt && !this.artWaitStart;
    if (firstHold) {
      this.artWaitStart = Date.now();
    }
    const waited = this.artWaitStart ? Date.now() - this.artWaitStart : 0;
    if (!this.card.hasArt && waited < this.o.assets.card.timeoutMs) {
      this.animate(
        "chargeHold",
        this.o.slice.chargeWaitMs,
        () => this.afterCharge(),
        !firstHold
      );
      if (waited + this.o.slice.chargeWaitMs >= this.o.assets.card.timeoutMs) {
        this.announceLegacyUnveil(this.o.slice.chargeWaitMs);
      }
      return;
    }
    this.card.beginFlip();
    this.animate("flip", this.o.slice.flipMs, () => this.land());
  }
  /**
   * Face up and down: the host feels it land, the stand comes in under it and
   * embers start up past it. A card that turned where the pack was gets its
   * stand once it has risen onto it.
   */
  land() {
    this.emit(MESSAGES.IMPACT);
    const lifts = this.card.lifts;
    if (!lifts) {
      this.pedestal.reveal();
    }
    this.effects.startEmbers(this.card.bounds(), this.o.slice);
    this.landClock = 0;
    this.animate("land", this.o.slice.landMs, () => {
      if (lifts) {
        this.pedestal.reveal();
      }
      this.card.hideTwinkles();
      this.animate(
        "hold",
        this.o.motion.reveal.holdMs,
        () => this.emit(MESSAGES.REVEALED, {
          card: this.card.bounds(),
          pedestal: this.pedestal.bounds()
        })
      );
    });
  }
  retract() {
    this.animate("retract", this.o.motion.retractMs, () => {
      this.trail = [];
      this.dir = 0;
      this.progress = 0;
      this.openness = 0;
      this.maxAdvance = 0;
      this.lastTick = 0;
      this.started = false;
      this.dirty = true;
      this.emit(MESSAGES.RETRACTED);
    });
  }
  /** Point on the synthetic slice arc used by the tap-to-open fallback. */
  arcPoint(t) {
    const { rect } = this;
    const arc = this.o.interaction.autoArc;
    const x0 = rect.left + rect.width * arc.inset;
    const x1 = rect.right - rect.width * arc.inset;
    const y0 = rect.top + rect.height * arc.fromY;
    const y1 = rect.top + rect.height * arc.toY;
    const cx = (x0 + x1) / 2;
    const cy = rect.top + rect.height * arc.controlY;
    const mt = 1 - t;
    return {
      x: mt * mt * x0 + 2 * mt * t * cx + t * t * x1,
      y: mt * mt * y0 + 2 * mt * t * cy + t * t * y1
    };
  }
  autoSlice() {
    if (this.locked) {
      return;
    }
    this.locked = true;
    this.dir = 1;
    const start = this.arcPoint(0);
    this.trail = [start];
    this.bladeX = start.x;
    this.bladeY = start.y;
    this.emit(MESSAGES.INTERACTION_START);
    this.animate("autoSlice", this.o.motion.autoSliceMs, () => {
      this.effects.burst(this.trail, this.o.slice, this.colors, this.wrapper.offsetY);
      this.openLid();
    });
  }
  setEnabled(value) {
    this.enabled = !!value;
  }
  /**
   * Only the scene graph — the renderer belongs to the host, which tears it
   * down itself. Keeps the variant safe to swap out without dropping the app.
   */
  destroy() {
    this.root.destroy({ children: true });
  }
  /**
   * Applies new options to a live scene. Numbers and colours land immediately —
   * the scene reads them where it uses them — but anything baked into a texture
   * or into the pack rect waits for the next `reset()`: rebuilding the card
   * mid-ceremony would strip the masks off the trail and blank the revealed art.
   */
  setOptions(next) {
    const before = this.o;
    this.o = next;
    this.colors = sceneColors3(next.theme);
    this.card.setOptions(next, this.colors);
    this.pedestal.setOptions(next);
    this.wrapper.setOptions(next);
    this.hint.setColor(toNumber(next.theme.hint));
    this.dirty = true;
    const baked = JSON.stringify(before.theme) !== JSON.stringify(next.theme) || JSON.stringify(before.layout) !== JSON.stringify(next.layout) || JSON.stringify(before.rest) !== JSON.stringify(next.rest) || JSON.stringify(before.interaction.band) !== JSON.stringify(next.interaction.band) || BAKED_SLICE.some((key) => before.slice[key] !== next.slice[key]);
    if (!baked) {
      this.redraw();
      return true;
    }
    if (this.anim || this.started || this.locked) {
      this.pendingRebuild = true;
      return false;
    }
    this.rebuild();
    return true;
  }
  /**
   * The stage changed size. Rebuilding mid-cut would strip the masks off the
   * trail and blank the revealed art, so a ceremony in flight keeps the pack it
   * started with and the new geometry rides on the next `reset()`.
   */
  resize() {
    if (this.anim || this.started || this.locked) {
      this.pendingRebuild = true;
      return;
    }
    this.rebuild();
  }
  /**
   * The pack's box. With `layout.pack.anchor: 'card'` the pack is placed so
   * its centre is where the card will come to rest — sized on a first pass,
   * then moved — so the cut does not hoist the card up out of the pack's
   * place. The default keeps it centred in the band the host left free,
   * nudged by `offsetY`.
   */
  layoutRect(width, height, aspect) {
    const { pack, stage } = this.o.layout;
    const { interaction } = this.o;
    const sized = computeSliceRect(
      width,
      height,
      aspect,
      interaction,
      pack,
      stage,
      void 0,
      this.bounds
    );
    if (pack.anchor !== "card") {
      return sized;
    }
    const anchorY = RevealCard.restingCentre({ width, height }, sized, this.o);
    return computeSliceRect(
      width,
      height,
      aspect,
      interaction,
      pack,
      stage,
      anchorY,
      this.bounds
    );
  }
  /** Re-derives the pack rect and the card, which bake options into textures. */
  rebuild() {
    this.pendingRebuild = false;
    this.rect = this.layoutRect(
      this.app.screen.width,
      this.app.screen.height,
      this.texture.width / this.texture.height
    );
    this.wrapper.layout(this.rect);
    if (this.card.built) {
      this.card.destroy();
      this.card.build(this.rect);
      this.card.rewind(this.rect);
    }
    this.dirty = true;
    this.redraw();
    this.emit(MESSAGES.LAYOUT, { rect: this.rect });
  }
  reset() {
    if (this.pendingRebuild) {
      this.rebuild();
    }
    this.anim = null;
    this.trail = [];
    this.dir = 0;
    this.progress = 0;
    this.openness = 0;
    this.release = 0;
    this.maxAdvance = 0;
    this.lastTick = 0;
    this.locked = false;
    this.started = false;
    this.ignoring = false;
    this.armed = false;
    this.tracking = false;
    this.openedPosted = false;
    this.chargeClock = 0;
    this.landClock = 0;
    this.root.y = 0;
    this.wrapper.reset();
    this.effects.reset();
    this.card.rewind(this.rect);
    this.pedestal.rewind();
    this.artWaitStart = 0;
    this.dirty = true;
    this.redraw();
  }
  animate(kind, duration, onDone, quiet = false) {
    this.anim = { kind, duration, elapsed: 0, onDone };
    if (!quiet) {
      this.emit(MESSAGES.PHASE, { name: kind, durationMs: duration });
      this.announceLegacyPhase(kind, duration);
    }
    if (kind === "runOut") {
      const n = this.trail.length;
      const last = this.trail[n - 1] ?? { x: this.bladeX, y: this.bladeY };
      const prev = this.trail[Math.max(0, n - 2)] ?? last;
      const dx = last.x - prev.x;
      this.runOutFrom = {
        x: this.bladeX,
        y: this.bladeY,
        slope: dx !== 0 ? clamp(
          (last.y - prev.y) / dx,
          -this.o.interaction.finishSlopeLimit,
          this.o.interaction.finishSlopeLimit
        ) : 0,
        targetX: this.dir > 0 ? this.rect.right + this.rect.width * this.o.interaction.finishOvershoot : this.rect.left - this.rect.width * this.o.interaction.finishOvershoot
      };
    }
    if (kind === "retract") {
      this.retractFrom = this.openness;
    }
  }
  /**
   * The phases 0.4 scored the ceremony by — `spin`, `spinHold`, `unveil`,
   * `beam` — announced beside this ceremony's own for hosts written against
   * them. Deprecated; they go in 0.6.
   *
   * A 0.4 score counts its leads to the landing from them: `spin + unveil +
   * beam` after `spin`, `unveil + beam` after `unveil`, `beam` after `beam`,
   * reading the lengths it was not told from `timeline`. The card landed as
   * the beam ended. So each starts with a phase here and runs until the next
   * one does — `spin` the lid, `unveil` the charge, `beam` the turn — and the
   * card lands as the beam ends, as it did.
   */
  announceLegacyPhase(kind, duration) {
    switch (kind) {
      case "open":
        this.legacyUnveiled = false;
        this.emit(MESSAGES.PHASE, { name: "spin", durationMs: duration });
        break;
      case "charge":
        if (this.card.hasArt) {
          this.announceLegacyUnveil(duration);
        }
        break;
      case "chargeHold":
        this.emit(MESSAGES.PHASE, { name: "spinHold", durationMs: duration });
        break;
      case "flip":
        this.announceLegacyUnveil(0);
        this.emit(MESSAGES.PHASE, { name: "beam", durationMs: duration });
        break;
      default:
        break;
    }
  }
  /**
   * `untilFlipMs` is what is left before the card turns over. Never less than
   * a millisecond: a 0.4 score reads a length of 0 as "not given" and falls
   * back to its own.
   */
  announceLegacyUnveil(untilFlipMs) {
    if (this.legacyUnveiled) {
      return;
    }
    this.legacyUnveiled = true;
    this.emit(MESSAGES.PHASE, {
      name: "unveil",
      durationMs: Math.max(1, Math.round(untilFlipMs))
    });
  }
  update(deltaMS) {
    const fx = this.o.slice;
    this.updateIntro(deltaMS);
    this.updateHint(deltaMS);
    this.wrapper.update(
      deltaMS,
      { touched: this.tracking || this.started || this.locked, opened: this.locked },
      this.colors
    );
    this.pedestal.update(deltaMS);
    this.effects.update(deltaMS, fx, this.colors);
    const anim = this.anim;
    if (anim) {
      anim.elapsed += deltaMS;
      const t = clamp(anim.elapsed / anim.duration, 0, 1);
      if (anim.kind === "runOut") {
        const from = this.runOutFrom;
        const eased = 1 - (1 - t) * (1 - t);
        const x = from.x + (from.targetX - from.x) * eased;
        const y = clamp(
          from.y + from.slope * (x - from.x),
          this.rect.cutTop,
          this.rect.cutBottom
        );
        this.moveBlade(x, y);
        this.openness = 1;
        this.dirty = true;
        this.wrapper.setJolt(t);
      } else if (anim.kind === "autoSlice") {
        const point = this.arcPoint(t);
        this.moveBlade(point.x, point.y);
        this.progress = t;
        this.openness = t;
        this.dirty = true;
        if (t - this.lastTick >= this.o.interaction.tickStep) {
          this.lastTick = t;
          this.emit(MESSAGES.TICK, { progress: t });
        }
      } else if (anim.kind === "open") {
        const lid = clamp(t / this.o.motion.open.lid, 0, 1);
        this.release = easeOut(lid);
        this.applyLid();
        const drop = this.applyWrapperSink(t);
        this.card.slide(t, fx.riseBloom, this.colors.seam);
        this.effects.pourAt(
          this.rect,
          this.cutY + drop,
          this.release * (1 - clamp((t - 0.45) / 0.5, 0, 1)),
          fx,
          this.colors
        );
        if (!this.openedPosted && lid >= 1) {
          this.openedPosted = true;
          this.emit(MESSAGES.OPENED);
        }
      } else if (anim.kind === "retract") {
        this.openness = this.retractFrom * (1 - t);
        this.dirty = true;
      } else if (anim.kind === "charge" || anim.kind === "chargeHold") {
        this.chargeClock += deltaMS;
        this.card.charge(
          anim.kind === "charge" ? t : 1,
          this.chargeClock,
          fx,
          this.colors
        );
      } else if (anim.kind === "flip") {
        if (this.card.flipOver(t, fx, this.colors)) {
          this.buildPedestal();
        }
      } else if (anim.kind === "land") {
        this.landClock += deltaMS;
        this.card.land(t, this.landClock, fx);
        const knock = clamp(this.landClock / 320, 0, 1);
        this.root.y = fx.landShake * Math.sin(knock * Math.PI * 3) * Math.pow(1 - knock, 2);
      } else {
        this.card.reveal(anim.kind, t);
      }
      if (t >= 1) {
        this.anim = null;
        anim.onDone?.();
      }
    }
    if (this.dirty) {
      this.redraw();
    }
    this.drawLight();
  }
  /**
   * The point of light under the blade, redrawn every frame the blade moves,
   * and the pour put out whenever the pack is not opening.
   */
  drawLight() {
    const fx = this.o.slice;
    const kind = this.anim?.kind;
    const cutting = this.tracking && this.started && !this.locked || kind === "runOut" || kind === "autoSlice";
    const onPack = this.bladeX >= this.rect.left && this.bladeX <= this.rect.right;
    this.effects.showBlade(
      cutting && onPack ? { x: this.bladeX, y: this.bladeY } : null,
      fx,
      this.colors
    );
    if (kind !== "open") {
      this.effects.pourAt(this.rect, 0, 0, fx, this.colors);
    }
  }
  updateIntro(deltaMS) {
    if (this.intro >= 1) {
      return;
    }
    this.intro = clamp(this.intro + deltaMS / this.o.motion.introMs, 0, 1);
    this.root.alpha = easeOut(this.intro);
  }
  /** Runs the hint loop while the pack is untouched, fades it out on contact. */
  updateHint(deltaMS) {
    this.hint.update(deltaMS, this.rect, this.o.hint, this.started || this.locked);
  }
  applyLid() {
    this.wrapper.applyLid(this.release, this.dir, this.o.motion.open);
  }
  /**
   * The sunken wrapper and the clip that hides whatever part of the card is
   * still behind its lip. The wrapper hands back the drop it used, so the two
   * cannot disagree for a frame — when they did, the wrapper visibly jumped.
   * The drop is handed on, for what rides the lip.
   */
  applyWrapperSink(t) {
    const open = this.o.motion.open;
    const drop = this.wrapper.sink(t, open);
    const lip = this.cutY + drop;
    const freed = clamp((t - open.clipFrom) / (open.gone - open.clipFrom), 0, 1);
    this.card.clip(
      lip + (this.app.screen.height + this.card.height - lip) * freed
    );
    return drop;
  }
};

// src/core/variants/slice/index.ts
var slice = {
  id: "slice",
  presets: PRESETS3,
  defaultPreset: "classic",
  create({ app, texture, options, emit }) {
    return new PackScene(app, texture, options, emit);
  }
};

// src/core/variants/index.ts
var VARIANTS = {
  [slice.id]: slice,
  [burst.id]: burst,
  [carousel.id]: carousel
};
var DEFAULT_VARIANT = slice.id;
var variantOf = (name) => name && VARIANTS[name] || VARIANTS[DEFAULT_VARIANT];

// src/core/config/resolve.ts
var CARD_TIMEOUT_MS = 4e3;
var SOUND_VOLUME = 0.8;
var isPlain = (value) => !!value && typeof value === "object" && !Array.isArray(value);
function merge(base2, patch) {
  if (!isPlain(patch)) {
    return patch === void 0 ? base2 : patch;
  }
  const out = { ...base2 };
  for (const [key, value] of Object.entries(patch)) {
    if (value === void 0) {
      continue;
    }
    out[key] = isPlain(value) ? merge(out[key], value) : value;
  }
  return out;
}
function applySpeed(motion) {
  const speed = motion.speed > 0 ? motion.speed : 1;
  if (speed === 1) {
    return motion;
  }
  const scale = (ms) => Math.max(1, Math.round(ms / speed));
  return {
    ...motion,
    // Baked into the durations above, so resolving an already-resolved object
    // is a no-op instead of speeding everything up a second time
    speed: 1,
    introMs: scale(motion.introMs),
    finishMs: scale(motion.finishMs),
    autoSliceMs: scale(motion.autoSliceMs),
    retractMs: scale(motion.retractMs),
    open: { ...motion.open, ms: scale(motion.open.ms) },
    reveal: {
      ...motion.reveal,
      holdMs: scale(motion.reveal.holdMs),
      artWaitSpinMs: scale(motion.reveal.artWaitSpinMs)
    }
  };
}
function scaleDurations(group, speed, keys) {
  if (speed === 1) {
    return group;
  }
  const out = { ...group };
  for (const key of keys) {
    const value = out[key];
    if (typeof value === "number") {
      out[key] = Math.max(1, Math.round(value / speed));
    }
  }
  return out;
}
var finite = (...values) => values.every((v) => typeof v === "number" && Number.isFinite(v));
function restOf(rest) {
  const out = {};
  const card = rest.card;
  if (card && finite(card.left, card.top, card.width, card.height) && card.width > 0 && card.height > 0) {
    out.card = { left: card.left, top: card.top, width: card.width, height: card.height };
  }
  const pedestal = rest.pedestal;
  if (pedestal && finite(pedestal.left, pedestal.width, pedestal.bottom) && pedestal.width > 0) {
    out.pedestal = { left: pedestal.left, width: pedestal.width, bottom: pedestal.bottom };
  }
  return out;
}
function resolveOptions(options) {
  const variant = variantOf(options.variant);
  const presetName = options.preset ?? variant.defaultPreset;
  const preset = variant.presets[presetName] ?? variant.presets[variant.defaultPreset];
  const resolved = {
    variant: variant.id,
    preset: presetName,
    assets: {
      pack: { url: options.assets?.pack?.url ?? "" },
      card: {
        url: options.assets?.card?.url ?? "",
        timeoutMs: options.assets?.card?.timeoutMs ?? CARD_TIMEOUT_MS,
        // Only what can be shown: a fact with nothing to say is dropped
        facts: (options.assets?.card?.facts ?? []).filter(
          (fact) => fact && String(fact.value ?? "").trim() && String(fact.label ?? "").trim()
        ),
        ...options.assets?.card?.badge?.label ? {
          badge: {
            label: options.assets.card.badge.label,
            color: options.assets.card.badge.color ?? "#f5d000"
          }
        } : {}
      },
      // Empty means "the one baked into the package" — the scene decides, so a
      // host that has no stand of its own passes nothing
      pedestal: { url: options.assets?.pedestal?.url ?? "" }
    },
    theme: merge(preset.theme, options.theme),
    motion: merge(preset.motion, options.motion),
    layout: merge(preset.layout, options.layout),
    // The host's own, whole or not at all: a box with a side missing is no box
    ...options.rest ? { rest: restOf(options.rest) } : {},
    performance: merge(preset.performance, options.performance),
    // The host's, not a preset's: a preset tunes the dance, not the room
    sound: {
      enabled: options.sound?.enabled ?? false,
      volume: Math.min(1, Math.max(0, options.sound?.volume ?? SOUND_VOLUME)),
      muted: options.sound?.muted ?? false,
      badge: options.sound?.badge || options.assets?.card?.badge?.label || "",
      samples: options.sound?.samples ?? {}
    },
    // Only for the mechanic that owns them: a preset without `interaction` has
    // no cut to read, one without `charge` has no pressure to build. Filling
    // them in regardless would hand every scene numbers for an animation it
    // is not, and a host tuning the wrong group would see nothing happen.
    interaction: preset.interaction ? merge(preset.interaction, options.interaction) : void 0,
    hint: preset.hint ? merge(preset.hint, options.hint) : void 0,
    slice: preset.slice ? merge(preset.slice, options.slice) : void 0,
    charge: preset.charge ? merge(preset.charge, options.charge) : void 0,
    burst: preset.burst ? merge(preset.burst, options.burst) : void 0,
    carousel: preset.carousel ? merge(preset.carousel, options.carousel) : void 0
  };
  const speed = resolved.motion.speed > 0 ? resolved.motion.speed : 1;
  resolved.motion = applySpeed(resolved.motion);
  if (resolved.slice) {
    resolved.slice = scaleDurations(resolved.slice, speed, [
      "floatMs",
      "foilEveryMs",
      "foilMs",
      "sparkLifeMs",
      "chargeMs",
      "chargeWaitMs",
      "tiltMs",
      "flipMs",
      "landMs",
      "twinkleMs",
      "emberMs"
    ]);
  }
  if (resolved.charge) {
    resolved.charge = scaleDurations(resolved.charge, speed, [
      "holdMs",
      "releaseMs",
      "breatheMs"
    ]);
  }
  if (resolved.burst) {
    resolved.burst = scaleDurations(resolved.burst, speed, [
      "flashMs",
      "beatMs",
      "shardMs",
      "spikeMs",
      "ringMs",
      "debrisMs",
      "glitterMs",
      "swarmMs",
      "assembleMs",
      "snapMs"
    ]);
  }
  if (resolved.carousel) {
    resolved.carousel = scaleDurations(resolved.carousel, speed, [
      "shuffleMs",
      "dropMs",
      "riseMs",
      "dissolveMs",
      "factMs",
      "factGapMs",
      "bannerMs",
      "bannerHoldMs",
      "flipMs",
      "settleMs",
      "hoverMs"
    ]);
  }
  return resolved;
}

// src/core/sound/cues.ts
var DEFAULT_SPIN_MS = 3400;
var DEFAULT_UNVEIL_MS = 600;
var DEFAULT_BEAM_MS = 800;
var DEFAULT_HOLD_MS = 1100;
var DEFAULT_SWARM_MS = 520;
var DEFAULT_ASSEMBLE_MS = 1400;
var DEFAULT_SNAP_MS = 420;
var DEFAULT_FACT_MS = 320;
var DEFAULT_FACT_GAP_MS = 700;
var SWEEP_LEAD_MS = 2e3;
var IMPACT_RISE_MS = 940;
var BLAST_RISE_MS = 570;
var own = (engine, cue, shared) => engine.has(cue) ? cue : shared;
var SPIN_TURNS = 2;
var EDGE_ON = Array.from({ length: SPIN_TURNS * 2 }, (_, k) => {
  const f = (k + 0.5) / (SPIN_TURNS * 2);
  return f < 0.5 ? Math.cbrt(f / 4) : 1 - Math.cbrt((1 - f) / 4);
});
var MIN_SWISH_SPIN_MS = 1200;
var TIERS = {
  Grail: "grail",
  Chase: "grail",
  "Big Hit": "grail",
  Epic: "epic",
  Rare: "rare"
};
function landingTierFor(badge) {
  return badge && TIERS[badge] || "common";
}
var IMPACT_GAIN = { common: 0.6, rare: 0.8, epic: 1, grail: 1 };
function keep(list, voice) {
  if (voice) list.push(voice);
}
function stopAll(list, fadeMs) {
  for (const voice of list) voice.stop(fadeMs);
  list.length = 0;
}
function sliceScore(engine, tier) {
  let timeline = {};
  let tear = null;
  let sweep = null;
  let held = false;
  const swishes = [];
  const landing = [];
  const startTear = (gain) => {
    tear?.stop(60);
    tear = engine.play("pack-open", { gain, fadeInMs: 20 });
  };
  const stopTear = (fadeMs) => {
    tear?.stop(fadeMs);
    tear = null;
  };
  return {
    onEvent(event) {
      switch (event.type) {
        case "timeline":
          timeline = event.timeline;
          break;
        case "interactionStart":
          startTear(0.8);
          break;
        case "tick":
          tear?.setRate(0.9 + 0.25 * event.progress, 120);
          break;
        case "cancel":
          stopTear(150);
          break;
        case "phase":
          switch (event.name) {
            case "autoSlice":
              if (!tear) startTear(1);
              break;
            case "open":
              stopTear(120);
              engine.play("whoosh-deep", { gain: 0.7 });
              engine.play("sub-hit", { gain: 0.55, delayMs: 40 });
              break;
            case "spin": {
              const spinMs = event.durationMs || DEFAULT_SPIN_MS;
              const unveilMs = timeline.unveilMs ?? DEFAULT_UNVEIL_MS;
              const beamMs = timeline.beamMs ?? DEFAULT_BEAM_MS;
              sweep?.stop(0);
              sweep = engine.play("reveal-sweep", {
                gain: 1,
                delayMs: Math.max(0, spinMs + unveilMs + beamMs - SWEEP_LEAD_MS)
              });
              held = false;
              if (spinMs < MIN_SWISH_SPIN_MS) break;
              for (const [k, fraction] of EDGE_ON.entries()) {
                keep(
                  swishes,
                  engine.play("swish", {
                    gain: 0.45 + k % 2 * 0.1,
                    rate: 1 + k % 2 * 0.12,
                    delayMs: Math.round(fraction * spinMs)
                  })
                );
              }
              break;
            }
            case "spinHold":
              sweep?.stop(0);
              sweep = null;
              held = true;
              break;
            case "unveil": {
              stopAll(swishes, 40);
              if (held) {
                held = false;
                const unveilMs2 = event.durationMs || timeline.unveilMs || DEFAULT_UNVEIL_MS;
                const beamMs2 = timeline.beamMs ?? DEFAULT_BEAM_MS;
                sweep = engine.play("reveal-sweep", {
                  gain: 1,
                  delayMs: Math.max(0, unveilMs2 + beamMs2 - SWEEP_LEAD_MS)
                });
              }
              const unveilMs = event.durationMs || timeline.unveilMs || DEFAULT_UNVEIL_MS;
              const beamMs = timeline.beamMs ?? DEFAULT_BEAM_MS;
              keep(
                landing,
                engine.play("impact", {
                  gain: IMPACT_GAIN[tier()],
                  delayMs: Math.max(0, unveilMs + beamMs - IMPACT_RISE_MS)
                })
              );
              break;
            }
            case "beam": {
              const beamMs = event.durationMs || DEFAULT_BEAM_MS;
              keep(landing, engine.play("magic", { gain: 1, delayMs: beamMs }));
              break;
            }
            case "retract":
              stopTear(150);
              break;
            default:
              break;
          }
          break;
        case "revealed":
          stopTear(60);
          stopAll(swishes, 40);
          break;
        case "reset":
          stopEverything(40);
          break;
        default:
          break;
      }
    },
    dispose() {
      stopEverything(60);
    }
  };
  function stopEverything(fadeMs) {
    stopTear(fadeMs);
    stopAll(swishes, fadeMs);
    sweep?.stop(fadeMs);
    sweep = null;
    stopAll(landing, fadeMs);
  }
}
function burstScore(engine, tier) {
  let timeline = {};
  let charge = null;
  let blast = null;
  let blastHoldMs = 0;
  let sweep = null;
  let sweepAt = 0;
  const landing = [];
  const startCharge = () => {
    charge?.stop(60);
    charge = engine.play("engine-low", { loop: true, gain: 0.2, rate: 0.8, fadeInMs: 120 });
  };
  const stopCharge = (fadeMs) => {
    charge?.stop(fadeMs);
    charge = null;
  };
  const cueBlast = (holdMs) => {
    if (blast && blastHoldMs === holdMs) return;
    blast?.stop(0);
    blast = engine.play("blast", { gain: 1, delayMs: Math.max(0, holdMs - BLAST_RISE_MS) });
    blastHoldMs = holdMs;
  };
  const cancelBlast = () => {
    blast?.stop(0);
    blast = null;
  };
  return {
    onEvent(event) {
      switch (event.type) {
        case "timeline":
          timeline = event.timeline;
          break;
        case "interactionStart":
          startCharge();
          cueBlast(timeline.chargeHoldMs ?? DEFAULT_HOLD_MS);
          break;
        case "tick":
          charge?.setGain(0.2 + 0.8 * event.progress, 100);
          charge?.setRate(0.8 + 0.5 * event.progress, 100);
          break;
        case "cancel":
          stopCharge(250);
          cancelBlast();
          break;
        case "opened":
          stopCharge(30);
          if (!blast) blast = engine.play("blast", { gain: 1 });
          engine.play("boom", { gain: 0.5 });
          break;
        case "phase":
          switch (event.name) {
            case "autoCharge": {
              if (!charge) startCharge();
              const holdMs = event.durationMs || timeline.chargeHoldMs || DEFAULT_HOLD_MS;
              charge?.setGain(1, holdMs);
              charge?.setRate(1.3, holdMs);
              cueBlast(holdMs);
              break;
            }
            case "release": {
              const bleedMs = event.durationMs || timeline.releaseMs || 260;
              charge?.setRate(0.6, bleedMs);
              stopCharge(bleedMs);
              cancelBlast();
              break;
            }
            case "swarm": {
              const swarmMs = event.durationMs || DEFAULT_SWARM_MS;
              const assembleMs = timeline.assembleMs ?? DEFAULT_ASSEMBLE_MS;
              const snapMs = timeline.snapMs ?? DEFAULT_SNAP_MS;
              sweep?.stop(0);
              sweep = engine.play(own(engine, "burst-sweep", "reveal-sweep"), {
                gain: 0.8,
                delayMs: Math.max(0, swarmMs + assembleMs + snapMs - SWEEP_LEAD_MS)
              });
              sweepAt = performance.now() + swarmMs;
              break;
            }
            case "assemble": {
              const assembleMs = event.durationMs || timeline.assembleMs || DEFAULT_ASSEMBLE_MS;
              const snapMs = timeline.snapMs ?? DEFAULT_SNAP_MS;
              if (performance.now() > sweepAt + 100) {
                sweep?.stop(0);
                sweep = engine.play(own(engine, "burst-sweep", "reveal-sweep"), {
                  gain: 0.8,
                  delayMs: Math.max(0, assembleMs + snapMs - SWEEP_LEAD_MS)
                });
              }
              keep(
                landing,
                engine.play(own(engine, "burst-impact", "impact"), {
                  gain: IMPACT_GAIN[tier()],
                  delayMs: Math.max(0, assembleMs + snapMs - IMPACT_RISE_MS)
                })
              );
              break;
            }
            case "snap":
              engine.play("card-place", { gain: 0.7 });
              break;
            case "settle":
              keep(landing, engine.play(own(engine, "burst-magic", "magic"), { gain: 1 }));
              break;
            default:
              break;
          }
          break;
        case "revealed":
          stopCharge(60);
          break;
        case "reset":
          stopEverything(40);
          break;
        default:
          break;
      }
    },
    dispose() {
      stopEverything(60);
    }
  };
  function stopEverything(fadeMs) {
    stopCharge(fadeMs);
    cancelBlast();
    sweep?.stop(fadeMs);
    sweep = null;
    stopAll(landing, fadeMs);
  }
}
function carouselScore(engine) {
  let timeline = {};
  let ambience = null;
  let selected = false;
  const chimes = [];
  const startAmbience = () => {
    if (ambience || !engine.has("carousel-bg")) return;
    ambience = engine.play("carousel-bg", { loop: true, gain: 0.3, fadeInMs: 600 });
  };
  const stopAmbience = (fadeMs) => {
    ambience?.stop(fadeMs);
    ambience = null;
  };
  return {
    onEvent(event) {
      switch (event.type) {
        case "timeline":
          timeline = event.timeline;
          startAmbience();
          break;
        case "phase":
          switch (event.name) {
            case "step":
              engine.play("ring-step", { gain: 0.7 });
              break;
            case "drop":
              selected = !!engine.play("pack-select", { gain: 1 });
              if (!selected) engine.play("card-place", { gain: 0.6 });
              stopAmbience(500);
              break;
            case "rise":
              if (!selected) engine.play("ring-whoosh", { gain: 0.9 });
              break;
            case "facts": {
              const factMs = timeline.factMs ?? DEFAULT_FACT_MS;
              const step = factMs + (timeline.factGapMs ?? DEFAULT_FACT_GAP_MS);
              const beats = Math.max(1, Math.round((event.durationMs || step) / step));
              stopAll(chimes, 40);
              for (let i = 0; i < beats; i++) {
                keep(
                  chimes,
                  engine.play("ring-whoosh", { gain: 0.7, delayMs: Math.round(i * step) })
                );
              }
              break;
            }
            case "banner":
              engine.play("ring-whoosh", { gain: 0.7 });
              break;
            case "flip":
              engine.play("chime", { gain: 1 });
              break;
            default:
              break;
          }
          break;
        case "revealed":
          stopAll(chimes, 40);
          break;
        case "reset":
          selected = false;
          stopEverything(40);
          break;
        default:
          break;
      }
    },
    dispose() {
      stopEverything(60);
    }
  };
  function stopEverything(fadeMs) {
    stopAmbience(fadeMs);
    stopAll(chimes, fadeMs);
  }
}
function createScore(engine, variant, tier) {
  if (variant === "carousel") return carouselScore(engine);
  return variant === "burst" ? burstScore(engine, tier) : sliceScore(engine, tier);
}

// src/core/sound/engine.ts
var MIN_GAIN = 1e-4;
function makeContext() {
  if (typeof window === "undefined") return null;
  const Ctx = window.AudioContext ?? window.webkitAudioContext;
  if (!Ctx) return null;
  const session = navigator.audioSession;
  if (session) {
    try {
      session.type = "ambient";
    } catch {
    }
  }
  try {
    return new Ctx({ latencyHint: "interactive" });
  } catch {
    return null;
  }
}
function createSoundEngine() {
  let context = null;
  let master = null;
  let level = 1;
  let closed = false;
  const buffers = /* @__PURE__ */ new Map();
  const voices = /* @__PURE__ */ new Set();
  const ensure = () => {
    if (context || closed) return context;
    context = makeContext();
    if (!context) return null;
    master = context.createGain();
    master.gain.value = level;
    master.connect(context.destination);
    return context;
  };
  return {
    get context() {
      return ensure();
    },
    unlock() {
      const ctx = ensure();
      if (ctx && ctx.state === "suspended") {
        void ctx.resume().catch(() => {
        });
      }
    },
    setLevel(next) {
      level = Math.min(1, Math.max(0, next));
      if (master && context) {
        master.gain.setTargetAtTime(level, context.currentTime, 0.02);
      }
    },
    register(cue, buffer) {
      buffers.set(cue, buffer);
    },
    has(cue) {
      return buffers.has(cue);
    },
    play(cue, options = {}) {
      const buffer = buffers.get(cue);
      if (!buffer || level <= 0) return null;
      const ctx = ensure();
      if (!ctx || !master) return null;
      if (ctx.state === "suspended") void ctx.resume().catch(() => {
      });
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.loop = options.loop ?? false;
      source.playbackRate.value = options.rate ?? 1;
      const gain = ctx.createGain();
      const target = options.gain ?? 1;
      const at = ctx.currentTime + (options.delayMs ?? 0) / 1e3;
      if (options.fadeInMs) {
        gain.gain.setValueAtTime(MIN_GAIN, at);
        gain.gain.linearRampToValueAtTime(target, at + options.fadeInMs / 1e3);
      } else {
        gain.gain.setValueAtTime(target, at);
      }
      source.connect(gain);
      gain.connect(master);
      source.start(at);
      let live = true;
      const voice = {
        stop(fadeMs = 0) {
          if (!live) return;
          live = false;
          voices.delete(voice);
          const now = ctx.currentTime;
          if (fadeMs > 0) {
            gain.gain.cancelScheduledValues(now);
            gain.gain.setValueAtTime(Math.max(MIN_GAIN, gain.gain.value), now);
            gain.gain.exponentialRampToValueAtTime(MIN_GAIN, now + fadeMs / 1e3);
            source.stop(now + fadeMs / 1e3 + 0.01);
          } else {
            source.stop(now);
          }
        },
        setGain(value, rampMs = 40) {
          if (!live) return;
          gain.gain.setTargetAtTime(Math.max(MIN_GAIN, value), ctx.currentTime, rampMs / 1e3);
        },
        setRate(value, rampMs = 40) {
          if (!live) return;
          source.playbackRate.setTargetAtTime(value, ctx.currentTime, rampMs / 1e3);
        }
      };
      source.onended = () => {
        live = false;
        voices.delete(voice);
      };
      voices.add(voice);
      return voice;
    },
    stopAll(fadeMs = 0) {
      for (const voice of [...voices]) voice.stop(fadeMs);
    },
    close() {
      closed = true;
      voices.clear();
      void context?.close().catch(() => {
      });
      context = null;
      master = null;
    }
  };
}

// src/core/sound/index.ts
async function decode(context, uri) {
  const binary = atob(uri.slice(uri.indexOf(",") + 1));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return context.decodeAudioData(bytes.buffer);
}
async function load(context, source) {
  if (source.startsWith("data:")) return decode(context, source);
  const response = await fetch(source);
  if (!response.ok) throw new Error(`${response.status} for ${source}`);
  return context.decodeAudioData(await response.arrayBuffer());
}
function createSound(variant, initial) {
  const engine = createSoundEngine();
  let current = initial;
  let loading = false;
  const score = createScore(engine, variant, () => landingTierFor(current.badge));
  const loadBank = () => {
    if (loading) return;
    loading = true;
    void import("./samples-XI4B54G7.js").then(async ({ default: samples }) => {
      const context = engine.context;
      if (!context) return;
      await Promise.all(
        Object.entries(samples).map(async ([cue, uri]) => {
          try {
            engine.register(cue, await decode(context, uri));
          } catch {
          }
        })
      );
      await Promise.all(
        Object.entries(current.samples).map(async ([cue, source]) => {
          try {
            engine.register(cue, await load(context, source));
          } catch {
          }
        })
      );
    }).catch(() => {
    });
  };
  const set = (sound) => {
    current = sound;
    engine.setLevel(sound.enabled && !sound.muted ? sound.volume : 0);
    if (sound.enabled) loadBank();
  };
  set(initial);
  return {
    hear(type, payload = {}) {
      switch (type) {
        case MESSAGES.TIMELINE:
          score.onEvent({ type: "timeline", timeline: payload });
          break;
        case MESSAGES.INTERACTION_START:
          score.onEvent({ type: "interactionStart" });
          break;
        case MESSAGES.TICK:
          score.onEvent({ type: "tick", progress: Number(payload.progress) || 0 });
          break;
        case MESSAGES.RETRACTED:
          score.onEvent({ type: "cancel" });
          break;
        case MESSAGES.PHASE:
          score.onEvent({
            type: "phase",
            name: String(payload.name),
            durationMs: Number(payload.durationMs) || 0
          });
          break;
        case MESSAGES.OPENED:
          score.onEvent({ type: "opened" });
          break;
        case MESSAGES.REVEALED:
          score.onEvent({ type: "revealed" });
          break;
        default:
          break;
      }
    },
    set,
    unlock() {
      if (current.enabled) engine.unlock();
    },
    reset() {
      score.onEvent({ type: "reset" });
    },
    destroy() {
      score.dispose();
      engine.close();
    }
  };
}

// src/core/index.ts
function timelineOf(resolved) {
  const o = resolved;
  const pick = (source, key) => typeof source?.[key] === "number" ? source[key] : void 0;
  const timeline = {
    // 0.4's slice phases start with the lid, the charge and the turn — see the
    // slice scene's `announceLegacyPhase`
    spinMs: o.slice ? pick(o.motion.open, "ms") : void 0,
    unveilMs: pick(o.slice, "chargeMs"),
    beamMs: pick(o.slice, "flipMs"),
    chargeMs: pick(o.slice, "chargeMs"),
    landMs: pick(o.slice, "landMs"),
    holdMs: pick(o.motion.reveal, "holdMs"),
    chargeHoldMs: pick(o.charge, "holdMs"),
    releaseMs: pick(o.charge, "releaseMs"),
    beatMs: pick(o.burst, "beatMs"),
    swarmMs: pick(o.burst, "swarmMs"),
    assembleMs: pick(o.burst, "assembleMs"),
    snapMs: pick(o.burst, "snapMs"),
    shuffleMs: pick(o.carousel, "shuffleMs"),
    dropMs: pick(o.carousel, "dropMs"),
    riseMs: pick(o.carousel, "riseMs"),
    dissolveMs: pick(o.carousel, "dissolveMs"),
    factMs: pick(o.carousel, "factMs"),
    factGapMs: pick(o.carousel, "factGapMs"),
    bannerMs: pick(o.carousel, "bannerMs"),
    bannerHoldMs: pick(o.carousel, "bannerHoldMs"),
    flipMs: pick(o.carousel, "flipMs") ?? pick(o.slice, "flipMs")
  };
  for (const key of Object.keys(timeline)) {
    if (timeline[key] === void 0) delete timeline[key];
  }
  return timeline;
}
async function loadImageTexture(url) {
  const image = new Image();
  image.crossOrigin = "anonymous";
  await new Promise((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () => reject(new Error(`could not load ${url}`));
    image.src = url;
  });
  return Texture10.from(image);
}
async function loadTexture(url) {
  try {
    return await Assets.load({ src: url, loadParser: "loadTextures" });
  } catch {
    const image = new Image();
    image.crossOrigin = "anonymous";
    await new Promise((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error(`could not load ${url}`));
      image.src = url;
    });
    return Texture10.from(image);
  }
}
async function createPackOpener(target, options, { onEvent } = {}) {
  const resolved = resolveOptions(options);
  let sound = null;
  const emit = (type, payload) => {
    sound?.hear(type, payload);
    onEvent?.(payload ? { type, ...payload } : { type });
  };
  const variant = variantOf(resolved.variant);
  let current = resolved;
  const isOpaque = (color) => !!color && color !== "transparent";
  const background = resolved.theme.background;
  const opaque = isOpaque(background);
  const app = new Application();
  await app.init({
    background: opaque ? background : void 0,
    backgroundAlpha: opaque ? 1 : 0,
    antialias: resolved.performance.antialias,
    resolution: Math.min(
      window.devicePixelRatio || 1,
      resolved.performance.resolutionCap
    ),
    autoDensity: true,
    // A full-page host (the WebView) tracks the window; an embedded canvas
    // tracks its own box, so the pack stays centred inside the element
    resizeTo: target === document.body ? window : target,
    preference: "webgl"
  });
  const canvas = app.canvas;
  canvas.style.display = "block";
  canvas.style.touchAction = "none";
  canvas.style.userSelect = "none";
  canvas.style.setProperty("-webkit-user-select", "none");
  canvas.style.setProperty("-webkit-user-drag", "none");
  canvas.style.setProperty("-webkit-touch-callout", "none");
  target.appendChild(canvas);
  let texture;
  try {
    texture = await loadTexture(resolved.assets.pack.url);
  } catch (error) {
    app.destroy(true, { children: true });
    throw error;
  }
  sound = createSound(resolved.variant, resolved.sound);
  const scene = variant.create({ app, texture, options: resolved, emit });
  const pedestalUrl = resolved.assets.pedestal.url;
  (pedestalUrl ? loadTexture(pedestalUrl) : loadImageTexture(DEFAULT_PEDESTAL_URI)).then(
    (pedestalTexture) => scene.setPedestalTexture(pedestalTexture)
  ).catch(() => {
  });
  if (resolved.assets.card.url) {
    loadTexture(resolved.assets.card.url).then((cardTexture) => scene.setCardTexture(cardTexture)).catch(() => {
    });
  }
  const frameCapFor = (activity) => {
    const perf = current.performance;
    if (activity === "idle") {
      return Math.max(1, perf.sleepFps);
    }
    return activity === "hint" ? perf.idleFps : perf.maxFps;
  };
  const wake = () => {
    app.ticker.maxFPS = current.performance.maxFps;
  };
  const tick = (ticker) => {
    scene.update(ticker.deltaMS);
    const wanted = frameCapFor(scene.activity ?? "busy");
    if (app.ticker.maxFPS !== wanted) {
      app.ticker.maxFPS = wanted;
    }
  };
  app.ticker.maxFPS = resolved.performance.maxFps;
  app.ticker.add(tick);
  const local = (event) => {
    const rect = canvas.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };
  let dragging = false;
  const onDown = (event) => {
    sound?.unlock();
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    wake();
    try {
      canvas.setPointerCapture(event.pointerId);
    } catch {
    }
    dragging = true;
    const p = local(event);
    scene.onDown(p.x, p.y);
  };
  const onMove = (event) => {
    if (!dragging) {
      return;
    }
    if (event.buttons === 0 && event.pointerType === "mouse") {
      onUp(event);
      return;
    }
    const p = local(event);
    scene.onMove(p.x, p.y);
  };
  const onUp = (event) => {
    if (!dragging) {
      return;
    }
    dragging = false;
    try {
      canvas.releasePointerCapture(event.pointerId);
    } catch {
    }
    scene.onUp();
  };
  const onDragStart = (event) => event.preventDefault();
  const onResize = () => scene.resize?.();
  app.renderer.on("resize", onResize);
  canvas.addEventListener("dragstart", onDragStart);
  canvas.addEventListener("pointerdown", onDown);
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerup", onUp);
  canvas.addEventListener("pointercancel", onUp);
  emit(MESSAGES.READY, {
    width: app.screen.width,
    height: app.screen.height,
    rect: scene.rect,
    renderer: app.renderer.name
  });
  emit(MESSAGES.TIMELINE, timelineOf(resolved));
  return {
    setOptions: (next) => {
      const nextResolved = resolveOptions(next);
      sound?.set(nextResolved.sound);
      if (nextResolved.variant !== current.variant || nextResolved.assets.pack.url !== current.assets.pack.url || !scene.setOptions) {
        return "scene";
      }
      const nextBackground = nextResolved.theme.background;
      app.renderer.background.color = isOpaque(nextBackground) ? nextBackground : 0;
      app.renderer.background.alpha = isOpaque(nextBackground) ? 1 : 0;
      if (nextResolved.assets.card.url !== current.assets.card.url) {
        const url = nextResolved.assets.card.url;
        if (url) {
          Assets.load({ src: url, loadParser: "loadTextures" }).then((texture2) => scene.setCardTexture(texture2)).catch(() => {
          });
        }
      }
      current = nextResolved;
      const live = scene.setOptions(nextResolved);
      wake();
      emit(MESSAGES.TIMELINE, timelineOf(nextResolved));
      return live ? "applied" : "deferred";
    },
    autoSlice: () => {
      wake();
      scene.autoSlice();
    },
    shuffle: () => {
      if (!scene.shuffle) return;
      wake();
      scene.shuffle();
    },
    reset: () => {
      wake();
      scene.reset();
      sound?.reset();
    },
    setEnabled: (value) => {
      wake();
      scene.setEnabled(value);
    },
    destroy: () => {
      app.renderer.off("resize", onResize);
      canvas.removeEventListener("dragstart", onDragStart);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointercancel", onUp);
      app.ticker.remove(tick);
      scene.destroy?.();
      sound?.destroy();
      app.destroy(true, { children: true });
    }
  };
}

export {
  MESSAGES,
  VARIANTS,
  variantOf,
  resolveOptions,
  createPackOpener
};
//# sourceMappingURL=chunk-OGAHQODY.js.map
