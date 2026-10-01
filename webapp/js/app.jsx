const { useState, useEffect, useCallback, createContext, useContext } = React;

const API_BASE = '/app/api';
const IS_ANDROID_SHELL = new URLSearchParams(window.location.search).get('client') === 'android';

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
    return fetch(`${API_BASE}${path}`, { ...options, headers: { ...headers, ...options.headers } })
        .then(async r => {
            const data = await r.json().catch(() => ({ error: 'request failed' }));
            if (!r.ok) {
                if (r.status === 401) {
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
    return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
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
    const items = [
        { id: 'profile', icon: '👤', label: 'Профиль' },
        { id: 'leaderboard', icon: '🏆', label: 'Рейтинг' },
        { id: 'games', icon: '🎮', label: 'Игры' },
        { id: 'shop', icon: '🛒', label: 'Магазин' },
        { id: 'ref', icon: '👥', label: 'Рефералы' },
    ];
    return (
        <nav className="nav-bar" aria-label="Разделы приложения">
            {items.map(it => (
                <button
                    key={it.id}
                    type="button"
                    className={`nav-item ${page === it.id ? 'active' : ''}`}
                    onClick={() => onNavigate(it.id)}
                    aria-current={page === it.id ? 'page' : undefined}
                >
                    <span className="nav-icon">{it.icon}</span>
                    {it.label}
                </button>
            ))}
        </nav>
    );
}

function FrameAvatar({ frame, photoUrl, initials, small = false, large = false }) {
    const frameId = FRAME_EMBLEMS[frame] ? frame : 'default';
    return (
        <div className={`frame-avatar frame-avatar--${frameId}${small ? ' frame-avatar--small' : ''}${large ? ' frame-avatar--large' : ''}`}>
            <div className="frame-avatar-core">
                {photoUrl ? <img src={photoUrl} alt="" /> : initials}
            </div>
            {FRAME_EMBLEMS[frame] && (
                <span className="frame-avatar-emblem" aria-hidden="true">{FRAME_EMBLEMS[frame]}</span>
            )}
        </div>
    );
}

function ProfilePage({ profile, refreshProfile }) {
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
        title_vip: 'ЛОВЕЦ УДАЧИ', title_legend: 'ПОВЕЛИТЕЛЬ РИСКА',
        title_elixir: 'ЛУННЫЙ АЛХИМИК', title_shadow: 'ХРАНИТЕЛЬ ТАЙНЫ',
        title_whale: 'АЛМАЗНЫЙ МАГНАТ', title_god: 'ВЛАДЫКА СУДЬБЫ',
        title_jackpot: 'ХРАНИТЕЛЬ ДЖЕКПОТА', title_fortune: 'АРХИТЕКТОР ФОРТУНЫ',
        title_owner: 'OWNER', title_ket: 'KET',
    };
    const initials = (profile.first_name || 'K')[0].toUpperCase();
    const tgUser = window.Telegram?.WebApp?.initDataUnsafe?.user;
    const photoUrl = tgUser?.photo_url;

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
                            {titleNames[profile.active_title] || profile.active_title}
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
            {IS_ANDROID_SHELL && <button className="android-signout" onClick={() => {
                localStorage.removeItem('webapp_token');
                window.dispatchEvent(new Event('webapp-auth-expired'));
            }}>Сменить Telegram-аккаунт</button>}
        </div>
    );
}

function GamesPage({ profile, refreshProfile }) {
    const [mineCount, setMineCount] = useState(3);
    const [bet, setBet] = useState('100');
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
                    { icon: '🃏', name: 'Джокер', desc: 'Пока в боте' },
                    { icon: '⚗️', name: 'Алхимик', desc: 'Пока в боте' },
                    { icon: '🂡', name: '21', desc: 'Пока в боте' },
                ].map(game => (
                    <div key={game.name} className="game-card game-card--disabled">
                        <div className="game-icon">{game.icon}</div>
                        <div className="game-name">{game.name}</div>
                        <div className="game-desc">{game.desc}</div>
                    </div>
                ))}
            </div>
        </div>
    );
}

