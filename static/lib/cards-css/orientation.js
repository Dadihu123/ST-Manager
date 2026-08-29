import { Subscribers } from "./subscribers.js";
const rawOrientation = (event) => {
    if (!event) {
        return { alpha: 0, beta: 0, gamma: 0 };
    }
    return { alpha: event.alpha ?? 0, beta: event.beta ?? 0, gamma: event.gamma ?? 0 };
};
let firstReading = true;
let baseOrientation = rawOrientation();
export const resetBaseOrientation = () => {
    firstReading = true;
    baseOrientation = rawOrientation();
};
const toRelative = (event) => {
    const o = rawOrientation(event);
    return {
        absolute: o,
        relative: {
            alpha: o.alpha - baseOrientation.alpha,
            beta: o.beta - baseOrientation.beta,
            gamma: o.gamma - baseOrientation.gamma,
        },
    };
};
const subscribers = new Subscribers(() => toRelative());
let listening = false;
const handleOrientation = (event) => {
    if (firstReading) {
        firstReading = false;
        baseOrientation = rawOrientation(event);
    }
    subscribers.emit(toRelative(event));
};
export const subscribeOrientation = (fn) => {
    const unsubscribe = subscribers.subscribe(fn);
    if (!listening && typeof window !== "undefined") {
        listening = true;
        window.addEventListener("deviceorientation", handleOrientation, true);
    }
    return () => {
        unsubscribe();
        if (subscribers.size === 0 && listening && typeof window !== "undefined") {
            listening = false;
            window.removeEventListener("deviceorientation", handleOrientation, true);
        }
    };
};
export const requestOrientationPermission = async () => {
    if (typeof DeviceOrientationEvent === "undefined") {
        return false;
    }
    const requester = DeviceOrientationEvent;
    if (typeof requester.requestPermission !== "function") {
        return true;
    }
    try {
        const result = await requester.requestPermission();
        return result === "granted";
    }
    catch {
        return false;
    }
};
//# sourceMappingURL=orientation.js.map