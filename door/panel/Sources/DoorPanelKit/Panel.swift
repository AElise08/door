import Foundation
#if canImport(Glibc)
import Glibc
#endif

public struct PanelConfig {
    /// Single-tenant shortcut (development / one owner). Multi-tenant deployments use the admin API instead.
    public var ownerToken: String?
    public var agentToken: String?
    /// Operator token for /admin/*. Without it the admin API does not exist.
    public var adminToken: String?
    /// JSON file with tenants (token hashes, plan). Written 0600.
    public var storePath: String?
    public var secureCookie: Bool
    public var trustProxy: Bool
    public var now: () -> Date
    public init(ownerToken: String? = nil, agentToken: String? = nil, adminToken: String? = nil, storePath: String? = nil,
                secureCookie: Bool = false, trustProxy: Bool = false, now: @escaping () -> Date = Date.init) {
        self.ownerToken = ownerToken; self.agentToken = agentToken; self.adminToken = adminToken; self.storePath = storePath
        self.secureCookie = secureCookie; self.trustProxy = trustProxy; self.now = now
    }
}

final class Tenant {
    let id: String
    var name: String
    var ownerHash: String
    var agentHash: String
    var createdAt: Double
    var disabled = false
    var planStatus: String?
    var planUntil: Double = 0
    // runtime only
    var snapshot: Data?
    var snapshotAt: Date?
    var commands: [[String: Any]] = []
    var ownerSeen: Date?
    var links: [String: Link] = [:]
    var cards: [String: Card] = [:]
    var signins: [String: Date] = [:]      // sha256(one-time sign-in code) -> expiry (never persisted)
    init(id: String, name: String, ownerHash: String, agentHash: String, createdAt: Double) {
        self.id = id; self.name = name; self.ownerHash = ownerHash; self.agentHash = agentHash; self.createdAt = createdAt
    }
    var persisted: [String: Any] {
        var d: [String: Any] = ["id": id, "name": name, "owner_hash": ownerHash, "agent_hash": agentHash, "created_at": createdAt, "disabled": disabled]
        if let s = planStatus { d["plan_status"] = s; d["plan_until"] = planUntil }
        return d
    }
}

func constantTimeEqual(_ a: String, _ b: String) -> Bool {
    let x = Array(a.utf8), y = Array(b.utf8)
    var diff = x.count ^ y.count
    for i in 0..<max(x.count, y.count) { diff |= Int(i < x.count ? x[i] : 0) ^ Int(i < y.count ? y[i] : 0) }
    return diff == 0
}

func randomHex(_ bytes: Int) -> String {
    var g = SystemRandomNumberGenerator()
    return (0..<bytes).map { _ in String(format: "%02x", UInt8.random(in: 0...255, using: &g)) }.joined()
}

/// Panel state. Each tenant (customer) has its own owner token, agent token, snapshot, command queue and plan.
/// Owner identity is issued here (session), never declared by the client.
public final class Panel: @unchecked Sendable {
    let cfg: PanelConfig
    let lock = NSLock()
    var tenants: [String: Tenant] = [:]
    var byOwner: [String: String] = [:]    // sha256(owner token) -> tenant id
    var byAgent: [String: String] = [:]    // sha256(agent token) -> tenant id
    var linkIndex: [String: (tenant: String, link: String)] = [:]   // sha256(link token) -> where it lives
    var sessions: [String: (tenant: String, exp: Date)] = [:]
    var loginFailures: [String: [Date]] = [:]       // failed sign-ins per client, so a stranger cannot lock the owner out
    var loginFailuresAll: [Date] = []               // and a global ceiling on guessing
    var _pendingLinks: [[String: Any]] = []
    var _pendingCards: [[String: Any]] = []
    static let sessionTTL: TimeInterval = 30 * 86400        // stay signed in for a month; sessions survive a restart (stored as hashes)
    static let maxQueue = 200
    static let maxTenants = 5000

    public init(_ cfg: PanelConfig) {
        self.cfg = cfg
        loadStore()
        if let o = cfg.ownerToken, let a = cfg.agentToken, !tenants.values.contains(where: { $0.ownerHash == SHA256.hex(o) }) {
            let t = Tenant(id: "t_default", name: "Door", ownerHash: SHA256.hex(o), agentHash: SHA256.hex(a), createdAt: cfg.now().timeIntervalSince1970)
            tenants[t.id] = t; index(t)
        }
        attachLinks()
    }

