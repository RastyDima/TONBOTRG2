(function (root) {
    const FIELD_SIZE = 25;
    const MAX_MULTIPLIER = 8;

    function multiplier(mineCount, openedCount) {
        if (openedCount === 0) return 1;
        let survival = 1;
        for (let i = 0; i < openedCount; i++) {
            survival *= (FIELD_SIZE - mineCount - i) / (FIELD_SIZE - i);
        }
        return Math.min(MAX_MULTIPLIER, Math.round((0.94 / survival) * 100) / 100);
    }

    function secureIndex(max) {
        const range = 0x100000000;
        const limit = range - (range % max);
        const value = new Uint32Array(1);
        do {
            root.crypto.getRandomValues(value);
        } while (value[0] >= limit);
        return value[0] % max;
    }

    function createRound(mineCount, randomIndex = secureIndex) {
        if (!Number.isInteger(mineCount) || mineCount < 1 || mineCount > 10) {
            throw new RangeError('mineCount must be from 1 to 10');
        }
        const cells = Array.from({ length: FIELD_SIZE }, (_, i) => i);
        for (let i = FIELD_SIZE - 1; i > 0; i--) {
            const j = randomIndex(i + 1);
            if (!Number.isInteger(j) || j < 0 || j > i) {
                throw new RangeError('randomIndex returned an invalid index');
            }
            [cells[i], cells[j]] = [cells[j], cells[i]];
        }
        return { mineCount, mines: cells.slice(0, mineCount), opened: [], status: 'playing', exploded: null };
    }

    function canCashout(round) {
        return round.status === 'playing'
            && round.opened.length > 0
            && multiplier(round.mineCount, round.opened.length) > 1;
    }

    function reveal(round, index) {
        if (round.status !== 'playing' || !Number.isInteger(index)
            || index < 0 || index >= FIELD_SIZE || round.opened.includes(index)) {
            return round;
        }
        if (round.mines.includes(index)) {
            return { ...round, status: 'lost', exploded: index };
        }
        const opened = [...round.opened, index];
        const reachedLimit = multiplier(round.mineCount, opened.length) >= MAX_MULTIPLIER;
        const clearedField = opened.length === FIELD_SIZE - round.mineCount;
        return { ...round, opened, status: reachedLimit || clearedField ? 'completed' : 'playing' };
    }

    function cashout(round) {
        return canCashout(round) ? { ...round, status: 'cashed' } : round;
    }

    const api = { FIELD_SIZE, MAX_MULTIPLIER, multiplier, createRound, canCashout, reveal, cashout };
    root.MinesDemo = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
