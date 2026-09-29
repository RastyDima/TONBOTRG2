const test = require('node:test');
const assert = require('node:assert/strict');
const demo = require('../webapp/js/mines-demo.js');

test('demo creates a 5×5 board with the requested number of mines', () => {
    const round = demo.createRound(10, () => 0);
    assert.equal(round.mines.length, 10);
    assert.equal(new Set(round.mines).size, 10);
    assert.ok(round.mines.every(index => index >= 0 && index < 25));
    assert.throws(() => demo.createRound(11), RangeError);
});

test('cashout requires a profitable reveal and never changes bot balance', () => {
    const initial = { mineCount: 1, mines: [24], opened: [], status: 'playing', exploded: null };
    assert.equal(demo.cashout(initial), initial);
    const first = demo.reveal(initial, 0);
    assert.equal(demo.canCashout(first), false);
    const second = demo.reveal(first, 1);
    assert.equal(demo.multiplier(1, 2), 1.02);
    assert.equal(demo.canCashout(second), true);
    const finished = demo.cashout(second);
    assert.equal(finished.status, 'cashed');
    assert.equal(demo.reveal(finished, 2), finished);
    assert.equal('balance' in finished, false);
});

test('a mine ends the round and the multiplier stops at ×8', () => {
    const initial = { mineCount: 10, mines: Array.from({ length: 10 }, (_, i) => i),
        opened: [], status: 'playing', exploded: null };
    const lost = demo.reveal(initial, 0);
    assert.equal(lost.status, 'lost');
    assert.equal(lost.exploded, 0);
    assert.equal(demo.reveal(lost, 10), lost);

    let round = initial;
    for (let i = 10; i < 25 && round.status === 'playing'; i++) {
        round = demo.reveal(round, i);
    }
    assert.equal(round.status, 'completed');
    assert.equal(demo.multiplier(round.mineCount, round.opened.length), 8);
});
