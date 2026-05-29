import Foundation
import Network

/// Browses the LAN for the hub's Bonjour service (_notebook._tcp) and keeps the
/// shared hubURL pointing at the hub's current address, so the app keeps working
/// after the hub's IP changes (DHCP) without re-pairing. Discovery only locates
/// the hub — the device token from pairing is what authenticates requests.
final class HubDiscovery {
    static let shared = HubDiscovery()
    private var browser: NWBrowser?
    private let defaults = UserDefaults(suiteName: "group.projectnotebook")

    func start() {
        guard browser == nil else { return }
        let params = NWParameters()
        params.includePeerToPeer = false
        let browser = NWBrowser(for: .bonjour(type: "_notebook._tcp", domain: nil), using: params)
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            guard let result = results.first else { return }
            self?.resolve(result.endpoint)
        }
        browser.start(queue: .global(qos: .utility))
        self.browser = browser
    }

    func stop() {
        browser?.cancel()
        browser = nil
    }

    /// Resolve a Bonjour service endpoint to a concrete host:port by opening a
    /// short-lived connection and reading the resolved remote endpoint.
    private func resolve(_ endpoint: NWEndpoint) {
        let conn = NWConnection(to: endpoint, using: .tcp)
        conn.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                if let remote = conn.currentPath?.remoteEndpoint,
                   case let .hostPort(host, port) = remote {
                    self?.updateHubURL(host: host, port: port)
                }
                conn.cancel()
            case .failed, .cancelled:
                conn.cancel()
            default:
                break
            }
        }
        conn.start(queue: .global(qos: .utility))
    }

    private func updateHubURL(host: NWEndpoint.Host, port: NWEndpoint.Port) {
        let hostString: String
        switch host {
        case .ipv4(let addr):
            hostString = String("\(addr)".split(separator: "%").first ?? "")
        case .ipv6(let addr):
            let raw = String("\(addr)".split(separator: "%").first ?? "")
            hostString = "[\(raw)]"
        case .name(let name, _):
            hostString = name
        @unknown default:
            return
        }
        guard !hostString.isEmpty else { return }
        defaults?.set("http://\(hostString):\(port.rawValue)", forKey: "hubURL")
    }
}
