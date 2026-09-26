import SwiftUI

@main
struct TranspeaktationApp: App {
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}

/// Native shell around the web app (web/). The route map UI is the same React code the browser gets;
/// Swift owns the window, launch, loading and offline states.
struct ContentView: View {
    @State private var state: WebView.LoadState = .loading
    @State private var reloadToken = 0

    private static let url: URL = {
        let raw = Bundle.main.object(forInfoDictionaryKey: "WebAppURL") as? String ?? ""
        return URL(string: raw) ?? URL(string: "http://localhost:3000")!
    }()

    var body: some View {
        ZStack {
            Color.appBackground.ignoresSafeArea()
            WebView(url: Self.url, reloadToken: reloadToken, state: $state)
                .ignoresSafeArea() // the page pads itself with env(safe-area-inset-*)
                .opacity(state == .loaded ? 1 : 0)

            switch state {
            case .loading:
                ProgressView().tint(Color.accent)
            case .failed(let message):
                OfflineView(url: Self.url, message: message) {
                    state = .loading
                    reloadToken += 1
                }
            case .loaded:
                EmptyView()
            }
        }
    }
}

struct OfflineView: View {
    let url: URL
    let message: String
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 14) {
            Text("Can't reach transPEAKtation")
                .font(.title3.weight(.semibold))
            Text(message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Text(url.absoluteString)
                .font(.footnote.monospaced())
                .foregroundStyle(.secondary)
            Button("Retry", action: retry)
                .font(.body.weight(.semibold))
                .foregroundStyle(.white)
                .padding(.horizontal, 28)
                .frame(height: 48)
                .background(Color.accent, in: Capsule())
                .padding(.top, 6)
        }
        .foregroundStyle(.primary)
        .padding(32)
    }
}

// Follows the device's light/dark setting, matching the web app's Meadow Green theme (web/app/globals.css).
extension Color {
    /// Map canvas behind the page until it paints: #E9F0E6 light, #0B1C2A dark.
    static let appBackground = Color(uiColor: UIColor { $0.userInterfaceStyle == .dark
        ? UIColor(red: 0.043, green: 0.110, blue: 0.165, alpha: 1)
        : UIColor(red: 0.914, green: 0.941, blue: 0.902, alpha: 1) })
    /// Action blue #1A759F in both modes (white text 5.1:1).
    static let accent = Color(red: 0.102, green: 0.459, blue: 0.624)
}
