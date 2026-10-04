# TON Casino for Android

This Android app opens the project's WebApp in a locked-down WebView. It uses the
same server, Telegram user ID, balance, profile, shop and Mines game as the bot.
The bot confirms a one-time login code; no bot token or database password is
packaged in the APK.

Install the [latest signed Android APK](https://github.com/RastyDima/TONBOTRG2/releases/latest/download/ton-casino.apk).
The APK connects to the current Render service. GitHub Actions verifies its
signature and installs it on an Android 15 emulator before publishing it.

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
The code expires after ten minutes and can be used once. The app shows the
remaining time. The mobile session lasts thirty days; connected Android devices
can be viewed and disconnected from the profile in either the app or Telegram
Mini App.

Version 0.3 uses the same private signing key as 0.2, so it can be installed
over 0.2 without losing app data. Existing users must confirm their Telegram
account once after this update to create a revocable device session. Version
0.3 must be installed manually; subsequent signed releases are checked when
the app opens, downloaded automatically, and offered for installation through
Android's system installer. Android may require allowing this app to install
updates. The feed at `android/latest.json` is published only after the signed
APK passes the Android 15 smoke test. Every release must increase
`versionCode`; replacing an APK with the same code does not publish an update.
This APK is distributed directly and has not been prepared for Google Play.
