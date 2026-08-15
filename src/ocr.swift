import Foundation
import Vision
import AppKit

// OCR each image path given on the command line, print "=== path" then the
// recognized lines in reading order.
for path in CommandLine.arguments.dropFirst() {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        print("=== \(path)\n[unreadable]")
        continue
    }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    do {
        try handler.perform([req])
    } catch {
        print("=== \(path)\n[error \(error)]")
        continue
    }
    let obs = (req.results ?? []).compactMap { $0 as? VNRecognizedTextObservation }
    // sort top-to-bottom, then left-to-right
    let sorted = obs.sorted {
        let a = $0.boundingBox, b = $1.boundingBox
        if abs(a.midY - b.midY) > 0.012 { return a.midY > b.midY }
        return a.minX < b.minX
    }
    print("=== \(path)")
    for o in sorted {
        if let t = o.topCandidates(1).first, t.confidence > 0.3 {
            print(t.string)
        }
    }
}
