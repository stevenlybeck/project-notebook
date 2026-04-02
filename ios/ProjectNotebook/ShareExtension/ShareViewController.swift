import UIKit
import UniformTypeIdentifiers

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

        navigationItem.leftBarButtonItem = UIBarButtonItem(
            barButtonSystemItem: .cancel, target: self, action: #selector(cancelTapped)
        )

        collectAttachments()
        setupUI()
        fetchProjects()
    }

    // MARK: - UI

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

    private func collectAttachments() {
        guard let items = extensionContext?.inputItems as? [NSExtensionItem] else { return }
        for item in items {
            for provider in item.attachments ?? [] {
                attachments.append(provider)
            }
        }
    }

    // MARK: - Hub communication

    private var hubBaseURL: String {
        let defaults = UserDefaults(suiteName: suiteName)
        return defaults?.string(forKey: hubURLKey) ?? ""
    }

    private func fetchProjects() {
        guard !hubBaseURL.isEmpty else {
            showStatus("Set hub URL in the Project Notebook app first")
            return
        }
        guard let url = URL(string: "\(hubBaseURL)/api/projects") else {
            showStatus("Invalid hub URL")
            return
        }

        URLSession.shared.dataTask(with: url) { [weak self] data, response, error in
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

    private func uploadFiles(to project: String) {
        showStatus("Uploading \(attachments.count) file(s)...")

        let group = DispatchGroup()
        var errors: [String] = []

        for provider in attachments {
            group.enter()

            // Try video first, then image, then any data
            let types: [UTType] = [.movie, .image, .audio, .data]
            loadFirst(provider: provider, types: types) { [weak self] url, suggestedName in
                guard let self = self, let url = url else {
                    errors.append("Failed to load attachment")
                    group.leave()
                    return
                }

                let filename = suggestedName ?? url.lastPathComponent
                guard let fileData = try? Data(contentsOf: url) else {
                    errors.append("Failed to read file data")
                    group.leave()
                    return
                }

                self.postToHub(project: project, filename: filename, data: fileData) { success, msg in
                    if !success { errors.append(msg ?? "Upload failed") }
                    group.leave()
                }
            }
        }

        group.notify(queue: .main) { [weak self] in
            if errors.isEmpty {
                self?.done()
            } else {
                self?.showStatus("Errors: \(errors.joined(separator: ", "))")
            }
        }
    }

    private func loadFirst(provider: NSItemProvider, types: [UTType], completion: @escaping (URL?, String?) -> Void) {
        func tryNext(_ index: Int) {
            guard index < types.count else {
                completion(nil, nil)
                return
            }
            let uti = types[index]
            if provider.hasItemConformingToTypeIdentifier(uti.identifier) {
                provider.loadFileRepresentation(forTypeIdentifier: uti.identifier) { url, error in
                    if let url = url {
                        // Copy to temp because the provided URL is deleted after this callback
                        let tmp = FileManager.default.temporaryDirectory
                            .appendingPathComponent(url.lastPathComponent)
                        try? FileManager.default.removeItem(at: tmp)
                        try? FileManager.default.copyItem(at: url, to: tmp)
                        completion(tmp, provider.suggestedName)
                    } else {
                        tryNext(index + 1)
                    }
                }
            } else {
                tryNext(index + 1)
            }
        }
        tryNext(0)
    }

    private func postToHub(project: String, filename: String, data: Data,
                           completion: @escaping (Bool, String?) -> Void) {
        guard let url = URL(string: "\(hubBaseURL)/api/ingest") else {
            completion(false, "Invalid URL")
            return
        }

        let boundary = UUID().uuidString
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 120

        var body = Data()

        // Project field
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"project\"\r\n\r\n".data(using: .utf8)!)
        body.append("\(project)\r\n".data(using: .utf8)!)

        // File field
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n".data(using: .utf8)!)

        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        request.httpBody = body

        URLSession.shared.dataTask(with: request) { _, response, error in
            if let error = error {
                completion(false, error.localizedDescription)
                return
            }
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            completion(status == 200, status == 200 ? nil : "HTTP \(status)")
        }.resume()
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
