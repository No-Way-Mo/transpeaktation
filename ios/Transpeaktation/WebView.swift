import CoreLocation
import SwiftUI
import WebKit

/// Hosts the web app full-screen. Reports load state so SwiftUI can show native loading/offline screens, and watches
/// GPS for arrival while the page navigates a saved trip (web/app/mobile.tsx: `arrival` message, `tp-arrived` event).
struct WebView: UIViewRepresentable {
    enum LoadState: Equatable { case loading, loaded, failed(String) }

    let url: URL
    let reloadToken: Int
    @Binding var state: LoadState

    func makeCoordinator() -> Coordinator { Coordinator(state: $state) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: "arrival")
        let web = WKWebView(frame: .zero, configuration: config)
        context.coordinator.web = web
        web.navigationDelegate = context.coordinator
        web.isOpaque = false                       // no white flash before the page paints
        web.backgroundColor = UIColor(Color.appBackground)
        web.scrollView.bounces = false             // the map handles its own panning
        web.scrollView.contentInsetAdjustmentBehavior = .never
        web.allowsBackForwardNavigationGestures = false
        #if DEBUG
        web.isInspectable = true                   // Safari > Develop > Simulator to debug the page
        #endif
        context.coordinator.lastToken = reloadToken
        web.load(URLRequest(url: url))
        return web
    }

    func updateUIView(_ web: WKWebView, context: Context) {
        guard context.coordinator.lastToken != reloadToken else { return }
        context.coordinator.lastToken = reloadToken
        web.load(URLRequest(url: url))
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        var state: Binding<LoadState>
        var lastToken = 0
        weak var web: WKWebView?
        private let location = CLLocationManager()
        private var destination: CLLocation?
        init(state: Binding<LoadState>) { self.state = state }

        /// Page → app: the destination {lat, lon} to watch for, or null to stop (trip ended or already arrived).
        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let d = message.body as? [String: Double], let lat = d["lat"], let lon = d["lon"] else {
                destination = nil
                location.stopUpdatingLocation()
                return
            }
            destination = CLLocation(latitude: lat, longitude: lon)
            location.delegate = self
            location.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
            if location.authorizationStatus == .notDetermined { location.requestWhenInUseAuthorization() }
            location.startUpdatingLocation()
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { state.wrappedValue = .loaded }
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { fail(error) }
        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { fail(error) }
        // Web content process can be killed in the background; reload instead of showing a blank view.
        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { webView.reload() }

        private func fail(_ error: Error) {
            if (error as NSError).code == NSURLErrorCancelled { return } // superseded by a newer load
            state.wrappedValue = .failed(error.localizedDescription)
        }
    }
}

extension WebView.Coordinator: @preconcurrency CLLocationManagerDelegate {
    /// Within this of the destination counts as arrived. Fixes coarser than that are skipped (indoors, cold start).
    /// ponytail: a fixed radius; a venue with a far-off parking lot may need the route's last point or a bigger one.
    static let arrivedRadius: CLLocationDistance = 100

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        if destination != nil { manager.startUpdatingLocation() } // permission just granted: start watching
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let destination, let here = locations.last,
              here.horizontalAccuracy >= 0, here.horizontalAccuracy <= Self.arrivedRadius,
              here.distance(from: destination) <= Self.arrivedRadius else { return }
        self.destination = nil
        manager.stopUpdatingLocation()
        web?.evaluateJavaScript("dispatchEvent(new Event('tp-arrived'))")
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {} // keeps trying; denied = no auto-arrive
}
