import SwiftUI
import UIKit

/// Drives pairing. Initiated by scanning the hub's QR with the system Camera,
/// which opens projectnotebook://pair?url=…&code=… and routes here. We confirm
/// Local Network permission (awaiting the user's answer), redeem the code at
/// <url>/api/pair, store the device token in the shared keychain, and save the
/// hub URL for the extension.
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
    private var pending: (hub: String, code: String)?

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
              let hub = items.first(where: { $0.name == "url" })?.value,
              let code = items.first(where: { $0.name == "code" })?.value else {
            state = .failed(message: "That QR code isn't a valid pairing link.", offerSettings: false)
            return
        }
        pending = (hub, code)
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
        guard let (hub, code) = pending else { return }
        state = .connecting

        // Confirm Local Network permission first. This awaits the user's answer
        // to the system prompt, so the request below runs only once it's granted.
        let granted = await LocalNetworkAuthorization.shared.requestAuthorization()
        guard granted else {
            state = .failed(
                message: "Project Notebook needs Local Network access to reach the hub on your Mac. Turn it on, then return to the app.",
                offerSettings: true)
            return
        }

        guard let url = URL(string: "\(hub)/api/pair") else {
            pending = nil
            state = .failed(message: "The hub address looks malformed.", offerSettings: false)
            return
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 8
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(
            withJSONObject: ["code": code, "device_name": UIDevice.current.name])

        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            guard let http = resp as? HTTPURLResponse else {
                state = .failed(message: "Unexpected response from the hub.", offerSettings: false)
                return
            }
            switch http.statusCode {
            case 200:
                guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let token = json["token"] as? String,
                      let deviceID = json["device_id"] as? String else {
                    state = .failed(message: "The hub sent an unexpected response.", offerSettings: false)
                    return
                }
                TokenStore.savePairing(token: token, deviceID: deviceID)
                defaults?.set(hub, forKey: "hubURL")
                pending = nil
                isPaired = true
                state = .idle
            case 403:
                pending = nil
                state = .failed(
                    message: "That pairing code expired. Re-run `project-notebook pair` on your Mac and scan again.",
                    offerSettings: false)
            default:
                state = .failed(message: "Pairing failed (HTTP \(http.statusCode)).", offerSettings: false)
            }
        } catch {
            state = .failed(
                message: "Couldn't reach the hub. Make sure your phone is on the same Wi-Fi as your Mac, then scan again.",
                offerSettings: false)
        }
    }
}
