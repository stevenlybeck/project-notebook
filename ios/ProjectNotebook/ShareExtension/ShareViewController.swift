import UIKit
import UniformTypeIdentifiers

/// Convenience wrapper that writes to the shared UploadLog file.
/// Used throughout the extension for debugging; logs are viewable in the container app's Logs screen.
private func log(_ msg: String) {
    UploadLog.shared.log(msg)
}

/// The main view controller for the Share Extension. Presented by iOS when the user shares
/// media via the share sheet and selects "Project Notebook". It fetches the list of active
/// projects from the hub server, lets the user pick one, then hands off the file to a
/// background URLSession for upload and dismisses immediately.
class ShareViewController: UIViewController {

    private let hubURLKey = "hubURL"
    private let suiteName = "group.projectnotebook"

    private var projects: [(name: String, path: String)] = []
    private var selectedProject: String?
    private var attachments: [NSItemProvider] = []

    private let tableView = UITableView(frame: .zero, style: .insetGrouped)
    private let statusLabel = UILabel()
    private let activityIndicator = UIActivityIndicatorView(style: .medium)


    // MARK: - Lifecycle

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        title = "Project Notebook"

        collectAttachments()
        setupUI()
        fetchProjects()
    }

    // MARK: - UI

    /// Builds the extension's interface: a navigation bar with cancel button, a table view
    /// for project selection, and a centered status label with activity indicator for
    /// loading/error states.
    private func setupUI() {
        let nav = UINavigationBar()
        let navItem = UINavigationItem(title: "Send to Project")
        navItem.leftBarButtonItem = UIBarButtonItem(
            barButtonSystemItem: .cancel, target: self, action: #selector(cancelTapped)
        )
        nav.setItems([navItem], animated: false)
        nav.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(nav)

        tableView.delegate = self
        tableView.dataSource = self
        tableView.register(UITableViewCell.self, forCellReuseIdentifier: "cell")
        tableView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(tableView)

        statusLabel.textAlignment = .center
        statusLabel.textColor = .secondaryLabel
        statusLabel.font = .systemFont(ofSize: 14)
        statusLabel.text = "Loading projects..."
        statusLabel.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(statusLabel)

        activityIndicator.translatesAutoresizingMaskIntoConstraints = false
        activityIndicator.startAnimating()
        view.addSubview(activityIndicator)

        NSLayoutConstraint.activate([
            nav.topAnchor.constraint(equalTo: view.topAnchor),
            nav.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            nav.trailingAnchor.constraint(equalTo: view.trailingAnchor),

            tableView.topAnchor.constraint(equalTo: nav.bottomAnchor),
            tableView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            tableView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            tableView.bottomAnchor.constraint(equalTo: view.bottomAnchor),

            activityIndicator.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            activityIndicator.centerYAnchor.constraint(equalTo: view.centerYAnchor, constant: -20),

            statusLabel.topAnchor.constraint(equalTo: activityIndicator.bottomAnchor, constant: 12),
            statusLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            statusLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),
        ])

        tableView.isHidden = true
    }

    // MARK: - Collect shared items

    /// Extracts NSItemProvider references from the share sheet's input items. These providers
    /// are not the actual files yet — they are handles that must be loaded asynchronously
    /// via loadFileRepresentation() later in loadFirst().
    private func collectAttachments() {
        guard let items = extensionContext?.inputItems as? [NSExtensionItem] else {
            log("ERROR: No input items")
            return
        }
        for item in items {
            for provider in item.attachments ?? [] {
                log("Attachment: \(provider.registeredTypeIdentifiers.joined(separator: ", "))")
                attachments.append(provider)
            }
        }
        log("Collected \(self.attachments.count) attachment(s)")
    }

    // MARK: - Hub communication

    /// Reads the hub URL from the App Group's shared UserDefaults. This value is set by the
    /// user in the container app's settings screen and shared with the extension via the
    /// "group.projectnotebook" App Group.
    private var hubBaseURL: String {
        let defaults = UserDefaults(suiteName: suiteName)
        return defaults?.string(forKey: hubURLKey) ?? ""
    }

    /// Fetches the list of active projects from the hub server (GET /api/projects) and
    /// populates the table view. Projects are registered with the hub by Claude Code sessions
    /// on the Mac, each with a name, path, and TTL.
    private func fetchProjects() {
        guard !hubBaseURL.isEmpty else {
            showStatus("Set hub URL in the Project Notebook app first")
            return
        }
        guard let url = URL(string: "\(hubBaseURL)/api/projects") else {
            showStatus("Invalid hub URL")
            return
        }
        var request = URLRequest(url: url)
        if let token = TokenStore.token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self = self else { return }
                if let error = error {
                    self.showStatus("Can't reach hub: \(error.localizedDescription)")
                    return
                }
                guard let data = data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let projectList = json["projects"] as? [[String: Any]] else {
                    self.showStatus("Invalid response from hub")
                    return
                }
                self.projects = projectList.compactMap { p in
                    guard let name = p["name"] as? String else { return nil }
                    let path = p["path"] as? String ?? ""
                    return (name: name, path: path)
                }
                if self.projects.isEmpty {
                    self.showStatus("No active projects")
                } else {
                    self.activityIndicator.stopAnimating()
                    self.statusLabel.isHidden = true
                    self.tableView.isHidden = false
                    self.tableView.reloadData()
                }
            }
        }.resume()
    }

    /// Called when the user taps a project. Iterates over all shared attachments, loads each
    /// one as a file via loadFirst(), then hands each file to startBackgroundUpload(). Dismisses
    /// the extension as soon as all uploads are kicked off — does NOT wait for uploads to complete,
    /// since the OS-managed background session handles that independently.
    private func uploadFiles(to project: String) {
        showStatus("Preparing...")
        log("uploadFiles called for project: \(project)")

        let group = DispatchGroup()
        var errors: [String] = []

        for (i, provider) in attachments.enumerated() {
            group.enter()
            log("Processing attachment \(i): types=\(provider.registeredTypeIdentifiers)")

            let types: [UTType] = [.movie, .image, .audio, .data]
            loadFirst(provider: provider, types: types) { [weak self] url, suggestedName in
                guard let self = self, let url = url else {
                    log("ERROR: Failed to load attachment \(i)")
                    errors.append("Failed to load attachment")
                    group.leave()
                    return
                }

                let filename = suggestedName ?? url.lastPathComponent
                let finalFilename: String
                if URL(fileURLWithPath: filename).pathExtension.isEmpty {
                    finalFilename = filename + "." + url.pathExtension
                } else {
                    finalFilename = filename
                }

                log("Loaded attachment \(i): \(finalFilename) at \(url.path)")

                self.startUpload(
                    project: project, filename: finalFilename, fileURL: url
                )
                group.leave()
            }
        }

        group.notify(queue: .main) { [weak self] in
            if errors.isEmpty {
                log("All uploads started, dismissing extension")
                self?.done()
            } else {
                log("ERROR: \(errors.joined(separator: ", "))")
                self?.showStatus("Errors: \(errors.joined(separator: ", "))")
            }
        }
    }

    /// Tries to load a file representation from an NSItemProvider by iterating through UTTypes
    /// in priority order (movie, image, audio, generic data). When iOS provides the file via
    /// the callback, it's a temporary URL that will be deleted — so we immediately copy it to
    /// the App Group shared container where the background URLSession can access it even after
    /// the extension process dies.
    private func loadFirst(provider: NSItemProvider, types: [UTType], completion: @escaping (URL?, String?) -> Void) {
        func tryNext(_ index: Int) {
            guard index < types.count else {
                log("ERROR: No matching type found for provider")
                completion(nil, nil)
                return
            }
            let uti = types[index]
            if provider.hasItemConformingToTypeIdentifier(uti.identifier) {
                log("Loading file representation for type: \(uti.identifier)")
                provider.loadFileRepresentation(forTypeIdentifier: uti.identifier) { url, error in
                    if let url = url {
                        log("Got file: \(url.lastPathComponent)")
                        let container = FileManager.default.containerURL(
                            forSecurityApplicationGroupIdentifier: "group.projectnotebook"
                        ) ?? FileManager.default.temporaryDirectory
                        let tmp = container.appendingPathComponent(UUID().uuidString + "_" + url.lastPathComponent)
                        do {
                            try? FileManager.default.removeItem(at: tmp)
                            try FileManager.default.copyItem(at: url, to: tmp)
                            log("Copied to shared container: \(tmp.lastPathComponent)")
                            completion(tmp, provider.suggestedName)
                        } catch {
                            log("ERROR: Failed to copy file: \(error.localizedDescription)")
                            completion(nil, nil)
                        }
                    } else {
                        log("WARN: loadFileRepresentation failed for \(uti.identifier): \(error?.localizedDescription ?? "nil")")
                        tryNext(index + 1)
                    }
                }
            } else {
                log("Provider doesn't conform to \(uti.identifier), trying next")
                tryNext(index + 1)
            }
        }
        tryNext(0)
    }

    /// Creates a background URLSession with BackgroundUploadDelegate attached, starts the upload,
    /// and saves the session ID so the container app can claim it after the extension dies.
    /// The extension receives progress callbacks while alive; the app takes over after.
    private func startUpload(project: String, filename: String, fileURL: URL) {
        let fileSize = (try? FileManager.default.attributesOfItem(atPath: fileURL.path)[.size] as? Int64) ?? nil
        let recordID = UploadLog.shared.add(
            filename: filename, project: project,
            fileSize: fileSize, localFilePath: fileURL.path
        )

        guard var urlComponents = URLComponents(string: "\(hubBaseURL)/api/ingest") else { return }
        urlComponents.queryItems = [
            URLQueryItem(name: "project", value: project),
            URLQueryItem(name: "filename", value: filename),
            URLQueryItem(name: "upload_id", value: recordID.uuidString),
        ]
        guard let ingestURL = urlComponents.url else { return }

        let sessionID = "group.projectnotebook.upload.\(recordID.uuidString)"
        let config = URLSessionConfiguration.background(withIdentifier: sessionID)
        config.sharedContainerIdentifier = suiteName
        config.sessionSendsLaunchEvents = true
        config.isDiscretionary = false
        UploadLog.shared.addSession(id: sessionID)

        let session = URLSession(configuration: config, delegate: nil, delegateQueue: nil)

        var request = URLRequest(url: ingestURL)
        request.httpMethod = "PUT"
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        if let token = TokenStore.token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let task = session.uploadTask(with: request, fromFile: fileURL)
        task.taskDescription = recordID.uuidString
        UploadLog.shared.updateStatus(id: recordID, status: .uploading)
        task.resume()

        log("Started upload: \(filename) (\(fileSize ?? 0) bytes) session=\(sessionID) record=\(recordID)")
    }

    // MARK: - Helpers

    private func showStatus(_ text: String) {
        DispatchQueue.main.async {
            self.activityIndicator.stopAnimating()
            self.statusLabel.text = text
            self.statusLabel.isHidden = false
            self.tableView.isHidden = true
        }
    }

    private func done() {
        extensionContext?.completeRequest(returningItems: nil)
    }

    @objc private func cancelTapped() {
        extensionContext?.cancelRequest(withError: NSError(domain: "user", code: 0))
    }
}

// MARK: - UITableView

/// Table view data source/delegate for the project picker. Each row shows a registered
/// project name. Tapping a row triggers uploadFiles(to:) which starts the background
/// upload and dismisses the extension.
extension ShareViewController: UITableViewDelegate, UITableViewDataSource {
    func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        projects.count
    }

    func tableView(_ tableView: UITableView, titleForHeaderInSection section: Int) -> String? {
        "Send \(attachments.count) file(s) to:"
    }

    func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = tableView.dequeueReusableCell(withIdentifier: "cell", for: indexPath)
        let project = projects[indexPath.row]
        cell.textLabel?.text = project.name
        cell.accessoryType = .disclosureIndicator
        return cell
    }

    func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        let project = projects[indexPath.row]
        tableView.isHidden = true
        uploadFiles(to: project.name)
    }
}
