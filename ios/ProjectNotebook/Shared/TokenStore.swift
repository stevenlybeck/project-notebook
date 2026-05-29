import Foundation
import Security

/// Stores the paired device token (and device id) in the keychain, shared
/// between the container app and the Share Extension via a keychain access
/// group. The app writes it during pairing; the extension reads it to
/// authenticate uploads.
enum TokenStore {
    // kSecAttrAccessGroup is intentionally NOT set. Each target's
    // keychain-access-groups entitlement has exactly one entry
    // ($(AppIdentifierPrefix)com.projectnotebook.shared), and the keychain
    // defaults to the first group in that list — so the app and the extension
    // share items without this code needing to know the team-ID prefix.
    private static let service = "com.projectnotebook"
    private static let tokenAccount = "deviceToken"
    private static let deviceIDAccount = "deviceID"

    static var token: String? { read(tokenAccount) }
    static var deviceID: String? { read(deviceIDAccount) }
    static var isPaired: Bool { token != nil }

    static func savePairing(token: String, deviceID: String) {
        write(token, account: tokenAccount)
        write(deviceID, account: deviceIDAccount)
    }

    static func clear() {
        delete(tokenAccount)
        delete(deviceIDAccount)
    }

    // MARK: - Keychain primitives

    private static func baseQuery(_ account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    private static func write(_ value: String, account: String) {
        var query = baseQuery(account)
        SecItemDelete(query as CFDictionary)  // replace any existing item
        query[kSecValueData as String] = Data(value.utf8)
        // AfterFirstUnlock so the extension can read it during background uploads.
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        SecItemAdd(query as CFDictionary, nil)
    }

    private static func read(_ account: String) -> String? {
        var query = baseQuery(account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func delete(_ account: String) {
        SecItemDelete(baseQuery(account) as CFDictionary)
    }
}
