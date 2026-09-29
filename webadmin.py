"""Веб-админ-панель бота: статистика, игроки, настройки игр.

Работает на том же aiohttp-сервере, что и бот (URL /admin).
Вход: ADMIN_PANEL_USER / ADMIN_PANEL_PASSWORD (config.py).
"""
import html
import logging
import math
import secrets
import time
from collections import defaultdict

from aiohttp import web

from config import ADMIN_PANEL_PASSWORD, ADMIN_PANEL_USER, MAX_BET, MAX_GAME_MULTIPLIER
from database import db
from games.joker import get_joker_levels
from games.mines import get_house_edge
from utils.helpers import format_number, get_daily_bonus, get_weekly_bonus
from utils.notify import send as notify_send

log = logging.getLogger("webadmin")

SESSION_TTL = 60 * 60 * 12  # 12 часов
_sessions: dict[str, float] = {}  # token -> expires_at

_login_attempts: dict[str, list[float]] = defaultdict(list)
LOGIN_RATE_LIMIT = 5
LOGIN_RATE_WINDOW = 60  # секунд


def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < LOGIN_RATE_WINDOW]
    if len(_login_attempts[ip]) >= LOGIN_RATE_LIMIT:
        return False
    _login_attempts[ip].append(now)
    return True


def _log_admin(action: str, ip: str, detail: str = "") -> None:
    log.warning("ADMIN %s from %s %s", action, ip, detail)

