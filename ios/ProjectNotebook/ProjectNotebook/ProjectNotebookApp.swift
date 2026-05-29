import SwiftUI

@main
struct ProjectNotebookApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegateAdaptor
    @StateObject private var pairing = PairingManager()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(pairing)
                .onOpenURL { pairing.handlePairingURL($0) }
        }
    }
}

/// Manages background upload sessions. The share extension starts uploads and saves session IDs
/// to shared storage. This app claims those sessions by creating URLSession objects with the
/// same identifiers, which causes nsurlsessiond to deliver progress and completion callbacks
/// to BackgroundUploadDelegate. Also handles OS-initiated wakeups for completed transfers.
/// Handles OS-initiated background session completion events. The app still needs this
/// so that when nsurlsessiond finishes an upload, the OS can deliver the completion event
/// and we can mark the upload as done (in case the app wasn't polling at that moment).
class AppDelegate: NSObject, UIApplicationDelegate {
    private var sessions: [URLSession] = []

    func application(_ application: UIApplication, handleEventsForBackgroundURLSession identifier: String, completionHandler: @escaping () -> Void) {
        UploadLog.shared.log("[App] OS delivered background session: \(identifier)")
        let config = URLSessionConfiguration.background(withIdentifier: identifier)
        config.sharedContainerIdentifier = "group.projectnotebook"
        let session = URLSession(configuration: config, delegate: BackgroundUploadDelegate.shared, delegateQueue: nil)
        sessions.append(session)
        BackgroundUploadDelegate.shared.completionHandlers[identifier] = completionHandler
    }
}

/// Main screen of the container app. Shows the hub URL configuration and a live-updating
/// list of all uploads (past and in-progress). On every 2-second refresh, tells AppDelegate
/// to claim any new background sessions so we receive progress and completion callbacks.
struct ContentView: View {
    @EnvironmentObject var pairing: PairingManager
    @Environment(\.scenePhase) private var scenePhase
    @State private var uploads: [UploadRecord] = []
    @State private var showLogs = false
    let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationView {
            Group {
                if pairing.isPaired {
                    pairedList
                } else {
                    PairingView()
                }
            }
            .navigationTitle(pairing.isPaired ? "Project Notebook" : "")
            .navigationBarTitleDisplayMode(pairing.isPaired ? .large : .inline)
            .toolbar {
                if pairing.isPaired {
                    Button("Logs") { showLogs = true }
                }
            }
            .sheet(isPresented: $showLogs) {
                LogView()
            }
            .onAppear { refreshUploads() }
            .onReceive(timer) { _ in refreshUploads() }
            .onChange(of: scenePhase) { newPhase in
                if newPhase == .active { pairing.retryIfPending() }
            }
        }
    }

    private var pairedList: some View {
        List {
            Section("Hub") {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Connected").fontWeight(.medium)
                        Text(pairing.hubURL)
                            .font(.caption)
                            .foregroundColor(.secondary)
                            .lineLimit(1)
                    }
                    Spacer()
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(.green)
                }
                Button("Unpair", role: .destructive) { pairing.unpair() }
            }

            Section("Uploads") {
                if uploads.isEmpty {
                    Text("No uploads yet. Use the Share button in any app to send files.")
                        .foregroundColor(.secondary)
                        .font(.subheadline)
                } else {
                    ForEach(uploads) { upload in
                        UploadRow(upload: upload)
                    }
                }
            }
        }
        .onAppear { HubDiscovery.shared.start() }
    }

    private func refreshUploads() {
        pollHubForProgress()
        uploads = UploadLog.shared.loadAll()
    }

    private func pollHubForProgress() {
        let hubURL = pairing.hubURL
        guard !hubURL.isEmpty,
              let url = URL(string: "\(hubURL)/api/uploads") else { return }

        let records = UploadLog.shared.loadAll()
        let hasActive = records.contains { $0.status == .uploading || $0.status == .pending }
        guard hasActive else { return }

        var request = URLRequest(url: url)
        if let token = TokenStore.token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        URLSession.shared.dataTask(with: request) { data, _, _ in
            guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let uploads = json["uploads"] as? [String: [String: Any]] else { return }

            for record in records where record.status == .uploading || record.status == .pending {
                if let upload = uploads[record.id.uuidString] {
                    let received = upload["received"] as? Int64 ?? 0
                    let status = upload["status"] as? String ?? ""

                    if status == "completed" {
                        UploadLog.shared.updateStatus(id: record.id, status: .completed)
                    } else {
                        UploadLog.shared.updateProgress(id: record.id, bytesUploaded: received)
                        if record.status == .pending {
                            UploadLog.shared.updateStatus(id: record.id, status: .uploading)
                        }
                    }
                }
            }
        }.resume()
    }
}

