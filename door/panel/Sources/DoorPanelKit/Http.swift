import Foundation
#if canImport(Glibc)
import Glibc
#elseif canImport(Darwin)
import Darwin
#endif

public struct HTTPRequest {
    public var method: String
    public var path: String
    public var query: [String: String]
    public var headers: [String: String]   // chaves em minúsculas
    public var body: Data
    public var peer: String          // who is on the other end of the socket (an IP address); "local" in tests
    public init(method: String, path: String, query: [String: String] = [:], headers: [String: String] = [:], body: Data = Data(), peer: String = "local") {
        self.peer = peer
        self.method = method; self.path = path; self.query = query
        self.headers = Dictionary(uniqueKeysWithValues: headers.map { ($0.key.lowercased(), $0.value) }); self.body = body
    }
    public var cookies: [String: String] {
        var out: [String: String] = [:]
        for part in (headers["cookie"] ?? "").split(separator: ";") {
            let kv = part.split(separator: "=", maxSplits: 1).map { $0.trimmingCharacters(in: .whitespaces) }
            if kv.count == 2 { out[kv[0]] = kv[1] }
        }
        return out
    }
}

public struct HTTPResponse {
    public var status: Int
    public var headers: [String: String]
    public var body: Data
    public init(status: Int, headers: [String: String] = [:], body: Data = Data()) {
        self.status = status; self.headers = headers; self.body = body
    }
    public static func json(_ obj: Any, status: Int = 200) -> HTTPResponse {
        let d = (try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys])) ?? Data("{}".utf8)
        return HTTPResponse(status: status, headers: ["Content-Type": "application/json; charset=utf-8"], body: d)
    }
    public static func text(_ s: String, status: Int = 200, type: String = "text/plain; charset=utf-8") -> HTTPResponse {
        HTTPResponse(status: status, headers: ["Content-Type": type], body: Data(s.utf8))
    }
}

public enum HTTPError: Error { case malformed, tooLarge, closed }

/// Glibc (Linux) types these constants differently from Darwin; these two helpers hide that.
#if canImport(Glibc)
let streamSocketType = Int32(SOCK_STREAM.rawValue)
let shutdownBoth = Int32(SHUT_RDWR)
#else
let streamSocketType = SOCK_STREAM
let shutdownBoth = SHUT_RDWR
#endif

public enum HTTP {
    public static let maxHeader = 16 * 1024
    public static let maxBody = 1 * 1024 * 1024

    /// Interpreta bytes já lidos até o fim dos cabeçalhos. Retorna nil se ainda falta.
    public static func parseHead(_ buf: Data) throws -> (HTTPRequest, bodyOffset: Int, length: Int)? {
        guard let r = buf.range(of: Data("\r\n\r\n".utf8)) else {
            if buf.count > maxHeader { throw HTTPError.tooLarge }
            return nil
        }
        guard r.lowerBound <= maxHeader, let head = String(data: buf[..<r.lowerBound], encoding: .utf8) else { throw HTTPError.malformed }
        var lines = head.components(separatedBy: "\r\n")
        let first = lines.removeFirst().split(separator: " ")
        guard first.count == 3, first[2].hasPrefix("HTTP/1.") else { throw HTTPError.malformed }
        var headers: [String: String] = [:]
        for l in lines {
            guard let c = l.firstIndex(of: ":") else { throw HTTPError.malformed }
            headers[l[..<c].lowercased()] = l[l.index(after: c)...].trimmingCharacters(in: .whitespaces)
        }
        if headers["transfer-encoding"] != nil { throw HTTPError.malformed }   // sem chunked: só Content-Length
        let len = Int(headers["content-length"] ?? "0") ?? -1
        guard len >= 0 else { throw HTTPError.malformed }
        guard len <= maxBody else { throw HTTPError.tooLarge }
        let target = String(first[1])
        let parts = target.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
        var query: [String: String] = [:]
        if parts.count == 2 { query = formDecode(String(parts[1])) }
        let req = HTTPRequest(method: String(first[0]), path: String(parts[0]), query: query, headers: headers)
        return (req, r.upperBound, len)
    }

    public static func formDecode(_ s: String) -> [String: String] {
        var out: [String: String] = [:]
        for pair in s.split(separator: "&") {
            let kv = pair.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            let dec = { (x: Substring) in String(x).replacingOccurrences(of: "+", with: " ").removingPercentEncoding ?? "" }
            out[dec(kv[0])] = kv.count == 2 ? dec(kv[1]) : ""
        }
        return out
    }

