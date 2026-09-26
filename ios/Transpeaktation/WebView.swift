import SwiftUI
import WebKit

/// Hosts the web app full-screen. Reports load state so SwiftUI can show native loading/offline screens.
struct WebView: UIViewRepresentable {
    enum LoadState: Equatable { case loading, loaded, failed(String) }

    let url: URL
    let reloadToken: Int
    @Binding var state: LoadState

    func makeCoordinator() -> Coordinator { Coordinator(state: $state) }

    func makeUIView(context: Context) -> WKWebView {
        let web = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
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

    final class Coordinator: NSObject, WKNavigationDelegate {
        var state: Binding<LoadState>
        var lastToken = 0
        init(state: Binding<LoadState>) { self.state = state }

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
