export class Subscribers {
    fns = new Set();
    getCurrent;
    constructor(getCurrent) {
        this.getCurrent = getCurrent;
    }
    subscribe(fn) {
        this.fns.add(fn);
        fn(this.getCurrent());
        return () => {
            this.fns.delete(fn);
        };
    }
    emit(value) {
        for (const fn of this.fns) {
            fn(value);
        }
    }
    get size() {
        return this.fns.size;
    }
    clear() {
        this.fns.clear();
    }
}
//# sourceMappingURL=subscribers.js.map