function ShopPage({ profile, refreshProfile }) {
    const [shop, setShop] = useState(null);
    const [category, setCategory] = useState('frames');
    const [toast, setToast] = useState(null);
    const [tryOn, setTryOn] = useState(null);
    const photoUrl = window.Telegram?.WebApp?.initDataUnsafe?.user?.photo_url;
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

function LeaderboardPage({ profile }) {
    const [tab, setTab] = useState('balance');
    const [data, setData] = useState(null);

    useEffect(() => {
        setData(null);
        api(`/leaderboard?mode=${tab}&limit=20`).then(setData).catch(() => {});
    }, [tab]);

    const medals = ['🥇', '🥈', '🥉'];
    const tabs = [
        { id: 'balance', label: '💰 Баланс' },
        { id: 'wins', label: '🏆 Победы' },
        { id: 'xp', label: '📊 Опыт' },
    ];

    return (
        <div className="page leaderboard-page">
            <div className="page-intro"><span>ЛИДЕРЫ</span><span className="page-intro-mark">ТОП 20</span></div>
            <div className="section-title">Рейтинг <span>Лучшие игроки клуба</span></div>
            <div className="leaderboard-tabs">
                {tabs.map(t => (
                    <button
                        key={t.id}
                        className={`btn btn-small ${tab === t.id ? 'btn-primary' : 'btn-secondary'}`}
                        onClick={() => setTab(t.id)}
                    >
                        {t.label}
                    </button>
                ))}
            </div>
            {!data ? <Loading /> : (
                <>
                    {data.my_rank && (
                        <div className="card my-rank">
                            <span>ВАША ПОЗИЦИЯ</span>
                            <strong>#{data.my_rank}</strong>
                        </div>
                    )}
                    <div className="card leaderboard-list">
                        {data.players.length === 0 ? (
                            <p style={{ textAlign: 'center', color: 'var(--text-dim)', padding: '20px 0' }}>
                                Пока нет данных
                            </p>
                        ) : data.players.map(p => (
                            <div key={p.user_id} className={`leaderboard-player${p.is_me ? ' is-me' : ''}`}>
                                <div style={{
                                    width: '28px',
                                    textAlign: 'center',
                                    fontSize: p.rank <= 3 ? '20px' : '15px',
                                    fontWeight: 700,
                                    color: p.rank <= 3 ? 'var(--gold)' : 'var(--text-dim)',
                                }}>
                                    {p.rank <= 3 ? medals[p.rank - 1] : p.rank}
                                </div>
                                <div className="avatar leaderboard-avatar">
                                    {(p.first_name || 'K')[0].toUpperCase()}
                                </div>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontSize: '14px', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {p.first_name || 'Игрок'}
                                        {p.username && <span style={{ color: 'var(--text-dim)', fontWeight: 400 }}> @{p.username}</span>}
                                    </div>
                                </div>
                                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                                    {tab === 'balance' ? (
                                        <>
                                            <div style={{ fontSize: '15px', fontWeight: 700, color: 'var(--gold)' }}>{formatNumber(p.max_balance)}</div>
                                            <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>TON</div>
                                        </>
                                    ) : tab === 'xp' ? (
                                        <>
                                            <div style={{ fontSize: '15px', fontWeight: 700, color: '#b478ff' }}>{formatNumber(p.xp || 0)}</div>
                                            <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>XP</div>
                                        </>
                                    ) : (
                                        <>
                                            <div style={{ fontSize: '15px', fontWeight: 700, color: 'var(--green)' }}>{formatNumber(p.wins)}</div>
                                            <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>{p.total_games} игр</div>
                                        </>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </>
            )}
        </div>
    );
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

    useEffect(() => {
        let active = true;
        setPair(null);
        setError('');
        api('/mobile/pair/start', { method: 'POST' }).then(data => {
            if (active) setPair(data);
        }).catch(() => {
            if (active) setError('Не удалось получить код. Проверьте подключение к интернету.');
        });
        return () => { active = false; };
    }, [attempt]);

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

function App() {
    const [user, setUser] = useState(null);
    const [profile, setProfile] = useState(null);
    const [page, setPage] = useState('profile');
    const [loading, setLoading] = useState(true);

    const refreshProfile = useCallback(() => {
        if (!user) return;
        return api('/profile').then(setProfile).catch(() => {});
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

            {page === 'profile' && <ProfilePage profile={profile} refreshProfile={refreshProfile} />}
            {page === 'games' && <GamesPage profile={profile} refreshProfile={refreshProfile} />}
            {page === 'shop' && <ShopPage profile={profile} refreshProfile={refreshProfile} />}
            {page === 'ref' && <ReferralPage profile={profile} />}
            {page === 'leaderboard' && <LeaderboardPage profile={profile} />}

            <NavBar page={page} onNavigate={setPage} />
        </div>
    );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
