import Foundation
import Network

/// Triggers the iOS Local Network permission prompt and resolves once the user
/// answers. iOS exposes no API to read the permission state, so this probes it:
/// advertise a Bonjour service with an NWListener and browse for it with an
/// NWBrowser. If the browser discovers the listener, browsing is allowed →
/// granted. If the browser reports PolicyDenied, the user has denied access.
///
/// The system prompt only appears the first time; afterward this resolves
/// without re-prompting, so it doubles as a permission check. All Network
/// callbacks run on a private serial queue, so the completion fires once.
final class LocalNetworkAuthorization: Sendable {
    static let shared = LocalNetworkAuthorization()

    private let serviceType = "_preflight_check._tcp"
    private let queue = DispatchQueue(label: "com.projectnotebook.localnetwork-auth")

    func requestAuthorization() async -> Bool {
        await withCheckedContinuation { continuation in
            queue.async { self.probe { continuation.resume(returning: $0) } }
        }
    }

    private func probe(completion: @escaping (Bool) -> Void) {
        var listener: NWListener?
        var browser: NWBrowser?
        var finished = false

        func finish(_ granted: Bool) {
            guard !finished else { return }
            finished = true
            listener?.cancel()
            browser?.cancel()
            completion(granted)
        }

        // Advertise a uniquely-named service on this device.
        guard let l = try? NWListener(using: NWParameters(tls: .none, tcp: .init())) else {
            finish(false)
            return
        }
        l.service = NWListener.Service(name: UUID().uuidString, type: serviceType)
        l.newConnectionHandler = { $0.cancel() }
        listener = l
        l.start(queue: queue)

        // Browse for that service type.
        let params = NWParameters()
        params.includePeerToPeer = true
        let b = NWBrowser(for: .bonjour(type: serviceType, domain: nil), using: params)
        b.stateUpdateHandler = { state in
            switch state {
            case .failed:
                finish(false)
            case .waiting(let error):
                if case .dns(let code) = error, code == kDNSServiceErr_PolicyDenied {
                    finish(false)
                }
            default:
                break
            }
        }
        b.browseResultsChangedHandler = { results, _ in
            if !results.isEmpty {
                finish(true)  // we can see our own listener → browsing is allowed
            }
        }
        browser = b
        b.start(queue: queue)
    }
}
