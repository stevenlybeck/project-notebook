import SwiftUI

@main
struct ProjectNotebookApp: App {
    @AppStorage("hubURL", store: UserDefaults(suiteName: "group.projectnotebook"))
    var hubURL: String = ""

    var body: some Scene {
        WindowGroup {
            VStack(spacing: 20) {
                Text("Project Notebook")
                    .font(.title)
                    .fontWeight(.bold)

                Text("Share photos, videos, and audio from any app to your active projects.")
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)

                VStack(alignment: .leading, spacing: 8) {
                    Text("Hub URL")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    TextField("http://your-mac.local:9999", text: $hubURL)
                        .textFieldStyle(.roundedBorder)
                        .autocapitalization(.none)
                        .disableAutocorrection(true)
                        .keyboardType(.URL)
                }
                .padding(.horizontal, 40)

                if !hubURL.isEmpty {
                    Label("Ready — use the Share button in any app", systemImage: "checkmark.circle.fill")
                        .foregroundColor(.green)
                } else {
                    Label("Enter your hub URL to get started", systemImage: "exclamationmark.circle")
                        .foregroundColor(.orange)
                }

                Spacer()
            }
            .padding(.top, 60)
        }
    }
}