    // MARK: tenants
    func index(_ t: Tenant) { byOwner[t.ownerHash] = t.id; byAgent[t.agentHash] = t.id }
    func unindex(_ t: Tenant) { byOwner[t.ownerHash] = nil; byAgent[t.agentHash] = nil }

    func loadStore() {
        guard let path = cfg.storePath, let d = FileManager.default.contents(atPath: path),
              let root = try? JSONSerialization.jsonObject(with: d) else { return }
        let arr: [[String: Any]] = (root as? [[String: Any]]) ?? ((root as? [String: Any])?["tenants"] as? [[String: Any]]) ?? []
        let links: [[String: Any]] = ((root as? [String: Any])?["links"] as? [[String: Any]]) ?? []
        for o in arr {
            guard let id = o["id"] as? String, let name = o["name"] as? String, let oh = o["owner_hash"] as? String, let ah = o["agent_hash"] as? String else { continue }
            let t = Tenant(id: id, name: name, ownerHash: oh, agentHash: ah, createdAt: (o["created_at"] as? Double) ?? 0)
            t.disabled = (o["disabled"] as? Bool) ?? false
            t.planStatus = o["plan_status"] as? String
            t.planUntil = (o["plan_until"] as? Double) ?? 0
            tenants[id] = t
            if !t.disabled { index(t) }
        }
        for o in ((root as? [String: Any])?["sessions"] as? [[String: Any]]) ?? [] {
            if let h = o["h"] as? String, let t = o["tenant"] as? String, let e = o["exp"] as? Double, Date(timeIntervalSince1970: e) > cfg.now() {
                sessions[h] = (t, Date(timeIntervalSince1970: e))
            }
        }
        pendingLinks = links
        _pendingCards = ((root as? [String: Any])?["cards"] as? [[String: Any]]) ?? []
        attachLinks()
    }

    var pendingLinks: [[String: Any]] {
        get { _pendingLinks }
        set { _pendingLinks = newValue }
    }

    /// Links of the single-tenant default tenant are attached once that tenant exists (it is created after the store loads).
    func attachLinks() {
        var keep: [[String: Any]] = []
        for o in _pendingLinks {
            guard let tid = o["tenant"] as? String, let t = tenants[tid], let id = o["id"] as? String, let th = o["token_hash"] as? String else { keep.append(o); continue }
            let l = Link(id: id, tokenHash: th, name: (o["name"] as? String) ?? "", days: (o["days"] as? Int) ?? 30,
                         created: (o["created"] as? Double) ?? 0, expires: (o["expires"] as? Double) ?? 0)
            l.bindHash = o["bind_hash"] as? String
            l.revoked = (o["revoked"] as? Bool) ?? false
            t.links[id] = l
            if !l.revoked { linkIndex[th] = (tid, id) }
        }
        _pendingLinks = keep
        var keepCards: [[String: Any]] = []
        for o in _pendingCards {
            guard let tid = o["tenant"] as? String, let t = tenants[tid], let id = o["id"] as? String, let title = o["title"] as? String else { keepCards.append(o); continue }
            let card = Card(id: id, title: title, note: (o["note"] as? String) ?? "", column: Panel.columns.contains((o["column"] as? String) ?? "") ? (o["column"] as! String) : "todo",
                            urgent: (o["urgent"] as? Bool) ?? false, important: (o["important"] as? Bool) ?? false, owner: (o["owner"] as? String) ?? "owner",
                            now: (o["created"] as? Double) ?? 0)
            card.updated = (o["updated"] as? Double) ?? card.created
            card.requestId = o["request_id"] as? String; card.verdict = o["verdict"] as? String; card.proof = o["proof"] as? String
            t.cards[id] = card
        }
        _pendingCards = keepCards
    }

