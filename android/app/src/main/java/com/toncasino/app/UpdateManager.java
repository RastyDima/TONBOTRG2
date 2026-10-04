package com.toncasino.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.net.ssl.HttpsURLConnection;

final class UpdateManager {
    private static final String FEED = "https://raw.githubusercontent.com/RastyDima/TONBOTRG2/main/android/latest.json";
    private static final long CHECK_INTERVAL_MS = 24L * 60 * 60 * 1000;
    private static final long MAX_APK_BYTES = 200L * 1024 * 1024;
    private final Activity activity;
    private final SharedPreferences preferences;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final AtomicBoolean busy = new AtomicBoolean(false);
    private volatile ReadyUpdate ready;
    private volatile boolean closed;
    private boolean foreground;
    private boolean waitingForPermission;
    private int promptedVersion;

    private static final class ReadyUpdate {
        final int versionCode;
        final String versionName;
        final File file;

        ReadyUpdate(int versionCode, String versionName, File file) {
            this.versionCode = versionCode;
            this.versionName = versionName;
            this.file = file;
        }
    }

    UpdateManager(Activity activity) {
        this.activity = activity;
        this.preferences = activity.getSharedPreferences("android_updates", Activity.MODE_PRIVATE);
    }

    void onResume() {
        foreground = true;
        if (waitingForPermission) {
            waitingForPermission = false;
            if (canInstallPackages()) installReady();
            else message("Разрешение на установку не выдано.");
        } else {
            promptReady(false);
        }
        checkForUpdates(false);
    }

    void onPause() { foreground = false; }

    void close() {
        closed = true;
        executor.shutdownNow();
    }

    void checkForUpdates(boolean manual) {
        if (BuildConfig.DEBUG) {
            if (manual) message("Проверка обновлений доступна в подписанной версии приложения.");
            return;
        }
        if (ready != null && ready.versionCode > installedVersionCode()) {
            if (manual) promptReady(true);
            return;
        }
        if (!manual && System.currentTimeMillis() - preferences.getLong("last_check", 0) < CHECK_INTERVAL_MS)
            return;
        if (!busy.compareAndSet(false, true)) {
            if (manual) message("Проверка уже идёт.");
            return;
        }
        if (manual) message("Проверяем новую версию…");
        executor.execute(() -> {
            try {
                JSONObject feed = readFeed();
                int code = feed.getInt("version_code");
                String name = feed.getString("version_name");
                long size = feed.getLong("size_bytes");
                String hash = feed.getString("sha256").toLowerCase(Locale.ROOT);
                String downloadUrl = feed.getString("apk_url");
                if (code < 1 || name.length() > 40 || size < 1 || size > MAX_APK_BYTES
                        || !hash.matches("[0-9a-f]{64}") || !validDownloadUrl(downloadUrl))
                    throw new IllegalArgumentException("Invalid update manifest");
                if (code <= installedVersionCode()) {
                    preferences.edit().putLong("last_check", System.currentTimeMillis()).apply();
                    if (manual) message("У вас уже установлена последняя версия.");
                    return;
                }
                if (manual) message("Скачиваем версию " + name + "…");
                File apk = downloadAndVerify(code, size, hash, downloadUrl);
                ready = new ReadyUpdate(code, name, apk);
                activity.runOnUiThread(() -> promptReady(false));
            } catch (Exception error) {
                if (manual) message("Не удалось проверить или скачать обновление. Попробуйте позже.");
            } finally {
                busy.set(false);
            }
        });
    }

    private JSONObject readFeed() throws Exception {
        URL url = new URL(FEED + "?t=" + System.currentTimeMillis());
        HttpsURLConnection connection = (HttpsURLConnection) url.openConnection();
        connection.setConnectTimeout(10000);
        connection.setReadTimeout(10000);
        connection.setRequestProperty("Cache-Control", "no-cache");
        try {
            if (connection.getResponseCode() != 200) throw new IllegalStateException("Update feed unavailable");
            try (InputStream input = connection.getInputStream(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[4096];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    if (output.size() + count > 16384) throw new IllegalStateException("Update feed too large");
                    output.write(buffer, 0, count);
                }
                return new JSONObject(new String(output.toByteArray(), StandardCharsets.UTF_8));
            }
        } finally {
            connection.disconnect();
        }
    }

    private boolean validDownloadUrl(String value) {
        Uri uri = Uri.parse(value);
        return "https".equals(uri.getScheme()) && "github.com".equalsIgnoreCase(uri.getHost())
                && uri.getPath() != null
                && uri.getPath().startsWith("/RastyDima/TONBOTRG2/releases/download/")
                && uri.getPath().endsWith(".apk");
    }

