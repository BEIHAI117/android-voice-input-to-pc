#!/usr/bin/env bash
# Build the PhoneMic Android APK without Android Studio.
#
# Prerequisites (installed by the agent into D:\android-toolchain):
#   - Temurin JDK 17
#   - Android cmdline-tools + platform-tools + platforms;android-35 + build-tools;35.0.0
#   - Gradle 8.9
#
# Usage:
#   ./build-apk.sh            # release APK (signed with the project keystore)
#   ./build-apk.sh debug      # debug APK
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TC="${TOOLCHAIN_DIR:-/d/android-toolchain}"

export JAVA_HOME="$( (ls -d "$TC"/jdk*/ 2>/dev/null || true) | head -1 | sed 's:/*$::')"
if [[ -z "${JAVA_HOME}" || ! -x "$JAVA_HOME/bin/java.exe" ]]; then
  echo "JDK not found under $TC — run the toolchain setup first." >&2
  exit 1
fi
# Gradle lands in $TC/gradle/bin or $TC/gradle-<version>/bin depending on how
# the archive was unpacked.
GRADLE_BIN="$( (ls -d "$TC"/gradle/bin "$TC"/gradle-*/bin 2>/dev/null || true) | head -1)"
if [[ -z "$GRADLE_BIN" ]]; then
  echo "Gradle not found under $TC — run the toolchain setup first." >&2
  exit 1
fi
export ANDROID_HOME="$TC/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$JAVA_HOME/bin:$GRADLE_BIN:$ANDROID_HOME/platform-tools:$PATH"

# Java .properties treats backslash as an escape character (\t becomes a tab!),
# so write the SDK path with forward slashes — Gradle accepts them on Windows.
printf 'sdk.dir=%s\n' "$(cygpath -m "$ANDROID_HOME")" > "$ROOT/android/local.properties"

echo "JAVA_HOME   = $JAVA_HOME"
echo "ANDROID_HOME= $ANDROID_HOME"
java -version 2>&1 | head -1

cd "$ROOT/android"
if [[ "${1:-release}" == "debug" ]]; then
  gradle --no-daemon :app:assembleDebug
  OUT=app/build/outputs/apk/debug/app-debug.apk
else
  if [[ ! -f "$ROOT/android/phonemic-release.keystore" ]]; then
    echo "missing android/phonemic-release.keystore" >&2
    exit 1
  fi
  gradle --no-daemon :app:assembleRelease
  OUT=app/build/outputs/apk/release/app-release.apk
fi

echo
echo "APK -> $ROOT/android/$OUT"
ls -lh "$ROOT/android/$OUT"
