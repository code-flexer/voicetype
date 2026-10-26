import AVFoundation
import CoreGraphics
import CoreMedia
import Foundation
import ScreenCaptureKit

enum CaptureError: Error, CustomStringConvertible {
    case message(String)
    var description: String {
        switch self { case .message(let value): return value }
    }
}

final class AudioCapture: NSObject, SCStreamOutput, SCStreamDelegate {
    let queue = DispatchQueue(label: "voicetype.audio.capture")
    var converters: [SCStreamOutputType: AVAudioConverter] = [:]
    var nextTimestamp: [SCStreamOutputType: Double] = [:]
    var failure: Error?
    var stopped: (() -> Void)?

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        queue.async {
            self.failure = error
            self.stopped?()
        }
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer,
                of type: SCStreamOutputType) {
        process(sample, type: type)
    }

    func process(_ sample: CMSampleBuffer, type: SCStreamOutputType) {
        guard failure == nil, type == .audio || type == .microphone,
              CMSampleBufferIsValid(sample),
              let description = CMSampleBufferGetFormatDescription(sample),
              let basic = CMAudioFormatDescriptionGetStreamBasicDescription(description),
              let inputFormat = AVAudioFormat(streamDescription: basic) else { return }
        do {
            var bytesNeeded = 0
            var block: CMBlockBuffer?
            _ = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
                sample, bufferListSizeNeededOut: &bytesNeeded, bufferListOut: nil,
                bufferListSize: 0, blockBufferAllocator: nil, blockBufferMemoryAllocator: nil,
                flags: 0, blockBufferOut: &block)
            let memory = UnsafeMutableRawPointer.allocate(byteCount: bytesNeeded, alignment: 16)
            defer { memory.deallocate() }
            let list = memory.bindMemory(to: AudioBufferList.self, capacity: 1)
            let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
                sample, bufferListSizeNeededOut: nil, bufferListOut: list,
                bufferListSize: bytesNeeded, blockBufferAllocator: nil,
                blockBufferMemoryAllocator: nil, flags: 0, blockBufferOut: &block)
            let frameCount = CMSampleBufferGetNumSamples(sample)
            guard status == noErr, frameCount > 0,
                  let input = AVAudioPCMBuffer(pcmFormat: inputFormat,
                                              frameCapacity: AVAudioFrameCount(frameCount)),
                  let outputFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                                   sampleRate: 16000, channels: 1,
                                                   interleaved: false) else {
                throw CaptureError.message("Unable to decode captured audio: \(status)")
            }
            input.frameLength = AVAudioFrameCount(frameCount)
            let sourceBuffers = UnsafeMutableAudioBufferListPointer(list)
            let destinationBuffers = UnsafeMutableAudioBufferListPointer(input.mutableAudioBufferList)
            guard sourceBuffers.count == destinationBuffers.count else {
                throw CaptureError.message("Captured audio channel layout changed")
            }
            for index in sourceBuffers.indices {
                let source = sourceBuffers[index]
                let destination = destinationBuffers[index]
                guard source.mDataByteSize <= destination.mDataByteSize,
                      let from = source.mData, let to = destination.mData else {
                    throw CaptureError.message("Captured audio buffer size is invalid")
                }
                memcpy(to, from, Int(source.mDataByteSize))
            }
            if converters[type]?.inputFormat != inputFormat {
                converters[type] = AVAudioConverter(from: inputFormat, to: outputFormat)
                nextTimestamp[type] = CMSampleBufferGetPresentationTimeStamp(sample).seconds
            }
            guard let converter = converters[type],
                  let output = AVAudioPCMBuffer(
                    pcmFormat: outputFormat,
                    frameCapacity: AVAudioFrameCount(ceil(Double(input.frameLength) * 16000 / inputFormat.sampleRate))) else {
                throw CaptureError.message("Unable to create the local audio converter")
            }
            var supplied = false
            var conversionError: NSError?
            let conversion = converter.convert(to: output, error: &conversionError) { _, state in
                if supplied { state.pointee = .noDataNow; return nil }
                supplied = true
                state.pointee = .haveData
                return input
            }
            if conversion == .error {
                throw conversionError ?? CaptureError.message("Audio conversion failed") as NSError
            }
            let timestamp = CMSampleBufferGetPresentationTimeStamp(sample).seconds
            guard timestamp.isFinite else { throw CaptureError.message("Invalid audio timestamp") }
            if let expected = nextTimestamp[type], abs(timestamp - expected) > 0.2 {
                nextTimestamp[type] = timestamp
            }
            try write(output, type: type)
        } catch {
            failure = error
            stopped?()
        }
    }

    func write(_ output: AVAudioPCMBuffer, type: SCStreamOutputType) throws {
        guard output.frameLength > 0, let channel = output.floatChannelData?[0],
              let timestamp = nextTimestamp[type] else { return }
        var data = Data("WKAE".utf8)
        for number in [UInt32(type == .audio ? 1 : 2), UInt32(16000), UInt32(output.frameLength)] {
            var value = number.littleEndian
            withUnsafeBytes(of: &value) { data.append(contentsOf: $0) }
        }
        var timeBits = timestamp.bitPattern.littleEndian
        withUnsafeBytes(of: &timeBits) { data.append(contentsOf: $0) }
        data.append(UnsafeBufferPointer(start: channel, count: Int(output.frameLength)))
        try FileHandle.standardOutput.write(contentsOf: data)
        nextTimestamp[type] = timestamp + Double(output.frameLength) / 16000
    }

    func flush() {
        do {
            for (type, converter) in converters {
                guard let output = AVAudioPCMBuffer(pcmFormat: converter.outputFormat, frameCapacity: 4096) else {
                    throw CaptureError.message("Unable to flush the audio converter")
                }
                var error: NSError?
                let result = converter.convert(to: output, error: &error) { _, state in
                    state.pointee = .endOfStream
                    return nil
                }
                if result == .error {
                    throw error ?? CaptureError.message("Unable to finish audio conversion") as NSError
                }
                try write(output, type: type)
            }
        } catch {
            failure = error
        }
    }
}

