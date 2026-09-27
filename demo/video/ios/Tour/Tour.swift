import XCTest

/// On-camera walkthrough for the pitch video; record.sh films the simulator while it runs.
/// Each beat prints `TOUR <beat> <unix time>` and each tap `TOUR-TAP x y <start> <end>`; record.sh turns them into
/// marks.json, which times pitch.html's captions and touch ripples.
/// Pauses are for the viewer; the video speeds up the dull parts.
final class Tour: XCTestCase {
    let app = XCUIApplication(bundleIdentifier: "app.transpeaktation.ios")
    var web: XCUIElement { app.webViews.firstMatch }

    func mark(_ beat: String) { print("TOUR \(beat) \(Date().timeIntervalSince1970)") }
    func pause(_ s: Double) { Thread.sleep(forTimeInterval: s) }
    func el(_ label: String, _ type: XCUIElement.ElementType = .any, op: String = "==") -> XCUIElement {
        web.descendants(matching: type).matching(NSPredicate(format: "label \(op) %@", label)).firstMatch
    }
    /// Taps and logs where (screen points) and when, so the video can draw a touch ripple the recording doesn't show.
    func tap(_ e: XCUIElement, wait: TimeInterval = 30) {
        XCTAssert(e.waitForExistence(timeout: wait), "not found: \(e)")
        let f = e.frame, t0 = Date().timeIntervalSince1970
        e.tap()
        print("TOUR-TAP \(f.midX) \(f.midY) \(t0) \(Date().timeIntervalSince1970)")
    }
    func type(_ text: String) {
        for ch in text { app.typeText(String(ch)); pause(0.09) }
    }
    /// Settings → AI & Privacy.
    func openPrivacy() {
        tap(el("Open menu")); pause(0.7)
        tap(el("Settings", .button)); pause(0.7)
        tap(el("AI & Privacy", .button)); pause(1.2)
    }
    func closeDialog() {
        let done = el("Done", .button)
        tap(done.exists ? done : el("Close", .button))
    }

    func testTour() {
        continueAfterFailure = false
        mark("home"); pause(1.5)
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        // First-boot "Ready for Apple Intelligence" banner: swipe it away so it doesn't cover the icons.
        let banner = springboard.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS 'Apple Intelligence'")).firstMatch
        if banner.waitForExistence(timeout: 4) { banner.swipeUp(); pause(1.5) }
        tap(springboard.icons["transPEAKtation"])
        mark("launch")
        XCTAssert(el("Where to?", .button).waitForExistence(timeout: 60))
        pause(4) // map tiles + event pins
        mark("map")
        pause(3)

        // Privacy first: every AI and data use is a switch the rider controls.
        mark("privacy")
        openPrivacy()
        pause(2.5)
        tap(el("Save my trips", .switch)) // opt out of trip saving
        mark("opt-out")
        pause(3)
        closeDialog(); pause(1.5)

        // Voice (staged): the mic really listens, but nobody speaks; the video overlays the spoken request and the
        // tour opens the same destination from Recent, as the voice intent would.
        mark("voice")
        tap(el("Say where to go")); pause(0.4)
        mark("say")
        pause(3.2)
        tap(el("Chase Center", .button, op: "BEGINSWITH"))
        mark("planning")
        XCTAssert(el("Recommended").waitForExistence(timeout: 45), "no routes")
        mark("routes")
        pause(3)
        tap(el("Expand panel", .button)); pause(0.5)
        if el("Expand panel", .button).exists { tap(el("Expand panel", .button)) } // half → full
        mark("explain")
        pause(6) // Gemini's note on the recommended route vs the regular ones
        tap(el("Collapse panel", .button)); pause(1.5)

        // Transparency: where this trip's data went, stop by stop.
        mark("trace")
        openPrivacy()
        pause(3)
        web.swipeUp(); pause(3)
        closeDialog(); pause(1.5)

        // Drive it: demo location mode, each tap on the turn banner moves to the next turn.
        mark("start")
        tap(el("Start", .button)); pause(2.5)
        mark("nav")
        let turn = web.buttons.matching(NSPredicate(format: "label ENDSWITH 'Next'")).firstMatch
        let arrivedBadge = el("Arrived", op: "BEGINSWITH")
        for _ in 0..<60 {
            if arrivedBadge.exists { break }
            guard turn.exists else { break } // already arrived and closed
            tap(turn, wait: 1)
            pause(1.1)
        }
        mark("arrived")
        pause(3)
        let end = el("End", .button)
        if end.exists { tap(end) }
        XCTAssert(el("Where to?", .button).waitForExistence(timeout: 15))
        pause(2)
        mark("done")
    }
}
