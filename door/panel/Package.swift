// swift-tools-version: 6.0
// Painel do dono da Door (Seção 11). Sem dependências, só POSIX: compila em macOS e Linux como o Hub do Colmeia.
import PackageDescription

let swiftSettings: [SwiftSetting] = [.swiftLanguageMode(.v5)]

let package = Package(
    name: "DoorPanel",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "door-panel", targets: ["door-panel"])],
    targets: [
        .target(name: "DoorPanelKit", swiftSettings: swiftSettings),
        .executableTarget(name: "door-panel", dependencies: ["DoorPanelKit"], swiftSettings: swiftSettings),
        // Sem XCTest nas Command Line Tools: os testes são um executável (`swift run panel-tests`).
        .executableTarget(name: "panel-tests", dependencies: ["DoorPanelKit"], swiftSettings: swiftSettings),
    ]
)
