// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "CodexApprovalMenubar",
    platforms: [
        .macOS(.v14),
    ],
    products: [
        .executable(name: "CodexApprovalMenubar", targets: ["CodexApprovalMenubar"]),
    ],
    targets: [
        .executableTarget(
            name: "CodexApprovalMenubar",
            path: "Sources"
        ),
    ]
)
