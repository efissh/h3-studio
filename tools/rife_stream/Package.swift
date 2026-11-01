// swift-tools-version: 5.10
import PackageDescription

// Pin upstream explicitly. Upgrade requires review and a new tested commit.
let package = Package(
    name: "H3RifeStream",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(url: "https://github.com/cinemore/rife-metal.git", exact: "0.1.8")
    ],
    targets: [
        .executableTarget(
            name: "h3-rife-stream",
            dependencies: [.product(name: "RifeMetal", package: "rife-metal")]
        )
    ]
)
