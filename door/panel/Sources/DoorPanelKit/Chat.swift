import Foundation

/// A shareable chat link for one guest. Only the SHA-256 of the token is stored; the owner sees the URL once, at creation.
final class Link {
    let id: String
    var tokenHash: String
    var name: String
    var days: Int
    var created: Double
    var expires: Double
    var bindHash: String?           // set on first open: the link then works from that browser only
    var revoked = false
    var lastSeen: Double = 0
    // runtime only
    var messages: [[String: Any]] = []
    var inbox: [[String: Any]] = []
    var sendTimes: [Date] = []
    var nextId = 1
    init(id: String, tokenHash: String, name: String, days: Int, created: Double, expires: Double) {
        self.id = id; self.tokenHash = tokenHash; self.name = name; self.days = days; self.created = created; self.expires = expires
    }
    var persisted: [String: Any] {
        var d: [String: Any] = ["id": id, "token_hash": tokenHash, "name": name, "days": days, "created": created, "expires": expires, "revoked": revoked]
        if let b = bindHash { d["bind_hash"] = b }
        return d
    }
}

/// A board card. The owner sees every card; a guest sees only the cards that belong to their own chat link.
final class Card {
    let id: String
    var title: String
    var note: String
    var column: String            // todo | doing | review | done
    var urgent: Bool
    var important: Bool
    var owner: String             // "owner", a link id, or "g_<guest id>"
    var requestId: String?
    var verdict: String?
    var proof: String?
    var created: Double
    var updated: Double
    init(id: String, title: String, note: String, column: String, urgent: Bool, important: Bool, owner: String, now: Double) {
        self.id = id; self.title = title; self.note = note; self.column = column; self.urgent = urgent; self.important = important
        self.owner = owner; self.created = now; self.updated = now
    }
    var json: [String: Any] {
        var d: [String: Any] = ["id": id, "title": title, "note": note, "column": column, "urgent": urgent, "important": important,
                                "owner": owner, "created": created, "updated": updated]
        if let r = requestId { d["request_id"] = r }
        if let v = verdict { d["verdict"] = v }
        if let p = proof { d["proof"] = p }
        return d
    }
}

extension Panel {
    static let columns: Set<String> = ["todo", "doing", "review", "done"]
    static let cardIdRe = try! NSRegularExpression(pattern: "^k_[0-9a-f]{8}$")
    static let maxCards = 1000
    static let maxCardsPerLink = 100
    static let tokenRe = try! NSRegularExpression(pattern: "^[0-9a-f]{48}$")
    static let linkIdRe = try! NSRegularExpression(pattern: "^l_[0-9a-f]{12}$")
    static let maxLinks = 200
    static let maxChatChars = 1600
    static let sendsPerMinute = 20
    static let maxInbox = 20

    func notValid() -> HTTPResponse {
        var res = page(ChatPage.invalid)
        res.status = 404
        return res
    }

    /// Caller holds the lock.
    func linkFor(token: String) -> (Tenant, Link)? {
        guard Panel.match(Panel.tokenRe, token), let ix = linkIndex[SHA256.hex(token)],
              let t = tenants[ix.tenant], !t.disabled, let l = t.links[ix.link], !l.revoked, l.expires > cfg.now().timeIntervalSince1970 else { return nil }
        return (t, l)
    }