_CSS = """
* { box-sizing: border-box; }
body,html { margin:0; padding:0; }
body {
  font-family:'Segoe UI',-apple-system,system-ui,Roboto,'Helvetica Neue',sans-serif;
  color:#e8ecf4; min-height:100vh;
  background:
    radial-gradient(1200px 600px at 80% -10%, rgba(99,102,241,.22) 0%, transparent 60%),
    radial-gradient(900px 500px at -10% 110%, rgba(168,85,247,.16) 0%, transparent 55%),
    #0c1220;
  background-attachment:fixed;
}
a { text-decoration:none; color:inherit; }

.navbar {
  position:sticky; top:0; z-index:50;
  display:flex; align-items:center; gap:8px; flex-wrap:wrap;
  padding:0 24px; height:64px;
  background:rgba(13,18,32,.82); backdrop-filter:blur(12px);
  border-bottom:1px solid rgba(255,255,255,.06);
}
.brand { display:flex; align-items:center; gap:10px; margin-right:18px; font-weight:800; font-size:17px; }
.logo-badge {
  width:36px; height:36px; border-radius:10px; display:grid; place-items:center; font-size:18px;
  background:linear-gradient(135deg,#6366f1,#a855f7); box-shadow:0 4px 14px rgba(99,102,241,.45);
}
.tabs { display:flex; gap:6px; flex-wrap:wrap; }
.tab { padding:9px 16px; border-radius:10px; font-size:14px; font-weight:600; color:#9aa6c3; transition:.2s; }
.tab:hover { color:#fff; background:rgba(255,255,255,.06); }
.tab.on { color:#fff; background:linear-gradient(135deg,#6366f1,#8b5cf6); box-shadow:0 4px 12px rgba(99,102,241,.35); }
.logout { margin-left:auto; padding:9px 16px; border-radius:10px; font-size:14px; font-weight:600; color:#fca5a5; transition:.2s; }
.logout:hover { background:rgba(248,113,113,.12); color:#fff; }

main { max-width:1120px; margin:0 auto; padding:28px 24px 60px; }
.page-title { font-size:24px; font-weight:800; margin:0 0 6px; }
.page-sub { color:#8a95b3; font-size:14px; margin-bottom:22px; }

.card {
  background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.07);
  border-radius:16px; padding:20px; margin-bottom:18px; box-shadow:0 8px 30px rgba(0,0,0,.25);
}
.card h2 { margin:0 0 6px; font-size:16px; font-weight:700; }
.card .hint { color:#8a95b3; font-size:13px; margin:0 0 16px; }

.strip { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:14px; margin-bottom:20px; }
.mini-stat {
  background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.07);
  border-radius:14px; padding:16px 18px;
}
.mini-stat span { color:#8a95b3; font-size:13px; }
.mini-stat b { display:block; font-size:24px; margin-top:6px; }

.search-row { display:flex; gap:10px; }
.search-row input { flex:1; }
input[type=text], input[type=password], input[type=number], input[type=search] {
  background:rgba(13,18,32,.7); border:1px solid rgba(255,255,255,.12); color:#e8ecf4;
  border-radius:10px; padding:10px 14px; font-size:14px; outline:none; transition:.2s;
}
input:focus { border-color:#8b5cf6; box-shadow:0 0 0 3px rgba(139,92,246,.25); }

.btn {
  display:inline-flex; align-items:center; gap:6px; justify-content:center;
  border:0; border-radius:10px; padding:10px 16px; font-size:14px; font-weight:600;
  cursor:pointer; transition:.2s; color:#fff; font-family:inherit;
}
.btn-primary { background:linear-gradient(135deg,#6366f1,#8b5cf6); box-shadow:0 4px 14px rgba(99,102,241,.35); }
.btn-primary:hover { filter:brightness(1.12); }
.btn-success { background:rgba(16,185,129,.9); }
.btn-success:hover { filter:brightness(1.12); }
.btn-danger { background:rgba(239,68,68,.9); }
.btn-danger:hover { filter:brightness(1.12); }
.btn-ghost { background:rgba(255,255,255,.08); }
.btn-ghost:hover { background:rgba(255,255,255,.14); }
.btn-sm { padding:7px 12px; font-size:13px; border-radius:8px; }

.table-wrap { border-radius:14px; overflow:hidden; margin-top:18px; }
table { width:100%; border-collapse:collapse; font-size:14px; }
th {
  text-align:left; padding:12px 14px; font-size:12px; letter-spacing:.5px; text-transform:uppercase;
  color:#8a95b3; background:rgba(255,255,255,.03); border-bottom:1px solid rgba(255,255,255,.06);
}
td { padding:12px 14px; border-bottom:1px solid rgba(255,255,255,.05); vertical-align:middle; }
tbody tr { transition:.15s; }
tbody tr:last-child td { border-bottom:0; }
tbody tr:hover { background:rgba(255,255,255,.03); }

.p-avatar {
  width:38px; height:38px; border-radius:12px; display:grid; place-items:center;
  font-weight:800; font-size:16px; color:#fff; flex-shrink:0;
  background:linear-gradient(135deg,#6366f1,#a855f7);
}
.p-name { display:flex; align-items:center; gap:10px; }
.p-name .txt b { display:block; font-size:14px; }
.p-name .txt span { color:#8a95b3; font-size:12px; }
.balance-cell { font-weight:800; font-size:15px; letter-spacing:.3px; }

.pill { display:inline-flex; align-items:center; gap:6px; padding:4px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.pill::before { content:''; width:7px; height:7px; border-radius:50%; }
.pill.green { background:rgba(16,185,129,.12); color:#6ee7b7; }
.pill.green::before { background:#10b981; box-shadow:0 0 8px #10b981; }
.pill.red { background:rgba(239,68,68,.12); color:#fca5a5; }
.pill.red::before { background:#ef4444; box-shadow:0 0 8px #ef4444; }

.amount-form { display:flex; gap:6px; align-items:center; }
.amount-form input { width:110px; }
.action-col { display:flex; gap:8px; }

.warn-banner {
  display:flex; gap:10px; align-items:flex-start; padding:14px 16px; border-radius:12px;
  background:rgba(245,158,11,.1); border:1px solid rgba(245,158,11,.25); color:#fcd34d;
  font-size:13px; line-height:1.5; margin-bottom:18px;
}
.settings-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:14px; }
.field { margin-bottom:18px; }
.field label { display:block; font-size:13px; color:#8a95b3; margin-bottom:8px; font-weight:600; }
.field .desc { font-size:12px; color:#6b7694; margin-top:6px; line-height:1.5; }
.field input { width:100%; }
.divider { height:1px; background:rgba(255,255,255,.07); margin:4px 0 18px; }

.msg { padding:12px 16px; border-radius:12px; margin-bottom:16px; font-size:14px; }
.ok { background:#052e25; border:1px solid rgba(16,185,129,.4); color:#6ee7b7; }
.err { background:#3a1115; border:1px solid rgba(239,68,68,.4); color:#fca5a5; }

.login-wrap { max-width:400px; margin:90px auto; }
.login-card {
  background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.1);
  border-radius:20px; padding:32px; text-align:center;
  box-shadow:0 20px 60px rgba(0,0,0,.5); backdrop-filter:blur(10px);
}
.login-badge {
  width:56px; height:56px; margin:0 auto 14px; border-radius:16px; display:grid; place-items:center;
  font-size:26px; background:linear-gradient(135deg,#6366f1,#a855f7); box-shadow:0 8px 24px rgba(99,102,241,.45);
}
.login-card h1 { font-size:20px; margin:0 0 6px; }
.login-card .sub { color:#8a95b3; font-size:13px; margin-bottom:22px; }
.login-card form { text-align:left; }
.login-card .btn { width:100%; margin-top:8px; }
.login-card label { display:block; font-size:13px; color:#8a95b3; margin:12px 0 6px; font-weight:600; }
.login-card input { width:100%; }
"""


