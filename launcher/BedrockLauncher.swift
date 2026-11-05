import AppKit
import SwiftUI
import Combine
import Darwin

struct Status: Decodable {
    let state: String
    let title: String
    let detail: String
    let progress: Double?
}

@MainActor
final class Launcher: ObservableObject {
    @Published var status = Status(state: "checking", title: "Minecraft on your Mac", detail: "Checking installation…", progress: nil)
    @Published var running = false
    @Published private(set) var market = "CA"
    private var process: Process?
    private var buffer = Data()
    private var cancellationRequested = false
    private enum Operation { case play, signOut, updateGame }
    private var retryOperation = Operation.play
    private let preferences: UserDefaults
    let root: URL

    init(preferences: UserDefaults = .standard) {
        self.preferences = preferences
        let savedMarket = preferences.string(forKey: "storeMarket") ?? "CA"
        _market = Published(initialValue: Self.validMarket(savedMarket) ? savedMarket : "CA")
        let path = Bundle.main.object(forInfoDictionaryKey: "BedrockProjectPath") as? String ?? ""
        root = path.isEmpty ? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Bedrock for Mac") : URL(fileURLWithPath: path)
        start(check: true)
    }

    func start(check: Bool = false, signOut: Bool = false, updateGame: Bool = false) {
        guard !running else { return }
        running = true
        buffer = Data()
        cancellationRequested = false
        if !check { retryOperation = signOut ? .signOut : updateGame ? .updateGame : .play }
        let task = Process()
        let pipe = Pipe()
        let resources = Bundle.main.resourceURL!
        let worker = resources.appendingPathComponent("worker/BedrockWorker")
        let packaged = FileManager.default.isExecutableFile(atPath: worker.path)
        task.executableURL = packaged ? worker : URL(fileURLWithPath: "/usr/bin/python3")
        task.arguments = (packaged ? [] : [root.appendingPathComponent("launcher/setup.py").path]) + ["--market", market] + (check ? ["--status"] : signOut ? ["--sign-out"] : updateGame ? ["--update-game"] : [])
        task.currentDirectoryURL = packaged ? resources : root
        task.standardOutput = pipe
        task.standardError = FileHandle.nullDevice
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        if packaged { env["BEDROCK_BUNDLE"] = resources.path }
        task.environment = env
        do {
            process = task
            if !check { status = Status(state: "busy", title: "Getting ready", detail: "Checking your Mac…", progress: nil) }
            try task.run()
            // Drain stdout before finishing the run. A timed delay can lose the
            // last status or let a previous worker overwrite a new attempt.
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                let reader = pipe.fileHandleForReading
                while true {
                    let data = reader.availableData
                    if data.isEmpty { break }
                    DispatchQueue.main.async { [weak self] in
                        guard let self, self.process === task else { return }
                        self.receive(data)
                    }
                }
                try? reader.close()
                task.waitUntilExit()
                DispatchQueue.main.async { [weak self] in
                    guard let self, self.process === task else { return }
                    if !self.buffer.isEmpty { self.receive(Data([10])) }
                    self.running = false
                    self.process = nil
                    if task.terminationStatus == 0 && ["ready", "new"].contains(self.status.state) {
                        self.retryOperation = .play
                    }
                    if self.cancellationRequested && self.status.state == "cancelling"
                        && task.terminationReason == .uncaughtSignal && task.terminationStatus == SIGTERM {
                        // Cancel can beat the worker's Python signal handler.
                        self.status = Status(state: "cancelled", title: "Setup paused", detail: "Continue when you’re ready.", progress: nil)
                    } else if task.terminationStatus != 0 && self.status.state != "error" {
                        self.status = Status(state: "error", title: "Couldn’t finish setup", detail: "Try again. If it happens again, open the setup log.", progress: nil)
                    } else if ["busy", "checking", "playing", "cancelling"].contains(self.status.state) {
                        self.status = Status(state: "error", title: "Setup stopped", detail: "Try again to continue.", progress: nil)
                    }
                }
            }
        } catch {
            running = false
            process = nil
            status = Status(state: "error", title: "Couldn’t start setup", detail: error.localizedDescription, progress: nil)
        }
    }

    private func receive(_ data: Data) {
        buffer.append(data)
        while let end = buffer.firstIndex(of: 10) {
            let line = buffer[..<end]
            if let next = try? JSONDecoder().decode(Status.self, from: line) {
                // Progress already queued by the worker must not undo Cancel
                // or permit another termination signal during cleanup.
                if !cancellationRequested || ["cancelled", "error", "ready", "new", "update"].contains(next.state) {
                    status = next
                }
            }
            buffer.removeSubrange(...end)
        }
    }

    var canCancel: Bool { running && !cancellationRequested && status.state == "busy" }

    static func validMarket(_ value: String) -> Bool {
        value.utf8.count == 2 && value.utf8.allSatisfy { (65...90).contains($0) }
    }

    func setMarket(_ value: String) {
        guard !running, Self.validMarket(value) else { return }
        preferences.set(value, forKey: "storeMarket")
        market = value
    }

    func cancel() {
        guard canCancel else { return }
        cancellationRequested = true
        status = Status(state: "cancelling", title: "Stopping setup", detail: "Keeping your existing game and saves.", progress: nil)
        process?.terminate()
    }

    func signOut() {
        guard !running else { return }
        let alert = NSAlert()
        alert.messageText = "Sign out of Microsoft?"
        alert.informativeText = "Your game and worlds will stay on this Mac. You can sign in with another account next time you play."
        alert.addButton(withTitle: "Cancel")
        alert.addButton(withTitle: "Sign Out")
        if alert.runModal() == .alertSecondButtonReturn { start(signOut: true) }
    }

    func retry() {
        start(signOut: retryOperation == .signOut, updateGame: retryOperation == .updateGame)
    }

    func updateGame() {
        guard !running else { return }
        let alert = NSAlert()
        alert.messageText = "Update Minecraft?"
        alert.informativeText = "Download the latest version available to your Microsoft account. Your worlds will be kept, with a backup of your current game and settings."
        alert.addButton(withTitle: "Cancel")
        alert.addButton(withTitle: "Update")
        if alert.runModal() == .alertSecondButtonReturn { start(updateGame: true) }
    }

    func showLog() {
        NSWorkspace.shared.open(root.appendingPathComponent("logs/standalone"))
    }
}