@main
struct CaptureMain {
    static func selfTest() throws {
        var basic = AudioStreamBasicDescription(mSampleRate: 48000,
            mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked,
            mBytesPerPacket: 4, mFramesPerPacket: 1, mBytesPerFrame: 4,
            mChannelsPerFrame: 1, mBitsPerChannel: 32, mReserved: 0)
        var description: CMAudioFormatDescription?
        guard CMAudioFormatDescriptionCreate(allocator: nil, asbd: &basic,
            layoutSize: 0, layout: nil, magicCookieSize: 0, magicCookie: nil,
            extensions: nil, formatDescriptionOut: &description) == noErr,
              let description else { throw CaptureError.message("Self-test format creation failed") }
        let recorder = AudioCapture()
        for kind in [SCStreamOutputType.audio, .microphone] {
            for index in 0..<3 {
                let samples: [Float] = (0..<4800).map {
                    0.25 * sin(Float(2 * Double.pi * 440 * Double($0 + index * 4800) / 48000))
                }
                var block: CMBlockBuffer?
                guard CMBlockBufferCreateWithMemoryBlock(allocator: nil, memoryBlock: nil,
                    blockLength: samples.count * 4, blockAllocator: nil,
                    customBlockSource: nil, offsetToData: 0, dataLength: samples.count * 4,
                    flags: 0, blockBufferOut: &block) == noErr, let block else {
                    throw CaptureError.message("Self-test sample allocation failed")
                }
                let copied = samples.withUnsafeBytes {
                    CMBlockBufferReplaceDataBytes(with: $0.baseAddress!, blockBuffer: block,
                                                   offsetIntoDestination: 0, dataLength: $0.count)
                }
                guard copied == noErr else { throw CaptureError.message("Self-test sample copy failed") }
                var sample: CMSampleBuffer?
                guard CMAudioSampleBufferCreateReadyWithPacketDescriptions(allocator: nil,
                    dataBuffer: block, formatDescription: description, sampleCount: 4800,
                    presentationTimeStamp: CMTime(seconds: 123 + Double(index) / 10,
                                                  preferredTimescale: 48000),
                    packetDescriptions: nil, sampleBufferOut: &sample) == noErr,
                      let sample else { throw CaptureError.message("Self-test sample buffer creation failed") }
                recorder.process(sample, type: kind)
            }
        }
        recorder.flush()
        if let error = recorder.failure { throw error }
    }

    static func main() async {
        do {
            if CommandLine.arguments.contains("--self-test") {
                try selfTest()
                return
            }
            if CommandLine.arguments.contains("--authorize") {
                _ = await AVCaptureDevice.requestAccess(for: .audio)
                if !CGPreflightScreenCaptureAccess() { _ = CGRequestScreenCaptureAccess() }
            }
            let permissions = [
                "microphone": AVCaptureDevice.authorizationStatus(for: .audio) == .authorized,
                "system_audio": CGPreflightScreenCaptureAccess(),
            ]
            if CommandLine.arguments.contains("--check") || CommandLine.arguments.contains("--authorize") {
                let json = try JSONSerialization.data(withJSONObject: permissions, options: .sortedKeys)
                try FileHandle.standardOutput.write(contentsOf: json + Data([10]))
                return
            }
            guard permissions["microphone"] == true, permissions["system_audio"] == true else {
                throw CaptureError.message("Music mode requires Microphone and Screen & System Audio Recording permission for VoiceType Audio. Use the Grant audio permissions menu, then restart VoiceType if macOS requests it.")
            }
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            guard let display = content.displays.first(where: { $0.displayID == CGMainDisplayID() }) else {
                throw CaptureError.message("The main display is unavailable for system-audio capture")
            }
            let config = SCStreamConfiguration()
            config.width = 16
            config.height = 16
            config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
            config.showsCursor = false
            config.capturesAudio = true
            config.excludesCurrentProcessAudio = true
            config.sampleRate = 16000
            config.channelCount = 1
            config.captureMicrophone = true
            let filter = SCContentFilter(display: display, excludingWindows: [])
            let recorder = AudioCapture()
            let stream = SCStream(filter: filter, configuration: config, delegate: recorder)
            try stream.addStreamOutput(recorder, type: .audio, sampleHandlerQueue: recorder.queue)
            try stream.addStreamOutput(recorder, type: .microphone, sampleHandlerQueue: recorder.queue)
            let (stop, continuation) = AsyncStream<Void>.makeStream()
            recorder.stopped = { continuation.yield(()) }
            signal(SIGINT, SIG_IGN)
            signal(SIGTERM, SIG_IGN)
            let sources = [SIGINT, SIGTERM].map { number in
                let source = DispatchSource.makeSignalSource(signal: number, queue: .main)
                source.setEventHandler { continuation.yield(()) }
                source.resume()
                return source
            }
            try await stream.startCapture()
            for await _ in stop { break }
            try await stream.stopCapture()
            recorder.queue.sync { recorder.flush() }
            sources.forEach { $0.cancel() }
            if let error = recorder.failure { throw error }
        } catch {
            let message = "ERROR: \(error)\n"
            try? FileHandle.standardError.write(contentsOf: Data(message.utf8))
            exit(1)
        }
    }
}