    /// Caller holds the lock.
    func saveStore() {
        guard let path = cfg.storePath else { return }
        let arr = tenants.values.filter { $0.id != "t_default" }.sorted { $0.createdAt < $1.createdAt }.map { $0.persisted }
        let links = tenants.values.flatMap { t in t.links.values.map { l -> [String: Any] in var d = l.persisted; d["tenant"] = t.id; return d } }
        let cards = tenants.values.flatMap { t in t.cards.values.map { c -> [String: Any] in var d = c.json; d["tenant"] = t.id; return d } }
        let t0 = cfg.now()
        let live = sessions.filter { $0.value.exp > t0 }.map { ["h": $0.key, "tenant": $0.value.tenant, "exp": $0.value.exp.timeIntervalSince1970] as [String: Any] }
        guard let d = try? JSONSerialization.data(withJSONObject: ["tenants": arr, "links": links, "cards": cards, "sessions": live], options: [.sortedKeys]) else { return }
        let tmp = path + ".tmp"
        guard FileManager.default.createFile(atPath: tmp, contents: d, attributes: [.posixPermissions: 0o600]) else { return }
        _ = rename(tmp, path)          // atomic replace on macOS and Linux (replaceItemAt needs the destination to exist already on Linux)
    }

    // MARK: routing
    public func handle(_ r: HTTPRequest) -> HTTPResponse {
        var res = route(r)
        res.headers["Cache-Control"] = "no-store"
        res.headers["X-Content-Type-Options"] = "nosniff"
        res.headers["X-Frame-Options"] = "DENY"
        res.headers["Referrer-Policy"] = "same-origin"
        return res
    }

    func route(_ r: HTTPRequest) -> HTTPResponse {
        if r.path.hasPrefix("/admin/") || r.path == "/admin" { return admin(r) }
        if r.path.hasPrefix("/c/") || r.path.hasPrefix("/chat/") { return guestRoute(r) }
        if r.method == "GET" && r.path.hasPrefix("/signin/") { return signin(r) }
        switch (r.method, r.path) {
        case ("GET", "/healthz"): return .text("ok")
        case ("GET", "/"): return tenantFor(r) != nil ? page(Dashboard.html) : page(Dashboard.login(error: nil))
        case ("POST", "/login"): return login(r)
        case ("POST", "/logout"): return logout(r)
        case ("GET", "/api/state"): return state(r)
        case ("POST", "/api/command"): return command(r)
        case ("PUT", "/agent/snapshot"): return agentSnapshot(r)
        case ("GET", "/agent/commands"): return agentCommands(r)
        case ("POST", "/agent/ack"): return agentAck(r)
        case ("GET", "/agent/inbox"): return agentInbox(r)
        case ("POST", "/agent/inbox/ack"): return agentInboxAck(r)
        case ("POST", "/agent/chat"): return agentChat(r)
        case ("POST", "/agent/card"): return agentCard(r)
        case ("POST", "/agent/links"): return agentLinks(r)
        case ("POST", "/agent/signin"): return agentSignin(r)
        default: return .text("not found", status: 404)
        }
    }

    // MARK: HTML with CSP nonce
    func page(_ html: String) -> HTTPResponse {
        let nonce = randomHex(12)
        var res = HTTPResponse.text(html.replacingOccurrences(of: "{{NONCE}}", with: nonce), type: "text/html; charset=utf-8")
        res.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'nonce-\(nonce)'; style-src 'nonce-\(nonce)'; style-src-attr 'unsafe-inline'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        return res
    }

    // MARK: owner authentication
    func tenantFor(_ r: HTTPRequest) -> Tenant? {
        guard let sid = r.cookies["door_session"] else { return nil }
        lock.lock(); defer { lock.unlock() }
        let key = SHA256.hex(sid)
        guard let s = sessions[key] else { return nil }
        if s.exp < cfg.now() { sessions[key] = nil; return nil }
        guard let t = tenants[s.tenant], !t.disabled else { sessions[key] = nil; return nil }
        return t
    }

    /// Who is asking. Behind our own TLS proxy every request comes from the proxy, so (only if the operator says the proxy is trusted)
    /// the first X-Forwarded-For address is used instead.
    func clientKey(_ r: HTTPRequest) -> String {
        if cfg.trustProxy, let f = r.headers["x-forwarded-for"], let first = f.split(separator: ",").first {
            return String(first.trimmingCharacters(in: .whitespaces).prefix(45))
        }
        return r.peer
    }

