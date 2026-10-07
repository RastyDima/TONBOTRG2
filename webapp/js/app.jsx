const { useState, useEffect, useCallback, createContext, useContext } = React;

const API_BASE = '/app/api';
const IS_ANDROID_SHELL = new URLSearchParams(window.location.search).get('client') === 'android';
const HAS_NATIVE_UPDATES = IS_ANDROID_SHELL && navigator.userAgent.includes('TonCasinoAndroid/');
const nativeVersion = (navigator.userAgent.match(/TonCasinoAndroid\/([0-9.]+)/)?.[1] || '0.0').split('.').map(Number);
const HAS_NATIVE_SECURITY = HAS_NATIVE_UPDATES && (nativeVersion[0] > 0 || nativeVersion[1] >= 4);

const TITLE_COLORS = {
    title_spark: { color: '#ffb86c', bg: 'rgba(255,184,108,0.15)' },
    title_crystal: { color: '#72e4ff', bg: 'rgba(114,228,255,0.15)' },
    title_vip: { color: '#ffd23c', bg: 'rgba(255,210,60,0.15)' },
    title_elixir: { color: '#b78cff', bg: 'rgba(183,140,255,0.15)' },
    title_legend: { color: '#ffb432', bg: 'rgba(255,180,50,0.15)' },
    title_shadow: { color: '#8995ff', bg: 'rgba(137,149,255,0.15)' },
    title_whale: { color: '#50c8ff', bg: 'rgba(80,200,255,0.15)' },
    title_jackpot: { color: '#ff75bb', bg: 'rgba(255,117,187,0.15)' },
    title_god: { color: '#b478ff', bg: 'rgba(180,120,255,0.15)' },
    title_fortune: { color: '#72f0b2', bg: 'rgba(114,240,178,0.15)' },
    title_owner: { color: '#ff5050', bg: 'rgba(255,80,80,0.15)' },
    title_ket: { color: '#64ffc8', bg: 'rgba(100,255,200,0.15)' },
    title_from_ket: { color: '#b663c9', bg: 'rgba(139,0,139,0.15)' },
    title_girl: { color: '#ff66ff', bg: 'rgba(255,0,255,0.15)' },
    title_huesos: {
        color: '#ff7676', bg: 'rgba(255,80,80,0.15)',
        gradient: 'linear-gradient(90deg, #ff0000, #ff7f00, #ffff00, #00ff00, #0000ff, #8b00ff)',
    },
};

const FRAME_EMBLEMS = {
    frame_neon_green: '◆',
    frame_fire_red: '✦',
    frame_ice_blue: '❄',
    frame_gold: '♛',
    frame_diamond: '✧',
};

const AuthContext = createContext(null);

function useAuth() {
    return useContext(AuthContext);
}

function api(path, options = {}) {
    const token = localStorage.getItem('webapp_token');
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return fetch(`${API_BASE}${path}`, { cache: 'no-store', ...options, headers: { ...headers, ...options.headers } })
        .then(async r => {
            const data = await r.json().catch(() => ({ error: 'request failed' }));
            if (!r.ok) {
                if (r.status === 401 && localStorage.getItem('webapp_token') === token) {
                    localStorage.removeItem('webapp_token');
                    window.dispatchEvent(new Event('webapp-auth-expired'));
                }
                const error = new Error(data.error || 'request failed');
                error.status = r.status;
                throw error;
            }
            return data;
        });
}

function formatNumber(n) {
    return Number(n || 0).toLocaleString('ru-RU');
}

function calcLevel(xp) {
    const level = Math.floor(Math.sqrt(xp / 50)) + 1;
    const currentXp = ((level - 1) ** 2) * 50;
    const nextXp = (level ** 2) * 50;
    const progress = Math.min((xp - currentXp) / Math.max(1, nextXp - currentXp), 1);
    let name = 'Новичок', color = '#b4a0d0';
    if (level >= 30) { name = 'Бог'; color = '#ff5050'; }
    else if (level >= 20) { name = 'Легенда'; color = '#ffb432'; }
    else if (level >= 15) { name = 'Мастер'; color = '#b478ff'; }
    else if (level >= 10) { name = 'Боец'; color = '#50c8ff'; }
    else if (level >= 5) { name = 'Игрок'; color = '#3cdc82'; }
    return { level, name, color, progress, xp, currentXp, nextXp };
}

// --- Components ---

function Loading() {
    return (
        <div className="loading">
            <div className="spinner" />
            Загрузка...
        </div>
    );
}

function Toast({ message, type }) {
    if (!message) return null;
    return <div className={`toast ${type}`}>{message}</div>;
}

function Stars({ filled, color = '#9656ff' }) {
    return (
        <div style={{ display: 'flex', gap: '6px', marginTop: '8px' }}>
            {[1, 2, 3].map(i => (
                <div key={i} style={{
                    width: '18px',
                    height: '18px',
                    position: 'relative',
                }}>
                    <svg viewBox="0 0 24 24" width="18" height="18">
                        <path
                            d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"
                            fill={i <= filled ? color : '#2a2050'}
                            stroke={i <= filled ? color : '#3a3060'}
                            strokeWidth="1"
                        />
                        {i <= filled && (
                            <path
                                d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"
                                fill="none"
                                stroke="white"
                                strokeWidth="0.5"
                                opacity="0.3"
                            />
                        )}
                    </svg>
                </div>
            ))}
        </div>
    );
}

function NavBar({ page, onNavigate }) {
    const activePage = page === 'coinflip' ? 'games' : ['shop', 'statistics', 'leaderboard', 'ref'].includes(page) ? 'more' : page;
    const items = [
        { id: 'home', icon: '✦', label: 'Главная' },
        { id: 'games', icon: '🎮', label: 'Игры' },
        { id: 'bonuses', icon: '🎁', label: 'Бонусы' },
        { id: 'history', icon: '↗', label: 'История' },
        { id: 'profile', icon: '👤', label: 'Профиль' },
        { id: 'more', icon: '⋯', label: 'Ещё' },
    ];
    return (
        <nav className="nav-bar" aria-label="Разделы приложения">
            {items.map(it => (
                <button
                    key={it.id}
                    type="button"
                    className={`nav-item ${activePage === it.id ? 'active' : ''}`}
                    onClick={() => onNavigate(it.id)}
                    aria-current={activePage === it.id ? 'page' : undefined}
                >
                    <span className="nav-icon">{it.icon}</span>
                    {it.label}
                </button>
            ))}
        </nav>
    );
}

function FrameAvatar({ frame, photoUrl, initials, small = false, large = false }) {
    const [failedUrl, setFailedUrl] = useState(null);
    const frameId = FRAME_EMBLEMS[frame] ? frame : 'default';
    return (
        <div className={`frame-avatar frame-avatar--${frameId}${small ? ' frame-avatar--small' : ''}${large ? ' frame-avatar--large' : ''}`}>
            <div className="frame-avatar-core">
                {photoUrl && failedUrl !== photoUrl
                    ? <img src={photoUrl} alt="" onError={() => setFailedUrl(photoUrl)} /> : initials}
            </div>
            {FRAME_EMBLEMS[frame] && (
                <span className="frame-avatar-emblem" aria-hidden="true">{FRAME_EMBLEMS[frame]}</span>
            )}
        </div>
    );
}

const GAME_CATALOG = [
    { id: 'mines', name: 'Мины', icon: '💣', desc: 'Открывайте поле и забирайте выигрыш' },
    { id: 'coinflip', name: 'Монетка', icon: '🪙', desc: 'Орёл или решка · выплата ×1,85' },
    { id: 'joker', name: 'Джокер', icon: '🃏', desc: 'Выбор дверей и уровней риска' },
    { id: 'alchemist', name: 'Алхимик', icon: '⚗️', desc: 'Ингредиенты и способы варки' },
    { id: 'blackjack', name: '21', icon: '🂡', desc: 'Карты против дилера' },
    { id: 'ruby_roulette', name: 'Рулетка', icon: '🎰', desc: 'Игра на рубины' },
];
const HISTORY_FILTERS = [['all', 'Все'], ['games', 'Игры'], ['bonuses', 'Бонусы'],
    ['transfers', 'Переводы'], ['shop', 'Магазин'], ['referrals', 'Рефералы']];
const TX_LABELS = { bonus: 'Бонус', daily: 'Ежедневный бонус', weekly: 'Недельный бонус',
    game_bet: 'Ставка', game_win: 'Выигрыш', transfer: 'Перевод', transfer_in: 'Перевод',
    transfer_out: 'Перевод', shop: 'Покупка', referral: 'Реферальный бонус', promo: 'Промокод' };

function botUrl(profile, action = '') {
    return 'https://t.me/' + (profile?.bot_username || 'tonbotgram_bot') + (action ? '?start=' + encodeURIComponent(action) : '');
}

function useResource(path) {
    const [data, setData] = useState(null);
    const [error, setError] = useState('');
    const [revision, setRevision] = useState(0);
    useEffect(() => {
        const controller = new AbortController();
        setData(null); setError('');
        api(path, { signal: controller.signal }).then(value => {
            if (!controller.signal.aborted) setData(value);
        }).catch(error => {
            if (error.name !== 'AbortError') setError('Не удалось загрузить данные. Проверьте соединение.');
        });
        return () => controller.abort();
    }, [path, revision]);
    return { data, error, reload: () => setRevision(value => value + 1) };
}

