# TON Casino for Android (test APK)

This Android app opens the project's WebApp in a locked-down WebView. It uses the
same server, Telegram user ID, balance, profile, shop and Mines game as the bot.
The bot confirms a one-time login code; no bot token or database password is
packaged in the APK.

For a quick test, install [ton-casino-test-0.1.apk](ton-casino-test-0.1.apk).
It connects to the current Render service by default.

Build a debug APK with Android SDK platform 34 and JDK 17 or 21. The wrapper
downloads Gradle 8.5 automatically:

```powershell
cd android
./gradlew.bat assembleDebug
```

The output is `app/build/outputs/apk/debug/app-debug.apk`. The default server
is `https://tonrgminer2026x.onrender.com`. To use another HTTPS origin:

```powershell
./gradlew.bat assembleDebug -PserverUrl=https://your-service.example
```

Install the APK, open it, then tap **Open bot and confirm**. The bot handles
`/start app_<code>` and the app picks up the authenticated account. If a
Telegram deep link is unavailable, send `/connect <code>` to the bot manually.
The code expires after ten minutes and can be used once. The mobile session
lasts thirty days; signing in again uses a new code.

This is a test build signed with the local Android debug key. It is not a
release build for Google Play. A later test build signed with another debug
key may require removing the old test app before installation.
