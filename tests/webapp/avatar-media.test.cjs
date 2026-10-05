const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../webapp/js/avatar.js'), 'utf8');

function media(fetch) {
    const context = { fetch };
    vm.runInNewContext(source, context);
    return context.AvatarMedia;
}

test('image request sends bearer header without putting credentials in the URL', async () => {
    const blob = new Blob(['GIF89a-original-bytes'], { type: 'image/gif' });
    const signal = new AbortController().signal;
    const result = await media(async (url, options) => {
        assert.equal(url, '/app/api/profile/avatar');
        assert.equal(options.headers.Authorization, 'Bearer signed-session');
        assert.equal(options.cache, 'no-store');
        assert.equal(options.signal, signal);
        return { ok: true, status: 200, blob: async () => blob };
    }).load('signed-session', signal);
    assert.equal(result, blob);
    assert.equal(await result.text(), 'GIF89a-original-bytes');
});

test('no avatar returns null without parsing an empty body', async () => {
    assert.equal(await media(async () => ({ status: 204 })).load('session'), null);
});

test('authentication and transient failures retain their HTTP status', async () => {
    for (const status of [401, 503]) {
        await assert.rejects(media(async () => ({ ok: false, status })).load('session'),
            error => error.status === status);
    }
});

test('non-image responses are not used as avatar blobs', async () => {
    await assert.rejects(media(async () => ({ ok: true, status: 200,
        blob: async () => new Blob(['html'], { type: 'text/html' }),
    })).load('session'), /Invalid avatar image/);
});
