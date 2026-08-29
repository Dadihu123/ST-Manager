import { Subscribers } from "./subscribers.js";
let activeCard = null;
const subscribers = new Subscribers(() => activeCard);
export const getActiveCard = () => activeCard;
export const setActiveCard = (card) => {
    if (card === activeCard) {
        return;
    }
    activeCard = card;
    subscribers.emit(activeCard);
};
export const subscribeActiveCard = (fn) => subscribers.subscribe(fn);
//# sourceMappingURL=active-registry.js.map