def _page(title: str, body: str, active: str) -> str:
    tabs = [
        ("players", "👥 Игроки", "/admin"),
        ("promos", "🎟 Промокоды", "/admin/promos"),
        ("settings", "⚙️ Настройки", "/admin/settings"),
    ]
    nav = "".join(
        f'<a class="tab {"on" if a == active else ""}" href="{u}">{t}</a>'
        for a, t, u in tabs
    )
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — Админка</title>
<style>{_CSS}</style></head><body>
<header class="navbar">
  <span class="brand"><span class="logo-badge">⚙️</span> Админка бота</span>
  <nav class="tabs">{nav}</nav>
  <a class="logout" href="/admin/logout">Выйти</a>
</header>
<main>{body}</main>
</body></html>"""


def _flash(msg: str, ok: bool = True) -> str:
    return f'<div class="msg {"ok" if ok else "err"}">{html.escape(msg)}</div>'


def _set_cookie(resp: web.Response, token: str) -> None:
    resp.set_cookie("adm", token, max_age=SESSION_TTL, httponly=True, samesite="Lax")


# ---------- Авторизация ----------

def _auth_ok(request: web.Request) -> bool:
    token = request.cookies.get("adm")
    if not token:
        return False
    exp = _sessions.get(token)
    if not exp:
        return False
    if time.time() > exp:
        _sessions.pop(token, None)
        return False
    return True


# ---------- Вкладка «Игроки» ----------

def _avatar(name: str) -> str:
    ch = (name or "?").strip()[:1].upper() or "?"
    return f'<span class="p-avatar">{html.escape(ch)}</span>'


def _player_row(u: dict) -> str:
    name = u["first_name"] or u["username"] or f"ID {u['id']}"
    nick = f"@{html.escape(u['username'])}" if u["username"] else f"ID {u['id']}"
    blocked = ('<span class="pill red">заблокирован</span>' if u["is_blocked"]
               else '<span class="pill green">активен</span>')
    toggle = "Разблокировать" if u["is_blocked"] else "Заблокировать"
    toggle_url = "/admin/unblock" if u["is_blocked"] else "/admin/block"
    toggle_cls = "ghost" if u["is_blocked"] else "danger"
    rubies = u.get('rubies', 0) or 0
    return f"""<tr>
<td>
  <div class="p-name">
    {_avatar(name)}
    <div class="txt"><b>{html.escape(name)}</b><span>{html.escape(nick)}</span></div>
  </div>
