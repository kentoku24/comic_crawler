import AppKit
import SwiftUI

@main
struct CodexApprovalMenubarMain {
    static func main() {
        if #available(macOS 14.0, *) {
            CodexApprovalMenubarApp.main()
        } else {
            let app = NSApplication.shared
            app.setActivationPolicy(.accessory)
            let delegate = LegacyAppDelegate()
            app.delegate = delegate
            app.run()
        }
    }
}

@available(macOS 14.0, *)
struct CodexApprovalMenubarApp: App {
    @StateObject private var store = ApprovalStore.preview()

    var body: some Scene {
        MenuBarExtra("Codex Approval", systemImage: store.menuBarSymbolName) {
            ApprovalMenuView(store: store)
        }
        .menuBarExtraStyle(.window)

        Window("Latest Approval", id: "latest-approval") {
            ApprovalDetailView(request: store.latestRequest)
        }
        .defaultSize(width: 520, height: 420)
    }
}

final class LegacyAppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem?.button?.title = "Codex Approval"
        let menu = NSMenu()
        menu.addItem(withTitle: "Requires macOS 14+ for full MVP", action: nil, keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit", action: #selector(quit), keyEquivalent: "q")
        statusItem?.menu = menu
    }

    @objc private func quit() {
        NSApplication.shared.terminate(nil)
    }
}