function ResourceState({ resource }) {
    if (resource.error) return <div className="card request-error" role="status">
        <p>{resource.error}</p><button className="btn btn-secondary" onClick={resource.reload}>Повторить</button>
    </div>;
    if (!resource.data) return <div className="card skeleton-card" role="status" aria-label="Загрузка данных">
        <div className="skeleton-line" /><div className="skeleton-line short" /><div className="skeleton-line" />
    </div>;
    return null;
}

function DashboardPage({ profile, photoUrl, onNavigate }) {
    const resource = useResource('/hub');
    const hub = resource.data;
    const available = hub ? Number(hub.bonuses.daily.available) + Number(hub.bonuses.weekly.available) : null;
    const prefs = profile.preferences || {};
    return <div className="page dashboard-page">
        <div className="page-intro"><span>ВАШ ИГРОВОЙ КЛУБ</span><span>✦ TON CASINO</span></div>
        <div className="profile-header dashboard-hero">
            <FrameAvatar frame={profile.active_frame} photoUrl={photoUrl} initials={(profile.first_name || 'И')[0].toUpperCase()} />
            <div className="profile-info"><span className="eyebrow">С возвращением</span>
                <h2>{profile.first_name || 'Игрок'}</h2><span className="muted">Уровень {calcLevel(profile.xp).level} · {formatNumber(profile.xp)} XP</span>
            </div>
            <button className="icon-button" aria-label="Настройки профиля" onClick={() => onNavigate('profile')}>⚙</button>
        </div>
        <div className="wallet-hero card">
            <span className="eyebrow">ВАШ БАЛАНС</span><strong>{formatNumber(profile.balance)} <small>TON</small></strong>
            <div className="wallet-footer"><span>💎 {formatNumber(profile.rubies)} рубинов</span>
                <button onClick={() => onNavigate('history')}>История ↗</button></div>
        </div>
        {hub?.active_game && <div className="card resume-card"><div><span className="eyebrow">НЕЗАВЕРШЁННАЯ ИГРА</span>
            <strong>{hub.active_game.name}</strong></div>
            {hub.active_game.type === 'mines' ? <button className="btn btn-primary" onClick={() => onNavigate('games')}>Продолжить</button>
                : <a className="btn btn-primary" href={botUrl(profile, 'resume')}>Продолжить в боте</a>}
        </div>}
        <button className="bonus-banner" onClick={() => onNavigate('bonuses')}>
            <span className="bonus-banner-icon">🎁</span><span><strong>{available === null ? 'Ваши бонусы' : available ? 'Доступно бонусов: ' + available : 'Бонусы получены'}</strong>
                <small>Ежедневный и недельный в одном месте</small></span><span>→</span>
        </button>
        <div className="section-heading"><h3>Ваши игры</h3><span>⭐ {prefs.favorites?.length || 0} в избранном</span></div>
        <div className="game-catalog">{GAME_CATALOG.filter(game => !prefs.favorites?.length || prefs.favorites.includes(game.id)).map(game =>
            game.id === 'mines' || game.id === 'coinflip'
                ? <button key={game.id} onClick={() => onNavigate(game.id === 'coinflip' ? 'coinflip' : 'games')}><span>{game.icon}</span><strong>{game.name}</strong><small>{game.desc}</small></button>
                : <a key={game.id} href={botUrl(profile, 'play_' + game.id)}><span>{game.icon}</span><strong>{game.name}</strong><small>Открыть в Telegram</small></a>)}</div>
        <ResourceState resource={resource} />
    </div>;
}

function BonusesPage({ refreshProfile }) {
    const resource = useResource('/bonuses');
    const [busy, setBusy] = useState('');
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');
    const claim = async kind => {
        if (busy) return;
        setBusy(kind); setNotice(''); setError('');
        try {
            const result = await api('/bonuses/claim', { method: 'POST', body: JSON.stringify({ kind }) });
            setNotice(result.claimed ? 'Получено ' + formatNumber(result.amount) + ' TON' : 'Этот бонус уже получен');
            await refreshProfile(); resource.reload();
        } catch { setError('Не удалось получить бонус. Попробуйте снова.'); }
        finally { setBusy(''); }
    };
    const reminder = async (kind, enabled) => {
        if (busy) return;
        setBusy('reminder'); setError('');
        try { await api('/bonuses/reminders', { method: 'PATCH', body: JSON.stringify({ [kind]: enabled }) }); resource.reload(); }
        catch { setError('Не удалось сохранить напоминание.'); }
        finally { setBusy(''); }
    };
    return <div className="page"><div className="section-title">Ваши бонусы <span>Каждый день и каждую неделю</span></div>
        <ResourceState resource={resource} />
        {notice && <p className="inline-success" role="status">{notice}</p>}
        {error && <p className="inline-error" role="alert">{error}</p>}
        {resource.data && ['daily', 'weekly'].map(kind => {
            const bonus = resource.data[kind];
            return <div className="card bonus-card" key={kind}><div className="bonus-heading">
                <span className="bonus-icon">{kind === 'daily' ? '☀️' : '🗓️'}</span>
                <div><h3>{kind === 'daily' ? 'Ежедневный бонус' : 'Недельный бонус'}</h3>
                    <span className={'status-pill ' + (bonus.available ? 'ready' : '')}>{bonus.available ? 'Доступен' : 'Получен'}</span></div></div>
                <strong className="bonus-amount">{formatNumber(bonus.amount)} <small>TON</small></strong>
                <button className="btn btn-primary" disabled={Boolean(busy) || !bonus.available} onClick={() => claim(kind)}>
                    {busy === kind ? 'Получаем…' : bonus.available ? 'Забрать бонус' : 'Уже получен'}</button>
                {!bonus.available && <p className="muted">Следующий: {new Date(bonus.next_at).toLocaleString('ru-RU')}</p>}
                <label className="switch-row"><span>Напоминать в Telegram</span><input type="checkbox" checked={bonus.reminder_enabled}
                    disabled={Boolean(busy)} onChange={event => reminder(kind, event.target.checked)} /></label>
            </div>;
        })}
        <p className="page-note">Бонусы и напоминания синхронизируются с ботом. Обновление — в полночь и в понедельник по времени сервера.</p>
    </div>;
}

