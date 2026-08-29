export const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());
const raf = typeof requestAnimationFrame !== "undefined"
    ? (cb) => requestAnimationFrame(cb)
    : (cb) => setTimeout(() => cb(now()), 1000 / 60);
const tasks = new Set();
const runTasks = (time) => {
    tasks.forEach((task) => {
        if (!task(time)) {
            tasks.delete(task);
        }
    });
    if (tasks.size !== 0) {
        raf(runTasks);
    }
};
export const loop = (callback) => {
    if (tasks.size === 0) {
        raf(runTasks);
    }
    tasks.add(callback);
    return {
        abort: () => {
            tasks.delete(callback);
        },
    };
};
//# sourceMappingURL=ticker.js.map