    private File downloadAndVerify(int code, long size, String expectedHash, String downloadUrl) throws Exception {
        File temp = new File(activity.getCacheDir(), "update-" + code + ".download.apk");
        File apk = new File(activity.getCacheDir(), "update-" + code + ".apk");
        if (apk.isFile() && apk.length() == size) {
            MessageDigest cachedDigest = MessageDigest.getInstance("SHA-256");
            try (InputStream input = new java.io.FileInputStream(apk)) {
                byte[] buffer = new byte[32768];
                int count;
                while ((count = input.read(buffer)) != -1) cachedDigest.update(buffer, 0, count);
            }
            StringBuilder actual = new StringBuilder();
            for (byte b : cachedDigest.digest()) actual.append(String.format(Locale.ROOT, "%02x", b & 0xff));
            if (expectedHash.equals(actual.toString())) {
                verifyPackage(apk, code);
                return apk;
            }
        }
        if (apk.exists() && !apk.delete()) throw new IllegalStateException("Cannot remove old cached APK");
        HttpsURLConnection connection = (HttpsURLConnection) new URL(downloadUrl).openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        try {
            if (connection.getResponseCode() != 200) throw new IllegalStateException("APK unavailable");
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            long received = 0;
            try (InputStream input = connection.getInputStream(); OutputStream output = new FileOutputStream(temp)) {
                byte[] buffer = new byte[32768];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    received += count;
                    if (received > size || received > MAX_APK_BYTES) throw new IllegalStateException("APK too large");
                    output.write(buffer, 0, count);
                    digest.update(buffer, 0, count);
                }
            }
            StringBuilder actual = new StringBuilder();
            for (byte b : digest.digest()) actual.append(String.format(Locale.ROOT, "%02x", b & 0xff));
            if (received != size || !expectedHash.equals(actual.toString()))
                throw new IllegalStateException("APK checksum mismatch");
            verifyPackage(temp, code);
            if (apk.exists() && !apk.delete()) throw new IllegalStateException("Cannot replace cached APK");
            if (!temp.renameTo(apk)) throw new IllegalStateException("Cannot save APK");
            return apk;
        } finally {
            connection.disconnect();
            if (temp.exists()) temp.delete();
        }
    }

    private int installedVersionCode() {
        try {
            PackageInfo info = activity.getPackageManager().getPackageInfo(activity.getPackageName(), 0);
            return (int) (Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode);
        } catch (PackageManager.NameNotFoundException error) {
            return BuildConfig.VERSION_CODE;
        }
    }

    private Signature[] signatures(PackageInfo info) {
        return Build.VERSION.SDK_INT >= 28
                ? info.signingInfo.getApkContentsSigners() : info.signatures;
    }

    private void verifyPackage(File apk, int expectedCode) throws Exception {
        PackageManager manager = activity.getPackageManager();
        int flags = Build.VERSION.SDK_INT >= 28
                ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES;
        PackageInfo current = manager.getPackageInfo(activity.getPackageName(), flags);
        PackageInfo candidate = manager.getPackageArchiveInfo(apk.getAbsolutePath(), flags);
        if (candidate == null || !activity.getPackageName().equals(candidate.packageName)
                || (Build.VERSION.SDK_INT >= 28 ? candidate.getLongVersionCode() : candidate.versionCode) != expectedCode)
            throw new IllegalStateException("Wrong package or version");
        Signature[] oldSigners = signatures(current);
        Signature[] newSigners = signatures(candidate);
        if (oldSigners == null || newSigners == null || oldSigners.length != 1 || newSigners.length != 1
                || !MessageDigest.isEqual(oldSigners[0].toByteArray(), newSigners[0].toByteArray()))
            throw new IllegalStateException("Wrong signing certificate");
    }

    private void promptReady(boolean force) {
        ReadyUpdate update = ready;
        if (update == null || !foreground || closed || activity.isFinishing() || activity.isDestroyed()) return;
        if (!force && promptedVersion == update.versionCode) return;
        promptedVersion = update.versionCode;
        new AlertDialog.Builder(activity)
                .setTitle("Доступна версия " + update.versionName)
                .setMessage("Обновление скачано и проверено. Установить сейчас?")
                .setPositiveButton("Установить", (dialog, which) -> installReady())
                .setNegativeButton("Позже", null)
                .show();
    }

    private boolean canInstallPackages() {
        return Build.VERSION.SDK_INT < 26 || activity.getPackageManager().canRequestPackageInstalls();
    }

    private void installReady() {
        ReadyUpdate update = ready;
        if (update == null || !update.file.isFile()) return;
        if (!canInstallPackages()) {
            new AlertDialog.Builder(activity)
                    .setTitle("Разрешите установку")
                    .setMessage("Android должен разрешить установку обновлений из этого приложения.")
                    .setPositiveButton("Открыть настройки", (dialog, which) -> {
                        waitingForPermission = true;
                        Intent intent = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                Uri.parse("package:" + activity.getPackageName()));
                        activity.startActivity(intent);
                    })
                    .setNegativeButton("Отмена", null)
                    .show();
            return;
        }
        executor.execute(() -> {
            try {
                verifyPackage(update.file, update.versionCode);
                PackageInstaller installer = activity.getPackageManager().getPackageInstaller();
                PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(
                        PackageInstaller.SessionParams.MODE_FULL_INSTALL);
                params.setAppPackageName(activity.getPackageName());
                if (Build.VERSION.SDK_INT >= 31)
                    params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED);
                int sessionId = installer.createSession(params);
                boolean committed = false;
                try {
                    try (PackageInstaller.Session session = installer.openSession(sessionId)) {
                        try (InputStream input = new java.io.FileInputStream(update.file);
                             OutputStream output = session.openWrite("base.apk", 0, update.file.length())) {
                            byte[] buffer = new byte[32768];
                            int count;
                            while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
                            session.fsync(output);
                        }
                        Intent status = new Intent(activity, UpdateInstallReceiver.class);
                        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
                        if (Build.VERSION.SDK_INT >= 31) flags |= PendingIntent.FLAG_MUTABLE;
                        PendingIntent pending = PendingIntent.getBroadcast(activity, update.versionCode, status, flags);
                        session.commit(pending.getIntentSender());
                        committed = true;
                    }
                } finally {
                    if (!committed) installer.abandonSession(sessionId);
                }
            } catch (Exception error) {
                message("Не удалось установить обновление. Попробуйте позже.");
            }
        });
    }

    private void message(String value) {
        if (!closed) activity.runOnUiThread(() -> Toast.makeText(activity, value, Toast.LENGTH_LONG).show());
    }
}
