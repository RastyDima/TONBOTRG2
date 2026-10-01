# Android signing key

The local `ton-casino-release.p12` and `credentials.txt` in this directory are
ignored by Git. Back up both files privately. GitHub Actions has encrypted
copies in `ANDROID_RELEASE_KEYSTORE_BASE64` and `ANDROID_RELEASE_PASSWORD`.
The same key must sign future APK updates. Never commit or share either file.

The previous debug-signed test APK cannot be updated in place with this key;
uninstall that test build once before installing the signed release.
