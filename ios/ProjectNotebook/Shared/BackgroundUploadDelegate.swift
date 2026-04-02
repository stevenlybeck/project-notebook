import Foundation

/// Singleton delegate for all background upload URLSessions, shared by both the share extension
/// and the container app. Receives progress and completion callbacks from nsurlsessiond (the OS
/// transfer daemon) and writes them to the shared UploadLog. Only one process uses this at a time
/// for a given session — the extension gets early callbacks before it dies, then the container app
/// reconnects and receives the rest.
class BackgroundUploadDelegate: NSObject, URLSessionDataDelegate {
    static let shared = BackgroundUploadDelegate()

    /// OS completion handlers keyed by session identifier. Set by the container app's
    /// AppDelegate.handleEventsForBackgroundURLSession when iOS wakes the app to deliver
    /// pending events. Called in urlSessionDidFinishEvents after all events are delivered.
    var completionHandlers: [String: () -> Void] = [:]

    /// Called by nsurlsessiond as chunks are uploaded. Updates the shared UploadLog so the
    /// container app's upload list shows live progress.
    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64, totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        guard let idString = task.taskDescription, let id = UUID(uuidString: idString) else {
            UploadLog.shared.log("[Delegate] didSendBodyData but no taskDescription")
            return
        }
        // Log every 10MB to avoid spamming
        if totalBytesSent % (10 * 1024 * 1024) < (1024 * 1024) {
            UploadLog.shared.log("[Delegate] Progress \(idString.prefix(8)): \(totalBytesSent)/\(totalBytesExpectedToSend)")
        }
        UploadLog.shared.updateProgress(id: id, bytesUploaded: totalBytesSent)
    }

    /// Called when an upload finishes or fails. Marks the upload as completed or failed in the
    /// shared UploadLog. The task.taskDescription contains the UploadRecord UUID that links
    /// this callback to the correct record.
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let idString = task.taskDescription, let id = UUID(uuidString: idString) else { return }

        if let error = error {
            UploadLog.shared.log("Upload failed for \(idString): \(error.localizedDescription)")
            UploadLog.shared.updateStatus(id: id, status: .failed, error: error.localizedDescription)
        } else {
            let httpStatus = (task.response as? HTTPURLResponse)?.statusCode ?? 0
            if httpStatus == 200 {
                UploadLog.shared.log("Upload completed for \(idString)")
                UploadLog.shared.updateStatus(id: id, status: .completed)
                // Clean up the temp file in the shared container
                let records = UploadLog.shared.loadAll()
                if let record = records.first(where: { $0.id == id }), let path = record.localFilePath {
                    try? FileManager.default.removeItem(atPath: path)
                }
            } else {
                UploadLog.shared.log("Upload failed for \(idString): HTTP \(httpStatus)")
                UploadLog.shared.updateStatus(id: id, status: .failed, error: "HTTP \(httpStatus)")
            }
        }
    }

    /// Called by the OS after all pending events for a background session have been delivered.
    /// Removes the session ID from shared storage (no longer needed) and calls the OS completion
    /// handler to let iOS know we're done processing. Only relevant in the container app — the
    /// share extension never sets completionHandlers.
    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        let id = session.configuration.identifier ?? ""
        UploadLog.shared.log("[Delegate] urlSessionDidFinishEvents for \(id)")
        UploadLog.shared.removeSession(id: id)
        DispatchQueue.main.async {
            self.completionHandlers[id]?()
            self.completionHandlers.removeValue(forKey: id)
        }
    }
}