</td>
<td class="balance-cell">{format_number(u['balance'])}</td>
<td class="balance-cell">💎 {rubies}</td>
<td>{blocked}</td>
<td>
  <form class="amount-form" method="post" action="/admin/give">
    <input type="hidden" name="uid" value="{u['id']}">
    <input type="number" name="amount" value="1000" min="1">
    <button class="btn btn-success btn-sm" title="Начислить TON">+</button>
    <button class="btn btn-danger btn-sm" name="neg" value="1" title="Списать TON">−</button>
  </form>
  <form class="amount-form" method="post" action="/admin/give_rubies">
    <input type="hidden" name="uid" value="{u['id']}">
    <input type="number" name="amount" value="1" min="0.1" step="0.1">
    <button class="btn btn-success btn-sm" title="Начислить рубины">💎+</button>
    <button class="btn btn-danger btn-sm" name="neg" value="1" title="Списать рубины">💎−</button>
  </form>
</td>
<td>
  <form class="amount-form" method="post" action="{toggle_url}">
    <input type="hidden" name="uid" value="{u['id']}">
    <button class="btn btn-{toggle_cls} btn-sm">{toggle}</button>
  </form>
</td>
</tr>"""


async def players_page(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.HTTPFound("/admin/login")
    q = request.query.get("q", "").strip()
    users = db.search_users(q, limit=100)
    ov = db.admin_overview()

    stats = [
        ("👥", "Игроков", ov["users"]),
        ("💰", "Монет в игре", format_number(ov["balance"])),
        ("🎮", "Сыграно игр", ov["games"]),
        ("🏆", "Выигрышей", ov["wins"]),
        ("💸", "Оборот", format_number(ov["tx_volume"])),
    ]
    strip = "".join(
        f'<div class="mini-stat"><span>{e}</span><b>{v}</b></div>' for _, e, v in stats
    )

    body = f"""
<div class="page-title">👥 Игроки</div>
<div class="page-sub">{'Результаты по запросу «' + html.escape(q) + '»' if q else 'База игроков бота. Нажмите + или − для выдачи / списания TON.'}</div>
<div class="strip">{strip}</div>
<form class="card" method="get" action="/admin">
  <div class="search-row">
    <input type="search" name="q" placeholder="Поиск: имя, @username, ID" value="{html.escape(q)}">
    <button class="btn btn-primary">Искать</button>
  </div>
</form>
<div class="card" style="padding:0">
  <div class="table-wrap"><table>
  <thead><tr><th>Игрок</th><th>Баланс (TON)</th><th>Рубины</th><th>Статус</th><th>Выдать / списать</th><th>Действия</th></tr></thead>
  <tbody>
  {''.join(_player_row(u) for u in users) or '<tr><td colspan="6" style="text-align:center;padding:32px;color:#8a95b3">Никого не найдено</td></tr>'}
  </tbody>
  </table></div>