    func guestRoute(_ r: HTTPRequest) -> HTTPResponse {
        let parts = r.path.split(separator: "/").map(String.init)   // ["c", token] | ["chat", token, action]
        guard parts.count >= 2 else { return notValid() }
        lock.lock(); defer { lock.unlock() }
        guard let (_, link) = linkFor(token: parts[1]) else {
            return parts[0] == "c" ? notValid() : .json(["error": "invalid link"], status: 404)
        }
        let cookieName = "dg_" + link.id
        let cookie = r.cookies[cookieName]
        let bound = link.bindHash != nil && cookie != nil && constantTimeEqual(SHA256.hex(cookie!), link.bindHash!)
        let now = cfg.now()
        // The page: the first browser to open the link keeps it; any other browser is told the link was used.
        if r.method == "GET" && parts.count == 2 && parts[0] == "c" {
            if link.bindHash == nil {
                let secret = randomHex(24)
                link.bindHash = SHA256.hex(secret)
                saveStore()
                var res = page(ChatPage.html)
                let secure = cfg.secureCookie ? "; Secure" : ""
                res.headers["Set-Cookie"] = "\(cookieName)=\(secret); HttpOnly; SameSite=Strict; Path=/; Max-Age=\(90 * 86400)\(secure)"
                link.lastSeen = now.timeIntervalSince1970
                return res
            }
            guard bound else { var res = page(ChatPage.used); res.status = 403; return res }
            link.lastSeen = now.timeIntervalSince1970
            return page(ChatPage.html)
        }
        guard bound, parts[0] == "chat", parts.count == 3 else { return .json(["error": "forbidden"], status: 403) }
        link.lastSeen = now.timeIntervalSince1970
        switch (r.method, parts[2]) {
        case ("GET", "board"), ("POST", "card"):
            guard let (t, _) = linkFor(token: parts[1]) else { return .json(["error": "invalid link"], status: 404) }
            return guestBoard(t, link, r, action: parts[2], now: now)
        case ("GET", "info"):
            var auto = false, tasks = false
            if let (t, _) = linkFor(token: parts[1]), let d = t.snapshot, let snap = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any] {
                let me = (snap["guests"] as? [[String: Any]] ?? []).first { ($0["link_id"] as? String) == link.id }
                let mode = (me?["approval"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? (snap["approval"] as? String) ?? "each"
                auto = mode == "auto" || mode == "default" && (snap["approval"] as? String) == "auto"
                tasks = (me?["level"] as? String) == "act"
            }
            return .json(["name": link.name, "expires": link.expires, "auto": auto, "tasks": tasks])
        case ("GET", "messages"):
            let after = Int(r.query["after"] ?? "0") ?? 0
            return .json(["messages": link.messages.filter { ($0["id"] as? Int ?? 0) > after }])
        case ("POST", "send"):
            guard r.headers["x-door-chat"] == "1", sameOrigin(r), r.headers["content-type"]?.hasPrefix("application/json") == true else {
                return .json(["error": "forbidden"], status: 403)
            }
            guard let o = try? JSONSerialization.jsonObject(with: r.body) as? [String: Any], let raw = o["text"] as? String else {
                return .json(["error": "invalid message"], status: 400)
            }
            let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty, text.count <= Panel.maxChatChars else { return .json(["error": "write 1 to \(Panel.maxChatChars) characters"], status: 400) }
            link.sendTimes.removeAll { now.timeIntervalSince($0) > 60 }
            guard link.sendTimes.count < Panel.sendsPerMinute, link.inbox.count < Panel.maxInbox else {
                return .json(["error": "too many messages; wait a moment"], status: 429)
            }
            link.sendTimes.append(now)
            let id = link.nextId; link.nextId += 1
            let m: [String: Any] = ["id": id, "role": "guest", "text": text, "at": Int(now.timeIntervalSince1970)]
            link.messages.append(m)
            link.inbox.append(["link_id": link.id, "id": id, "text": text, "kind": "chat"])
            if link.messages.count > 500 { link.messages.removeFirst(link.messages.count - 500) }
            return .json(["id": id])
        default:
            return .json(["error": "not found"], status: 404)
        }
    }

    // MARK: owner commands for links (called from command() with the lock held)
    func createLink(_ t: Tenant, name: String, days: Int, ttl: Int) -> HTTPResponse {
        guard t.links.count < Panel.maxLinks else { return .json(["error": "too many links"], status: 429) }
        let token = randomHex(24)
        let now = cfg.now().timeIntervalSince1970
        let l = Link(id: "l_" + randomHex(6), tokenHash: SHA256.hex(token), name: name, days: days, created: now, expires: now + Double(ttl) * 86400)
        t.links[l.id] = l
        linkIndex[l.tokenHash] = (t.id, l.id)
        saveStore()
        return .json(["link_id": l.id, "path": "/c/" + token])
    }

    func revokeLink(_ t: Tenant, id: String) -> HTTPResponse {
        guard let l = t.links[id] else { return .json(["error": "unknown link"], status: 404) }
        l.revoked = true
        linkIndex[l.tokenHash] = nil
        t.commands.append(["id": "c_" + randomHex(8), "type": "link_revoked", "link_id": id, "at": Int(cfg.now().timeIntervalSince1970)])
        saveStore()
        return .json(["ok": true])
    }

    func linksJSON(_ t: Tenant) -> [[String: Any]] {
        t.links.values.sorted { $0.created > $1.created }.map {
            ["id": $0.id, "name": $0.name, "days": $0.days, "expires": $0.expires, "opened": $0.bindHash != nil,
             "revoked": $0.revoked, "last_seen": $0.lastSeen]
        }
    }

    // MARK: agent side (the cloud agent polls here; the panel never calls it)
    func agentInbox(_ r: HTTPRequest) -> HTTPResponse {
        guard let t = agentTenant(r) else { return .json(["error": "unauthorized"], status: 401) }
        lock.lock(); defer { lock.unlock() }
        var out: [[String: Any]] = []
        for l in t.links.values where !l.revoked {
            for m in l.inbox { out.append(m.merging(["name": l.name, "days": l.days]) { $1 }) }
        }
        return .json(["messages": out])
    }

    func agentInboxAck(_ r: HTTPRequest) -> HTTPResponse {
        guard let t = agentTenant(r) else { return .json(["error": "unauthorized"], status: 401) }
        guard let o = try? JSONSerialization.jsonObject(with: r.body) as? [String: Any], let ids = o["ids"] as? [String] else {
            return .json(["error": "invalid ids"], status: 400)
        }
        let set = Set(ids)
        lock.lock(); defer { lock.unlock() }
        for l in t.links.values { l.inbox.removeAll { set.contains("\(l.id):\($0["id"] as? Int ?? 0)") } }
        return .json(["ok": true])
    }

    func agentChat(_ r: HTTPRequest) -> HTTPResponse {
        guard let t = agentTenant(r) else { return .json(["error": "unauthorized"], status: 401) }
        guard let o = try? JSONSerialization.jsonObject(with: r.body) as? [String: Any], let lid = o["link_id"] as? String,
              let text = o["text"] as? String, !text.isEmpty, text.count <= 4000 else { return .json(["error": "invalid message"], status: 400) }
        let kind = (o["kind"] as? String) == "agent" ? "agent" : "system"
        lock.lock(); defer { lock.unlock() }
        guard let l = t.links[lid] else { return .json(["error": "unknown link"], status: 404) }
        let id = l.nextId; l.nextId += 1
        l.messages.append(["id": id, "role": kind, "text": text, "at": Int(cfg.now().timeIntervalSince1970)])
        if l.messages.count > 500 { l.messages.removeFirst(l.messages.count - 500) }
        return .json(["id": id])
    }
}

// MARK: - Kanban board
extension Panel {
    static func cleanText(_ v: Any?, max: Int) -> String? {
        guard let s = v as? String else { return nil }
        return String(s.trimmingCharacters(in: .whitespacesAndNewlines).prefix(max))
    }

