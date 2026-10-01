#!/usr/bin/env bash
set -euo pipefail

apk="$GITHUB_WORKSPACE/android/app/build/outputs/apk/release/app-release.apk"
adb install -r "$apk"
adb shell pm path com.toncasino.app
adb shell am start -W -n com.toncasino.app/.MainActivity
sleep 5
adb shell pidof com.toncasino.app