struct LauncherWindowAttachment: NSViewRepresentable {
    let attach: (NSWindow) -> Void
    final class View: NSView {
        var attach: ((NSWindow) -> Void)?
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            if let window { attach?(window) }
        }
    }
    func makeNSView(context: Context) -> View {
        let view = View()
        view.attach = attach
        return view
    }
    func updateNSView(_ view: View, context: Context) {
        view.attach = attach
        if let window = view.window { attach(window) }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    var launcher: Launcher? {
        didSet {
            dismissQuitAlert()
            sessionObservation = launcher.map { launcher in
                launcher.$running.combineLatest(launcher.$status)
                    .receive(on: RunLoop.main)
                    .sink { [weak self] _, _ in
                        guard let self, let current = self.launcher else { return }
                        // Read current values: queued publisher events may predate the sheet.
                        if !current.running || current.status.state != self.quitAlertState {
                            self.dismissQuitAlert()
                        }
                    }
            }
        }
    }
    private var sessionObservation: AnyCancellable?
    private var windowCloseObservation: AnyCancellable?
    var reopenWindow: (() -> Void)?
    private var reopeningWindow = false
    private weak var launcherWindow: NSWindow?
    private(set) var quitAlert: NSAlert?
    private var quitAlertState: String?

    func attachWindow(_ window: NSWindow) {
        reopeningWindow = false
        guard launcherWindow !== window else { return }
        launcherWindow = window
        windowCloseObservation = NotificationCenter.default.publisher(for: NSWindow.willCloseNotification, object: window)
            .sink { [weak self] _ in self?.launcherWindow = nil }
    }

    private func requestReopen() {
        guard !reopeningWindow, let reopenWindow else { return }
        reopeningWindow = true
        reopenWindow()
    }

    private func dismissQuitAlert() {
        guard let alert = quitAlert else { return }
        quitAlert = nil
        quitAlertState = nil
        alert.window.sheetParent?.endSheet(alert.window, returnCode: .abort)
        alert.window.orderOut(nil)
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard launcher?.running == true else {
            dismissQuitAlert()
            return .terminateNow
        }
        // Return immediately so worker completion can reach the main queue.
        // Repeated Cmd-Q must reuse the existing sheet, never nest modal loops.
        guard quitAlert == nil else { return .terminateCancel }
        guard let window = launcherWindow else {
            requestReopen()
            return .terminateCancel
        }
        let alert = NSAlert()
        if launcher?.canCancel == true {
            alert.messageText = "Stop setup?"
            alert.informativeText = "You can continue later. Your game and saves will be kept."
            alert.addButton(withTitle: "Keep Going")
            alert.addButton(withTitle: "Stop Setup")
        } else if launcher?.status.state == "playing" {
            alert.messageText = "Minecraft is still running"
            alert.informativeText = "Quit Minecraft first to finish your session safely. You can close the launcher window while you play."
            alert.addButton(withTitle: "Keep Open")
        } else {
            alert.messageText = launcher?.status.state == "cancelling" ? "Setup is stopping" : "Checking installation"
            alert.informativeText = "Wait for this step to finish, then quit the app."
            alert.addButton(withTitle: "Keep Open")
        }
        quitAlert = alert
        quitAlertState = launcher?.status.state
        window.makeKeyAndOrderFront(nil)
        alert.beginSheetModal(for: window) { [weak self, weak alert] response in
            guard let self, let alert, self.quitAlert === alert else { return }
            self.dismissQuitAlert()
            if response == .alertSecondButtonReturn { self.launcher?.cancel() }
        }
        return .terminateCancel
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if let window = launcherWindow { window.makeKeyAndOrderFront(nil) }
        else { requestReopen() }
        // We handled the reopen; suppress the default WindowGroup reopen as well.
        return false
    }
}

