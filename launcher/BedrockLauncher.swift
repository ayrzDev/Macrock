import AppKit
import SwiftUI
import Combine
import Darwin

struct Status: Decodable {
    let state: String
    let title: String
    let detail: String
    let progress: Double?
    var gameVersion: String?
    var account: String?
}

@MainActor
final class Launcher: ObservableObject {
    @Published var status = Status(state: "checking", title: "Minecraft on your Mac", detail: "Checking installation…", progress: nil)
    @Published var running = false
    @Published private(set) var market = "CA"
    @Published private(set) var gameVersion: String?
    @Published private(set) var accountStatus = "Microsoft account"
    private var process: Process?
    private var buffer = Data()
    private var cancellationRequested = false
    private enum Operation { case play, signIn, signOut, updateGame }
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

    func start(check: Bool = false, signOut: Bool = false, updateGame: Bool = false, signIn: Bool = false) {
        guard !running else { return }
        running = true
        buffer = Data()
        cancellationRequested = false
        if !check { retryOperation = signOut ? .signOut : signIn ? .signIn : updateGame ? .updateGame : .play }
        let task = Process()
        let pipe = Pipe()
        let resources = Bundle.main.resourceURL!
        let worker = resources.appendingPathComponent("worker/BedrockWorker")
        let packaged = FileManager.default.isExecutableFile(atPath: worker.path)
        task.executableURL = packaged ? worker : URL(fileURLWithPath: "/usr/bin/python3")
        let operation = check ? ["--status"] : signOut ? ["--sign-out"] : signIn ? ["--sign-in"] : updateGame ? ["--update-game"] : []
        task.arguments = (packaged ? [] : [root.appendingPathComponent("launcher/setup.py").path]) + ["--market", market] + operation
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
                    if task.terminationStatus == 0 && ["ready", "new", "update"].contains(self.status.state) {
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
                    if self.retryOperation == .updateGame && self.status.state == "cancelled" && self.gameVersion != nil {
                        self.retryOperation = .play
                        self.status = Status(state: "ready", title: "Update cancelled", detail: "Play the installed release or check for updates again.", progress: nil)
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
                    if ["ready", "new", "update"].contains(next.state) { gameVersion = next.gameVersion }
                    if next.account == "signedIn" { accountStatus = "Signed in" }
                    if next.account == "signedOut" { accountStatus = "Signed out" }
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
        start(signOut: retryOperation == .signOut, updateGame: retryOperation == .updateGame, signIn: retryOperation == .signIn)
    }

    func updateGame() {
        guard !running else { return }
        let alert = NSAlert()
        alert.messageText = "Update Minecraft?"
        alert.informativeText = "Check the latest version available to your Microsoft account. Macrock downloads it only if it differs from the installed package."
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
    private let mint = Color(red: 0.42, green: 0.94, blue: 0.72)
    private var state: String { launcher.status.state }
    private var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "Development"
    }
    private var playLabel: String {
        switch state {
        case "error": "Try Again"
        case "new": "Install & Play"
        case "cancelled", "update": "Continue"
        default: "Play"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Label("Macrock", systemImage: "cube.transparent.fill")
                    .font(.system(size: 26, weight: .bold, design: .rounded))
                    .foregroundStyle(mint)
                Spacer()
                Text("Launcher " + appVersion)
                    .font(.caption.monospaced())
                    .foregroundStyle(.white.opacity(0.72))
                    .padding(.horizontal, 12).padding(.vertical, 6)
                    .background(.white.opacity(0.08), in: Capsule())
            }

            hero

            HStack(alignment: .top, spacing: 14) {
                detailCard("Game version", icon: "square.stack.3d.up", value: launcher.gameVersion ?? "Not installed") {
                    Menu("Version options") {
                        if let version = launcher.gameVersion {
                            Button("Play " + version) { launcher.start() }
                            Button("Check for updates…") { launcher.updateGame() }
                        } else {
                            Button("Install latest release") { launcher.start() }
                        }
                    }
                    .disabled(launcher.running)
                }
                detailCard("Account", icon: "person.crop.circle", value: launcher.accountStatus) {
                    Menu("Manage account") {
                        Button("Sign in with Microsoft…") { launcher.start(signIn: true) }
                        Button("Sign out…") { launcher.signOut() }
                        Link("Create a Microsoft account", destination: URL(string: "https://signup.live.com/")!)
                    }
                    .disabled(launcher.running)
                }
            }

            HStack(spacing: 16) {
                Button("Game Data", systemImage: "folder") { NSWorkspace.shared.open(launcher.root) }
                Button("Setup Logs", systemImage: "doc.text.magnifyingglass") { launcher.showLog() }
                Spacer()
                SettingsLink { Label("Settings", systemImage: "gearshape") }
            }
            .buttonStyle(.plain)
            .font(.callout)
            .foregroundStyle(.white.opacity(0.75))
        }
        .padding(24)
        .frame(width: 720)
        .background(Color(red: 0.055, green: 0.075, blue: 0.09))
        .preferredColorScheme(.dark)
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("MINECRAFT")
                .font(.caption.monospaced().weight(.semibold))
                .tracking(3)
                .foregroundStyle(mint)
            Text("Bedrock Edition")
                .font(.system(size: 38, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
                .accessibilityAddTraits(.isHeader)
            Text(launcher.status.title)
                .font(.headline)
                .foregroundStyle(.white.opacity(0.92))
            let detail = state == "new" && launcher.status.detail.isEmpty
                ? "Sign in with the account that owns Minecraft for Windows."
                : launcher.status.detail
            if !detail.isEmpty {
                Text(detail)
                    .font(.callout)
                    .foregroundStyle(.white.opacity(0.75))
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 14) {
                if launcher.running && state != "playing" {
                    if let progress = launcher.status.progress {
                        ProgressView(value: progress)
                            .tint(mint)
                            .frame(maxWidth: 220)
                            .accessibilityLabel("Installation progress")
                    } else {
                        ProgressView().controlSize(.small)
                    }
                    if launcher.canCancel {
                        Button("Cancel") { launcher.cancel() }
                            .keyboardShortcut(.cancelAction)
                    }
                } else if !launcher.running {
                    Button(playLabel, systemImage: "play.fill") { launcher.retry() }
                        .buttonStyle(PlayButtonStyle(color: mint))
                        .keyboardShortcut(.defaultAction)
                }
            }
            .padding(.top, 6)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(26)
        .background(alignment: .trailing) {
            RoundedRectangle(cornerRadius: 22)
                .fill(LinearGradient(colors: [Color(red: 0.075, green: 0.19, blue: 0.17),
                                              Color(red: 0.13, green: 0.28, blue: 0.23)],
                                     startPoint: .topLeading, endPoint: .bottomTrailing))
                .overlay(alignment: .trailing) {
                    Image(systemName: "cube.transparent.fill")
                        .font(.system(size: 178, weight: .ultraLight))
                        .rotationEffect(.degrees(-14))
                        .foregroundStyle(mint.opacity(0.13))
                        .padding(.trailing, 18)
                        .accessibilityHidden(true)
                }
                .clipShape(RoundedRectangle(cornerRadius: 22))
        }
    }

    private func detailCard<Actions: View>(_ title: String, icon: String, value: String,
                                          @ViewBuilder actions: () -> Actions) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Label(title, systemImage: icon)
                .font(.caption.weight(.semibold))
                .foregroundStyle(mint)
            Text(value)
                .font(.title3.weight(.semibold))
                .foregroundStyle(.white)
            actions()
                .controlSize(.regular)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(.white.opacity(0.055), in: RoundedRectangle(cornerRadius: 16))
    }
}

private struct PlayButtonStyle: ButtonStyle {
    let color: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(.black)
            .padding(.horizontal, 22)
            .frame(minHeight: 44)
            .background(color.opacity(configuration.isPressed ? 0.75 : 1), in: RoundedRectangle(cornerRadius: 12))
    }
}

@main
struct BedrockLauncherApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var launcher = Launcher()
    @Environment(\.openWindow) private var openWindow
    var body: some Scene {
        WindowGroup("Macrock", id: "launcher") {
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
                Button("Macrock Help") {
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
