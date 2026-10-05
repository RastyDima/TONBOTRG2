const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const root = path.join(__dirname, '../..');
const reactRoot = path.dirname(require.resolve('react/package.json'));
const domRoot = path.dirname(require.resolve('react-dom/package.json'));
const gif = Buffer.from('R0lGODlhEAAQAIEAAP8AAAAAAAAAAAAAACH/C05FVFNDQVBFMi4wAwEAAAAh+QQADAAAACwAAAAAEAAQAAAIHQABCBxIsKDBgwgTKlzIsKHDhxAjSpxIsaLFgQEBACH5BAEMAAEALAAAAAAQABAAgQAA/wAAAAAAAAAAAAgdAAEIHEiwoMGDCBMqXMiwocOHECNKnEixosWBAQEAOw==', 'base64');
const profile = { user_id: 101, first_name: 'Анна', balance: 1000, rubies: 0, xp: 0,
    total_games: 0, wins: 0, losses: 0, total_bet: 0, total_won: 0,
    referral_count: 0, earned_achievements: [], showcase: [] };
let browser;
before(async () => { browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox'],
}); });
after(async () => { await browser?.close(); });

async function openApp(t, avatarResponse) {
    const context = await browser.newContext();
    context.setDefaultTimeout(10000);
    context.setDefaultNavigationTimeout(10000);
    t.after(() => context.close());
    const page = await context.newPage();
    const requests = [], errors = [];
    page.on('pageerror', error => {
        errors.push(error.message);
        console.error('WebApp browser error:', error.message);
    });
    page.on('console', message => {
        if (message.type() === 'error') console.error('Browser console:', message.text());
    });
    await page.addInitScript(() => {
        localStorage.setItem('webapp_token', 'signed-session');
        window.__avatarImageErrors = 0;
        window.addEventListener('error', event => {
            if (event.target instanceof HTMLImageElement) window.__avatarImageErrors++;
        }, true);
    });
    await page.route('**/*', async route => {
        const request = route.request(), url = new URL(request.url());
        const file = (filename, contentType) => route.fulfill({ body: fs.readFileSync(filename),
            contentType, headers: { 'Access-Control-Allow-Origin': '*' } });
        const json = body => route.fulfill({ json: body });
        if (url.hostname === 'telegram.org') return route.fulfill({ body: '', contentType: 'text/javascript' });
        if (url.hostname === 'unpkg.com') {
            if (url.pathname.includes('react-dom@')) return file(path.join(domRoot, 'umd/react-dom.production.min.js'), 'text/javascript');
            if (url.pathname.includes('react@')) return file(path.join(reactRoot, 'umd/react.production.min.js'), 'text/javascript');
            return file(require.resolve('@babel/standalone/babel.min.js'), 'text/javascript');
        }
        if (url.pathname === '/app/') return file(path.join(root, 'webapp/index.html'), 'text/html');
        if (url.pathname.startsWith('/app/static/')) return file(
            path.join(root, 'webapp', url.pathname.slice('/app/static/'.length)),
            url.pathname.endsWith('.css') ? 'text/css' : 'text/javascript');
        if (url.pathname === '/app/api/profile/avatar') {
            requests.push({ url: request.url(), authorization: request.headers().authorization });
            return route.fulfill(await avatarResponse(requests.length));
        }
        if (url.pathname === '/app/api/profile') return json(profile);
        if (url.pathname === '/app/api/mobile/sessions') return json({ sessions: [] });
        if (url.pathname === '/app/api/shop') return json({ balance: 1000, frames: [
            { id: 'frame_gold', name: 'Золотая', price: 100, owned: false, color: [255, 215, 0] },
        ], titles: [] });
        return route.fulfill({ status: 404 });
    });
    await page.goto('http://avatar.local/app/?client=android');
    try {
        await page.waitForSelector('.profile-header');
    } catch (error) {
        console.error('WebApp DOM:', await page.locator('#root').innerHTML());
        throw error;
    }
    return { page, requests, errors };
}

test('Android without Telegram user data loads the same GIF in profile and shop', async t => {
    const { page, requests, errors } = await openApp(t, async () => ({ body: gif, contentType: 'image/gif' }));
    await page.waitForFunction(() => document.querySelector('.profile-header img')?.naturalWidth === 16);
    const url = await page.locator('.profile-header img').getAttribute('src');
    assert.ok(url.startsWith('blob:'));
    const loadedBytes = await page.evaluate(async src => Array.from(new Uint8Array(await (await fetch(src)).arrayBuffer())), url);
    assert.deepEqual(Buffer.from(loadedBytes), gif);
    await page.getByRole('button', { name: 'Магазин' }).click();
    await page.waitForFunction(() => document.querySelector('.shop-card img')?.naturalWidth === 16);
    assert.equal(await page.locator('.shop-card img').getAttribute('src'), url);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].authorization, 'Bearer signed-session');
    assert.equal(new URL(requests[0].url).search, '');
    assert.deepEqual(errors, []);
});

test('missing avatar displays initials', async t => {
    const { page, errors } = await openApp(t, async () => ({ status: 204 }));
    assert.equal(await page.locator('.profile-header .frame-avatar-core').innerText(), 'А');
    assert.equal(await page.locator('.profile-header img').count(), 0);
    assert.deepEqual(errors, []);
});

test('invalid image falls back to initials instead of a broken image', async t => {
    const { page, errors } = await openApp(t, async () => ({ body: 'GIF89a-invalid', contentType: 'image/gif' }));
    await page.waitForFunction(() => window.__avatarImageErrors > 0);
    await page.waitForFunction(() => document.querySelector('.profile-header .frame-avatar-core')?.textContent === 'А');
    assert.equal(await page.locator('.profile-header img').count(), 0);
    assert.deepEqual(errors, []);
});

test('temporary avatar error recovers when connectivity returns', async t => {
    const { page, requests, errors } = await openApp(t, async count => count === 1
        ? { status: 503 } : { body: gif, contentType: 'image/gif' });
    await page.waitForFunction(() => document.querySelector('.profile-header .frame-avatar-core')?.textContent === 'А');
    await page.evaluate(() => window.dispatchEvent(new Event('online')));
    await page.waitForFunction(() => document.querySelector('.profile-header img')?.naturalWidth === 16);
    assert.ok(requests.length >= 2);
    assert.deepEqual(errors, []);
});