    /// Caller holds the lock. 5 wrong tries a minute per client; 100 a minute in total across everyone.
    func guessingBlocked(_ who: String, _ now: Date) -> Bool {
        loginFailures[who] = (loginFailures[who] ?? []).filter { now.timeIntervalSince($0) <= 60 }
        loginFailuresAll.removeAll { now.timeIntervalSince($0) > 60 }
        if loginFailures[who]!.isEmpty { loginFailures[who] = nil }
        return (loginFailures[who]?.count ?? 0) >= 5 || loginFailuresAll.count >= 100
    }

    func noteFailure(_ who: String, _ now: Date) {
        loginFailures[who, default: []].append(now); loginFailuresAll.append(now)
        if loginFailures.count > 5000 { loginFailures = loginFailures.filter { !$0.value.isEmpty } }
    }

    func sameOrigin(_ r: HTTPRequest) -> Bool {
        if let site = r.headers["sec-fetch-site"] { return site == "same-origin" || site == "none" }
        guard let o = r.headers["origin"] else { return true }
        guard let host = r.headers["host"] else { return false }
        return o.hasSuffix("://" + host)
    }

    func login(_ r: HTTPRequest) -> HTTPResponse {
        guard sameOrigin(r) else { return .text("invalid origin", status: 403) }
        let now = cfg.now()
        let who = clientKey(r)
        lock.lock()
        let blocked = guessingBlocked(who, now)
        lock.unlock()
        if blocked { return .text("too many attempts; wait 1 minute", status: 429) }
        let token = HTTP.formDecode(String(data: r.body, encoding: .utf8) ?? "")["token"] ?? ""
        lock.lock()
        let tid = byOwner[SHA256.hex(token)]
        lock.unlock()
        guard let tenant = tid else {
            lock.lock(); noteFailure(who, now); lock.unlock()
            var res = page(Dashboard.login(error: "Invalid token."))
            res.status = 401
            return res
        }
        let sid = randomHex(32)
        lock.lock(); sessions[SHA256.hex(sid)] = (tenant, now.addingTimeInterval(Panel.sessionTTL)); loginFailures[who] = nil; saveStore(); lock.unlock()
        let secure = cfg.secureCookie ? "; Secure" : ""
        return HTTPResponse(status: 302, headers: ["Location": "/", "Set-Cookie": "door_session=\(sid); HttpOnly; SameSite=Strict; Path=/; Max-Age=\(Int(Panel.sessionTTL))\(secure)"])
    }

    func logout(_ r: HTTPRequest) -> HTTPResponse {
        guard sameOrigin(r), r.headers["x-door-panel"] == "1" || r.headers["content-type"]?.hasPrefix("application/x-www-form-urlencoded") == true else { return .text("forbidden", status: 403) }
        if let sid = r.cookies["door_session"] { lock.lock(); sessions[SHA256.hex(sid)] = nil; saveStore(); lock.unlock() }
        return HTTPResponse(status: 302, headers: ["Location": "/", "Set-Cookie": "door_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"])
    }

    // MARK: owner API
    func state(_ r: HTTPRequest) -> HTTPResponse {
        guard let t = tenantFor(r) else { return .json(["error": "not authenticated"], status: 401) }
        let now = cfg.now()
        lock.lock(); defer { lock.unlock() }
        t.ownerSeen = now
        var snap: Any = NSNull()
        if let d = t.snapshot, let o = try? JSONSerialization.jsonObject(with: d) { snap = o }
        let age = t.snapshotAt.map { now.timeIntervalSince($0) }
        return .json(["snapshot": snap, "snapshot_age_s": age.map { Int($0) } as Any, "stale": (age ?? .infinity) > 30,
                      "pending_commands": t.commands.count, "tenant": t.name, "links": linksJSON(t), "cards": cardsJSON(t)])
    }

    static let idRe = try! NSRegularExpression(pattern: "^[0-9A-Z]{26}$")
    static let gidRe = try! NSRegularExpression(pattern: "^[0-9A-Z]{26}$")
    static let hashRe = try! NSRegularExpression(pattern: "^[0-9a-f]{64}$")
    static let phoneRe = try! NSRegularExpression(pattern: "^\\+[1-9][0-9]{6,14}$")
    static let codeRe = try! NSRegularExpression(pattern: "^[A-Z0-9-]{4,20}$")

