import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import RifeMetal

// Persistent, newline-delimited JSON protocol: one RIFE graph/model load per video.
// Input: {"a":"/path/1.png","b":"/path/2.png","times":[0.4,0.8],"outputs":["...","..."]}
// Output: {"ok":true} or {"ok":false,"error":"..."}. Paths are local to the trusted server.
struct FrameTask: Decodable {
    let a: String
    let b: String
    let times: [Float]
    let outputs: [String]
}
func readPNG(_ path: String) throws -> CGImage {
    let url = URL(fileURLWithPath: path) as CFURL
    guard let src = CGImageSourceCreateWithURL(url, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
        throw NSError(domain: "H3RifeStream", code: 1,
                      userInfo: [NSLocalizedDescriptionKey: "Cannot read input frame"])
    }
    return img
}
func writePNG(_ image: CGImage, _ path: String) throws {
    let url = URL(fileURLWithPath: path) as CFURL
    guard let destination = CGImageDestinationCreateWithURL(
        url, UTType.png.identifier as CFString, 1, nil
    ) else {
        throw NSError(domain: "H3RifeStream", code: 2,
                      userInfo: [NSLocalizedDescriptionKey: "Cannot create frame"])
    }
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else {
        throw NSError(domain: "H3RifeStream", code: 3,
                      userInfo: [NSLocalizedDescriptionKey: "Cannot save frame"])
    }
}
func respond(_ value: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: value) else { return }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
}

do {
    let interpolator = try RifeInterpolator(
        configuration: .bundled(qualityTier: .hq)
    )
    while let line = readLine() {
        do {
            guard let data = line.data(using: .utf8) else { continue }
            let item = try JSONDecoder().decode(FrameTask.self, from: data)
            guard !item.times.isEmpty, item.times.count == item.outputs.count,
                  item.times.count <= 16,
                  item.times.allSatisfy({ $0 > 0 && $0 < 1 }) else {
                throw NSError(domain: "H3RifeStream", code: 4,
                              userInfo: [NSLocalizedDescriptionKey: "Invalid timesteps"])
            }
            let result = try interpolator.interpolate(
                previous: readPNG(item.a), current: readPNG(item.b),
                timesteps: item.times
            )
            guard result.count == item.outputs.count else {
                throw NSError(domain: "H3RifeStream", code: 5,
                              userInfo: [NSLocalizedDescriptionKey: "Output count mismatch"])
            }
            for (img, path) in zip(result, item.outputs) { try writePNG(img, path) }
            respond(["ok": true])
        } catch {
            respond(["ok": false, "error": String(describing: error).prefix(240).description])
        }
    }
} catch {
    FileHandle.standardError.write(Data("RIFE initialization failed: \(error)\n".utf8))
    exit(1)
}