    /// Caller holds the lock. Validates and applies card fields; returns false if a given field is invalid.
    func applyCard(_ card: Card, _ f: [String: Any], allowColumn: Bool, allowOutcome: Bool = false) -> Bool {
        if let v = f["title"] { guard let t = Panel.cleanText(v, max: 120), !t.isEmpty else { return false }; card.title = t }
        if let v = f["note"] { guard let t = Panel.cleanText(v, max: 1000) else { return false }; card.note = t }
        if let v = f["urgent"] { guard let b = v as? Bool else { return false }; card.urgent = b }
        if let v = f["important"] { guard let b = v as? Bool else { return false }; card.important = b }
        if let v = f["column"] {
            guard allowColumn, let s = v as? String, Panel.columns.contains(s) else { return false }
            card.column = s
        }
        if allowOutcome {
            if let v = f["verdict"] { guard let s = Panel.cleanText(v, max: 40) else { return false }; card.verdict = s.isEmpty ? nil : s }
            if let v = f["proof"] { guard let s = Panel.cleanText(v, max: 1500) else { return false }; card.proof = s.isEmpty ? nil : s }
        }
        card.updated = cfg.now().timeIntervalSince1970
        return true
    }

    func newCard(_ t: Tenant, owner: String, _ f: [String: Any], column: String = "todo") -> Card? {
        guard t.cards.count < Panel.maxCards, let title = Panel.cleanText(f["title"], max: 120), !title.isEmpty else { return nil }
        let c = Card(id: "k_" + randomHex(4), title: title, note: Panel.cleanText(f["note"], max: 1000) ?? "", column: column,
                     urgent: (f["urgent"] as? Bool) ?? false, important: (f["important"] as? Bool) ?? false, owner: owner,
                     now: cfg.now().timeIntervalSince1970)
        t.cards[c.id] = c
        return c
    }

