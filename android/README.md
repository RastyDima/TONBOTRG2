# TON Casino for Android

This Android app opens the project's WebApp in a locked-down WebView. It uses the
same server, Telegram user ID, balance, profile, shop and Mines game as the bot.
The bot confirms a one-time login code; no bot token or database password is
packaged in the APK.

Install [ton-casino-0.2.apk](ton-casino-0.2.apk). The APK connects to the
current Render service. GitHub Actions verifies its signature and installs it
on an Android 15 emulator before publishing it.

Build a debug APK with Android SDK platform 34 and JDK 17 or 21. The wrapper
downloads Gradle 8.5 automatically:

```powershell
cd android
./gradlew.bat assembleDebug
```

The output is `app/build/outputs/apk/debug/app-debug.apk`. To build the signed
release, provide `ANDROID_RELEASE_KEYSTORE` and `ANDROID_RELEASE_PASSWORD`
from the private [signing backup](signing/README.md), then run `assembleRelease`.
The default server
is `https://tonrgminer2026x.onrender.com`. To use another HTTPS origin:

```powershell
./gradlew.bat assembleDebug -PserverUrl=https://your-service.example
```

Install the APK, open it, then tap **Open bot and confirm**. The bot handles
`/start app_<code>` and the app picks up the authenticated account. If a
Telegram deep link is unavailable, send `/connect <code>` to the bot manually.
The code expires after ten minutes and can be used once. The mobile session
lasts thirty days; signing in again uses a new code.

Version 0.2 uses a stable private signing key so later APKs can update it.
If you installed the previous debug-signed test APK, uninstall it once before
installing 0.2. This APK is distributed directly and has not been prepared for
Google Play.
