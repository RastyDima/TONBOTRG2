# Player experience

The bot, WebApp and Android WebView share player settings, bonus claims,
reminders, transaction history and avatars in the existing database.

## WebApp and Android

- Home: balance, bonus availability, favorite games and an unfinished-game shortcut.
- Bonuses: daily and weekly claims and explicit Telegram reminder preferences.
- History: filters, snapshot pagination, refresh and an authenticated CSV export
  of the most recent 1000 transactions. Android opens the bot's CSV export.
- Statistics: 7/30/90-day balance graph and completed-game results.
- Rankings: all-time maximum balance, XP and wins; calendar-week and calendar-month
  wins/game counts. Hidden and blocked users are omitted; your position is computed
  across the entire eligible ranking.
- Profile: description (200 characters), favorite games, saved bet, light/dark theme,
  ranking privacy and a custom photo or animated GIF.
- Games: Mines and Coinflip run in the WebApp; the remaining games open in Telegram.

Avatars are authenticated binary uploads stored in SQLite/PG, rather than Render's
ephemeral filesystem. JPEG, PNG, GIF and WebP are validated with Pillow and retain
their original bytes. Limits: 2 MiB, 4 million pixels per frame, 120 frames and
40 million pixels across the image. Resetting returns to the Telegram photo.
For animated images sent to the bot, send the original file: Telegram's compressed
animation messages can be MP4 and are not accepted as image uploads.

Coinflip chooses its outcome on the server and settles the balance, game, stats,
XP, referral commission and receipt in one database transaction. A 32-character
random request ID is scoped to the authenticated user. Repeating the ID with the
same bet/choice returns the original result; changing it returns a conflict.
The browser retains unanswered requests in session storage until the result is
resolved, including after navigation. An active game blocks a fresh Coinflip.

Android 0.4.0 adds the system document picker and optional device authentication.
The PIN is handled by Android and never sent to the server. API 30+ supports strong
biometrics or device credentials; API 24–29 uses device credentials. An enabled
lock covers the WebView on return and prevents screenshots/recents previews.
The user enables it in Profile and can disconnect lost devices through the bot.

## Bot commands

| Command | Behavior |
| --- | --- |
| /settings | Profile settings and shortcuts |
| /avatar | Upload a custom photo or GIF file |
| /bio | Change description; a hyphen clears it |
| /bet | Save the default TON stake |
| /favorites | Manage favorites and open games |
| /resume | Show the current round without placing another stake |
| /stats | Personal completed-game summary for 30 days |
| /devices | List/revoke your Android sessions in private chat |
| /history_export | Download your last 1000 transactions in private chat |

Existing /daily, /weekly, /reminders, /history and game commands continue
to use the same account. Editing profile fields does not cancel an active game.

## Verification

GitHub Actions runs SQLite and real PostgreSQL financial/concurrency checks,
authenticated HTTP tests, bot shortcut/ownership regressions and Playwright
journeys using the actual React/JSX and CSS. The webapp-previews artifact contains
360px screenshots of the new screens. Android PR checks compile and lint the app;
the existing main-branch release workflow builds a signed APK and runs its emulator
smoke check. Biometrics must also be exercised on a physical enrolled device.