</div>"""
    return web.Response(text=_page("Игроки", body, "players"), content_type="text/html", charset="utf-8")


async def give_coins(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.HTTPFound("/admin/login")
    ip = request.remote or "unknown"
    form = await request.post()
    uid, amount = form.get("uid", ""), form.get("amount", "")
    try:
        uid = int(uid)
        amount = int(amount)
    except (TypeError, ValueError):
        return web.HTTPFound("/admin")
    if amount <= 0 or amount > 10_000_000_000:
        return web.HTTPFound("/admin")
    user = db.get_user(uid)
    if not user:
        return web.HTTPFound("/admin")
    if form.get("neg"):
        amount = -amount
    db.add_balance(uid, amount, "admin", "Веб-админка: изменение баланса")
    latest = db.get_user(uid)
    _log_admin("GIVE_COINS", ip, f"uid={uid} amount={amount} new_bal={latest['balance']}")
    if amount > 0:
        await notify_send(
            uid,
            f"💰 <b>Вам начислено {format_number(amount)} TON</b>\n\n"
            f"💳 Баланс: {format_number(latest['balance'])}",
        )
    else:
        await notify_send(
            uid,
            f"⚠️ С вашего счёта списано {format_number(-amount)} TON\n\n"
            f"💳 Баланс: {format_number(latest['balance'])}",
        )
    return web.HTTPFound("/admin")


async def give_rubies(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.HTTPFound("/admin/login")
    ip = request.remote or "unknown"
    form = await request.post()
    uid, amount = form.get("uid", ""), form.get("amount", "")
    try:
        uid = int(uid)
        amount = float(amount)
    except (TypeError, ValueError):
        return web.HTTPFound("/admin")
    if amount <= 0 or amount > 1_000_000:
        return web.HTTPFound("/admin")
    user = db.get_user(uid)
    if not user:
        return web.HTTPFound("/admin")
    if form.get("neg"):
        amount = -amount
    db.add_rubies(uid, amount)
    latest = db.get_user(uid)
    _log_admin("GIVE_RUBIES", ip, f"uid={uid} amount={amount} new_rubies={latest.get('rubies', 0)}")
    if amount > 0:
        await notify_send(
            uid,
            f"💎 <b>Вам начислено {amount} рубинов</b>\n\n"
            f"💎 Рубины: {latest.get('rubies', 0) or 0}",
        )
    else:
        await notify_send(
            uid,
            f"⚠️ Списано {abs(amount)} рубинов\n\n"
            f"💎 Рубины: {latest.get('rubies', 0) or 0}",
        )
    return web.HTTPFound("/admin")


async def block_user(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.HTTPFound("/admin/login")
    ip = request.remote or "unknown"
    form = await request.post()
    uid = form.get("uid", "")
    if uid.isdigit():
        db.set_blocked(int(uid), True)
        _log_admin("BLOCK", ip, f"uid={uid}")
    return web.HTTPFound("/admin")


async def unblock_user(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.HTTPFound("/admin/login")
    ip = request.remote or "unknown"
    form = await request.post()
    uid = form.get("uid", "")
    if uid.isdigit():
        db.set_blocked(int(uid), False)
        _log_admin("UNBLOCK", ip, f"uid={uid}")
    return web.HTTPFound("/admin")


# ---------- Вкладка «Настройки» ----------

def _field(name: str, label: str, value, step: str, minv: str, maxv: str, desc: str, itype: str = "number") -> str:
    return f"""<div class="field">
<label for="{name}">{label}</label>
<input type="{itype}" step="{step}" min="{minv}" max="{maxv}" name="{name}" id="{name}" value="{value}">
<div class="desc">{desc}</div>
</div>"""


async def settings_page(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.HTTPFound("/admin/login")
    levels = get_joker_levels()
    current = {
        "mines_house_edge": get_house_edge(),
        "joker_mult_1": levels[1]["mult"],
        "joker_mult_2": levels[2]["mult"],
        "daily_bonus": get_daily_bonus(),
        "weekly_bonus": get_weekly_bonus(),
    }
    body = f"""
<div class="page-title">⚠️ Настройки</div>
<div class="page-sub">Коэффициенты игр. Применяются сразу, без перезапуска бота.</div>
<p class="hint">Максимальная ставка: {format_number(MAX_BET)} TON. Максимальный множитель в «Минах» и «Джокере»: ×{MAX_GAME_MULTIPLIER:g}.</p>

{f'<div class="warn-banner" style="border-color:rgba(16,185,129,.4)"><span style="font-size:18px">✅</span><span><b>База данных сброшена.</b> Все балансы и статистика обнулены.</span></div>' if request.query.get("resetted") else ''}

<div class="warn-banner">
  <span style="font-size:18px">⚠️</span>
  <span><b>Опасная зона.</b> От этих значений напрямую зависит баланс заведения: уменьшите множители — игроки будут получать меньше, увеличьте — бот будет терять больше. Вводите значения аккуратно.</span>
</div>

<form method="post" action="/admin/settings">
<div class="card">
  <h2>🎮 Мины</h2>
  <p class="hint">Доля честной выплаты (0.1–0.94). Чем выше значение, тем больше получают игроки.</p>
  {_field("mines_house_edge", "Доля выплаты", current["mines_house_edge"], "0.01", "0.1", "0.94", "Пример: 0.94 — выплата составляет 94% от честного множителя.")}
