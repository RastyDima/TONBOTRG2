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
offline_seen=0
for attempt in $(seq 1 15); do
  adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
  if adb shell cat /sdcard/window.xml 2>/dev/null | grep -F 'Нет интернета' >/dev/null; then
    offline_seen=1
    break
  fi
  sleep 2
done
test "$offline_seen" -eq 1

adb shell cmd connectivity airplane-mode disable
recovered=0
for attempt in $(seq 1 20); do
  adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
  if ! adb shell cat /sdcard/window.xml 2>/dev/null | grep -F 'Нет интернета' >/dev/null; then
    recovered=1
    break
  fi
  sleep 2
done
test "$recovered" -eq 1
