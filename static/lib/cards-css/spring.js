import { loop, now } from "./ticker.js";
import { Subscribers } from "./subscribers.js";
const MAX_FRAME_DELTA = 2;
const clampFrameDelta = (dt) => Math.max(0, Math.min(dt, MAX_FRAME_DELTA));
const tickScalar = (ctx, axis, lastValue, currentValue, targetValue) => {
    const delta = targetValue - currentValue;
    const velocity = (currentValue - lastValue) / (ctx.dt || 1 / 60);
    const spring = axis.stiffness * delta;
    const damper = axis.damping * velocity;
    const acceleration = (spring - damper) * ctx.invMass;
    const d = (velocity + acceleration) * ctx.dt;
    if (Math.abs(d) < axis.precision && Math.abs(delta) < axis.precision) {
        return targetValue;
    }
    ctx.settled = false;
    return currentValue + d;
};
const resolveAxis = (ctx, key) => {
    const override = ctx.axes?.[key];
    if (!override) {
        return ctx;
    }
    return {
        stiffness: override.stiffness ?? ctx.stiffness,
        damping: override.damping ?? ctx.damping,
        precision: override.precision ?? ctx.precision,
    };
};
const tick = (ctx, last, current, target) => {
    if (typeof current === "number") {
        return tickScalar(ctx, ctx, last, current, target);
    }
    const cur = current;
    const lst = last;
    const tgt = target;
    const result = {};
    for (const key in cur) {
        const c = cur[key] ?? 0;
        result[key] = tickScalar(ctx, resolveAxis(ctx, key), lst[key] ?? c, c, tgt[key] ?? c);
    }
    return result;
};
export class Spring {
    stiffness;
    damping;
    precision;
    axes;
    value;
    lastValue;
    targetValue;
    invMass = 1;
    invMassRecoveryRate = 0;
    cancelTask = false;
    task = null;
    lastTime = 0;
    settlePromise = null;
    settleResolve = null;
    subscribers = new Subscribers(() => this.value);
    constructor(value, opts = {}) {
        this.value = value;
        this.lastValue = value;
        this.targetValue = value;
        this.stiffness = opts.stiffness ?? 0.15;
        this.damping = opts.damping ?? 0.8;
        this.precision = opts.precision ?? 0.01;
        this.axes = opts.axes;
    }
    get current() {
        return this.value;
    }
    /** Whether the spring is at rest (no animation task is running). */
    get settled() {
        return this.task === null;
    }
    subscribe(fn) {
        return this.subscribers.subscribe(fn);
    }
    notify() {
        this.subscribers.emit(this.value);
    }
    set(newValue, opts = {}) {
        this.targetValue = newValue;
        if (opts.hard || (this.stiffness >= 1 && this.damping >= 1)) {
            this.cancelTask = true;
            if (this.task) {
                this.task.abort();
                this.task = null;
            }
            this.lastTime = now();
            this.lastValue = newValue;
            this.value = newValue;
            this.notify();
            this.resolveSettle();
            return Promise.resolve();
        }
        if (opts.soft) {
            const rate = opts.soft === true ? 0.5 : opts.soft;
            this.invMassRecoveryRate = 1 / (rate * 60);
            this.invMass = 0;
        }
        if (!this.task) {
            this.lastTime = now();
            this.cancelTask = false;
            this.task = loop((time) => {
                if (this.cancelTask) {
                    this.cancelTask = false;
                    this.task = null;
                    return false;
                }
                this.invMass = Math.min(this.invMass + this.invMassRecoveryRate, 1);
                const ctx = {
                    invMass: this.invMass,
                    stiffness: this.stiffness,
                    damping: this.damping,
                    precision: this.precision,
                    axes: this.axes,
                    settled: true,
                    dt: clampFrameDelta(((time - this.lastTime) * 60) / 1000),
                };
                const next = tick(ctx, this.lastValue, this.value, this.targetValue);
                this.lastTime = time;
                this.lastValue = this.value;
                this.value = next;
                this.notify();
                if (ctx.settled) {
                    this.task = null;
                    this.resolveSettle();
                }
                return !ctx.settled;
            });
        }
        if (!this.settlePromise) {
            this.settlePromise = new Promise((resolve) => {
                this.settleResolve = resolve;
            });
        }
        return this.settlePromise;
    }
    resolveSettle() {
        const resolve = this.settleResolve;
        this.settlePromise = null;
        this.settleResolve = null;
        resolve?.();
    }
    destroy() {
        this.cancelTask = true;
        this.task?.abort();
        this.task = null;
        this.resolveSettle();
        this.subscribers.clear();
    }
}
//# sourceMappingURL=spring.js.map