// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "JevMenuBar",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "JevMenuBar", targets: ["JevMenuBar"])],
    targets: [.executableTarget(name: "JevMenuBar")]
)
