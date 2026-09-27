# Pitch video

A ~3:12 silent 1080p30 pitch video, in light mode, ready for a voiceover:
`footage/transpeaktation-pitch.mp4` (gitignored: render it, or share the file).

The phone recording is committed (`footage/sim.mov` + `footage/marks.json`), so editing `pitch.html` and rendering
needs only `npm install`, Chrome and ffmpeg. `./record.sh` (Mac + Xcode) replaces that take with a new one.

```sh
cd demo/video && npm install
./record.sh        # ~3 min: boots a fresh iPhone simulator on camera, taps through the app → footage/sim.mov + marks.json
npm run render     # ~4 min: pitch.html frame by frame → footage/transpeaktation-pitch.mp4
npm run preview    # play it live: http://127.0.0.1:8123/demo/video/pitch.html (Space pauses, arrows seek, ?t=75)
node render.mjs --stills 75,150   # single frames → footage/still-<t>.jpg; --from 140 --to 160 renders a slice
```

Needs Xcode (iOS 26 simulator), `xcodegen`, `ffmpeg` and Google Chrome. The app loads the deployed site
(`WEB_APP_URL`, default https://yowaymo.us), so no local api/web is needed. Routes and ETAs are live when you
record: record in the evening for evening arrival times.

## How it's made

| File | Does |
|---|---|
| `pitch.html` | The whole video on one clock: `../index.html?theme=light` for the first minute, then the recording in a phone frame with captions, then the closing scenes. Every frame is a pure function of time. |
| `ios/` | XcodeGen project: includes `ios/project.yml` unchanged and adds `Tour`, a UI test that taps through the app on camera and logs each beat and tap. |
| `record.sh` | Erases and boots a dedicated simulator ("transPEAKtation pitch") with the recording already running, installs the app, runs `Tour`. |
| `marks.py` | Turns the tour log into `footage/marks.json`: beats and taps in recording seconds. The recording's clock starts at its first frame, seconds after `recordVideo` starts, so the offset is measured by lining taps up with the screen changes they cause. |
| `render.mjs` | Serves the repo, steps `pitch.html` frame by frame in Chrome, pipes the frames to ffmpeg. The demo iframe runs on a virtual clock (timers and CSS transitions advance exactly one frame per frame). |

Things to know before presenting:
- **Voice is staged.** The mic really opens ("Listening…"), but nobody speaks. The speech bubble is drawn by the
  video, and the tour opens Chase Center from Recent, as the voice intent would. The feature itself (ElevenLabs
  speech-to-text via `api/ /voice`) is real.
- **Tap ripples** are drawn by the video at the tour's logged tap points; the simulator doesn't show touches.
- **Adoption numbers** (`ADOPTION` in `pitch.html`) are the SUMO runs for the fireworks exodus with the 6,000-car crowd
  and the PPO policy, the series that improves at every step up in adoption. At 30% and 50% adoption, total
  vehicle-hours still rise (+38%, +5%). The chart shows the whole-city number only from 80%, and the footnote says so.
  Change the rows or `CITY_FROM` and re-render.

## Timeline and voiceover

Times are for the current take (`npm run render` prints each scene's start, and the app beats' times).

| Time | On screen | Suggested voiceover |
|---|---|---|
| 0:00 | July 4 fireworks, San Francisco, SUMO replay | "July 4th in San Francisco. The fireworks end, and the whole crowd drives home at once." |
| 0:07 | Everyone takes their own fastest route → gridlock | "Every map app gives every driver the same fastest route. So they all pick the same few streets, and the city locks up." |
| 0:22 | 1:00 AM, most cars still stuck | "Hours later, most cars still haven't made it home." |
| 0:24 | Rewind → same night with transPEAKtation | "Now rewind. transPEAKtation knows the fireworks are coming, forecasts the jam before it forms, and routes the whole crowd together." |
| 0:51 | Side by side: fastest route vs. routing together | "Routed together, 6,881 of 7,000 cars are home by 1 AM." (the two panels are different simulation setups, as the footnote says, so don't call it a before/after) |
| 1:00 | iPhone boots, app launches | "Here's the app, filmed live on an iPhone." |
| 1:13 | AI & Privacy switches, trip saving off | "First, you decide what AI touches your trip. Every model is a switch. Here we turn trip saving off." |
| 1:24 | Mic → "Go to Chase Center" | "Then just say where you're going." |
| 1:34 | Recommended route vs. regular routes | "It compares its event-aware pick with the regular routes, and shows the delay the forecast predicts on each." |
| 1:39 | Gemini's explanation | "Gemini explains why, in plain words, without ever seeing your address." |
| 1:47 | Where your data went | "And you can see exactly where your trip's data went, stop by stop. Nothing was saved." |
| 1:58 | Turn-by-turn → arrived | "Then it drives you there. No chat window anywhere: the AI works inside the trip." |
| 2:20 | Adoption: 30% → 100% | "It works from the first riders. At 30% adoption, our riders' trips are 19% shorter. And the more people use it, the better it gets: past 80%, the whole city's total driving time drops: 27% at 80%, 46% when everyone's on it." |
| 2:36 | People + robotaxi fleets | "The same forecast serves people and robotaxi fleets like Waymo. They share the same streets, so spreading both keeps everyone moving." |
| 2:49 | The problem | "Because the problem isn't a lack of roads. Every map app sends every driver down the same road, reacts after the jam, and robotaxis will multiply it. And riders can't see what the AI does with their data." |
| 3:04 | End card | "transPEAKtation. More way to go." |
