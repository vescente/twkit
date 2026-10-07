import Foundation
import Vision
import AppKit
let path = CommandLine.arguments[1]
guard let img = NSImage(contentsOfFile: path),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { print("[]"); exit(1) }
let W = Double(cg.width), H = Double(cg.height)
let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = false
try VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
var out: [[String: Any]] = []
for o in req.results ?? [] {
  guard let c = o.topCandidates(1).first else { continue }
  let b = o.boundingBox
  out.append(["t": c.string, "c": c.confidence,
              "x": Int(b.minX*W), "y": Int((1-b.maxY)*H), "w": Int(b.width*W), "h": Int(b.height*H)])
}
print(String(data: try JSONSerialization.data(withJSONObject: out), encoding: .utf8)!)
