package com.toncasino.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.KeyguardManager;
import android.content.Intent;
import android.graphics.Color;
import android.hardware.biometrics.BiometricManager;
import android.hardware.biometrics.BiometricPrompt;
import android.os.Build;
import android.os.CancellationSignal;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/** Optional device authentication. Never store or handle the user's PIN. */
final class DeviceLockController {
    private static final int REQUEST_UNLOCK = 4801;
    private final Activity activity;
    private final LinearLayout overlay;
    private final Runnable changed;
    private boolean needsUnlock, authenticating, enabling, closed;
    private CancellationSignal cancellation;

    DeviceLockController(Activity activity, FrameLayout root, Runnable changed) {
        this.activity = activity;
        this.changed = changed;
        overlay = new LinearLayout(activity);
        overlay.setOrientation(LinearLayout.VERTICAL);
        overlay.setGravity(Gravity.CENTER);
        overlay.setBackgroundColor(Color.rgb(12, 22, 29));
        overlay.setPadding(40, 40, 40, 40);
        TextView title = new TextView(activity);
        title.setText("TON CASINO\nПриложение защищено");
        title.setTextSize(24);
        title.setTextColor(Color.WHITE);
        title.setGravity(Gravity.CENTER);
        overlay.addView(title);
        Button unlock = new Button(activity);
        unlock.setText("Разблокировать");
        unlock.setAllCaps(false);
        unlock.setOnClickListener(view -> authenticate());
        overlay.addView(unlock);
        overlay.setClickable(true);
        root.addView(overlay, new FrameLayout.LayoutParams(-1, -1));
        needsUnlock = isEnabled();
        updateVisibility();
    }

    boolean isEnabled() {
        return activity.getSharedPreferences("device_security", 0).getBoolean("enabled", false);
    }

    boolean isLocked() { return needsUnlock; }

    private void updateVisibility() {
        overlay.setVisibility(needsUnlock ? View.VISIBLE : View.GONE);
        if (isEnabled() || enabling) activity.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        else activity.getWindow().clearFlags(WindowManager.LayoutParams.FLAG_SECURE);
    }

    void toggle() {
        if (authenticating || needsUnlock) return;
        if (isEnabled()) {
            new AlertDialog.Builder(activity).setTitle("Защита входа")
                    .setMessage("Отключить подтверждение входа на этом устройстве?")
                    .setNegativeButton("Оставить", null)
                    .setPositiveButton("Отключить", (dialog, which) -> {
                        activity.getSharedPreferences("device_security", 0).edit().putBoolean("enabled", false).apply();
                        needsUnlock = false;
                        updateVisibility();
                        changed.run();
                    }).show();
            return;
        }
        KeyguardManager keyguard = (KeyguardManager) activity.getSystemService(Activity.KEYGUARD_SERVICE);
        if (!keyguard.isDeviceSecure()) {
            Toast.makeText(activity, "Сначала настройте PIN или пароль в настройках телефона.", Toast.LENGTH_LONG).show();
            return;
        }
        enabling = true;
        needsUnlock = true;
        updateVisibility();
        authenticate();
    }

    private void authenticate() {
        if (authenticating || closed) return;
        authenticating = true;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            cancellation = new CancellationSignal();
            new BiometricPrompt.Builder(activity).setTitle("Вход в TON Casino")
                    .setSubtitle("Подтвердите вход отпечатком, лицом или кодом телефона")
                    .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG
                            | BiometricManager.Authenticators.DEVICE_CREDENTIAL)
                    .build().authenticate(cancellation, activity.getMainExecutor(), new BiometricPrompt.AuthenticationCallback() {
                        @Override public void onAuthenticationSucceeded(BiometricPrompt.AuthenticationResult result) { finish(true); }
                        @Override public void onAuthenticationError(int code, CharSequence message) { finish(false); }
                    });
        } else {
            KeyguardManager keyguard = (KeyguardManager) activity.getSystemService(Activity.KEYGUARD_SERVICE);
            Intent intent = keyguard.createConfirmDeviceCredentialIntent("Вход в TON Casino", "Введите код телефона");
            if (intent == null) finish(false);
            else activity.startActivityForResult(intent, REQUEST_UNLOCK);
        }
    }

    private void finish(boolean success) {
        if (closed) return;
        authenticating = false;
        if (success && enabling) activity.getSharedPreferences("device_security", 0).edit().putBoolean("enabled", true).apply();
        if (success || enabling) needsUnlock = false;
        enabling = false;
        updateVisibility();
        changed.run();
    }

    boolean onActivityResult(int requestCode, int resultCode) {
        if (requestCode != REQUEST_UNLOCK) return false;
        finish(resultCode == Activity.RESULT_OK);
        return true;
    }

    void onResume() {
        if (isEnabled() && needsUnlock) authenticate();
    }

    void onPause() {
        if (isEnabled() && !authenticating) {
            needsUnlock = true;
            updateVisibility();
        }
    }

    void close() {
        closed = true;
        if (cancellation != null) cancellation.cancel();
    }
}
