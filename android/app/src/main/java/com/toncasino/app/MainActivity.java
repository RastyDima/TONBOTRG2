package com.toncasino.app;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.ValueCallback;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private WebView webView;
    private ProgressBar loading;
    private LinearLayout errorPanel;
    private TextView errorTitle;
    private TextView errorMessage;
    private ConnectivityManager connectivity;
    private ConnectivityManager.NetworkCallback networkCallback;
    private UpdateManager updateManager;
    private DeviceLockController deviceLock;
    private ValueCallback<Uri[]> filePicker;
    private static final int REQUEST_AVATAR = 4802;
    private boolean pageFailed;
    private Boolean lastNetworkOnline;
    private final Handler networkHandler = new Handler(Looper.getMainLooper());
    private final Runnable networkPoll = new Runnable() {
        @Override public void run() {
            if (webView != null) onNetworkChanged();
            networkHandler.postDelayed(this, 3000);
        }
    };

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private boolean hasInternet() {
        Network network = connectivity.getActiveNetwork();
        NetworkCapabilities capabilities = connectivity.getNetworkCapabilities(network);
        return capabilities != null && capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                && capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED);
    }

    private void showFailure(boolean offline) {
        pageFailed = true;
        loading.setVisibility(View.GONE);
        webView.setVisibility(View.INVISIBLE);
        errorTitle.setText(offline ? "Нет интернета" : "Сервер недоступен");
        errorMessage.setText(offline
                ? "Проверьте подключение. Когда сеть вернётся, мы попробуем снова."
                : "Не удалось открыть игру. Повторите загрузку чуть позже.");
        errorPanel.setVisibility(View.VISIBLE);
    }

    private void retryPage() {
        if (!hasInternet()) {
            showFailure(true);
            return;
        }
        pageFailed = false;
        errorPanel.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        loading.setVisibility(View.VISIBLE);
        if (webView.getUrl() == null) webView.loadUrl(BuildConfig.SERVER_URL + "/app/?client=android");
        else webView.reload();
        updateManager.checkForUpdates(false);
    }

    private void onNetworkChanged() {
        boolean online = hasInternet();
        if (lastNetworkOnline == null || lastNetworkOnline != online) {
            Log.i("TonCasinoNetwork", "validated network: " + online);
            lastNetworkOnline = online;
        }
        if (!online) showFailure(true);
        else if (pageFailed && "Нет интернета".contentEquals(errorTitle.getText())) retryPage();
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        connectivity = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(18, 13, 33));
        webView = new WebView(this);
        webView.setBackgroundColor(Color.rgb(18, 13, 33));
        root.addView(webView, new FrameLayout.LayoutParams(-1, -1));
        loading = new ProgressBar(this);
        FrameLayout.LayoutParams progressLayout = new FrameLayout.LayoutParams(dp(54), dp(54), Gravity.CENTER);
        root.addView(loading, progressLayout);

        errorPanel = new LinearLayout(this);
        errorPanel.setOrientation(LinearLayout.VERTICAL);
        errorPanel.setGravity(Gravity.CENTER);
        errorPanel.setPadding(dp(26), dp(30), dp(26), dp(30));
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.rgb(30, 37, 57));
        background.setCornerRadius(dp(22));
        background.setStroke(dp(1), Color.rgb(65, 111, 112));
        errorPanel.setBackground(background);
        FrameLayout.LayoutParams panelLayout = new FrameLayout.LayoutParams(-1, -2, Gravity.CENTER);
        panelLayout.setMargins(dp(24), 0, dp(24), 0);
        root.addView(errorPanel, panelLayout);
        TextView symbol = new TextView(this);
        symbol.setText("✦");
        symbol.setTextColor(Color.rgb(116, 227, 193));
        symbol.setTextSize(38);
        errorPanel.addView(symbol);
        errorTitle = new TextView(this);
        errorTitle.setTextColor(Color.WHITE);
        errorTitle.setTextSize(23);
        errorTitle.setTypeface(null, Typeface.BOLD);
        errorTitle.setGravity(Gravity.CENTER);
        errorPanel.addView(errorTitle);
        errorMessage = new TextView(this);
        errorMessage.setTextColor(Color.rgb(169, 188, 196));
        errorMessage.setTextSize(14);
        errorMessage.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams messageLayout = new LinearLayout.LayoutParams(-1, -2);
        messageLayout.topMargin = dp(10);
        errorPanel.addView(errorMessage, messageLayout);
        Button retry = new Button(this);
        retry.setText("Повторить");
        retry.setTextColor(Color.WHITE);
        retry.setAllCaps(false);
        retry.setBackgroundTintList(android.content.res.ColorStateList.valueOf(Color.rgb(36, 115, 109)));
        LinearLayout.LayoutParams retryLayout = new LinearLayout.LayoutParams(-1, dp(50));
        retryLayout.topMargin = dp(22);
        errorPanel.addView(retry, retryLayout);
        retry.setOnClickListener(view -> retryPage());
        errorPanel.setVisibility(View.GONE);
        setContentView(root);
        deviceLock = new DeviceLockController(this, root, this::publishNativeSettings);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setMediaPlaybackRequiresUserGesture(true);
        String model = (Build.MANUFACTURER + " " + Build.MODEL).replaceAll("[^\\p{L}\\p{N} ._-]", " ")
                .replaceAll("\\s+", " ").trim();
        if (model.length() > 56) model = model.substring(0, 56);
        settings.setUserAgentString(settings.getUserAgentString() + " TonCasinoAndroid/"
                + BuildConfig.VERSION_NAME + " (" + model + "; Android " + Build.VERSION.RELEASE + ")");
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) settings.setSafeBrowsingEnabled(true);

        updateManager = new UpdateManager(this);
        Uri server = Uri.parse(BuildConfig.SERVER_URL);
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (!request.isForMainFrame()) return false;
                Uri target = request.getUrl();
                if ("toncasino".equals(target.getScheme()) && "check-update".equals(target.getHost())) {
                    updateManager.checkForUpdates(true);
                    return true;
                }
                if ("toncasino".equals(target.getScheme()) && "device-lock".equals(target.getHost())) {
                    deviceLock.toggle();
                    return true;
                }
                if ("https".equals(target.getScheme())
                        && server.getHost().equalsIgnoreCase(target.getHost())
                        && server.getPort() == target.getPort()) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, target));
                } catch (ActivityNotFoundException ignored) {
                    // No app can handle the external link.
                }
                return true;
            }

            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                if (!pageFailed) loading.setVisibility(View.VISIBLE);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) showFailure(!hasInternet());
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                            WebResourceResponse response) {
                if (request.isForMainFrame() && response.getStatusCode() >= 400)
                    showFailure(!hasInternet());
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                loading.setVisibility(View.GONE);
                if (!pageFailed) errorPanel.setVisibility(View.GONE);
                publishNativeSettings();
            }
        });
        webView.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                                       FileChooserParams params) {
                if (filePicker != null) filePicker.onReceiveValue(null);
                filePicker = callback;
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("image/*")
                        .addCategory(Intent.CATEGORY_OPENABLE)
                        .putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"image/jpeg", "image/png", "image/gif", "image/webp"})
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                try { startActivityForResult(intent, REQUEST_AVATAR); }
                catch (ActivityNotFoundException error) { filePicker.onReceiveValue(null); filePicker = null; }
                return true;
            }
        });
        if (savedInstanceState != null) webView.restoreState(savedInstanceState);
        else if (hasInternet()) webView.loadUrl(BuildConfig.SERVER_URL + "/app/?client=android");
        else showFailure(true);

        networkCallback = new ConnectivityManager.NetworkCallback() {
            @Override public void onAvailable(Network network) { runOnUiThread(() -> onNetworkChanged()); }
            @Override public void onLost(Network network) { runOnUiThread(() -> onNetworkChanged()); }
            @Override public void onCapabilitiesChanged(Network network, NetworkCapabilities capabilities) {
                runOnUiThread(() -> onNetworkChanged());
            }
        };
        connectivity.registerDefaultNetworkCallback(networkCallback);
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        webView.saveState(outState);
        super.onSaveInstanceState(outState);
    }

    @Override
    public void onBackPressed() {
        if (deviceLock != null && deviceLock.isLocked()) finish();
        else if (webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) webView.onResume();
        if (deviceLock != null) deviceLock.onResume();
        if (updateManager != null) updateManager.onResume();
        if (errorPanel != null) {
            networkHandler.removeCallbacks(networkPoll);
            networkHandler.post(networkPoll);
        }
    }

    @Override
    protected void onPause() {
        if (deviceLock != null) deviceLock.onPause();
        networkHandler.removeCallbacks(networkPoll);
        if (updateManager != null) updateManager.onPause();
        if (webView != null) webView.onPause();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        if (deviceLock != null) deviceLock.close();
        if (filePicker != null) { filePicker.onReceiveValue(null); filePicker = null; }
        if (networkCallback != null) connectivity.unregisterNetworkCallback(networkCallback);
        if (updateManager != null) updateManager.close();
        if (webView != null) {
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    private void publishNativeSettings() {
        if (webView == null || deviceLock == null) return;
        webView.evaluateJavascript("window.__tonNativeSettings={device_lock:" + deviceLock.isEnabled()
                + "};window.dispatchEvent(new CustomEvent('ton-native-settings',{detail:window.__tonNativeSettings}));", null);
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (deviceLock != null && deviceLock.onActivityResult(requestCode, resultCode)) return;
        if (requestCode == REQUEST_AVATAR && filePicker != null) {
            Uri[] uris = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
            if (uris != null) for (Uri uri : uris) if (!"content".equals(uri.getScheme())) { uris = null; break; }
            filePicker.onReceiveValue(uris);
            filePicker = null;
        }
    }
}