    /// Owner commands for cards (called from command() with the lock held).
    func cardCommand(_ t: Tenant, _ c: [String: Any]) -> HTTPResponse {
        let type = c["type"] as? String ?? ""
        if type == "card_add" {
            let col = (c["column"] as? String) ?? "todo"
            guard Panel.columns.contains(col), let card = newCard(t, owner: "owner", c, column: col) else { return .json(["error": "invalid card"], status: 400) }
            saveStore(); return .json(["card_id": card.id])
        }
        guard let id = c["card_id"] as? String, let card = t.cards[id] else { return .json(["error": "unknown card"], status: 404) }
        switch type {
        case "card_delete": t.cards[id] = nil
        case "card_move": guard applyCard(card, ["column": c["column"] as Any], allowColumn: true) else { return .json(["error": "invalid column"], status: 400) }
        default: guard applyCard(card, c, allowColumn: false) else { return .json(["error": "invalid card"], status: 400) }
        }
        saveStore()
        return .json(["ok": true])
    }

    func cardsJSON(_ t: Tenant) -> [[String: Any]] { t.cards.values.sorted { $0.created < $1.created }.map { $0.json } }

    // Guest side: only the cards of their own link. Called from guestRoute with the lock held and the browser already checked.
    func guestBoard(_ t: Tenant, _ link: Link, _ r: HTTPRequest, action: String, now: Date) -> HTTPResponse {
        let mine = t.cards.values.filter { $0.owner == link.id }.sorted { $0.created < $1.created }
        if r.method == "GET" { return .json(["cards": mine.map { $0.json }]) }
        guard r.headers["x-door-chat"] == "1", sameOrigin(r), r.headers["content-type"]?.hasPrefix("application/json") == true,
              let o = try? JSONSerialization.jsonObject(with: r.body) as? [String: Any], let op = o["op"] as? String else {
            return .json(["error": "forbidden"], status: 403)
        }
        guard ["add", "update", "delete", "run"].contains(op) else { return .json(["error": "unknown action"], status: 400) }
        link.sendTimes.removeAll { now.timeIntervalSince($0) > 60 }
        guard link.sendTimes.count < Panel.sendsPerMinute else { return .json(["error": "too many requests; wait a moment"], status: 429) }
        link.sendTimes.append(now)
        if op == "add" {
            guard mine.count < Panel.maxCardsPerLink, let card = newCard(t, owner: link.id, o) else { return .json(["error": "could not add the card"], status: 400) }
            saveStore(); return .json(["card_id": card.id])
        }
        guard let id = o["card_id"] as? String, let card = t.cards[id], card.owner == link.id else { return .json(["error": "unknown card"], status: 404) }
        switch op {
        case "update":
            let fields = o.filter { ["title", "note", "urgent", "important"].contains($0.key) }
            guard card.column != "done", applyCard(card, fields, allowColumn: false) else { return .json(["error": "invalid card"], status: 400) }
        case "delete":
            guard card.column == "todo" else { return .json(["error": "only cards that were not started can be removed"], status: 400) }
            t.cards[id] = nil
        case "run":
            guard card.column == "todo", link.inbox.count < Panel.maxInbox else { return .json(["error": "this card cannot be started now"], status: 400) }
            let mid = link.nextId; link.nextId += 1
            link.inbox.append(["link_id": link.id, "id": mid, "text": card.note.isEmpty ? card.title : "\(card.title)\n\(card.note)", "kind": "task", "card_id": card.id])
            link.messages.append(["id": mid, "role": "guest", "text": "Do: " + card.title, "at": Int(now.timeIntervalSince1970)])
        default: return .json(["error": "unknown action"], status: 400)
        }
        saveStore()
        return .json(["ok": true])
    }

