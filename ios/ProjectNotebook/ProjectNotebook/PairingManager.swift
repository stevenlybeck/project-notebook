import SwiftUI
import UIKit

/// Drives pairing. Initiated by scanning the hub's QR with the system Camera,
/// which opens projectnotebook://pair?url=…&url=…&code=… and routes here. The
/// QR encodes every IPv4 address the phone might be able to reach (LAN,
/// Tailscale, other overlays); we confirm Local Network permission, try each
/// `url=` value in order, store the device token in the shared keychain on the
/// first success, and save the *working* URL for the extension to use.
@MainActor
final class PairingManager: ObservableObject {
    enum State: Equatable {
        case idle                                       // unpaired, waiting for a scan
        case connecting                                 // pairing underway
        case failed(message: String, offerSettings: Bool)
    }

    @Published private(set) var isPaired: Bool = false
    @Published private(set) var state: State = .idle

    private let defaults = UserDefaults(suiteName: "group.projectnotebook")
    private var pending: (hubs: [String], code: String)?

    var hubURL: String { defaults?.string(forKey: "hubURL") ?? "" }

    init() {
        // iOS keeps keychain items across app deletion, but the App-Group
        // UserDefaults (where hubURL lives) is cleared on uninstall — which
        // would leave a stale token with no hub URL after a reinstall. Standard
        // UserDefaults *is* wiped on uninstall, so its absence marks a fresh
        // install: forget the pairing so a reinstall starts clean. App updates
        // keep the marker, so they keep the pairing.
        if !UserDefaults.standard.bool(forKey: "pn.installed") {
            TokenStore.clear()
            UserDefaults.standard.set(true, forKey: "pn.installed")
        }
        isPaired = TokenStore.isPaired
    }

    func handlePairingURL(_ url: URL) {
        guard url.scheme == "projectnotebook", url.host == "pair",
              let comps = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let items = comps.queryItems,
              let code = items.first(where: { $0.name == "code" })?.value else {
            state = .failed(message: "That QR code isn't a valid pairing link.", offerSettings: false)
            return
        }
        let hubs = items.filter { $0.name == "url" }.compactMap { $0.value }
        guard !hubs.isEmpty else {
            state = .failed(message: "That QR code isn't a valid pairing link.", offerSettings: false)
            return
        }
        print("[Pair] received deep link with \(hubs.count) hub URL(s): \(hubs)")
        pending = (hubs, code)
        Task { await pair() }
    }

    /// Re-attempt after the user may have toggled the permission in Settings.
    func retryIfPending() {
        guard pending != nil, case .failed = state else { return }
        Task { await pair() }
    }

    func unpair() {
        TokenStore.clear()
        defaults?.removeObject(forKey: "hubURL")
        isPaired = false
        state = .idle
    }

    private func pair() async {
        guard let (hubs, code) = pending else { return }
        state = .connecting

        // Confirm Local Network permission first. This awaits the user's answer
        // to the system prompt, so the requests below run only once it's granted.
        let granted = await LocalNetworkAuthorization.shared.requestAuthorization()
        guard granted else {
            state = .failed(
                message: "Project Notebook needs Local Network access to reach the hub on your Mac. Turn it on, then return to the app.",
                offerSettings: true)
            return
        }

        var failures: [String] = []
        for hub in hubs {
            print("[Pair] attempting \(hub)")
            switch await attemptPair(hub: hub, code: code) {
            case .success:
                print("[Pair] paired via \(hub)")
                return
            case .failedHard(let message):
                // The hub responded with a real HTTP status (expired code,
                // unexpected response, etc.) — same code + same hub state for
                // every candidate, so don't bother trying others.
                print("[Pair] hard failure: \(message)")
                pending = nil
                state = .failed(message: message, offerSettings: false)
                return
            case .unreachable(let detail):
                print("[Pair] unreachable: \(hub) — \(detail)")
                failures.append("• \(hub) — \(detail)")
            }
        }
        let breakdown = failures.joined(separator: "\n")
        state = .failed(
            message: "Couldn't reach the hub at any address:\n\(breakdown)\n\nMake sure your phone and Mac share a network (Wi-Fi, Tailscale, …), then scan again.",
            offerSettings: false)
    }

    private enum AttemptResult {
        case success
        case failedHard(message: String)
        case unreachable(detail: String)
    }

    private func attemptPair(hub: String, code: String) async -> AttemptResult {
        guard let url = URL(string: "\(hub)/api/pair") else {
            return .failedHard(message: "The hub address looks malformed.")
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 5  // first connection over Tailscale/VPN can take a few seconds
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(
            withJSONObject: ["code": code, "device_name": UIDevice.current.name])

        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            guard let http = resp as? HTTPURLResponse else {
                return .failedHard(message: "Unexpected response from the hub.")
            }
            switch http.statusCode {
            case 200:
                guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let token = json["token"] as? String,
                      let deviceID = json["device_id"] as? String else {
                    return .failedHard(message: "The hub sent an unexpected response.")
                }
                TokenStore.savePairing(token: token, deviceID: deviceID)
                defaults?.set(hub, forKey: "hubURL")  // save the *working* address
                pending = nil
                isPaired = true
                state = .idle
                return .success
            case 403:
                return .failedHard(message: "That pairing code expired. Re-run `project-notebook pair` on your Mac and scan again.")
            default:
                return .failedHard(message: "Pairing failed (HTTP \(http.statusCode)).")
            }
        } catch {
            return .unreachable(detail: shortError(error))
        }
    }

    /// Map URLSession errors to compact human-readable labels (so the failure
    /// screen and Xcode console both show what actually went wrong).
    private func shortError(_ error: Error) -> String {
        let nsErr = error as NSError
        switch nsErr.code {
        case NSURLErrorTimedOut: return "timeout"
        case NSURLErrorCannotConnectToHost: return "cannot connect to host"
        case NSURLErrorCannotFindHost: return "cannot find host"
        case NSURLErrorNetworkConnectionLost: return "connection lost"
        case NSURLErrorNotConnectedToInternet: return "no network"
        case NSURLErrorAppTransportSecurityRequiresSecureConnection:
            return "ATS blocked plaintext (-1022)"
        default:
            return "\(error.localizedDescription) (\(nsErr.code))"
        }
    }
}
