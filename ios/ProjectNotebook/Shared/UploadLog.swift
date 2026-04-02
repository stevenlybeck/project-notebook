import Foundation

/// Represents a single upload in the shared log. Created by the share extension when an upload
/// starts, then updated by whichever delegate (extension's UploadDelegate or app's
/// SessionReconnectDelegate) receives callbacks from nsurlsessiond. Stored as JSON in the
/// App Group's UserDefaults so both processes can read and write it.
struct UploadRecord: Codable, Identifiable {
    let id: UUID
    let filename: String
    let project: String
    let timestamp: Date
    let fileSize: Int64?
    let localFilePath: String?
    var bytesUploaded: Int64
    var status: UploadStatus
    var errorMessage: String?

    enum UploadStatus: String, Codable {
        case pending
        case uploading
        case completed
        case failed
    }

    var formattedSize: String {
        guard let size = fileSize else { return "" }
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file
        return formatter.string(fromByteCount: size)
    }

    var progress: Double? {
        guard let total = fileSize, total > 0 else { return nil }
        return Double(bytesUploaded) / Double(total)
    }

    var formattedProgress: String {
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file
        let uploaded = formatter.string(fromByteCount: bytesUploaded)
        if let total = fileSize {
            let totalStr = formatter.string(fromByteCount: total)
            return "\(uploaded) / \(totalStr)"
        }
        return uploaded
    }
}

/// Central shared state for uploads, accessible by both the share extension and the container app
/// via the "group.projectnotebook" App Group. Manages three things:
/// 1. Upload records (pending/uploading/completed/failed with progress)
/// 2. Active background session IDs (so the container app can reconnect to orphaned sessions)
/// 3. A debug log file for troubleshooting
class UploadLog {
    static let shared = UploadLog()

    private let suiteName = "group.projectnotebook"
    private let key = "uploadLog"
    private let queue = DispatchQueue(label: "uploadlog", attributes: .concurrent)

    private var defaults: UserDefaults? {
        UserDefaults(suiteName: suiteName)
    }

    /// Creates a new upload record in pending state. Called by the share extension's
    /// startBackgroundUpload() just before handing the file to the background URLSession.
    /// Returns the record's UUID which is stored in the URLSessionTask's taskDescription
    /// so delegates can link callbacks back to this record.
    /// Creates a new upload record in pending state. Called by the share extension after
    /// copying the file to the shared container. The localFilePath tells the container app
    /// where to find the file to upload. Returns the record's UUID.
    func add(filename: String, project: String, fileSize: Int64? = nil, localFilePath: String? = nil) -> UUID {
        let record = UploadRecord(
            id: UUID(),
            filename: filename,
            project: project,
            timestamp: Date(),
            fileSize: fileSize,
            localFilePath: localFilePath,
            bytesUploaded: 0,
            status: .pending
        )
        var records = loadAll()
        records.insert(record, at: 0)
        if records.count > 100 { records = Array(records.prefix(100)) }
        save(records)
        return record.id
    }

    /// Updates the status of an upload record. Called by UploadDelegate or SessionReconnectDelegate
    /// when an upload completes or fails. When marking as completed, automatically sets
    /// bytesUploaded to the full file size.
    func updateStatus(id: UUID, status: UploadRecord.UploadStatus, error: String? = nil) {
        var records = loadAll()
        if let index = records.firstIndex(where: { $0.id == id }) {
            records[index].status = status
            records[index].errorMessage = error
            if status == .completed, let size = records[index].fileSize {
                records[index].bytesUploaded = size
            }
            save(records)
        }
    }

    /// Updates the bytes-uploaded count for an in-progress upload. Called by the URLSession
    /// delegate's didSendBodyData callback, which fires as each chunk is transmitted. The
    /// container app's UI polls loadAll() every 2 seconds to reflect these updates.
    func updateProgress(id: UUID, bytesUploaded: Int64) {
        var records = loadAll()
        if let index = records.firstIndex(where: { $0.id == id }) {
            records[index].bytesUploaded = bytesUploaded
            save(records)
        }
    }

    func loadAll() -> [UploadRecord] {
        defaults?.synchronize()
        guard let data = defaults?.data(forKey: key) else { return [] }
        return (try? JSONDecoder().decode([UploadRecord].self, from: data)) ?? []
    }

    private func save(_ records: [UploadRecord]) {
        guard let data = try? JSONEncoder().encode(records) else { return }
        defaults?.set(data, forKey: key)
    }

    // MARK: - Background session tracking

    /// These methods track which background URLSession identifiers are currently active.
    /// The share extension calls addSession() when creating a new background session.
    /// The container app reads activeSessions() to know which sessions to reconnect to.
    /// SessionReconnectDelegate calls removeSession() after all events have been delivered.

    private let sessionsKey = "activeBackgroundSessions"

    func addSession(id: String) {
        defaults?.synchronize()
        var sessions = defaults?.stringArray(forKey: sessionsKey) ?? []
        sessions.append(id)
        defaults?.set(sessions, forKey: sessionsKey)
        defaults?.synchronize()
        log("[UploadLog] addSession: \(id), total now: \(sessions.count)")
    }

    func removeSession(id: String) {
        defaults?.synchronize()
        var sessions = defaults?.stringArray(forKey: sessionsKey) ?? []
        sessions.removeAll { $0 == id }
        defaults?.set(sessions, forKey: sessionsKey)
        defaults?.synchronize()
    }

    func activeSessions() -> [String] {
        defaults?.synchronize()
        return defaults?.stringArray(forKey: sessionsKey) ?? []
    }

    // MARK: - Debug log

    /// File-based debug log in the shared App Group container. Both the share extension and
    /// the container app write to this file. The container app's LogView reads and displays it.
    /// Separate from the upload records — this is free-form text for debugging.

    private var logFile: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: suiteName)?
            .appendingPathComponent("upload.log")
    }

    func log(_ message: String) {
        let timestamp = ISO8601DateFormatter().string(from: Date())
        let line = "[\(timestamp)] \(message)\n"
        guard let url = logFile else { return }
        if let handle = try? FileHandle(forWritingTo: url) {
            handle.seekToEndOfFile()
            handle.write(line.data(using: .utf8)!)
            handle.closeFile()
        } else {
            try? line.write(to: url, atomically: true, encoding: .utf8)
        }
    }

    func readLog() -> String {
        guard let url = logFile, let data = try? String(contentsOf: url, encoding: .utf8) else {
            return "No logs yet."
        }
        let lines = data.components(separatedBy: "\n")
        return lines.suffix(100).joined(separator: "\n")
    }

    func clearLog() {
        guard let url = logFile else { return }
        try? "".write(to: url, atomically: true, encoding: .utf8)
    }
}