    // Agent side: tasks create and move their own cards.
    func agentCard(_ r: HTTPRequest) -> HTTPResponse {
        guard let t = agentTenant(r) else { return .json(["error": "unauthorized"], status: 401) }
        guard let o = try? JSONSerialization.jsonObject(with: r.body) as? [String: Any], let op = o["op"] as? String else { return .json(["error": "invalid body"], status: 400) }
        lock.lock(); defer { lock.unlock() }
        if op == "add" {
            let owner = (o["owner"] as? String) ?? "owner"
            guard owner == "owner" || t.links[owner] != nil || (owner.hasPrefix("g_") && owner.count <= 40) else { return .json(["error": "unknown owner"], status: 400) }
            guard let card = newCard(t, owner: owner, o, column: Panel.columns.contains((o["column"] as? String) ?? "") ? (o["column"] as! String) : "doing") else {
                return .json(["error": "could not add the card"], status: 400)
            }
            if let rid = o["request_id"] as? String { card.requestId = String(rid.prefix(40)) }
            saveStore(); return .json(["card_id": card.id])
        }
        let card = (o["card_id"] as? String).flatMap { t.cards[$0] } ?? (o["request_id"] as? String).flatMap { rid in t.cards.values.first { $0.requestId == rid } }
        guard let c = card else { return .json(["error": "unknown card"], status: 404) }
        if let rid = o["request_id"] as? String, c.requestId == nil { c.requestId = String(rid.prefix(40)) }
        var f: [String: Any] = [:]
        for k in ["title", "note", "column", "verdict", "proof"] { if let v = o[k] { f[k] = v } }
        guard applyCard(c, f, allowColumn: true, allowOutcome: true) else { return .json(["error": "invalid card"], status: 400) }
        saveStore(); return .json(["ok": true])
    }
}


// MARK: - Things the agent asks the panel to do for the owner (so the owner can just text the agent)
extension Panel {
    static let signinTTL: TimeInterval = 600

    /// POST /agent/links: make a chat link. The URL is returned once, to the agent, which texts it to the owner.
    func agentLinks(_ r: HTTPRequest) -> HTTPResponse {
        guard let t = agentTenant(r) else { return .json(["error": "unauthorized"], status: 401) }
        guard let o = try? JSONSerialization.jsonObject(with: r.body) as? [String: Any] else { return .json(["error": "invalid body"], status: 400) }
        let days = (o["days"] as? Int) ?? 30, ttl = (o["ttl_days"] as? Int) ?? 7
        guard (1...90).contains(days), (1...30).contains(ttl) else { return .json(["error": "invalid days"], status: 400) }
        lock.lock(); defer { lock.unlock() }
        return createLink(t, name: String(((o["name"] as? String) ?? "").prefix(60)), days: days, ttl: ttl)
    }

    /// POST /agent/signin: a single-use sign-in link for the owner (valid 10 minutes), so no long-lived token has to be texted around.
    func agentSignin(_ r: HTTPRequest) -> HTTPResponse {
        guard let t = agentTenant(r) else { return .json(["error": "unauthorized"], status: 401) }
        lock.lock(); defer { lock.unlock() }
        t.signins = t.signins.filter { $0.value > cfg.now() }
        guard t.signins.count < 5 else { return .json(["error": "too many open sign-in links"], status: 429) }
        let code = randomHex(24)
        t.signins[SHA256.hex(code)] = cfg.now().addingTimeInterval(Panel.signinTTL)
        return .json(["path": "/signin/" + code])
    }

    /// GET /signin/<code>: consumes the code and starts the owner's session.
    func signin(_ r: HTTPRequest) -> HTTPResponse {
        let code = String(r.path.dropFirst("/signin/".count))
        let now = cfg.now()
        let who = clientKey(r)
        lock.lock(); defer { lock.unlock() }
        guard !guessingBlocked(who, now) else { return .text("too many attempts; wait 1 minute", status: 429) }
        let h = SHA256.hex(code)
        guard Panel.match(Panel.tokenRe, code), let t = tenants.values.first(where: { !$0.disabled && ($0.signins[h] ?? .distantPast) > now }) else {
            noteFailure(who, now)
            var res = page(Dashboard.login(error: "That sign-in link is not valid or has expired. Text your Door number \"Door Panel\" for a new one."))
            res.status = 401
            return res
        }
        t.signins[h] = nil                                              // single use
        let sid = randomHex(32)
        sessions[SHA256.hex(sid)] = (t.id, now.addingTimeInterval(Panel.sessionTTL)); saveStore()
        let secure = cfg.secureCookie ? "; Secure" : ""
        return HTTPResponse(status: 302, headers: ["Location": "/", "Set-Cookie": "door_session=\(sid); HttpOnly; SameSite=Strict; Path=/; Max-Age=\(Int(Panel.sessionTTL))\(secure)"])
    }
}
