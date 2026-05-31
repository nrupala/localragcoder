# localRAGcoder — Cross-Platform Deployment Guide
#
# Build targets:
#   Android APK   → Chaquopy (Python-in-Android)
#   iOS IPA       → PythonKit / Swift wrapper
#   PWA           → Progressive Web App (browser + installable)
#   Windows EXE   → PyInstaller (self-contained)
#   Linux AppImage → PyInstaller / AppImageTool
#
# CI: .github/workflows/build.yml  (GitHub Actions)

# ─────────────────────────────────────────────────────────────
# ANDROID (APK)
# ─────────────────────────────────────────────────────────────
.PHONY: android
android:
	cd packaging/android && ./gradlew assembleRelease
	@echo "APK at: packaging/android/app/build/outputs/apk/release/"

# ─────────────────────────────────────────────────────────────
# iOS (IPA) — macOS only (Xcode + PythonKit)
# ─────────────────────────────────────────────────────────────
.PHONY: ios
ios:
	cd packaging/ios && xcodebuild -project localRAGcoder.xcodeproj \
	  -scheme localRAGcoder -configuration Release archive \
	  -archivePath build/localRAGcoder.xcarchive
	@echo "IPA requires Xcode Organizer export"

# ─────────────────────────────────────────────────────────────
# PWA
# ─────────────────────────────────────────────────────────────
.PHONY: pwa
pwa:
	cd packaging/pwa && npm install && npm run build
	@echo "PWA at: packaging/pwa/dist/"

# ─────────────────────────────────────────────────────────────
# WINDOWS (EXE)
# ─────────────────────────────────────────────────────────────
.PHONY: windows
windows:
	pip install pyinstaller
	pyinstaller --onefile --name localRAGcoder --distpath packaging/windows/dist \
	  --add-data "engine:engine" run_tests.py
	@echo "EXE at: packaging/windows/dist/localRAGcoder.exe"

# ─────────────────────────────────────────────────────────────
# LINUX (AppImage)
# ─────────────────────────────────────────────────────────────
.PHONY: linux
linux:
	pip install pyinstaller
	pyinstaller --onefile --name localRAGcoder --distpath packaging/linux/dist \
	  --add-data "engine:engine" run_tests.py
	@echo "Binary at: packaging/linux/dist/localRAGcoder"

# ─────────────────────────────────────────────────────────────
# ALL platforms (requires appropriate host OS for each)
# ─────────────────────────────────────────────────────────────
.PHONY: all
all: pwa windows linux

# ─────────────────────────────────────────────────────────────
# Clean build artifacts
# ─────────────────────────────────────────────────────────────
.PHONY: clean
clean:
	rm -rf packaging/*/dist packaging/*/build packaging/*/__pycache__
	rm -rf packaging/android/app/build
	rm -rf packaging/ios/build
