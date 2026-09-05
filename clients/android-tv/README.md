# CapsStream Android TV Companion

A lightweight Leanback companion app for **CapsStream** designed for Android TV and Google TV devices (Chromecast with Google TV, Nvidia Shield, Fire TV, Sony Bravia, Xiaomi TV Box, etc.).

## Features

- **Leanback Launcher Integration**: Registers as a native Android TV app with banner on the home screen.
- **LAN Auto-Discovery**: Automatically discovers your CapsStream server on the local Wi-Fi / Ethernet network via UDP beacon or mDNS.
- **Full D-Pad Remote Navigation**: Native handling of directional buttons (Up, Down, Left, Right, Center/OK, Play/Pause, Fast Forward, Rewind, Back).
- **Hardware-Accelerated Playback**: Uses hardware decoding via Android WebView + HTML5 media pipeline for smooth, stutter-free playback.
- **No Crash / Zero Bloat**: No heavy JavaScript desktop runtimes or crash-prone toolchains.

## Project Structure

```
clients/android-tv/
├── build.gradle
├── settings.gradle
└── app/
    ├── build.gradle
    └── src/main/
        ├── AndroidManifest.xml
        ├── java/com/capsstream/tv/
        │   ├── MainActivity.kt
        │   └── DiscoveryHelper.kt
        └── res/
            ├── layout/activity_main.xml
            ├── values/
            │   ├── colors.xml
            │   ├── strings.xml
            │   └── styles.xml
            └── drawable/
```

## How to Build & Install

### Prerequisites
- Android Studio or Android SDK Command-Line Tools
- Target Android 7.0+ (API Level 24 to 34+)

### Build APK
```bash
cd clients/android-tv
./gradlew assembleRelease
```
The output APK will be in `app/build/outputs/apk/release/app-release-unsigned.apk`.

### Sideload to TV via ADB
```bash
adb connect <YOUR_ANDROID_TV_IP>:5555
adb install app/build/outputs/apk/debug/app-debug.apk
```
