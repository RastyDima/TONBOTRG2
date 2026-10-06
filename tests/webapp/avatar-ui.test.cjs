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

async function openApp(t, avatarResponse, options = {}) {
    const context = await browser.newContext({ viewport: { width: 360, height: 780 },
        ...options.context });
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
        if (url.pathname.startsWith('/app/api/') && options.handleApi) {
            const response = await options.handleApi(request, url);
            if (response) return route.fulfill(response);
        }
        if (url.pathname === '/app/api/profile/avatar') {
            requests.push({ url: request.url(), authorization: request.headers().authorization });
            return route.fulfill(await avatarResponse(requests.length));
        }
        if (url.pathname === '/app/api/profile') return json(options.profile || profile);
        if (url.pathname === '/app/api/hub') return json({ bonuses: {
            daily: { available: true }, weekly: { available: true } }, active_game: null });
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

const prefs = { bio: '', theme: 'dark', saved_bet: 100, hide_stats: false, favorites: [], custom_avatar: false };
const player = () => ({ ...profile, preferences: { ...prefs, favorites: [] }, max_bet: 250000 });
const previews = path.join(__dirname, 'screenshots');
async function preview(page, name) {
    fs.mkdirSync(previews, { recursive: true });
    await page.screenshot({ path: path.join(previews, name + '.png'), fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true,
        name + ' must fit a 360px screen');
}

test('daily and weekly bonuses share a page and reminders survive refresh', async t => {
    const current = player();
    const bonuses = { daily: { amount: 17, available: true, reminder_enabled: true, next_at: '2026-10-07T00:00:00' },
        weekly: { amount: 29, available: true, reminder_enabled: true, next_at: '2026-10-12T00:00:00' } };
    let claims = 0;
    const { page, errors } = await openApp(t, async () => ({ status: 204 }), { profile: current,
        handleApi: async (request, url) => {
            if (url.pathname === '/app/api/bonuses') return { json: bonuses };
            if (url.pathname === '/app/api/bonuses/claim') {
                const { kind } = request.postDataJSON(); claims++;
                bonuses[kind].available = false; current.balance += bonuses[kind].amount;
                return { json: { claimed: true, amount: bonuses[kind].amount } };
            }
            if (url.pathname === '/app/api/bonuses/reminders') {
                for (const [kind, enabled] of Object.entries(request.postDataJSON())) bonuses[kind].reminder_enabled = enabled;
                return { json: bonuses };
            }
        } });
    await page.getByRole('navigation').getByRole('button', { name: 'Бонусы' }).click();
    await page.getByRole('button', { name: 'Забрать бонус' }).first().click();
    await page.getByText('Получено 17 TON', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Уже получен' }).waitFor();
    await page.getByRole('checkbox').first().uncheck();
    await page.waitForFunction(() => document.querySelector('.bonus-card input')?.checked === false);
    assert.equal(claims, 1);
    assert.equal(bonuses.daily.reminder_enabled, false);
    await preview(page, 'bonuses-dark');
    assert.deepEqual(errors, []);
});

test('history navigation keeps its snapshot and supports empty filters', async t => {
    const queries = [];
    const { page, errors } = await openApp(t, async () => ({ status: 204 }), {
        handleApi: async (request, url) => {
            if (url.pathname !== '/app/api/history') return;
            queries.push(url.searchParams);
            const category = url.searchParams.get('category'), number = Number(url.searchParams.get('page'));
            return { json: { page: number, pages: category === 'shop' ? 1 : 2, anchor: 42, total: category === 'shop' ? 0 : 11,
                transactions: category === 'shop' ? [] : [{ id: 42 - number, amount: number ? 100 : -100,
                    type: 'game_bet', description: number ? 'Возврат неоткрытой игры' : 'Ставка', created_at: '2026-10-06 12:00' }] } };
        } });
    await page.getByRole('navigation').getByRole('button', { name: 'История' }).click();
    await page.getByRole('button', { name: 'Далее →' }).click();
    await page.getByText('Возврат ставки', { exact: true }).waitFor();
    assert.equal(queries.at(-1).get('anchor'), '42');
    await page.getByRole('group', { name: 'Фильтр истории' }).getByRole('button', { name: 'Магазин' }).click();
    await page.getByText('Здесь пока пусто', { exact: true }).waitFor();
    assert.equal(queries.at(-1).get('page'), '0');
    assert.deepEqual(errors, []);
    await preview(page, 'history-empty');
});

test('profile saves theme, favorites, bet and animated avatar across navigation', async t => {
    const current = player();
    let uploaded = false;
    const { page, errors } = await openApp(t, async () => uploaded ? { body: gif, contentType: 'image/gif' } : { status: 204 }, {
        profile: current, handleApi: async (request, url) => {
            if (url.pathname === '/app/api/preferences') {
                Object.assign(current.preferences, request.postDataJSON());
                return { json: current.preferences };
            }
            if (url.pathname === '/app/api/favorites') {
                const { game_id, enabled } = request.postDataJSON();
                current.preferences.favorites = enabled ? [game_id] : [];
                return { json: current.preferences };
            }
            if (url.pathname === '/app/api/profile/avatar' && request.method() === 'PUT') {
                assert.deepEqual(request.postDataBuffer(), gif);
                uploaded = current.preferences.custom_avatar = true;
                return { json: { ok: true } };
            }
        } });
    await preview(page, 'home-dark');
    await page.getByRole('navigation').getByRole('button', { name: 'Профиль' }).click();
    await page.locator('.profile-settings textarea').fill('Мой профиль');
    await page.getByLabel('Сохранённая ставка, TON').fill('245');
    await page.getByRole('button', { name: 'Сохранить профиль' }).click();
    await page.getByText('Настройки сохранены', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Светлая' }).click();
    await page.waitForFunction(() => document.body.dataset.theme === 'light');
    await page.locator('.favorite-picker').getByRole('button', { name: 'Монетка' }).click();
    await page.waitForFunction(() => document.querySelector('.favorite-picker button:nth-child(2)')?.getAttribute('aria-pressed') === 'true');
    await page.locator('input[type=file]').setInputFiles({ name: 'avatar.gif', mimeType: 'image/gif', buffer: gif });
    await page.waitForFunction(() => document.querySelector('.profile-header img')?.naturalWidth === 16);
    assert.equal(current.preferences.saved_bet, 245);
    assert.equal(current.preferences.bio, 'Мой профиль');
    await preview(page, 'profile-light');
    await page.getByRole('navigation').getByRole('button', { name: 'Главная' }).click();
    assert.equal(await page.locator('.game-catalog button').count(), 1);
    await page.locator('.game-catalog').getByRole('button', { name: 'Монетка' }).click();
    assert.equal(await page.getByLabel('Ставка в Монетке').inputValue(), '245');
    await preview(page, 'coinflip-light');
    assert.deepEqual(errors, []);
});

test('coinflip retries a lost response with exactly the same request after navigation', async t => {
    const rounds = [];
    const { page, errors } = await openApp(t, async () => ({ status: 204 }), { profile: player(),
        handleApi: async (request, url) => {
            if (url.pathname !== '/app/api/coinflip') return;
            rounds.push(request.postDataJSON());
            if (rounds.length === 1) return { status: 503, json: { error: 'temporarily unavailable' } };
            return { json: { round: { ...rounds[0], result: 'орёл', payout: 185, won: true }, balance: 1085 } };
        } });
    await page.locator('.game-catalog').getByRole('button', { name: 'Монетка' }).click();
    await page.getByRole('button', { name: 'Орёл', exact: true }).click();
    await page.getByRole('button', { name: 'Узнать результат · повторить запрос' }).waitFor();
    await page.getByRole('navigation').getByRole('button', { name: 'Главная' }).click();
    await page.locator('.game-catalog').getByRole('button', { name: 'Монетка' }).click();
    await page.getByRole('button', { name: 'Узнать результат · повторить запрос' }).click();
    await page.getByText('Выпало: орёл', { exact: true }).waitFor();
    assert.equal(rounds.length, 2);
    assert.deepEqual(rounds[0], rounds[1]);
    assert.equal(await page.evaluate(() => sessionStorage.getItem('coinflip-pending:101')), null);
    assert.deepEqual(errors, []);
});

test('statistics and weekly rankings use real requested periods', async t => {
    const paths = [];
    const { page, errors } = await openApp(t, async () => ({ status: 204 }), { profile: player(),
        handleApi: async (request, url) => {
            paths.push(url.pathname + url.search);
            if (url.pathname === '/app/api/statistics') return { json: { days: Number(url.searchParams.get('days')),
                summary: { games: 2, wins: 1, winrate: 50, net: 85 }, games: [],
                points: [{ day: '2026-10-01', balance: 1000 }, { day: '2026-10-06', balance: 1085 }] } };
            if (url.pathname === '/app/api/leaderboard') return { json: { my_rank: 24, players: [
                { user_id: 202, first_name: 'Иван', score: 3, rank: 1, is_me: false }] } };
        } });
    await page.getByRole('button', { name: 'Статистика', exact: true }).click();
    await page.getByRole('button', { name: '7 дней', exact: true }).click();
    await page.getByRole('img', { name: 'График баланса за 7 дней' }).waitFor();
    assert.ok(paths.includes('/app/api/statistics?days=7'));
    await preview(page, 'statistics-dark');
    await page.getByRole('navigation').getByRole('button', { name: 'Главная' }).click();
    await page.getByRole('button', { name: 'Рейтинг', exact: true }).click();
    await page.getByRole('button', { name: 'Неделя', exact: true }).click();
    await page.getByText('#24', { exact: true }).waitFor();
    assert.ok(paths.includes('/app/api/leaderboard?mode=wins&period=week&limit=20'));
    await preview(page, 'rank-week');
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