    static func match(_ re: NSRegularExpression, _ s: String) -> Bool {
        re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil
    }

    /// Only these commands exist. No free-form commands: the panel is the only way to widen access (spec 8.3).
    public static func validate(_ c: [String: Any]) -> [String: Any]? {
        guard let t = c["type"] as? String else { return nil }
        switch t {
        case "approve", "deny":
            // The decision is bound to the exact text the owner saw (spec 8.3).
            guard let id = c["request_id"] as? String, match(idRe, id), let h = c["text_hash"] as? String, match(hashRe, h) else { return nil }
            return ["type": t, "request_id": id, "text_hash": h]
        case "cancel", "release", "discard":
            guard let id = c["request_id"] as? String, match(idRe, id) else { return nil }
            return ["type": t, "request_id": id]
        case "suspend", "revoke", "reactivate":
            guard let g = c["guest_id"] as? String, match(gidRe, g) else { return nil }
            return ["type": t, "guest_id": g]
        case "pause", "resume":
            return ["type": t]
        case "set_approval":
            guard let m = c["mode"] as? String, ["auto", "each"].contains(m) else { return nil }
            return ["type": t, "mode": m]
        case "guest_approval":
            guard let g = c["guest_id"] as? String, match(gidRe, g), let m = c["mode"] as? String, ["auto", "each", "default"].contains(m) else { return nil }
            return ["type": t, "guest_id": g, "mode": m]
        case "card_add", "card_update", "card_move", "card_delete":
            var out: [String: Any] = ["type": t]
            if t != "card_add" { guard let id = c["card_id"] as? String, match(cardIdRe, id) else { return nil }; out["card_id"] = id }
            if t == "card_delete" { return out }
            if t == "card_move" { guard let col = c["column"] as? String, columns.contains(col) else { return nil }; out["column"] = col; return out }
            if t == "card_add" || c["title"] != nil { guard let title = c["title"] as? String, !title.trimmingCharacters(in: .whitespaces).isEmpty, title.count <= 120 else { return nil }; out["title"] = title }
            if let n = c["note"] { guard let s = n as? String, s.count <= 1000 else { return nil }; out["note"] = s }
            for k in ["urgent", "important"] { if let v = c[k] { guard let b = v as? Bool else { return nil }; out[k] = b } }
            if t == "card_add", let col = c["column"] { guard let s = col as? String, columns.contains(s) else { return nil }; out["column"] = s }
            return out
        case "guest_level":
            guard let g = c["guest_id"] as? String, match(gidRe, g), let l = c["level"] as? String, ["ask", "act"].contains(l) else { return nil }
            return ["type": t, "guest_id": g, "level": l]
        case "action_allow", "action_deny":
            guard let id = c["request_id"] as? String, match(idRe, id), let a = c["action_id"] as? String, a.range(of: "^a_[0-9a-z]{8}$", options: .regularExpression) != nil else { return nil }
            return ["type": t, "request_id": id, "action_id": a]
        case "web_link":
            let name = String(((c["display_name"] as? String) ?? "").prefix(60))
            let days = (c["days"] as? Int) ?? 30, ttl = (c["ttl_days"] as? Int) ?? 7
            guard (1...90).contains(days), (1...30).contains(ttl) else { return nil }
            return ["type": t, "display_name": name, "days": days, "ttl_days": ttl]
        case "revoke_link":
            guard let id = c["link_id"] as? String, match(linkIdRe, id) else { return nil }
            return ["type": t, "link_id": id]
        case "invite":
            let name = String(((c["display_name"] as? String) ?? "").prefix(60))
            let days = (c["days"] as? Int) ?? 30, ttl = (c["ttl_days"] as? Int) ?? 7
            guard (1...90).contains(days), (1...30).contains(ttl) else { return nil }
            return ["type": t, "display_name": name, "days": days, "ttl_days": ttl]
        case "revoke_invite":
            guard let code = c["code"] as? String, match(codeRe, code) else { return nil }
            return ["type": t, "code": code]
        case "allow_access", "ignore_access":
            guard let p = c["phone"] as? String, match(phoneRe, p) else { return nil }
            return ["type": t, "phone": p]
        case "add_guest":
            guard let p = c["phone"] as? String, match(phoneRe, p) else { return nil }
            let name = String(((c["display_name"] as? String) ?? "").prefix(60))
            var out: [String: Any] = ["type": t, "phone": p, "display_name": name]
            let days = (c["days"] as? Int) ?? 30
            guard (1...90).contains(days) else { return nil }
            out["days"] = days
            for k in ["daily_requests", "daily_tokens", "max_open"] {
                if let v = c[k] {
                    guard let n = v as? Int, (1...10_000_000).contains(n) else { return nil }
                    out[k] = n
                }
            }
            return out
        default: return nil
        }
    }

