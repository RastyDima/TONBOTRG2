#!/usr/bin/env bash
set -euo pipefail

apk="$GITHUB_WORKSPACE/android/app/build/outputs/apk/release/app-release.apk"
old_apk="$GITHUB_WORKSPACE/android/ton-casino-0.2.apk"
adb install "$old_apk"
adb shell dumpsys package com.toncasino.app | grep 'versionCode=2 ' >/dev/null
adb install -r "$apk"
adb shell dumpsys package com.toncasino.app | grep "versionCode=${ANDROID_VERSION_CODE} " >/dev/null
adb shell pm path com.toncasino.app
adb shell am start -W -n com.toncasino.app/.MainActivity
sleep 5
adb shell pidof com.toncasino.app

adb shell cmd connectivity airplane-mode enable
adb shell svc wifi disable
adb shell svc data disable
echo "Airplane mode: $(adb shell settings get global airplane_mode_on)"
offline_seen=0
for attempt in $(seq 1 15); do
  adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
  if adb shell cat /sdcard/window.xml 2>/dev/null | grep -F 'Нет интернета' >/dev/null; then
    offline_seen=1
    break
  fi
  sleep 2
done
echo "Offline screen observed: $offline_seen"
if [ "$offline_seen" -ne 1 ]; then
  adb shell pidof com.toncasino.app || true
  adb shell dumpsys activity activities | grep -E 'mResumed|topResumed' | head -n 8 || true
  adb shell dumpsys connectivity | grep -E 'VALIDATED|DefaultNetwork' | head -n 12 || true
  adb shell uiautomator dump /sdcard/window.xml || true
  adb shell cat /sdcard/window.xml 2>/dev/null | grep -oE 'text="(Нет интернета|Сервер недоступен|Повторить)"' || true
  adb pull /sdcard/window.xml "$GITHUB_WORKSPACE/android/offline-failure.xml" >/dev/null 2>&1 || true
  adb exec-out screencap -p > "$GITHUB_WORKSPACE/android/offline-failure.png" || true
  adb logcat -d -s AndroidRuntime:E | tail -n 50 || true
  adb logcat -d -s TonCasinoNetwork:I | tail -n 20 || true
fi
test "$offline_seen" -eq 1

adb shell cmd connectivity airplane-mode disable
adb shell svc wifi enable
adb shell svc data enable
recovered=0
for attempt in $(seq 1 20); do
  adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
  if ! adb shell cat /sdcard/window.xml 2>/dev/null | grep -F 'Нет интернета' >/dev/null; then
    recovered=1
    break
  fi
  sleep 2
done
echo "Recovery observed: $recovered"
test "$recovered" -eq 1