struct StoreSettingsView: View {
    @ObservedObject var launcher: Launcher
    @State private var country = ""
    private var normalized: String { country.trimmingCharacters(in: .whitespacesAndNewlines).uppercased() }

    var body: some View {
        Form {
            TextField("Store country code", text: $country)
                .disabled(launcher.running)
            Text("Use your Microsoft Store country, for example CA, US, GB, or TR. This applies to your next sign-in and game update.")
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if !Launcher.validMarket(normalized) {
                Text("Enter a two-letter country code.").font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if launcher.running {
                Text("Wait for setup or Minecraft to finish before changing the country.")
                    .font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Button(country == launcher.market ? "Saved" : "Save") {
                launcher.setMarket(normalized)
                country = launcher.market
            }
            .disabled(launcher.running || !Launcher.validMarket(normalized) || normalized == launcher.market)
            .keyboardShortcut(.defaultAction)
        }
        .padding(24).frame(width: 380)
        .onAppear { country = launcher.market }
    }
}

struct LauncherView: View {
    @ObservedObject var launcher: Launcher
    private var fresh: Bool { launcher.status.state == "new" }
    var body: some View {
        VStack(spacing: 24) {
            Image(systemName: "cube.fill")
                .font(.system(size: 66, weight: .medium))
                .foregroundStyle(.green.gradient)
                .accessibilityHidden(true)
            VStack(spacing: 12) {
                Text(launcher.status.title).font(.system(size: 29, weight: .semibold))
                if fresh || !launcher.status.detail.isEmpty {
                    Text(fresh ? "Sign in with the Microsoft account that owns Minecraft for Windows." : launcher.status.detail)
                        .font(.body).foregroundStyle(.secondary)
                        .multilineTextAlignment(.center).frame(maxWidth: 365).fixedSize(horizontal: false, vertical: true)
                }
            }
            if launcher.running && launcher.status.state != "playing" {
                VStack(spacing: 10) {
                    if let progress = launcher.status.progress {
                        ProgressView(value: progress).accessibilityLabel("Installation progress")
                    } else { ProgressView().controlSize(.small) }
                }.frame(width: 300)
                if launcher.canCancel {
                    Button("Cancel") { launcher.cancel() }
                        .buttonStyle(.plain).foregroundStyle(.secondary)
                        .keyboardShortcut(.cancelAction)
                }
            } else if !launcher.running {
                Button(launcher.status.state == "error" ? "Try Again" : fresh ? "Install & Play" : ["cancelled", "update"].contains(launcher.status.state) ? "Continue" : "Play") {
                    launcher.retry()
                }
                .buttonStyle(.borderedProminent).tint(.green)
                .controlSize(.large).keyboardShortcut(.defaultAction)
                if fresh {
                    Text("Minecraft downloads after sign-in.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            if launcher.status.state == "error" {
                Button("Open Setup Log") { launcher.showLog() }.buttonStyle(.link)
            }
        }
        .padding(40).frame(width: 480, height: 390)
    }
}

@main
struct BedrockLauncherApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var launcher = Launcher()
    @Environment(\.openWindow) private var openWindow
    var body: some Scene {
        WindowGroup("Bedrock for Mac", id: "launcher") {
            LauncherView(launcher: launcher)
                .background(LauncherWindowAttachment { delegate.attachWindow($0) })
                .onAppear {
                    delegate.launcher = launcher
                    let open = openWindow
                    delegate.reopenWindow = { open(id: "launcher") }
                    NSApp.activate(ignoringOtherApps: true)
                }
        }
        .windowResizability(.contentSize)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandGroup(after: .appInfo) {
                Button("Update Minecraft…") { launcher.updateGame() }
                    .disabled(launcher.running)
                Button("Sign Out of Microsoft…") { launcher.signOut() }
                    .disabled(launcher.running || launcher.status.state == "new")
            }
            CommandGroup(replacing: .help) {
                Button("Open Game Data") { NSWorkspace.shared.open(launcher.root) }
                Button("Bedrock for Mac Help") {
                    NSWorkspace.shared.open(URL(string: "https://github.com/1JRobertson/bedrock-mac#readme")!)
                }
                Button("Open Setup Logs") { launcher.showLog() }
            }
        }
        Settings {
            StoreSettingsView(launcher: launcher)
        }
    }
}