    func command(_ r: HTTPRequest) -> HTTPResponse {
        guard let t = tenantFor(r) else { return .json(["error": "not authenticated"], status: 401) }
        guard r.headers["x-door-panel"] == "1", sameOrigin(r), r.headers["content-type"]?.hasPrefix("application/json") == true else {
            return .json(["error": "forbidden"], status: 403)
        }
        guard let o = try? JSONSerialization.jsonObject(with: r.body) as? [String: Any], var c = Panel.validate(o) else {
            return .json(["error": "invalid command"], status: 400)
        }
        if let ty = c["type"] as? String, ty.hasPrefix("card_") {
            lock.lock(); defer { lock.unlock() }
            return cardCommand(t, c)
        }
        if c["type"] as? String == "web_link" || c["type"] as? String == "revoke_link" {
            lock.lock(); defer { lock.unlock() }
            if c["type"] as? String == "web_link" { return createLink(t, name: c["display_name"] as? String ?? "", days: c["days"] as! Int, ttl: c["ttl_days"] as! Int) }
            return revokeLink(t, id: c["link_id"] as! String)
        }
        let id = "c_" + randomHex(8)
        c["id"] = id
        c["at"] = Int(cfg.now().timeIntervalSince1970)
        lock.lock(); defer { lock.unlock() }
        guard t.commands.count < Panel.maxQueue else { return .json(["error": "queue full"], status: 429) }
        t.commands.append(c)
        return .json(["queued": id])
    }

    // MARK: agent API (the agent calls out to here; the panel never reaches the agent or the owner's Mac)
    func agentTenant(_ r: HTTPRequest) -> Tenant? {
        let h = r.headers["authorization"] ?? ""
        guard h.hasPrefix("Bearer ") else { return nil }
        lock.lock(); defer { lock.unlock() }
        guard let id = byAgent[SHA256.hex(String(h.dropFirst(7)))], let t = tenants[id], !t.disabled else { return nil }
        return t
    }

    func agentSnapshot(_ r: HTTPRequest) -> HTTPResponse {
        guard let t = agentTenant(r) else { return .json(["error": "unauthorized"], status: 401) }
        guard (try? JSONSerialization.jsonObject(with: r.body) as? [String: Any]) != nil else { return .json(["error": "invalid json"], status: 400) }
        lock.lock(); t.snapshot = r.body; t.snapshotAt = cfg.now(); lock.unlock()
        return .json(["ok": true])
    }

    func agentCommands(_ r: HTTPRequest) -> HTTPResponse {
        guard let t = agentTenant(r) else { return .json(["error": "unauthorized"], status: 401) }
        lock.lock(); defer { lock.unlock() }
        let present = t.ownerSeen.map { cfg.now().timeIntervalSince($0) < 15 } ?? false
        var out: [String: Any] = ["commands": t.commands, "owner_present": present]
        // Billing phase A: the operator sets the plan here; the agent enforces it.
        if let s = t.planStatus { out["plan"] = ["status": s, "active_until": t.planUntil] }
        return .json(out)
    }

    func agentAck(_ r: HTTPRequest) -> HTTPResponse {
        guard let t = agentTenant(r) else { return .json(["error": "unauthorized"], status: 401) }
        guard let o = try? JSONSerialization.jsonObject(with: r.body) as? [String: Any], let ids = o["ids"] as? [String] else {
            return .json(["error": "invalid ids"], status: 400)
        }
        let set = Set(ids)
        lock.lock(); t.commands.removeAll { set.contains($0["id"] as? String ?? "") }; lock.unlock()
        return .json(["ok": true])
    }