    static let reasons = [200: "OK", 204: "No Content", 302: "Found", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
                          405: "Method Not Allowed", 413: "Payload Too Large", 429: "Too Many Requests", 500: "Internal Server Error"]

    public static func serialize(_ r: HTTPResponse) -> Data {
        var h = r.headers
        h["Content-Length"] = String(r.body.count)
        h["Connection"] = "close"
        var out = "HTTP/1.1 \(r.status) \(reasons[r.status] ?? "OK")\r\n"
        for (k, v) in h.sorted(by: { $0.key < $1.key }) { out += "\(k): \(v)\r\n" }
        return Data((out + "\r\n").utf8) + r.body
    }
}

/// Servidor bloqueante, uma thread por conexão, Connection: close. Suficiente para um único dono.
public final class HTTPServer: @unchecked Sendable {
    let handler: (HTTPRequest) -> HTTPResponse
    var fd: Int32 = -1
    /// A thread serves each connection, so the number open at once is capped: a flood of idle connections cannot exhaust the machine.
    public static let maxConnections = 400
    let activeLock = NSLock()
    var active = 0
    public private(set) var port: UInt16 = 0

    public init(handler: @escaping (HTTPRequest) -> HTTPResponse) { self.handler = handler }

    public func start(host: String, port: UInt16) throws {
        fd = socket(AF_INET, streamSocketType, 0)
        guard fd >= 0 else { throw HTTPError.closed }
        var one: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, socklen_t(MemoryLayout<Int32>.size))
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = port.bigEndian
        guard inet_pton(AF_INET, host, &addr.sin_addr) == 1 else { throw HTTPError.malformed }
        let ok = withUnsafePointer(to: &addr) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) } }
        guard ok == 0, listen(fd, 64) == 0 else { throw HTTPError.closed }
        var bound = sockaddr_in(); var len = socklen_t(MemoryLayout<sockaddr_in>.size)
        _ = withUnsafeMutablePointer(to: &bound) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(fd, $0, &len) } }
        self.port = UInt16(bigEndian: bound.sin_port)
        let lfd = fd
        Thread.detachNewThread { [weak self] in
            while true {
                let c = accept(lfd, nil, nil)
                if c < 0 { if errno == EINTR { continue }; return }
                guard let me = self, me.enter() else { close(c); continue }          // over the cap: drop it at once
                Thread.detachNewThread { me.serve(c); me.leave() }
            }
        }
    }

    public func stop() { if fd >= 0 { shutdown(fd, shutdownBoth); close(fd); fd = -1 } }

    func serve(_ c: Int32) {
        defer { close(c) }
        var tv = timeval(tv_sec: 10, tv_usec: 0)
        setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))
        var buf = Data(); var chunk = [UInt8](repeating: 0, count: 8192)
        var parsed: (HTTPRequest, bodyOffset: Int, length: Int)?
        do {
            while parsed == nil {
                let n = recv(c, &chunk, chunk.count, 0)
                if n <= 0 { return }
                buf.append(chunk, count: n)
                parsed = try HTTP.parseHead(buf)
            }
            var (req, off, len) = parsed!
            while buf.count - off < len {
                let n = recv(c, &chunk, chunk.count, 0)
                if n <= 0 { return }
                buf.append(chunk, count: n)
            }
            req.body = buf.subdata(in: off..<(off + len))
            req.peer = peerAddress(c)
            send(c, HTTP.serialize(handler(req)))
        } catch HTTPError.tooLarge {
            send(c, HTTP.serialize(.text("payload too large", status: 413)))
        } catch {
            send(c, HTTP.serialize(.text("bad request", status: 400)))
        }
    }

    func enter() -> Bool { activeLock.lock(); defer { activeLock.unlock() }; if active >= HTTPServer.maxConnections { return false }; active += 1; return true }
    func leave() { activeLock.lock(); active -= 1; activeLock.unlock() }

    func peerAddress(_ c: Int32) -> String {
        var addr = sockaddr_in(); var len = socklen_t(MemoryLayout<sockaddr_in>.size)
        let ok = withUnsafeMutablePointer(to: &addr) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getpeername(c, $0, &len) } }
        guard ok == 0 else { return "unknown" }
        var a = addr.sin_addr; var buf = [CChar](repeating: 0, count: 64)
        return inet_ntop(AF_INET, &a, &buf, 64).map { String(cString: $0) } ?? "unknown"
    }

    func send(_ c: Int32, _ d: Data) {
        d.withUnsafeBytes { p in
            var sent = 0
            while sent < d.count {
                let n = write(c, p.baseAddress!.advanced(by: sent), d.count - sent)
                if n <= 0 { return }
                sent += n
            }
        }
    }
}
