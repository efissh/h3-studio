import Foundation
import CoreGraphics
import ImageIO
import CoreVideo
import CoreImage
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
func makePixelBuffer(_ image: CGImage) throws -> CVPixelBuffer {
    let attrs: [String: Any] = [
        kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA),
        kCVPixelBufferWidthKey as String: image.width,
        kCVPixelBufferHeightKey as String: image.height,
        kCVPixelBufferMetalCompatibilityKey as String: true,
        kCVPixelBufferIOSurfacePropertiesKey as String: [:] as [String: Any]
    ]
    var buffer: CVPixelBuffer?
    let status = CVPixelBufferCreate(kCFAllocatorDefault, image.width, image.height,
                                     kCVPixelFormatType_32BGRA, attrs as CFDictionary, &buffer)
    guard status == kCVReturnSuccess, let buffer = buffer else {
        throw NSError(domain: "H3RifeStream", code: 6,
                      userInfo: [NSLocalizedDescriptionKey: "Could not allocate pixel buffer"])
    }
    CVPixelBufferLockBaseAddress(buffer, [])
    defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
    let info = CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedFirst.rawValue |
                                         CGBitmapInfo.byteOrder32Little.rawValue)
    guard let context = CGContext(data: CVPixelBufferGetBaseAddress(buffer),
                                  width: image.width, height: image.height,
                                  bitsPerComponent: 8,
                                  bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
                                  space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: info.rawValue) else {
        throw NSError(domain: "H3RifeStream", code: 7,
                      userInfo: [NSLocalizedDescriptionKey: "Could not draw image"])
    }
    context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
    return buffer
}
let ciContext = CIContext(options: [.useSoftwareRenderer: false])
func writePNG(_ buffer: CVPixelBuffer, _ path: String) throws {
    let image = CIImage(cvPixelBuffer: buffer)
    guard let cgImage = ciContext.createCGImage(
        image, from: CGRect(x: 0, y: 0,
                            width: CVPixelBufferGetWidth(buffer),
                            height: CVPixelBufferGetHeight(buffer))) else {
        throw NSError(domain: "H3RifeStream", code: 8,
                      userInfo: [NSLocalizedDescriptionKey: "Could not convert output frame"])
    }
    try writeCGImage(cgImage, path)
}
func writeCGImage(_ image: CGImage, _ path: String) throws {
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
                previous: try makePixelBuffer(readPNG(item.a)),
                current: try makePixelBuffer(readPNG(item.b)),
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
