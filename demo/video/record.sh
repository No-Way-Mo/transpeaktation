#!/usr/bin/env bash
# Films the iOS app for the pitch video: boots a dedicated simulator on camera, then ios/Tour taps through the app.
# Out: footage/sim.mov (the raw recording) + footage/marks.json (seconds into sim.mov of each tour beat, for pitch.html).
# Needs Xcode + xcodegen. The app loads WEB_APP_URL (default: the deployed site, so no local web/api needed).
set -euo pipefail
cd "$(dirname "$0")"
WEB_APP_URL=${WEB_APP_URL:-https://yowaymo.us}
DEVICE=${DEVICE:-transPEAKtation pitch}       # created on first run, erased every run: clean home screen
MODEL=${MODEL:-iPhone 17 Pro}
BUILD=.build
mkdir -p footage

UDID=$(xcrun simctl list devices -j | python3 -c "import json,sys; n=sys.argv[1]; print(next((d['udid'] for r in json.load(sys.stdin)['devices'].values() for d in r if d['name']==n), ''))" "$DEVICE")
[ -n "$UDID" ] || UDID=$(xcrun simctl create "$DEVICE" "$MODEL")
xcrun simctl shutdown "$UDID" 2>/dev/null || true
xcrun simctl erase "$UDID"

(cd ios && xcodegen -q)
xcodebuild -project ios/TranspeaktationTour.xcodeproj -scheme Tour -destination "id=$UDID" -derivedDataPath "$BUILD" \
  WEB_APP_URL="$WEB_APP_URL" build-for-testing -quiet

# Camera rolling from boot.
open -a Simulator --args -CurrentDeviceUDID "$UDID"
xcrun simctl boot "$UDID"
xcrun simctl io "$UDID" recordVideo --codec=h264 --force footage/sim.mov 2> footage/record.log &
REC=$!
until grep -q "Recording started" footage/record.log 2>/dev/null; do sleep 0.05; done
T0=$(python3 -c 'import time; print(time.time())')
trap 'kill -INT $REC 2>/dev/null; wait $REC 2>/dev/null || true' EXIT

xcrun simctl bootstatus "$UDID" -b >/dev/null
xcrun simctl ui "$UDID" appearance light
xcrun simctl status_bar "$UDID" override --batteryState charged --batteryLevel 100 --cellularBars 4 --wifiBars 3
APP=$(ls -d "$BUILD"/Build/Products/Debug-iphonesimulator/Transpeaktation.app)
xcrun simctl install "$UDID" "$APP"
xcrun simctl privacy "$UDID" grant microphone app.transpeaktation.ios   # voice beat: listening state, no prompt
xcrun simctl privacy "$UDID" grant location app.transpeaktation.ios

xcodebuild -project ios/TranspeaktationTour.xcodeproj -scheme Tour -destination "id=$UDID" -derivedDataPath "$BUILD" \
  WEB_APP_URL="$WEB_APP_URL" test-without-building -only-testing:Tour/Tour/testTour > footage/tour.log 2>&1 || true
sleep 1
kill -INT $REC; wait $REC 2>/dev/null || true; trap - EXIT

echo "$T0" > footage/t0
python3 marks.py
grep -q "Test Suite 'Tour' passed" footage/tour.log || { echo "tour failed: see footage/tour.log" >&2; exit 1; }
echo "wrote footage/sim.mov + footage/marks.json"