function HistoryPage({ profile }) {
    const [category, setCategory] = useState('all');
    const [page, setPage] = useState(0);
    const [anchor, setAnchor] = useState(null);
    const [exporting, setExporting] = useState(false);
    const [exportError, setExportError] = useState('');
    const resource = useResource('/history?category=' + category + '&page=' + page + (anchor === null ? '' : '&anchor=' + anchor));
    const view = resource.data;
    const changeFilter = value => { setCategory(value); setPage(0); };
    const changePage = value => { setAnchor(view.anchor); setPage(value); };
    const download = async () => {
        if (IS_ANDROID_SHELL) { window.location.href = botUrl(profile, 'history_export'); return; }
        setExporting(true); setExportError('');
        try {
            const response = await fetch(API_BASE + '/history/export', { headers: { Authorization: 'Bearer ' + localStorage.getItem('webapp_token') }, cache: 'no-store' });
            if (!response.ok) throw new Error('Export failed');
            const url = URL.createObjectURL(await response.blob());
            const link = document.createElement('a'); link.href = url; link.download = 'ton-history.csv'; link.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch { setExportError('Не удалось выгрузить историю.'); }
        finally { setExporting(false); }
    };
    return <div className="page"><div className="section-title">История <span>Все изменения баланса</span></div>
        <div className="filter-scroll" role="group" aria-label="Фильтр истории">{HISTORY_FILTERS.map(([id, label]) =>
            <button key={id} className={category === id ? 'selected' : ''} onClick={() => changeFilter(id)}>{label}</button>)}</div>
        <div className="history-toolbar"><button onClick={() => { setPage(0); setAnchor(null); resource.reload(); }}>↻ Обновить</button>
            <button disabled={exporting} onClick={download}>{exporting ? 'Готовим…' : IS_ANDROID_SHELL ? 'CSV в Telegram' : 'Экспорт CSV'}</button></div>
        <ResourceState resource={resource} />
        {view && <div className="card transaction-list">{!view.transactions.length
            ? <div className="empty-state"><span>↗</span><h3>Здесь пока пусто</h3><p>Операции появятся после бонуса, игры или покупки.</p></div>
            : view.transactions.map(tx => <div className="transaction-row" key={tx.id}>
                <span className={'transaction-icon ' + (tx.amount >= 0 ? 'positive' : '')}>{tx.amount >= 0 ? '↙' : '↗'}</span>
                <div><strong>{tx.type === 'game_bet' && tx.amount > 0 ? 'Возврат ставки' : TX_LABELS[tx.type] || tx.type}</strong>
                    <p>{tx.description}</p><small>{tx.created_at}</small></div>
                <strong className={tx.amount >= 0 ? 'positive' : 'negative'}>{tx.amount > 0 ? '+' : ''}{formatNumber(tx.amount)}<small> TON</small></strong>
            </div>)}</div>}
        {view && <div className="pagination"><button disabled={view.page === 0} onClick={() => changePage(view.page - 1)}>← Назад</button>
            <span>{view.page + 1} / {view.pages} · {view.total} операций</span>
            <button disabled={view.page + 1 >= view.pages} onClick={() => changePage(view.page + 1)}>Далее →</button></div>}
        {exportError && <p className="inline-error" role="alert">{exportError}</p>}
        <p className="page-note">CSV содержит до 1000 последних операций.</p>
    </div>;
}

function StatisticsPage() {
    const [days, setDays] = useState(30);
    const resource = useResource('/statistics?days=' + days);
    const data = resource.data;
    const points = data?.points || [];
    const values = points.map(point => point.balance);
    const low = Math.min(...values), high = Math.max(...values);
    const coords = points.map((point, index) => (12 + index / Math.max(1, points.length - 1) * 316) + ',' + (145 - (point.balance - low) / Math.max(1, high - low) * 120)).join(' ');
    return <div className="page"><div className="section-title">Статистика <span>Ваши результаты и баланс</span></div>
        <div className="filter-scroll" aria-label="Период статистики">{[7, 30, 90].map(value =>
            <button key={value} className={days === value ? 'selected' : ''} onClick={() => setDays(value)}>{value} дней</button>)}</div>
        <ResourceState resource={resource} />
        {data && <><div className="card balance-chart"><div className="section-heading"><h3>Баланс</h3><button onClick={resource.reload}>↻ Обновить</button></div>
            <strong>{formatNumber(points[points.length - 1]?.balance)} <small>TON</small></strong>
            <svg viewBox="0 0 340 168" role="img" aria-label={'График баланса за ' + days + ' дней'}>
                <line x1="12" y1="145" x2="328" y2="145" stroke="var(--border)" />
                <polyline points={coords} fill="none" stroke="var(--green)" strokeWidth="3" strokeLinejoin="round" />
                {points.map((point, index) => <circle key={point.day} cx={12 + index / Math.max(1, points.length - 1) * 316}
                    cy={145 - (point.balance - low) / Math.max(1, high - low) * 120} r="3" fill="var(--green)">
                    <title>{point.day + ': ' + formatNumber(point.balance) + ' TON'}</title></circle>)}
            </svg><div className="chart-labels"><span>{points[0]?.day}</span><span>{points[points.length - 1]?.day}</span></div></div>
            <div className="metric-grid">{[['Игр', data.summary.games], ['Побед', data.summary.wins],
                ['Доля побед', data.summary.winrate + '%'], ['Результат игр', (data.summary.net > 0 ? '+' : '') + formatNumber(data.summary.net) + ' TON']].map(([label, value]) =>
                    <div className="card" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
            <div className="card"><h3>По играм</h3>{data.games.length ? data.games.map(game => <div className="game-stats-row" key={game.game_type}>
                <div><strong>{GAME_CATALOG.find(item => item.id === game.game_type)?.name || game.game_type}</strong><small>{game.games} игр · {game.wins} побед</small></div>
                <strong className={game.payouts - game.bets >= 0 ? 'positive' : 'negative'}>{formatNumber(game.payouts - game.bets)} TON</strong>
            </div>) : <p className="muted">За выбранный период ещё нет завершённых игр.</p>}</div>
            <p className="page-note">Результат игр — выплаты минус ставки. График учитывает бонусы, покупки и переводы.</p></>}
    </div>;
}

function ProfileSettingsCard({ profile, refreshProfile }) {
    const prefs = profile.preferences || {};
    const [bio, setBio] = useState(prefs.bio || '');
    const [bet, setBet] = useState(String(prefs.saved_bet || 100));
    const [busy, setBusy] = useState(false);
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');
    const [nativeSettings, setNativeSettings] = useState(window.__tonNativeSettings || {});
    useEffect(() => { setBio(prefs.bio || ''); setBet(String(prefs.saved_bet || 100)); }, [prefs.bio, prefs.saved_bet]);
    useEffect(() => {
        const handler = event => setNativeSettings(event.detail || {});
        window.addEventListener('ton-native-settings', handler);
        return () => window.removeEventListener('ton-native-settings', handler);
    }, []);
    const change = async values => {
        if (busy) return;
        setBusy(true); setError(''); setNotice('');
        try { await api('/preferences', { method: 'PATCH', body: JSON.stringify(values) }); await refreshProfile(); setNotice('Настройки сохранены'); }
        catch { setError('Не удалось сохранить. Проверьте описание и размер ставки.'); }
        finally { setBusy(false); }
    };
    const upload = async file => {
        if (!file) return;
        if (file.size > 2 * 1024 * 1024) { setError('Выберите изображение до 2 МиБ.'); return; }
        setBusy(true); setError(''); setNotice('');
        try {
            await api('/profile/avatar', { method: 'PUT', body: file, headers: { 'Content-Type': file.type || 'application/octet-stream' } });
            await refreshProfile(); setNotice('Аватар сохранён');
        } catch { setError('Не удалось загрузить. Поддерживаются JPEG, PNG, GIF и WebP до 2 МиБ.'); }
        finally { setBusy(false); }
    };
    const reset = async () => {
        setBusy(true); setError('');
        try { await api('/profile/avatar', { method: 'DELETE' }); await refreshProfile(); setNotice('Используется фото Telegram'); }
        catch { setError('Не удалось сбросить аватар.'); }
        finally { setBusy(false); }
    };
    const favorite = async (game_id, enabled) => {
        setBusy(true); setError('');
        try { await api('/favorites', { method: 'PUT', body: JSON.stringify({ game_id, enabled }) }); await refreshProfile(); }
        catch { setError('Не удалось сохранить избранное.'); }
        finally { setBusy(false); }
    };
    return <div className="card profile-settings"><div className="card-title">Настройки профиля <span>ВАШ СТИЛЬ</span></div>
        <div className="settings-field"><strong>Фото или GIF</strong><p>Аватар будет общим для бота и приложения. До 2 МиБ.</p>
            {HAS_NATIVE_UPDATES && !HAS_NATIVE_SECURITY ? <button className="btn btn-secondary" onClick={() => { window.location.href = 'toncasino://check-update'; }}>Обновить приложение для выбора файла</button>
                : <label className={'btn btn-secondary upload-button' + (busy ? ' disabled' : '')}>Загрузить фото / GIF
                    <input type="file" accept="image/jpeg,image/png,image/gif,image/webp" disabled={busy}
                        onChange={event => { upload(event.target.files?.[0]); event.target.value = ''; }} /></label>}
            {prefs.custom_avatar && <button className="text-button" disabled={busy} onClick={reset}>Вернуть фото Telegram</button>}
        </div>
        <label className="settings-field"><strong>Описание</strong><textarea maxLength="200" value={bio} onChange={event => setBio(event.target.value)}
            placeholder="Расскажите немного о себе" /><small>{bio.length}/200</small></label>
        <label className="settings-field"><strong>Сохранённая ставка, TON</strong>
            <input type="number" min="1" max={profile.max_bet || 250000} value={bet} onChange={event => setBet(event.target.value)} /></label>
        <button className="btn btn-primary" disabled={busy} onClick={() => change({ bio, saved_bet: Number(bet) })}>Сохранить профиль</button>
        <div className="settings-field"><strong>Тема оформления</strong><div className="theme-picker">
            {['dark', 'light'].map(theme => <button key={theme} className={(prefs.theme || 'dark') === theme ? 'selected' : ''} disabled={busy}
                onClick={() => change({ theme })}>{theme === 'dark' ? '☾ Тёмная' : '☀ Светлая'}</button>)}</div></div>
        <label className="switch-row"><span>Скрыть себя в рейтингах</span><input type="checkbox" checked={Boolean(prefs.hide_stats)} disabled={busy}
            onChange={event => change({ hide_stats: event.target.checked })} /></label>
        <div className="settings-field"><strong>Избранные игры</strong><div className="favorite-picker">{GAME_CATALOG.map(game =>
            <button key={game.id} aria-pressed={prefs.favorites?.includes(game.id) || false} disabled={busy}
                onClick={() => favorite(game.id, !prefs.favorites?.includes(game.id))}>
                {prefs.favorites?.includes(game.id) ? '★' : '☆'} {game.icon} {game.name}</button>)}</div></div>
        {HAS_NATIVE_SECURITY && <div className="settings-field"><strong>Защита входа на этом телефоне</strong>
            <p>Подтверждение системным PIN-кодом, отпечатком или лицом после возвращения в приложение.</p>
            <button className="btn btn-secondary" onClick={() => { window.location.href = 'toncasino://device-lock'; }}>
                {nativeSettings.device_lock ? 'Отключить защиту входа' : 'Включить защиту входа'}</button></div>}
        {notice && <p className="inline-success" role="status">{notice}</p>}{error && <p className="inline-error" role="alert">{error}</p>}
    </div>;
}

function CoinflipPage({ profile, refreshProfile }) {
    const key = 'coinflip-pending:' + profile.user_id;
    const [pending, setPending] = useState(() => {
        try { return JSON.parse(sessionStorage.getItem(key)) || null; } catch { return null; }
    });
    const [bet, setBet] = useState(String(profile.preferences?.saved_bet || 100));
    const [result, setResult] = useState(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const play = async choice => {
        if (busy) return;
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        const request = pending || { request_id: Array.from(bytes).map(value => value.toString(16).padStart(2, '0')).join(''), bet: Number(bet), choice };
        setPending(request); sessionStorage.setItem(key, JSON.stringify(request)); setBusy(true); setError('');
        try {
            const data = await api('/coinflip', { method: 'POST', body: JSON.stringify(request) });
            setResult(data.round); setPending(null); sessionStorage.removeItem(key); await refreshProfile();
        } catch (error) {
            if (error.status && error.status < 500) { setPending(null); sessionStorage.removeItem(key); }
            setError(error.status === 402 ? 'Недостаточно TON для этой ставки.' : error.status === 409 ? 'Сначала завершите текущую игру.' :
                error.status === 400 ? 'Введите целую ставку в допустимом диапазоне.' : 'Ответ не получен. Повторите запрос, чтобы узнать результат этой игры.');
        } finally { setBusy(false); }
    };
    return <div className="page coinflip-page"><div className="section-title">Монетка <span>Орёл или решка · ×1,85</span></div>
        <div className="card coinflip-card"><div className={'coin-visual' + (busy ? ' tossing' : '')}>{result ? result.result === 'орёл' ? '✦' : '◆' : '✦'}</div>
            <p className="muted">Ставка списывается при выборе стороны.</p>
            <label className="settings-field"><strong>Ставка, TON</strong><input aria-label="Ставка в Монетке" type="number" min="1"
                max={profile.max_bet || 250000} value={pending ? pending.bet : bet} disabled={busy || Boolean(pending)} onChange={event => setBet(event.target.value)} /></label>
            <div className="coin-choices">{['орёл', 'решка'].map(choice => <button className="btn btn-primary" key={choice}
                disabled={busy || Boolean(pending)} onClick={() => play(choice)}>{choice === 'орёл' ? 'Орёл' : 'Решка'}</button>)}</div>
            {pending && !busy && <button className="btn btn-secondary" onClick={() => play(pending.choice)}>Узнать результат · повторить запрос</button>}
            {busy && <p role="status">Получаем результат…</p>}
            {result && !busy && <div className={'coin-result ' + (result.won ? 'positive' : 'negative')} role="status">
                <h3>Выпало: {result.result}</h3><p>{result.won ? 'Выплата ' + formatNumber(result.payout) + ' TON' : 'Ставка ' + formatNumber(result.bet) + ' TON проиграна'}</p>
            </div>}{error && <p className="inline-error" role="alert">{error}</p>}
        </div>
        <p className="page-note">Повтор запроса возвращает результат той же игры и не списывает ставку снова.</p>
    </div>;
}

function MorePage({ profile, onNavigate }) {
    return <div className="page"><div className="section-title">Ваш клуб <span>Всё в одном месте</span></div>
        <div className="more-grid">{[['shop', '🛒', 'Магазин', 'Рамки и титулы'], ['leaderboard', '🏆', 'Рейтинг', 'Неделя, месяц и всё время'],
            ['statistics', '📈', 'Статистика', 'График и результаты'], ['ref', '👥', 'Рефералы', 'Приглашения и награды']].map(item =>
                <button className="card" key={item[0]} onClick={() => onNavigate(item[0])}><span>{item[1]}</span><strong>{item[2]}</strong><small>{item[3]}</small></button>)}</div>
        <div className="card faq-card"><h3>Помощь</h3>
            <details><summary>Как получить бонусы?</summary><p>Откройте раздел «Бонусы». Получение в боте и приложении общее: каждый бонус начисляется один раз за период.</p></details>
            <details><summary>Как поставить GIF на аватар?</summary><p>Откройте профиль и загрузите GIF до 2 МиБ. В боте используйте /avatar и отправьте GIF как файл без сжатия.</p></details>
            <details><summary>Как отключить потерянный телефон?</summary><p>В профиле откройте «Подключённые устройства» или отправьте /devices боту. Завершите вход на нужном устройстве.</p></details>
            <a className="btn btn-secondary" href={botUrl(profile, 'help')}>Открыть помощь в Telegram</a>
        </div></div>;
}

function DevicesCard() {
    const [sessions, setSessions] = useState([]);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    const loadSessions = useCallback(async () => {
        try {
            const data = await api('/mobile/sessions');
            setSessions(data.sessions || []);
            setError('');
        } catch {
            setError('Не удалось загрузить устройства.');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { loadSessions(); }, [loadSessions]);

    const revoke = async session => {
        if (busy) return;
        setBusy(true);
        try {
            await api(`/mobile/sessions/${encodeURIComponent(session.id)}`, { method: 'DELETE' });
            if (session.is_current) {
                localStorage.removeItem('webapp_token');
                window.dispatchEvent(new Event('webapp-auth-expired'));
            } else {
                await loadSessions();
            }
        } catch {
            setError('Не удалось отключить устройство. Попробуйте ещё раз.');
        } finally {
            setBusy(false);
        }
    };

    const revokeOthers = async () => {
        if (busy) return;
        setBusy(true);
        try {
            await api('/mobile/sessions/revoke-others', { method: 'POST' });
            await loadSessions();
        } catch {
            setError('Не удалось отключить устройства.');
        } finally {
            setBusy(false);
        }
    };

    const signOut = async () => {
        if (busy) return;
        setBusy(true);
        try {
            await api('/mobile/sessions/logout', { method: 'POST' });
            localStorage.removeItem('webapp_token');
            window.dispatchEvent(new Event('webapp-auth-expired'));
        } catch {
            setError('Нет связи с сервером. Не удалось безопасно выйти.');
        } finally {
            setBusy(false);
        }
    };

    const current = sessions.some(session => session.is_current);
    const otherCount = sessions.filter(session => !session.is_current).length;
    const formatSeen = seconds => new Date(seconds * 1000).toLocaleString('ru-RU', {
        day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });

    return <div className="card devices-card">
        <div className="card-title">Подключённые устройства <span>ANDROID</span></div>
        <p className="devices-caption">Здесь можно завершить вход на потерянном или чужом телефоне.</p>
        {loading ? <p className="devices-muted">Загружаем устройства…</p> : sessions.length === 0
            ? <p className="devices-muted">Подключённых Android-устройств нет.</p>
            : <div className="devices-list">{sessions.map(session =>
                <div className="device-row" key={session.id}>
                    <span className="device-icon" aria-hidden="true">▣</span>
                    <div className="device-info">
                        <strong>{session.device_label}</strong>
                        <small>Активность: {formatSeen(session.last_seen_at)}</small>
                        {session.is_current && <small className="device-current">Это устройство</small>}
                    </div>
                    <button className="device-revoke" disabled={busy} onClick={() => revoke(session)}
                        aria-label={`Отключить ${session.device_label}`}>Отключить</button>
                </div>
            )}</div>}
        {otherCount > 0 && <button className="devices-revoke-all" disabled={busy} onClick={revokeOthers}>
            {current ? 'Отключить все остальные' : 'Отключить все Android-устройства'}
        </button>}
        {error && <p className="devices-error">{error}</p>}
        {IS_ANDROID_SHELL && <>
            {HAS_NATIVE_UPDATES && <button className="devices-update" onClick={() => { window.location.href = 'toncasino://check-update'; }}>
                Проверить обновления приложения
            </button>}
            <button className="android-signout" disabled={busy} onClick={signOut}>Сменить Telegram-аккаунт</button>
        </>}
    </div>;
}

function ProfilePage({ profile, refreshProfile, photoUrl }) {
    const [editingShowcase, setEditingShowcase] = useState(false);
    const [showcaseBusy, setShowcaseBusy] = useState(false);
    const [showcaseError, setShowcaseError] = useState('');
    if (!profile) return <Loading />;
    const showcase = profile.showcase || [];
    const earnedAwards = profile.earned_achievements || [];
    const toggleAward = async (awardId) => {
        if (showcaseBusy) return;
        setShowcaseBusy(true);
        setShowcaseError('');
        try {
            await api('/profile/showcase', {
                method: 'POST',
                body: JSON.stringify({ achievement_id: awardId }),
            });
            await refreshProfile();
        } catch (e) {
            setShowcaseError(e.message === 'showcase full'
                ? 'Можно выбрать только три награды.' : 'Не удалось обновить витрину.');
        } finally {
            setShowcaseBusy(false);
        }
    };
    const level = calcLevel(profile.xp || 0);
    const winrate = profile.total_games > 0
        ? ((profile.wins / profile.total_games) * 100).toFixed(1)
        : '0.0';
    const titleInfo = profile.active_title ? TITLE_COLORS[profile.active_title] : null;
    const titleNames = {
        title_spark: 'СОБИРАТЕЛЬ ИСКР', title_crystal: 'ИСКАТЕЛЬ КРИСТАЛЛОВ',
        title_vip: 'ЛОВЕЦ УДАЧИ', title_legend: 'РИСКОВЫЙ ПАРЕНЬ',
        title_elixir: 'ЛУННЫЙ АЛХИМИК', title_shadow: 'ХРАНИТЕЛЬ ТАЙНЫ',
        title_whale: 'МАГНАТ', title_god: 'СУДЬБА',
        title_jackpot: 'ХРАНИТЕЛЬ ДЖЕКПОТА', title_fortune: 'АРХИТЕКТОР ФОРТУНЫ',
        title_owner: 'OWNER', title_ket: 'KET',
        title_from_ket: 'ОТ КЕТА', title_girl: 'ДЕВЧЕНКА', title_huesos: 'ХУЕСОС',
    };
    const initials = (profile.first_name || 'K')[0].toUpperCase();

    return (
        <div className="page profile-page">
            <div className="page-intro"><span>ВАШ ПРОФИЛЬ</span><span className="page-intro-mark">✦ TON CASINO</span></div>
            <div className="profile-header">
                <FrameAvatar frame={profile.active_frame} photoUrl={photoUrl} initials={initials} />
                <div className="profile-info">
                    <div className="profile-name">{profile.first_name || 'Игрок'}</div>
                    <div className="profile-id">ID: {profile.user_id}</div>
                    {profile.active_title && titleInfo && (
                        <div
                            className="profile-title-banner"
                            style={{
                                color: titleInfo.color,
                                background: titleInfo.bg,
                                border: `1px solid ${titleInfo.color}40`,
                            }}
                        >
                            <span style={titleInfo.gradient ? {
                                backgroundImage: titleInfo.gradient,
                                backgroundClip: 'text', WebkitBackgroundClip: 'text',
                                WebkitTextFillColor: 'transparent',
                            } : undefined}>
                                {titleNames[profile.active_title] || profile.active_title}
                            </span>
                        </div>
                    )}
                    <div className="profile-progress">
                        <div className="profile-level-row">
                            <span className="profile-level" style={{ color: level.color }}>
                                Ур. {level.level}
                            </span>
                            <span className="profile-level-name" style={{ color: level.color }}>
                                {level.name}
                            </span>
                        </div>
                        <div className="profile-progress-track">
                            <div style={{
                                width: `${Math.round(level.progress * 100)}%`,
                                height: '100%',
                                background: `linear-gradient(90deg, ${level.color}, ${level.color}88)`,
                                transition: 'width 0.3s',
                            }} />
                        </div>
                        <div className="profile-progress-caption">
                            {level.xp} / {level.nextXp} XP
                        </div>
                    </div>
                </div>
            </div>

            <div className="card wallet-card">
                <div className="balance-row">
                    <div className="balance-item">
                        <div className="balance-label">Баланс</div>
                        <div className="balance-symbol ton-symbol" aria-hidden="true">◆</div>
                        <div className="balance-value ton">{formatNumber(profile.balance)}</div>
                        <div className="balance-unit">TON</div>
                    </div>
                    <div className="balance-item">
                        <div className="balance-label">Рубины</div>
                        <div className="balance-symbol ruby-symbol" aria-hidden="true">♦</div>
                        <div className="balance-value ruby">{formatNumber(Math.floor(profile.rubies))}</div>
                        <div className="balance-unit">GEMS</div>
                    </div>
                </div>
            </div>

            <div className="card stats-card">
                <div className="card-title">Статистика <span>ВСЁ ВРЕМЯ</span></div>
                <div className="stats-primary">
                    <div className="stat-row">
                        <span className="stat-label">Игр</span>
                        <span className="stat-value">{formatNumber(profile.total_games)}</span>
                    </div>
                    <div className="stat-row">
                        <span className="stat-label">Побед</span>
                        <span className="stat-value green">{formatNumber(profile.wins)}</span>
                    </div>
                    <div className="stat-row">
                        <span className="stat-label">Поражений</span>
                        <span className="stat-value red">{formatNumber(profile.losses)}</span>
                    </div>
                </div>
                <div className="winrate-container">
                    <div className="winrate-header">
                        <span className="stat-label">Винрейт</span>
                        <span className="stat-value gold">{winrate}%</span>
                    </div>
                    <div className="winrate-bar">
                        <div className="winrate-fill" style={{ width: `${winrate}%` }} />
                    </div>
                </div>
                <div className="stat-row">
                    <span className="stat-label">Общие ставки</span>
                    <span className="stat-value">{formatNumber(profile.total_bet)}</span>
                </div>
                <div className="stat-row">
                    <span className="stat-label">Общий выигрыш</span>
                    <span className="stat-value green">{formatNumber(profile.total_won)}</span>
                </div>
                <div className="stat-row">
                    <span className="stat-label">Рефералы</span>
                    <span className="stat-value">{profile.referral_count}</span>
                </div>
            </div>
            <div className="card showcase-card">
                <div className="showcase-heading">
                    <div className="card-title">✨ Витрина достижений</div>
                    {earnedAwards.length > 0 && (
                        <button className="showcase-edit" onClick={() => setEditingShowcase(!editingShowcase)}>
                            {editingShowcase ? 'Готово' : 'Изменить'}
                        </button>
                    )}
                </div>
                <div className="showcase-slots">
                    {[0, 1, 2].map(index => {
                        const award = showcase[index];
                        return (
                            <div className={`showcase-slot ${award ? 'filled' : ''}`} key={index}>
                                {award ? <><span className="showcase-icon">{award.icon}</span><span>{award.name}</span></>
                                    : <span className="showcase-empty">Награда</span>}
                            </div>
                        );
                    })}
                </div>
                {earnedAwards.length === 0 && <p className="showcase-hint">Сыграйте первую игру, чтобы открыть награду.</p>}
                {editingShowcase && (
                    <div className="showcase-picker">
                        <p className="showcase-hint">Выберите до трёх полученных достижений.</p>
                        {earnedAwards.map(award => {
                            const selected = showcase.some(item => item.id === award.id);
                            return (
                                <button key={award.id} className={`showcase-option ${selected ? 'selected' : ''}`}
                                    disabled={showcaseBusy || (!selected && showcase.length >= 3)}
                                    onClick={() => toggleAward(award.id)}>
                                    <span>{award.icon} {award.name}</span><span>{selected ? '✓' : '+'}</span>
                                </button>
                            );
                        })}
                        {showcaseError && <p className="showcase-error">{showcaseError}</p>}
                    </div>
                )}
            </div>
            <ProfileSettingsCard profile={profile} refreshProfile={refreshProfile} />
            <DevicesCard />
        </div>
    );
}

function GamesPage({ profile, refreshProfile, onNavigate }) {
    const [mineCount, setMineCount] = useState(3);
    const [bet, setBet] = useState(String(profile?.preferences?.saved_bet || 100));
    const [round, setRound] = useState(null);
    const [balance, setBalance] = useState(profile?.balance ?? 0);
    const [maxBet, setMaxBet] = useState(250000);
    const [otherGame, setOtherGame] = useState(null);
    const [busy, setBusy] = useState(false);
    const [loadingRound, setLoadingRound] = useState(true);
    const [error, setError] = useState('');
    const opened = round?.opened?.length || 0;
    const playing = round?.status === 'playing';
    const currentMultiplier = round?.multiplier ?? 1;

    const loadRound = useCallback(async () => {
        const data = await api('/mines');
        setRound(data.round);
        setBalance(data.balance);
        setOtherGame(data.other_game);
        setMaxBet(data.max_bet);
        if (data.round?.status === 'playing') {
            setMineCount(data.round.mine_count);
            setBet(String(data.round.bet));
        }
    }, []);

    useEffect(() => {
        let mounted = true;
        api('/mines').then(data => {
            if (!mounted) return;
            setRound(data.round);
            setBalance(data.balance);
            setOtherGame(data.other_game);
            setMaxBet(data.max_bet);
            if (data.round?.status === 'playing') {
                setMineCount(data.round.mine_count);
                setBet(String(data.round.bet));
            }
        }).catch(() => {
            if (mounted) setError('Не удалось загрузить игру. Попробуйте открыть раздел ещё раз.');
        }).finally(() => {
            if (mounted) setLoadingRound(false);
        });
        return () => { mounted = false; };
    }, []);

    const explainError = e => ({
        'active game': 'Сначала завершите текущую игру в боте.',
        'insufficient balance': 'Недостаточно TON для такой ставки.',
        'round not found': 'Раунд уже завершён. Обновите игру.',
        'cashout unavailable': 'Сначала откройте безопасные клетки до прибыльного множителя.',
        'cell already opened': 'Эта клетка уже открыта.',
    }[e.message] || 'Не удалось выполнить ход. Попробуйте ещё раз.');

    const applyResult = data => {
        setRound(data.round);
        setBalance(data.balance);
        setOtherGame(null);
        if (data.round?.status === 'playing') {
            setMineCount(data.round.mine_count);
            setBet(String(data.round.bet));
        }
        refreshProfile();
    };

    const startRound = async () => {
        const amount = Number(bet);
        if (!Number.isSafeInteger(amount) || amount < 1 || amount > maxBet) {
            setError(`Укажите ставку от 1 до ${formatNumber(maxBet)} TON.`);
            return;
        }
        if (amount > balance) {
            setError('Недостаточно TON для такой ставки.');
            return;
        }
        setBusy(true);
        setError('');
        try {
            applyResult(await api('/mines/start', {
                method: 'POST', body: JSON.stringify({ bet: amount, mine_count: mineCount }),
            }));
        } catch (e) {
            setError(explainError(e));
            await loadRound().catch(() => {});
        } finally {
            setBusy(false);
        }
    };

    const act = async (action, extra = {}) => {
        if (!round || busy) return;
        setBusy(true);
        setError('');
        try {
            applyResult(await api(`/mines/${action}`, {
                method: 'POST', body: JSON.stringify({ round_id: round.id, ...extra }),
            }));
        } catch (e) {
            setError(explainError(e));
            await loadRound().catch(() => {});
        } finally {
            setBusy(false);
        }
    };

    const cancelRound = () => {
        if (round?.can_refund) {
            act('cancel');
            return;
        }
        const prompt = 'После открытия клетки ставка сгорит. Сдаться?';
        const tg = window.Telegram?.WebApp;
        if (tg?.initData && tg?.showConfirm) tg.showConfirm(prompt, confirmed => confirmed && act('cancel'));
        else if (window.confirm(prompt)) act('cancel');
    };

    let statusText = 'Укажите ставку и количество мин, затем начните раунд.';
    if (playing) statusText = round.can_cashout
        ? `Можно забрать ${formatNumber(round.payout)} TON или рискнуть ещё раз.`
        : 'Открывайте клетки. После первого хода отмена сжигает ставку.';
    if (round?.status === 'lost') statusText = round.exploded === null
        ? 'Вы сдались. Ставка проиграна.'
        : '💥 Мина! Ставка проиграна.';
    if (round?.status === 'won') statusText = `🏆 Выигрыш: ${formatNumber(round.payout)} TON (×${currentMultiplier}).`;
    if (round?.status === 'cancelled') statusText = 'Раунд отменён до первого хода. Ставка возвращена.';
    return (
        <div className="page games-page">
            <GameTabs page="games" onNavigate={onNavigate} />
            <div className="page-intro"><span>ИГРОВАЯ ЗОНА</span><span className="page-intro-mark">01 / 04</span></div>
            <div className="section-title">Игры <span>Выберите свой риск</span></div>
            <div className="mines-demo card">
                <div className="mines-demo-header">
                    <div>
                        <div className="mines-demo-eyebrow">ИГРА НА TON</div>
                        <h2>💣 Мины</h2>
                        <p>Найдите кристаллы и вовремя заберите множитель.</p>
                    </div>
                    <span className="mines-demo-badge">До ×8</span>
                </div>

                <div className="mines-balance">Баланс <strong>{formatNumber(balance)} TON</strong></div>
                <div className="mines-demo-settings">
                    <label className="mines-bet-label" htmlFor="mines-bet">Ставка, TON</label>
                    <input id="mines-bet" className="mines-bet-input" type="number" min="1" max={maxBet}
                        step="1" inputMode="numeric" value={bet} disabled={playing || busy}
                        onChange={event => setBet(event.target.value)} />
                    <div className="mines-bet-hint">От 1 до {formatNumber(maxBet)} TON</div>
                    <div className="mines-demo-setting-label">
                        <span>Количество мин</span><strong>{playing ? round.mine_count : mineCount} / 10</strong>
                    </div>
                    <input type="range" min="1" max="10" value={mineCount}
                        disabled={playing || busy} onChange={event => setMineCount(Number(event.target.value))}
                        aria-label="Количество мин" />
                    <div className="mines-demo-scale"><span>Спокойнее</span><span>Рискованнее</span></div>
                </div>

                <div className="mines-demo-stats">
                    <div><span>Открыто</span><strong>{opened} / {round?.safe_total ?? 25 - mineCount}</strong></div>
                    <div><span>Множитель</span><strong>×{currentMultiplier}</strong></div>
                    <div><span>Следующий ход</span><strong>{playing ? `${round.next_chance}%` : '—'}</strong></div>
                </div>

                <div className="mines-demo-board" role="grid" aria-label="Поле мин 5 на 5">
                    {Array.from({ length: 25 }, (_, index) => {
                        const openedCell = round?.opened?.includes(index);
                        const shownMine = round?.mines?.includes(index);
                        const exploded = round?.exploded === index;
                        return (
                            <button key={index} type="button" role="gridcell"
                                className={`mines-demo-cell${openedCell ? ' is-gem' : ''}${shownMine ? ' is-mine' : ''}${exploded ? ' is-exploded' : ''}`}
                                disabled={!playing || openedCell || busy}
                                aria-label={openedCell ? `Клетка ${index + 1}: кристалл`
                                    : shownMine ? `Клетка ${index + 1}: мина`
                                    : `Клетка ${index + 1}: закрыта`}
                                onClick={() => act('reveal', { index })}>
                                {openedCell ? '💎' : shownMine ? '💣' : '✦'}
                            </button>
                        );
                    })}
                </div>

                <p className="mines-demo-status" aria-live="polite">{statusText}</p>
                {error && <p className="mines-error" role="alert">{error}</p>}
                {otherGame && <p className="mines-error">У вас уже идёт другая игра в боте. Завершите её перед новой ставкой.</p>}
                <div className="mines-demo-actions">
                    {playing ? <>
                        <button type="button" className="btn btn-primary" disabled={!round.can_cashout || busy}
                            onClick={() => act('cashout')}>
                            {round.can_cashout ? `Забрать ${formatNumber(round.payout)} TON` : 'Откройте безопасную клетку'}
                        </button>
                        <button type="button" className="btn btn-secondary" disabled={busy} onClick={cancelRound}>
                            {round.can_refund ? 'Отменить' : 'Сдаться'}
                        </button>
                    </> : <button type="button" className="btn btn-primary"
                        disabled={loadingRound || busy || !!otherGame} onClick={startRound}>
                        {busy ? 'Подождите...' : round ? '↻ Новый раунд' : 'Поставить и играть'}
                    </button>}
                </div>
                {round?.seed_hash && <details className="mines-proof">
                    <summary>Проверка честности раунда</summary>
                    <span>Хеш семени, зафиксированный до первого хода:</span>
                    <code>{round.seed_hash}</code>
                    {round.seed && <><span>Семя после завершения:</span><code>{round.seed}</code></>}
                </details>}
                <p className="mines-demo-note">Ставка и выигрыш учитываются в балансе бота. После безопасного хода отмена сжигает ставку.</p>
            </div>
            <div className="games-grid">
                {[
                    { id: 'joker', icon: '🃏', name: 'Джокер', desc: 'Открыть в Telegram' },
                    { id: 'alchemist', icon: '⚗️', name: 'Алхимик', desc: 'Открыть в Telegram' },
                    { id: 'blackjack', icon: '🂡', name: '21', desc: 'Открыть в Telegram' },
                    { id: 'ruby_roulette', icon: '🎰', name: 'Рулетка', desc: 'Открыть в Telegram' },
                ].map(game => (
                    <a key={game.id} className="game-card" href={botUrl(profile, 'play_' + game.id)}>
                        <div className="game-icon">{game.icon}</div>
                        <div className="game-name">{game.name}</div>
                        <div className="game-desc">{game.desc}</div>
                    </a>
                ))}
            </div>
        </div>
    );
}

function ShopPage({ profile, refreshProfile, photoUrl }) {
    const [shop, setShop] = useState(null);
    const [category, setCategory] = useState('frames');
    const [toast, setToast] = useState(null);
    const [tryOn, setTryOn] = useState(null);
    const initials = (profile?.first_name || 'И')[0].toUpperCase();

    useEffect(() => {
        api('/shop').then(setShop).catch(() => {});
    }, []);

    const showToast = (msg, type = 'success') => {
        setToast({ message: msg, type });
        setTimeout(() => setToast(null), 3000);
    };

    const buy = async (itemId) => {
        try {
            const res = await api('/shop/buy', {
                method: 'POST',
                body: JSON.stringify({ item_id: itemId }),
            });
            showToast('Покупка успешна!');
            setShop(s => ({ ...s, balance: res.balance }));
            refreshProfile();
            // Mark as owned in local state
            setShop(s => {
                if (!s) return s;
                const update = items => items.map(i =>
                    i.id === itemId ? { ...i, owned: true } : i
                );
                return { ...s, frames: update(s.frames), titles: update(s.titles) };
            });
            return true;
        } catch (e) {
            if (e.message === 'insufficient balance') showToast('Недостаточно TON', 'error');
            else if (e.message === 'already owned') showToast('Уже куплено', 'error');
            else showToast('Ошибка', 'error');
            return false;
        }
    };

    const equip = async (itemId, category) => {
        try {
            await api('/shop/equip', {
                method: 'POST',
                body: JSON.stringify({ item_id: itemId }),
            });
            showToast('Экипировано!');
            refreshProfile();
            setShop(s => s && ({ ...s,
                frames: itemId.startsWith('frame') ? s.frames.map(i => ({ ...i, active: i.id === itemId })) : s.frames,
                titles: itemId.startsWith('title') ? s.titles.map(i => ({ ...i, active: i.id === itemId })) : s.titles,
            }));
        } catch (e) {
            showToast('Ошибка', 'error');
        }
    };

    const unequip = async (category) => {
        try {
            await api('/shop/equip', {
                method: 'POST',
                body: JSON.stringify({ item_id: '', category }),
            });
            showToast('Снято');
            refreshProfile();
            setShop(s => s && ({ ...s,
                frames: category === 'frame' ? s.frames.map(i => ({ ...i, active: false })) : s.frames,
                titles: category === 'title' ? s.titles.map(i => ({ ...i, active: false })) : s.titles,
            }));
        } catch (e) {
            showToast('Ошибка', 'error');
        }
    };

    if (!shop) return <Loading />;

    return (
        <div className="page shop-page">
            <Toast {...toast} />
            {tryOn && (
                <div className="tryon-overlay" role="dialog" aria-modal="true" aria-label="Примерка рамки"
                    onClick={() => setTryOn(null)}>
                    <div className="tryon-panel" onClick={event => event.stopPropagation()}>
                        <button className="tryon-close" onClick={() => setTryOn(null)} aria-label="Закрыть">×</button>
                        <div className="tryon-label">ПРИМЕРКА РАМКИ</div>
                        <div className="tryon-profile">
                            <FrameAvatar frame={tryOn.id} photoUrl={photoUrl} initials={initials} large />
                            <div className="profile-info">
                                <div className="profile-name">{profile?.first_name || 'Игрок'}</div>
                                <div className="profile-id">ID: {profile?.user_id || '—'}</div>
                                <div className="tryon-level">Уровень {calcLevel(profile?.xp || 0).level}</div>
                            </div>
                        </div>
                        <div className="tryon-name">{tryOn.name}</div>
                        <p className="tryon-note">Так рамка будет выглядеть на вашем аватаре.</p>
                        {!tryOn.owned && (
                            <button className="btn btn-gold" onClick={async () => {
                                if (await buy(tryOn.id)) setTryOn(null);
                            }}>Купить за {formatNumber(tryOn.price)} TON</button>
                        )}
                    </div>
                </div>
            )}
            <div className="page-intro"><span>КОЛЛЕКЦИЯ</span><span className="page-intro-mark">✦ СТИЛЬ ИГРОКА</span></div>
            <div className="section-title">Магазин <span>Соберите свой образ</span></div>
            <div className="card shop-wallet">
                <div className="balance-row">
                    <div className="balance-item">
                        <div className="balance-label">Баланс</div>
                        <div className="balance-value ton">{formatNumber(shop.balance)}</div>
                        <div className="balance-unit">TON</div>
                    </div>
                </div>
            </div>

            <div className="category-switch" role="tablist" aria-label="Товары магазина">
                <button type="button" role="tab" aria-selected={category === 'frames'} className={category === 'frames' ? 'active' : ''} onClick={() => setCategory('frames')}>Рамки <span>{shop.frames.length}</span></button>
                <button type="button" role="tab" aria-selected={category === 'titles'} className={category === 'titles' ? 'active' : ''} onClick={() => setCategory('titles')}>Титулы <span>{shop.titles.length}</span></button>
            </div>
            {category === 'frames' && <div className="card shop-section" role="tabpanel">
                <div className="card-title">🖼 Рамки профиля</div>
                <div className="shop-category">
                    {shop.frames.map(f => (
                        <div
                            key={f.id}
                            className={`shop-card ${f.active ? 'active' : ''}`}
                            style={{ borderColor: f.active ? `rgb(${f.color.join(',')})` : undefined }}
                        >
                            <FrameAvatar frame={f.id} photoUrl={photoUrl} initials={initials} small />
                            <div className="item-name" style={{ color: `rgb(${f.color.join(',')})` }}>{f.name}</div>
                            <button className="btn-unequip tryon-trigger" onClick={() => setTryOn(f)}>Примерить</button>
                            {f.owned ? (
                                <>
                                    <div className="item-owned">✓ Куплено</div>
                                    {f.active ? (
                                        <button className="btn-unequip" onClick={() => unequip('frame')}>Снять</button>
                                    ) : (
                                        <button className="btn btn-small btn-primary" style={{ marginTop: 8 }} onClick={() => equip(f.id)}>Экипировать</button>
                                    )}
                                </>
                            ) : (
                                <div className="item-price">{formatNumber(f.price)} TON</div>
                            )}
                            {!f.owned && (
                                <button className="btn btn-small btn-gold" style={{ marginTop: 8 }} onClick={() => buy(f.id)}>Купить</button>
                            )}
                        </div>
                    ))}
                </div>
            </div>}

            {category === 'titles' && <div className="card shop-section" role="tabpanel">
                <div className="card-title">🏷 Титулы</div>
                <div className="shop-category">
                    {shop.titles.map(t => {
                        const tc = TITLE_COLORS[t.id] || { color: '#ffd23c', bg: 'rgba(255,210,60,0.15)' };
                        return (
                            <div
                                key={t.id}
                                className={`shop-card ${t.active ? 'active' : ''}`}
                            >
                                <div className="item-name" style={{ color: tc.color }}>{t.name}</div>
                                {t.owned ? (
                                    <>
                                        <div className="item-owned">✓ Куплено</div>
                                        {t.active ? (
                                            <button className="btn-unequip" onClick={() => unequip('title')}>Снять</button>
                                        ) : (
                                            <button className="btn btn-small btn-primary" style={{ marginTop: 8 }} onClick={() => equip(t.id)}>Экипировать</button>
                                        )}
                                    </>
                                ) : (
                                    <div className="item-price">{formatNumber(t.price)} TON</div>
                                )}
                                {!t.owned && (
                                    <button className="btn btn-small btn-gold" style={{ marginTop: 8 }} onClick={() => buy(t.id)}>Купить</button>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>}
        </div>
    );
}

function ReferralPage({ profile }) {
    const botUsername = 'tonbotgram_bot';
    const refLink = `https://t.me/${botUsername}?start=ref${profile?.user_id || ''}`;
    const [copied, setCopied] = useState(false);

    const copyLink = () => {
        navigator.clipboard.writeText(refLink).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        });
    };

    return (
        <div className="page referrals-page">
            <div className="page-intro"><span>КОМАНДА</span><span className="page-intro-mark">✦ 5% БОНУС</span></div>
            <div className="section-title">Рефералы <span>Приглашайте друзей</span></div>
            <div className="card">
                <div className="card-title">Ваша ссылка</div>
                <div className="ref-link">{refLink}</div>
                <button className="btn btn-primary" onClick={copyLink}>
                    {copied ? '✓ Скопировано!' : '📋 Копировать ссылку'}
                </button>
            </div>
            <div className="card">
                <div className="card-title">Статистика</div>
                <div className="ref-stats">
                    <div className="balance-item">
                        <div className="balance-label">Рефералов</div>
                        <div className="balance-value" style={{ color: 'var(--cyan)' }}>
                            {profile?.referral_count || 0}
                        </div>
                    </div>
                    <div className="balance-item">
                        <div className="balance-label">Бонус</div>
                        <div className="balance-value" style={{ color: 'var(--green)' }}>
                            5%
                        </div>
                    </div>
                </div>
                <p style={{ marginTop: 12, fontSize: '13px', color: 'var(--text-dim)' }}>
                    Получайте 5% от ставок каждого приглашённого игрока.
                </p>
            </div>
        </div>
    );
}

function GameTabs({ page, onNavigate }) {
    return <div className="game-tabs" aria-label="Выбор игры">
        <button className={page === 'games' ? 'selected' : ''} onClick={() => onNavigate('games')}>💣 Мины</button>
        <button className={page === 'coinflip' ? 'selected' : ''} onClick={() => onNavigate('coinflip')}>🪙 Монетка</button>
    </div>;
}

function LeaderboardPage({ profile }) {
    const [tab, setTab] = useState('balance');
    const [period, setPeriod] = useState('all');
    const resource = useResource('/leaderboard?mode=' + tab + '&period=' + period + '&limit=20');
    const data = resource.data;
    const changePeriod = value => { setPeriod(value); if (value !== 'all') setTab('wins'); };
    return <div className="page leaderboard-page">
        <div className="section-title">Рейтинг <span>Ваше место в клубе</span></div>
        <div className="filter-scroll" aria-label="Период рейтинга">{[['all', 'Всё время'], ['week', 'Неделя'], ['month', 'Месяц']].map(([id, label]) =>
            <button key={id} className={period === id ? 'selected' : ''} onClick={() => changePeriod(id)}>{label}</button>)}</div>
        <div className="leaderboard-tabs">{(period === 'all' ? [['balance', 'Максимум TON'], ['wins', 'Победы'], ['xp', 'Опыт']] :
            [['wins', 'Победы'], ['games', 'Игры']]).map(([id, label]) =>
                <button className={'btn btn-small ' + (tab === id ? 'btn-primary' : 'btn-secondary')} key={id} onClick={() => setTab(id)}>{label}</button>)}</div>
        <ResourceState resource={resource} />
        {data && <>{data.my_rank && <div className="card my-rank"><span>ВАША ПОЗИЦИЯ</span><strong>#{data.my_rank}</strong></div>}
            {profile.preferences?.hide_stats && <p className="page-note">Вы скрыты в рейтингах. Видимость можно изменить в профиле.</p>}
            <div className="card leaderboard-list">{data.players.length ? data.players.map(player =>
                <div className={'leaderboard-player' + (player.is_me ? ' is-me' : '')} key={player.user_id}>
                    <span className="rank-number">{player.rank <= 3 ? ['🥇', '🥈', '🥉'][player.rank - 1] : player.rank}</span>
                    <div className="leader-name"><strong>{player.first_name || 'Игрок'}</strong>
                        <small>{player.is_me ? 'Это вы' : player.username ? '@' + player.username : 'Участник клуба'}</small></div>
                    <strong>{formatNumber(player.score)} <small>{tab === 'balance' ? 'TON' : tab === 'xp' ? 'XP' : tab === 'games' ? 'игр' : 'побед'}</small></strong>
                </div>) : <div className="empty-state"><span>🏆</span><h3>Рейтинг ещё пуст</h3><p>Завершённые игры появятся здесь.</p></div>}</div>
        </>}
    </div>;
}

function AuthScreen({ onAuth }) {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(false);

    useEffect(() => {
        const tg = window.Telegram?.WebApp;
        const data = tg?.initData;
        if (data) {
            setLoading(true);
            onAuth(data).then(ok => {
                if (!ok) {
                    setLoading(false);
                    setError(true);
                }
            });
        } else {
            setError(true);
        }
    }, []);

    const handleAuth = () => {
        setLoading(true);
        const tg = window.Telegram?.WebApp;
        const data = tg?.initData;
        if (data) {
            onAuth(data).then(ok => {
                if (!ok) {
                    setLoading(false);
                    setError(true);
                }
            });
        } else {
            setLoading(false);
            setError(true);
        }
    };

    return (
        <div className="auth-screen">
            <div className="auth-orbit" aria-hidden="true"><span>✦</span></div>
            <div className="auth-kicker">ИГРА · СТИЛЬ · СООБЩЕСТВО</div>
            <h2>TON Casino</h2>
            <p>Ваш игровой клуб в Telegram</p>
            {loading ? (
                <p style={{ color: 'var(--purple)' }}>Вход...</p>
            ) : error ? (
                <>
                    <p style={{ color: 'var(--red)', marginBottom: 16 }}>
                        Откройте приложение из бота
                    </p>
                    <button className="btn btn-primary" onClick={handleAuth}>
                        Попробовать снова
                    </button>
                </>
            ) : (
                <button className="btn btn-primary" onClick={handleAuth}>
                    Войти через Telegram
                </button>
            )}
        </div>
    );
}

function AndroidPairScreen({ onAuth }) {
    const [pair, setPair] = useState(null);
    const [error, setError] = useState('');
    const [attempt, setAttempt] = useState(0);
    const [remaining, setRemaining] = useState(0);

    useEffect(() => {
        let active = true;
        setPair(null);
        setError('');
        api('/mobile/pair/start', { method: 'POST' }).then(data => {
            if (active) {
                const clockOffset = data.server_time * 1000 - Date.now();
                setRemaining(Math.max(0, Math.ceil((data.expires_at * 1000
                    - Date.now() - clockOffset) / 1000)));
                setPair({ ...data, clock_offset: clockOffset });
            }
        }).catch(() => {
            if (active) setError('Не удалось получить код. Проверьте подключение к интернету.');
        });
        return () => { active = false; };
    }, [attempt]);

    useEffect(() => {
        if (!pair) return;
        const tick = () => {
            const seconds = Math.max(0, Math.ceil((pair.expires_at * 1000
                - Date.now() - pair.clock_offset) / 1000));
            setRemaining(seconds);
            if (seconds === 0) {
                setPair(null);
                setError('Код истёк. Запросите новый.');
            }
        };
        tick();
        const timer = setInterval(tick, 1000);
        document.addEventListener('visibilitychange', tick);
        return () => { clearInterval(timer); document.removeEventListener('visibilitychange', tick); };
    }, [pair?.request_id]);

    useEffect(() => {
        if (!pair?.request_id) return;
        let active = true;
        let checking = false;
        const check = async () => {
            if (checking || !active) return;
            checking = true;
            try {
                const data = await api('/mobile/pair/complete', {
                    method: 'POST', body: JSON.stringify({ request_id: pair.request_id }),
                });
                if (active && data.token) {
                    active = false;
                    if (!await onAuth(data.token)) {
                        setError('Не удалось войти. Запросите новый код.');
                        setPair(null);
                    }
                }
            } catch (e) {
                if (active) {
                    setError(e.message === 'pairing expired'
                        ? 'Код истёк. Запросите новый.' : 'Не удалось подтвердить вход. Попробуйте снова.');
                    setPair(null);
                }
            } finally {
                checking = false;
            }
        };
        check();
        const timer = setInterval(check, 2500);
        return () => { active = false; clearInterval(timer); };
    }, [pair?.request_id]);

    return (
        <div className="auth-screen android-pair-screen">
            <div className="auth-orbit" aria-hidden="true"><span>✦</span></div>
            <div className="auth-kicker">ОДИН АККАУНТ · БОТ И ПРИЛОЖЕНИЕ</div>
            <h2>Подключите Telegram</h2>
            <p>Подтвердите вход в боте. Баланс и достижения появятся здесь автоматически.</p>
            {pair ? <>
                <div className="pair-code-label">Ваш одноразовый код</div>
                <div className="pair-code">{pair.code}</div>
                <p className="pair-countdown">Код действует ещё {String(Math.floor(remaining / 60)).padStart(2, '0')}:{String(remaining % 60).padStart(2, '0')}</p>
                <a className="btn btn-primary pair-open-bot" href={pair.bot_url}>Открыть бота и подтвердить</a>
                <p className="pair-hint">Если ссылка не сработала, отправьте боту <code>/connect {pair.code}</code></p>
                <p className="pair-waiting">Ожидаем подтверждения…</p>
            </> : <>
                {error ? <p className="pair-error">{error}</p> : <p>Создаём код входа…</p>}
                {error && <button className="btn btn-primary" onClick={() => setAttempt(value => value + 1)}>
                    Получить новый код
                </button>}
            </>}
        </div>
    );
}

function useAvatar(userId, refreshKey) {
    const [avatar, setAvatar] = useState(null);
    useEffect(() => {
        setAvatar(null);
        if (!userId) return;
        let disposed = false, objectUrl = null, controller = null, retryTimer = null;
        const load = async (attempt = 0) => {
            controller?.abort();
            clearTimeout(retryTimer);
            const requestController = new AbortController();
            controller = requestController;
            const token = localStorage.getItem('webapp_token');
            if (!token) return;
            try {
                const blob = await AvatarMedia.load(token, requestController.signal);
                if (disposed || controller !== requestController) return;
                const nextUrl = blob ? URL.createObjectURL(blob) : null;
                if (objectUrl) URL.revokeObjectURL(objectUrl);
                objectUrl = nextUrl;
                setAvatar({ userId, url: objectUrl });
            } catch (error) {
                if (disposed || controller !== requestController || error.name === 'AbortError') return;
                if (error.status === 401) {
                    if (localStorage.getItem('webapp_token') === token) {
                        localStorage.removeItem('webapp_token');
                        window.dispatchEvent(new Event('webapp-auth-expired'));
                    }
                } else if (attempt < 2) {
                    retryTimer = setTimeout(() => load(attempt + 1), 3000 * (attempt + 1));
                }
            }
        };
        const onVisible = () => { if (!document.hidden) load(); };
        const onOnline = () => load();
        load();
        window.addEventListener('online', onOnline);
        document.addEventListener('visibilitychange', onVisible);
        return () => {
            disposed = true;
            controller?.abort();
            clearTimeout(retryTimer);
            if (objectUrl) URL.revokeObjectURL(objectUrl);
            window.removeEventListener('online', onOnline);
            document.removeEventListener('visibilitychange', onVisible);
        };
    }, [userId, refreshKey]);
    return avatar && avatar.userId === userId ? avatar.url : null;
}

function App() {
    const [user, setUser] = useState(null);
    const [profile, setProfile] = useState(null);
    const [page, setPage] = useState('home');
    const [loading, setLoading] = useState(true);
    const [avatarRefresh, setAvatarRefresh] = useState(0);
    const photoUrl = useAvatar(user?.user_id, avatarRefresh);
    useEffect(() => {
        const theme = profile?.preferences?.theme || 'dark';
        document.body.dataset.theme = theme;
        localStorage.setItem('ton-theme', theme);
    }, [profile?.preferences?.theme]);

    const refreshProfile = useCallback(() => {
        if (!user) return;
        return api('/profile').then(p => {
            setProfile(p);
            setAvatarRefresh(value => value + 1);
        }).catch(() => {});
    }, [user]);

    useEffect(() => {
        const token = localStorage.getItem('webapp_token');
        if (token) {
            api('/profile').then(p => {
                setProfile(p);
                setUser({ user_id: p.user_id });
            }).catch(() => {
                localStorage.removeItem('webapp_token');
            }).finally(() => {
                setLoading(false);
            });
        } else {
            setLoading(false);
        }

        // Telegram WebApp init
        if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.ready();
            window.Telegram.WebApp.expand();
        }
    }, []);

    useEffect(() => {
        const resetAuth = () => {
            setUser(null);
            setProfile(null);
            setPage('home');
        };
        window.addEventListener('webapp-auth-expired', resetAuth);
        return () => window.removeEventListener('webapp-auth-expired', resetAuth);
    }, []);

    const handleAuth = async (initData) => {
        try {
            const res = await fetch(`${API_BASE}/auth`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ initData }),
            });
            const data = await res.json();
            if (!res.ok || !data.token) return false;
            localStorage.setItem('webapp_token', data.token);
            const loadedProfile = await api('/profile');
            setProfile(loadedProfile);
            setUser({ user_id: loadedProfile.user_id });
            return true;
        } catch (e) {
            console.error('Auth error:', e);
            localStorage.removeItem('webapp_token');
            return false;
        }
    };

    const handlePairedToken = async token => {
        try {
            localStorage.setItem('webapp_token', token);
            const loadedProfile = await api('/profile');
            setProfile(loadedProfile);
            setUser({ user_id: loadedProfile.user_id });
            return true;
        } catch {
            localStorage.removeItem('webapp_token');
            return false;
        }
    };

    if (loading) return <Loading />;
    if (!user) return IS_ANDROID_SHELL
        ? <AndroidPairScreen onAuth={handlePairedToken} />
        : <AuthScreen onAuth={handleAuth} />;

    return (
        <div className="app">
            <div className="header">
                <div className="brand-mark" aria-hidden="true">✦</div>
                <div className="brand-copy"><h1>TON CASINO</h1><div className="subtitle">ИГРА · СТИЛЬ · СООБЩЕСТВО</div></div>
                <div className="header-spark" aria-hidden="true">✧</div>
            </div>

            {page === 'home' && <DashboardPage profile={profile} photoUrl={photoUrl} onNavigate={setPage} />}
            {page === 'bonuses' && <BonusesPage refreshProfile={refreshProfile} />}
            {page === 'history' && <HistoryPage profile={profile} />}
            {page === 'statistics' && <StatisticsPage />}
            {page === 'coinflip' && <><GameTabs page="coinflip" onNavigate={setPage} /><CoinflipPage profile={profile} refreshProfile={refreshProfile} /></>}
            {page === 'more' && <MorePage profile={profile} onNavigate={setPage} />}
            {page === 'profile' && <ProfilePage profile={profile} refreshProfile={refreshProfile} photoUrl={photoUrl} />}
            {page === 'games' && <GamesPage profile={profile} refreshProfile={refreshProfile} onNavigate={setPage} />}
            {page === 'shop' && <ShopPage profile={profile} refreshProfile={refreshProfile} photoUrl={photoUrl} />}
            {page === 'ref' && <ReferralPage profile={profile} />}
            {page === 'leaderboard' && <LeaderboardPage profile={profile} />}

            <NavBar page={page} onNavigate={setPage} />
        </div>
    );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