</div>

<div class="card">
  <h2>🃏 Джокер</h2>
  <p class="hint">Множитель, который накапливается за каждую удачно открытую дверь.</p>
  <div class="settings-grid">
    <div>{_field("joker_mult_1", "💀 Уровень 1 — 1 скелет", current["joker_mult_1"], "0.1", "1", "1.4", "Максимум ×1.4 при шансе 2 из 3.")}</div>
    <div>{_field("joker_mult_2", "💀 Уровень 2 — 2 скелета", current["joker_mult_2"], "0.1", "1", "2.8", "Максимум ×2.8 при шансе 1 из 3.")}</div>
  </div>
</div>

<div class="card">
  <h2>🎁 Бонусы</h2>
  <p class="hint">Размер бонусов, которые игроки получают раз в день и раз в неделю. Бот сам напоминает игрокам, когда бонус снова доступен.</p>
  <div class="settings-grid">
    <div>{_field("daily_bonus", "☀️ Ежедневный бонус", current["daily_bonus"], "1", "0", "1000000000000", "Начисляется один раз в сутки через /daily или кнопку «Бонус».")}</div>
    <div>{_field("weekly_bonus", "🗓 Еженедельный бонус", current["weekly_bonus"], "1", "0", "1000000000000", "Начисляется один раз в неделю через /weekly или уведомление.")}</div>
  </div>
</div>

<div class="card">
  <div style="display:flex;align-items:center;gap:12px">
    <button class="btn btn-primary">💾 Сохранить настройки</button>
    <span class="muted" style="font-size:13px">Изменения вступят в силу сразу после сохранения</span>
  </div>
</div>
</form>

<div class="card" style="border-color:rgba(239,68,68,.35); background:rgba(239,68,68,.04)">
  <h2 style="color:#fca5a5">🗑 Сброс базы данных</h2>
  <p class="hint">Всем игрокам будет установлен стартовый баланс, статистика, история транзакций, игры и активации промокодов будут удалены. Промокоды как записи сохранятся. Действие необратимо.</p>
  <form method="post" action="/admin/reset"
        onsubmit="return confirm('Точно сбросить БАЗУ ДАННЫХ всем игрокам? Это необратимо.');">
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <input type="text" name="confirm" placeholder="Введите слово СБРОС" required
             style="width:200px" autocomplete="off">
      <button class="btn btn-danger">🗑 Сбросить базу данных</button>
    </div>
  </form>
</div>"""
    return web.Response(text=_page("Настройки", body, "settings"), content_type="text/html", charset="utf-8")


async def reset_database(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.HTTPFound("/admin/login")
    ip = request.remote or "unknown"
    form = await request.post()
    if (form.get("confirm", "") or "").strip().upper() != "СБРОС":
        return web.HTTPFound("/admin/settings")
    db.reset_database()
    _log_admin("RESET_DB", ip, "DATABASE FULLY RESET")
    return web.HTTPFound("/admin/settings?resetted=1")


async def save_settings(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.HTTPFound("/admin/login")
    ip = request.remote or "unknown"
    form = await request.post()

    def _parse(name: str) -> float | None:
        raw = form.get(name, "")
        try:
            value = float(raw.replace(",", "."))
            return value if math.isfinite(value) else None
        except (TypeError, ValueError):
            return None

    def _parse_int(name: str) -> int | None:
        raw = form.get(name, "")
        try:
            return int(float(raw.replace(",", ".")))
        except (TypeError, ValueError):
            return None

    vals = {
        "mines_house_edge": _parse("mines_house_edge"),
        "joker_mult_1": _parse("joker_mult_1"),
        "joker_mult_2": _parse("joker_mult_2"),
        "daily_bonus": _parse_int("daily_bonus"),
        "weekly_bonus": _parse_int("weekly_bonus"),
    }
    ok = True
    if not vals["mines_house_edge"] or not 0.1 <= vals["mines_house_edge"] <= 0.94:
        ok = False
    if not vals["joker_mult_1"] or not 1 <= vals["joker_mult_1"] <= 1.4:
        ok = False
    if not vals["joker_mult_2"] or not 1 <= vals["joker_mult_2"] <= 2.8:
        ok = False
    if vals["daily_bonus"] is None or not 0 <= vals["daily_bonus"] <= 10 ** 12:
        ok = False
    if vals["weekly_bonus"] is None or not 0 <= vals["weekly_bonus"] <= 10 ** 12:
        ok = False
    if ok:
        for key, val in vals.items():
            db.set_setting(key, val)
    return web.HTTPFound("/admin/settings")


# ---------- Промокоды ----------

def _promo_row(p: dict) -> str:
    status = ('<span class="pill green">активен</span>' if p["is_active"]
              else '<span class="pill red">неактивен</span>')
    toggle_label = "⛔ Выключить" if p["is_active"] else "✅ Включить"
    toggle_val = "0" if p["is_active"] else "1"
    return f"""<tr>