/// Shown when no device token is stored yet: walks the user through pairing
/// by scanning the hub's QR with the system Camera (which opens the
/// projectnotebook:// deep link handled in PairingManager).
struct PairingView: View {
    @EnvironmentObject var pairing: PairingManager

    var body: some View {
        VStack(spacing: 28) {
            Spacer(minLength: 0)
            switch pairing.state {
            case .idle:
                instructions
            case .connecting:
                connecting
            case .failed(let message, let offerSettings):
                failure(message: message, offerSettings: offerSettings)
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(24)
    }

    private var instructions: some View {
        VStack(spacing: 24) {
            Image(systemName: "qrcode.viewfinder")
                .font(.system(size: 64))
                .foregroundColor(.accentColor)

            Text("Connect to your Mac")
                .font(.title2)
                .fontWeight(.semibold)

            VStack(alignment: .leading, spacing: 14) {
                Label("On your Mac, run `project-notebook pair`", systemImage: "1.circle.fill")
                Label("Point your Camera app at the QR code", systemImage: "2.circle.fill")
                Label("Tap the banner to open and pair", systemImage: "3.circle.fill")
            }
            .font(.subheadline)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal)
        }
    }

    private var connecting: some View {
        VStack(spacing: 24) {
            Image(systemName: "qrcode.viewfinder")
                .font(.system(size: 64))
                .foregroundColor(.accentColor)

            Text("Connecting to your Mac…")
                .font(.title2)
                .fontWeight(.semibold)

            ProgressView()

            Text("Allow Local Network access if you're asked.")
                .font(.caption)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func failure(message: String, offerSettings: Bool) -> some View {
        VStack(spacing: 24) {
            Image(systemName: "wifi.exclamationmark")
                .font(.system(size: 64))
                .foregroundColor(.orange)

            Text("Couldn't pair")
                .font(.title2)
                .fontWeight(.semibold)

            Text(message)
                .font(.subheadline)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal)

            if offerSettings {
                Button("Open Settings") {
                    if let url = URL(string: UIApplication.openSettingsURLString) {
                        UIApplication.shared.open(url)
                    }
                }
                .buttonStyle(.borderedProminent)
            }
        }
    }
}

/// Debug log viewer. Reads from the shared log file (written by both the share extension
/// and the container app) and displays it as selectable monospaced text. Auto-refreshes
/// every second so you can watch events in real-time.
struct LogView: View {
    @State private var logText: String = "Loading..."
    let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button("Copy") {
                    UIPasteboard.general.string = logText
                }
                Spacer()
                Text("Logs").font(.headline)
                Spacer()
                Button("Clear") {
                    UploadLog.shared.clearLog()
                    logText = "Cleared."
                }
            }
            .padding()

            ScrollView {
                Text(logText)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding()
            }
        }
        .onAppear {
            logText = UploadLog.shared.readLog()
        }
        .onReceive(timer) { _ in
            logText = UploadLog.shared.readLog()
        }
    }
}

/// A single row in the uploads list. Shows filename, project, timestamp, file size/progress,
/// a progress bar during active uploads, and a status icon (clock/spinner/checkmark/error).
struct UploadRow: View {
    let upload: UploadRecord

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(upload.filename)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .lineLimit(1)

                Spacer()

                statusIcon
            }

            HStack(spacing: 4) {
                Text(upload.project)
                Text("·")
                Text(upload.timestamp, format: .dateTime.hour().minute())
                Text("·")
                Text(upload.formattedProgress)
            }
            .font(.caption)
            .foregroundColor(.secondary)

            if upload.status == .uploading, let progress = upload.progress {
                ProgressView(value: progress)
                    .tint(.blue)
            }

            if let error = upload.errorMessage {
                Text(error)
                    .font(.caption)
                    .foregroundColor(.red)
            }
        }
        .padding(.vertical, 2)
    }

    @ViewBuilder
    private var statusIcon: some View {
        switch upload.status {
        case .pending:
            Image(systemName: "clock")
                .foregroundColor(.orange)
        case .uploading:
            ProgressView()
        case .completed:
            Image(systemName: "checkmark.circle.fill")
                .foregroundColor(.green)
        case .failed:
            Image(systemName: "xmark.circle.fill")
                .foregroundColor(.red)
        }
    }
}