    // MARK: operator admin API (onboarding + manual billing)
    func adminAuthorized(_ r: HTTPRequest) -> Bool {
        guard let a = cfg.adminToken else { return false }
        let h = r.headers["authorization"] ?? ""
        return h.hasPrefix("Bearer ") && constantTimeEqual(String(h.dropFirst(7)), a)
    }

    func admin(_ r: HTTPRequest) -> HTTPResponse {
        guard cfg.adminToken != nil else { return .text("not found", status: 404) }
        guard adminAuthorized(r) else { return .json(["error": "unauthorized"], status: 401) }
        let parts = r.path.split(separator: "/").map(String.init)   // ["admin", "tenants", id?, action?]
        guard parts.count >= 2, parts[1] == "tenants" else { return .text("not found", status: 404) }
        let body = (try? JSONSerialization.jsonObject(with: r.body) as? [String: Any]) ?? [:]
        lock.lock(); defer { lock.unlock() }
        let now = cfg.now()
        switch (r.method, parts.count) {
        case ("GET", 2):
            let list = tenants.values.filter { $0.id != "t_default" }.sorted { $0.createdAt < $1.createdAt }.map { t -> [String: Any] in
                var d: [String: Any] = ["id": t.id, "name": t.name, "disabled": t.disabled, "created_at": t.createdAt]
                if let s = t.planStatus { d["plan_status"] = s; d["plan_until"] = t.planUntil }
                if let at = t.snapshotAt { d["last_seen_s"] = Int(now.timeIntervalSince(at)) }
                return d
            }
            return .json(["tenants": list])
        case ("POST", 2):
            guard let name = (body["name"] as? String)?.trimmingCharacters(in: .whitespaces), !name.isEmpty, name.count <= 80 else {
                return .json(["error": "name required (max 80 characters)"], status: 400)
            }
            guard tenants.count < Panel.maxTenants else { return .json(["error": "tenant limit"], status: 429) }
            let owner = "dro_" + randomHex(24), agent = "dra_" + randomHex(24)
            let t = Tenant(id: "t_" + randomHex(6), name: name, ownerHash: SHA256.hex(owner), agentHash: SHA256.hex(agent), createdAt: now.timeIntervalSince1970)
            t.planStatus = "inactive"
            tenants[t.id] = t; index(t); saveStore()
            // Tokens are shown once; only their hashes are stored.
            return .json(["tenant_id": t.id, "owner_token": owner, "agent_token": agent], status: 200)
        case ("POST", 4) where parts[3] == "plan":
            guard let t = tenants[parts[2]] else { return .json(["error": "unknown tenant"], status: 404) }
            guard let s = body["status"] as? String, ["active", "inactive", "canceled"].contains(s),
                  let until = (body["active_until"] as? Double) ?? (body["active_until"] as? Int).map(Double.init) else {
                return .json(["error": "status (active|inactive|canceled) and active_until (unix seconds) required"], status: 400)
            }
            t.planStatus = s; t.planUntil = until; saveStore()
            return .json(["ok": true])
        case ("POST", 4) where parts[3] == "disable" || parts[3] == "enable":
            guard let t = tenants[parts[2]] else { return .json(["error": "unknown tenant"], status: 404) }
            t.disabled = parts[3] == "disable"
            if t.disabled { unindex(t); sessions = sessions.filter { $0.value.tenant != t.id } } else { index(t) }
            saveStore()
            return .json(["ok": true])
        case ("POST", 4) where parts[3] == "rotate":
            guard let t = tenants[parts[2]] else { return .json(["error": "unknown tenant"], status: 404) }
            unindex(t)
            let owner = "dro_" + randomHex(24), agent = "dra_" + randomHex(24)
            t.ownerHash = SHA256.hex(owner); t.agentHash = SHA256.hex(agent)
            if !t.disabled { index(t) }
            sessions = sessions.filter { $0.value.tenant != t.id }
            saveStore()
            return .json(["tenant_id": t.id, "owner_token": owner, "agent_token": agent])
        default:
            return .text("not found", status: 404)
        }
    }
}