<td><b><code>{html.escape(p['code'])}</code></b></td>
<td class="balance-cell">{format_number(p['amount'])}</td>
<td>{p['used_count']} / {p['max_uses']}</td>
<td>{status}</td>
<td><span class="muted" style="font-size:12px">{p['created_at']}</span></td>
<td>
  <form class="amount-form" method="post" action="/admin/promos/toggle">
    <input type="hidden" name="pid" value="{p['id']}">
    <input type="hidden" name="active" value="{toggle_val}">
    <button class="btn btn-ghost btn-sm">{toggle_label}</button>
  </form>
  <form class="amount-form" method="post" action="/admin/promos/delete">
    <input type="hidden" name="pid" value="{p['id']}">
    <button class="btn btn-danger btn-sm">🗑 Удалить</button>
  </form>
</td>
</tr>"""


async def promos_page(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.HTTPFound("/admin/login")
    promos = db.list_promos()
    body = f"""
<div class="page-title">🎟 Промокоды</div>
<div class="page-sub">Игрок вводит код сообщением вида <code>#КОД</code> — и получает TON. Лимит активаций считается на всех игроков.</div>

<form class="card" method="post" action="/admin/promos/create">
  <h2>➕ Новый промокод</h2>
  <p class="hint">В коде только буквы, цифры, _ и - (до 32 символов). Игрок пишет <code>#КОД</code> в чат бота.</p>
  <div class="settings-grid">
    <div>{_field("code", "Код", "", "1", "1", "1", "Используйте заглавные буквы/цифры, например HELLO100", itype="text")}</div>
    <div>{_field("amount", "Сумма TON", 1000, "1", "1", "1000000000000", "Сколько TON получит игрок за активацию.")}</div>
    <div>{_field("max_uses", "Максимум активаций", 1, "1", "1", "1000000", "Сколько раз всего можно активировать промокод.")}</div>
  </div>
  <button class="btn btn-primary">🎟 Создать промокод</button>
</form>

<div class="card" style="padding:0">
  <div class="table-wrap"><table>
  <thead><tr><th>Код</th><th>Сумма</th><th>Активации</th><th>Статус</th><th>Создан</th><th>Действия</th></tr></thead>
  <tbody>
  {''.join(_promo_row(p) for p in promos) or '<tr><td colspan="6" style="text-align:center;padding:32px;color:#8a95b3">Пока нет промокодов</td></tr>'}
  </tbody>
  </table></div>
