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
        .preferredColorScheme(.dark)
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
                .foregroundStyle(Color.muted)
                .multilineTextAlignment(.center)
            Text(url.absoluteString)
                .font(.footnote.monospaced())
                .foregroundStyle(Color.muted)
            Button("Retry", action: retry)
                .font(.body.weight(.semibold))
                .foregroundStyle(Color(red: 0.043, green: 0.063, blue: 0.125))
                .padding(.horizontal, 28)
                .frame(height: 48)
                .background(Color.accent, in: Capsule())
                .padding(.top, 6)
        }
        .foregroundStyle(.white)
        .padding(32)
    }
}

extension Color {
    static let appBackground = Color(red: 0.024, green: 0.047, blue: 0.090) // #060C17
    static let accent = Color(red: 0.616, green: 0.549, blue: 1.0)          // #9D8CFF
    static let muted = Color(red: 0.549, green: 0.604, blue: 0.702)         // #8C9AB3
}