</div>"""
    return web.Response(text=_page("Промокоды", body, "promos"), content_type="text/html", charset="utf-8")


async def create_promo(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.HTTPFound("/admin/login")
    form = await request.post()
    code = (form.get("code", "") or "").strip()
    try:
        amount = int(float((form.get("amount", "") or "").replace(",", ".")))
        max_uses = int(float((form.get("max_uses", "") or "").replace(",", ".")))
    except (TypeError, ValueError):
        return web.HTTPFound("/admin/promos")
    if not code or len(code) > 32 or not all(
        ch.isalnum() or ch in "_-" for ch in code
    ) or not 1 <= amount <= 10 ** 12 or not 1 <= max_uses <= 10 ** 6:
        return web.HTTPFound("/admin/promos")
    db.create_promo(code, amount, max_uses)
    return web.HTTPFound("/admin/promos")


async def toggle_promo(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.HTTPFound("/admin/login")
    form = await request.post()
    pid = form.get("pid", "")
    active = form.get("active", "1") != "0"
    if pid.isdigit():
        db.toggle_promo(int(pid), active)
    return web.HTTPFound("/admin/promos")


async def delete_promo(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.HTTPFound("/admin/login")
    form = await request.post()
    pid = form.get("pid", "")
    if pid.isdigit():
        db.delete_promo(int(pid))
    return web.HTTPFound("/admin/promos")


# ---------- Логин ----------

def _login_form() -> str:
    return """
<div class="login-wrap">
  <div class="login-card">
    <div class="login-badge">⚙️</div>
    <h1>Вход в админку</h1>
    <div class="sub">Панель управления ботом</div>
    <form method="post" action="/admin/login">
      <label for="user">Логин</label>
      <input type="text" name="user" id="user" autocomplete="username" required>
      <label for="pass">Пароль</label>
      <input type="password" name="pass" id="pass" autocomplete="current-password" required>
      <button class="btn btn-primary">Войти</button>
    </form>
  </div>
</div>"""


async def login_page(request: web.Request) -> web.Response:
    if _auth_ok(request):
        return web.HTTPFound("/admin")
    body = _login_form()
    return web.Response(text=_page("Вход", body, ""), content_type="text/html", charset="utf-8")


async def login(request: web.Request) -> web.Response:
    ip = request.remote or "unknown"
    form = await request.post()
    user = form.get("user", "")
    password = form.get("pass", "")
    if not _check_rate_limit(ip):
        _log_admin("LOGIN_BLOCKED", ip, "rate limit exceeded")
        body = _flash("Слишком много попыток. Подождите минуту.", ok=False) + _login_form()
        return web.Response(text=_page("Вход", body, ""), content_type="text/html", charset="utf-8")
    if user == ADMIN_PANEL_USER and password == ADMIN_PANEL_PASSWORD:
        token = secrets.token_urlsafe(32)
        _sessions[token] = time.time() + SESSION_TTL
        _log_admin("LOGIN_OK", ip, f"user={user}")
        resp = web.HTTPFound("/admin")
        _set_cookie(resp, token)
        return resp
    _log_admin("LOGIN_FAIL", ip, f"user={user}")
    body = _flash("Неверный логин или пароль", ok=False) + _login_form()
    return web.Response(text=_page("Вход", body, ""), content_type="text/html", charset="utf-8")


async def logout(request: web.Request) -> web.Response:
    token = request.cookies.get("adm")
    if token:
        _sessions.pop(token, None)
    resp = web.HTTPFound("/admin/login")
    resp.del_cookie("adm")
    return resp


def register_admin_routes(app: web.Application) -> None:
    app.router.add_get("/admin", players_page)
    app.router.add_get("/admin/", players_page)
    app.router.add_get("/admin/login", login_page)
    app.router.add_post("/admin/login", login)
    app.router.add_post("/admin/give", give_coins)
    app.router.add_post("/admin/give_rubies", give_rubies)
    app.router.add_post("/admin/block", block_user)
    app.router.add_post("/admin/unblock", unblock_user)
    app.router.add_get("/admin/settings", settings_page)
    app.router.add_post("/admin/settings", save_settings)
    app.router.add_post("/admin/reset", reset_database)
    app.router.add_get("/admin/promos", promos_page)
    app.router.add_post("/admin/promos/create", create_promo)
    app.router.add_post("/admin/promos/toggle", toggle_promo)
    app.router.add_post("/admin/promos/delete", delete_promo)
    app.router.add_get("/admin/logout", logout)
