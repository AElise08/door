import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
@testable import DoorPanelKit

final class PanelTests {
    var t = Date(timeIntervalSince1970: 1_800_000_000)
    var panel: Panel!
    let owner = String(repeating: "o", count: 30), agent = String(repeating: "a", count: 30)

    init() { panel = Panel(PanelConfig(ownerToken: owner, agentToken: agent, now: { self.t })) }

    func req(_ m: String, _ p: String, _ h: [String: String] = [:], _ body: String = "") -> HTTPRequest {
        HTTPRequest(method: m, path: p, headers: h, body: Data(body.utf8))
    }
    func login() -> String {
        let r = panel.handle(req("POST", "/login", ["Content-Type": "application/x-www-form-urlencoded"], "token=\(owner)"))
        XCTAssertEqual(r.status, 302)
        return r.headers["Set-Cookie"]!.components(separatedBy: ";")[0]
    }
    func agentCmds() -> ([[String: Any]], Bool) {
        let o = try! JSONSerialization.jsonObject(with: panel.handle(req("GET", "/agent/commands", A())).body) as! [String: Any]
        return (o["commands"] as! [[String: Any]], o["owner_present"] as! Bool)
    }
    let json = ["Content-Type": "application/json", "X-Door-Panel": "1"]
    func A(_ extra: [String: String] = [:]) -> [String: String] { ["Authorization": "Bearer " + agent].merging(extra) { $1 } }

    func testLoginRequiredAndWrongTokenFails() {
        XCTAssertEqual(panel.handle(req("GET", "/api/state")).status, 401)
        XCTAssertEqual(panel.handle(req("POST", "/login", [:], "token=errado")).status, 401)
        XCTAssertTrue(String(data: panel.handle(req("GET", "/")).body, encoding: .utf8)!.contains("Owner token"))
    }

    func testLoginFromBrowserFormWorks() {
        // Chrome/Safari: POST de formulário no mesmo site, com Sec-Fetch-Site ou com Origin igual ao Host
        XCTAssertEqual(panel.handle(req("POST", "/login", ["Sec-Fetch-Site": "same-origin"], "token=\(owner)")).status, 302)
        XCTAssertEqual(panel.handle(req("POST", "/login", ["Origin": "http://127.0.0.1:9630", "Host": "127.0.0.1:9630"], "token=\(owner)")).status, 302)
        XCTAssertEqual(panel.handle(req("POST", "/login", ["Sec-Fetch-Site": "cross-site"], "token=\(owner)")).status, 403)
        XCTAssertEqual(panel.handle(req("POST", "/login", ["Origin": "https://evil.example", "Host": "painel.x"], "token=\(owner)")).status, 403)
    }

    func testLoginRateLimit() {
        for _ in 0..<5 { _ = panel.handle(req("POST", "/login", [:], "token=x")) }
        XCTAssertEqual(panel.handle(req("POST", "/login", [:], "token=\(owner)")).status, 429)
        t += 61
        XCTAssertEqual(panel.handle(req("POST", "/login", [:], "token=\(owner)")).status, 302)
    }

    func testSessionExpires() {
        let c = login()
        XCTAssertEqual(panel.handle(req("GET", "/api/state", ["Cookie": c])).status, 200)
        t += 13 * 3600                                                                     // still signed in the next morning
        XCTAssertEqual(panel.handle(req("GET", "/api/state", ["Cookie": c])).status, 200)
        t += 31 * 86400                                                                    // but not forever
        XCTAssertEqual(panel.handle(req("GET", "/api/state", ["Cookie": c])).status, 401)
    }

    func testCookieFlags() {
        let r = panel.handle(req("POST", "/login", [:], "token=\(owner)"))
        let c = r.headers["Set-Cookie"]!
        XCTAssertTrue(c.contains("HttpOnly") && c.contains("SameSite=Strict"))
    }

    func testCommandNeedsSessionHeaderAndValidShape() {
        let c = login()
        let ok = #"{"type":"approve","request_id":"01ARZ3NDEKTSV4RRFFQ69G5FAV","text_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}"#
        XCTAssertEqual(panel.handle(req("POST", "/api/command", json, ok)).status, 401)                        // sem sessão
        XCTAssertEqual(panel.handle(req("POST", "/api/command", ["Cookie": c, "Content-Type": "application/json"], ok)).status, 403)  // sem X-Door-Panel (CSRF)
        XCTAssertEqual(panel.handle(req("POST", "/api/command", json.merging(["Cookie": c, "Origin": "https://evil.example", "Host": "painel.x"]) { $1 }, ok)).status, 403)
        XCTAssertEqual(panel.handle(req("POST", "/api/command", json.merging(["Cookie": c]) { $1 }, ok)).status, 200)
        for bad in [#"{"type":"approve","request_id":"01ARZ3NDEKTSV4RRFFQ69G5FAV"}"#, #"{"type":"deny","request_id":"01ARZ3NDEKTSV4RRFFQ69G5FAV","text_hash":"zz"}"#, #"{"type":"rm -rf"}"#, #"{"type":"approve","request_id":"../../x"}"#, #"{"type":"add_guest","phone":"123"}"#,
                    #"{"type":"add_guest","phone":"+5511999999999","days":9999}"#, #"{"type":"suspend","guest_id":"x"}"#] {
            XCTAssertEqual(panel.handle(req("POST", "/api/command", json.merging(["Cookie": c]) { $1 }, bad)).status, 400, bad)
        }
    }

    func testAgentRoundTripWithAck() {
        let c = login()
        XCTAssertEqual(panel.handle(req("PUT", "/agent/snapshot", [:], "{}")).status, 401)
        XCTAssertEqual(panel.handle(req("PUT", "/agent/snapshot", ["Authorization": "Bearer " + owner], "{}")).status, 401)   // token do dono não vale
        XCTAssertEqual(panel.handle(req("PUT", "/agent/snapshot", A(), "[1]")).status, 400)
        XCTAssertEqual(panel.handle(req("PUT", "/agent/snapshot", A(), #"{"queue":[{"text":"<script>alert(1)</script>"}]}"#)).status, 200)
        let st = try! JSONSerialization.jsonObject(with: panel.handle(req("GET", "/api/state", ["Cookie": c])).body) as! [String: Any]
        XCTAssertEqual(st["stale"] as? Bool, false)
        _ = panel.handle(req("POST", "/api/command", json.merging(["Cookie": c]) { $1 }, #"{"type":"pause"}"#))
        let (cmds, present) = agentCmds()
        XCTAssertEqual(cmds.count, 1)
        XCTAssertEqual(present, true)                       // dono abriu o painel há instantes
        XCTAssertEqual(agentCmds().0.count, 1)              // sem ack, o comando continua (entrega pelo menos uma vez)
        _ = panel.handle(req("POST", "/agent/ack", A(), #"{"ids":["\#(cmds[0]["id"] as! String)"]}"#))
        XCTAssertEqual(agentCmds().0.count, 0)
        t += 60
        XCTAssertEqual(agentCmds().1, false)
    }

    func testStaleSnapshotFlag() {
        let c = login()
        _ = panel.handle(req("PUT", "/agent/snapshot", A(), "{}"))
        t += 40
        let st = try! JSONSerialization.jsonObject(with: panel.handle(req("GET", "/api/state", ["Cookie": c])).body) as! [String: Any]
        XCTAssertEqual(st["stale"] as? Bool, true)
    }

    func testSecurityHeadersAndNoInlineDataInHTML() {
        let r = panel.handle(req("GET", "/", ["Cookie": login()]))
        XCTAssertTrue(r.headers["Content-Security-Policy"]!.contains("default-src 'none'"))
        XCTAssertEqual(r.headers["X-Frame-Options"], "DENY")
        let html = String(data: r.body, encoding: .utf8)!
        XCTAssertFalse(html.contains("innerHTML"))
        XCTAssertFalse(html.contains("{{NONCE}}"))
    }

    func testHTTPParsing() throws {
        let raw = Data("POST /api/command?x=1 HTTP/1.1\r\nHost: a\r\nContent-Length: 2\r\n\r\n{}".utf8)
        let (r, off, len) = try HTTP.parseHead(raw)!
        XCTAssertEqual(r.method + r.path + (r.query["x"] ?? "") + String(len), "POST/api/command12")
        XCTAssertEqual(raw.count - off, 2)
        assertThrows(try HTTP.parseHead(Data("POST / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n".utf8)))
        assertThrows(try HTTP.parseHead(Data("POST / HTTP/1.1\r\nContent-Length: 99999999\r\n\r\n".utf8)))
    }

    func testRealSocket() throws {
        let s = HTTPServer(handler: panel.handle)
        try s.start(host: "127.0.0.1", port: 0)
        defer { s.stop() }
        var rq = URLRequest(url: URL(string: "http://127.0.0.1:\(s.port)/healthz")!)
        rq.timeoutInterval = 5
        let sem = DispatchSemaphore(value: 0)
        var code = 0, body = ""
        URLSession.shared.dataTask(with: rq) { d, r, _ in
            code = (r as? HTTPURLResponse)?.statusCode ?? 0; body = String(data: d ?? Data(), encoding: .utf8) ?? ""; sem.signal()
        }.resume()
        XCTAssertEqual(sem.wait(timeout: .now() + 8), .success)
        XCTAssertEqual(code, 200); XCTAssertEqual(body, "ok")
    }

    // MARK: multi-tenant
    let admin = String(repeating: "z", count: 40)
    func adminReq(_ m: String, _ p: String, _ body: String = "", token: String? = nil) -> HTTPRequest {
        req(m, p, ["Authorization": "Bearer " + (token ?? admin), "Content-Type": "application/json"], body)
    }
    func jsonObj(_ r: HTTPResponse) -> [String: Any] { (try? JSONSerialization.jsonObject(with: r.body) as? [String: Any]) ?? [:] }
    func makePanel(path: String? = nil) -> Panel { Panel(PanelConfig(adminToken: admin, storePath: path, now: { self.t })) }
    func newTenant(_ p: Panel, _ name: String) -> (id: String, owner: String, agent: String) {
        let o = jsonObj(p.handle(adminReq("POST", "/admin/tenants", #"{"name":"\#(name)"}"#)))
        return (o["tenant_id"] as! String, o["owner_token"] as! String, o["agent_token"] as! String)
    }
    func loginAs(_ p: Panel, _ token: String) -> String? {
        let r = p.handle(req("POST", "/login", [:], "token=\(token)"))
        return r.status == 302 ? r.headers["Set-Cookie"]!.components(separatedBy: ";")[0] : nil
    }

    func testSha256Vectors() {
        XCTAssertEqual(SHA256.hex(""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        XCTAssertEqual(SHA256.hex("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        XCTAssertEqual(SHA256.hex("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"), "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1")
        XCTAssertEqual(SHA256.hex(String(repeating: "a", count: 1000)), "41edece42d63e8d9bf515a9ba6932e1c20cbc9f5a5d134645adb5db1b9737ea3")
    }

    func testTenantsAreIsolated() {
        let p = makePanel()
        let a = newTenant(p, "Acme"), b = newTenant(p, "Beta")
        let put = { (tok: String, body: String) in p.handle(self.req("PUT", "/agent/snapshot", ["Authorization": "Bearer " + tok], body)).status }
        XCTAssertEqual(put(a.agent, #"{"queue":[{"text":"ACME SECRET QUESTION"}]}"#), 200)
        XCTAssertEqual(put(b.agent, #"{"queue":[]}"#), 200)
        let ca = loginAs(p, a.owner)!, cb = loginAs(p, b.owner)!
        let sa = String(data: p.handle(req("GET", "/api/state", ["Cookie": ca])).body, encoding: .utf8)!
        let sb = String(data: p.handle(req("GET", "/api/state", ["Cookie": cb])).body, encoding: .utf8)!
        XCTAssertTrue(sa.contains("ACME SECRET QUESTION")); XCTAssertFalse(sb.contains("ACME SECRET QUESTION"))
        XCTAssertTrue(sa.contains("Acme")); XCTAssertTrue(sb.contains("Beta"))
        // B's owner cannot queue commands for A, and B's agent token cannot read A's commands
        _ = p.handle(req("POST", "/api/command", json.merging(["Cookie": cb]) { $1 }, #"{"type":"pause"}"#))
        let ga = jsonObj(p.handle(req("GET", "/agent/commands", ["Authorization": "Bearer " + a.agent])))
        XCTAssertEqual((ga["commands"] as! [Any]).count, 0)
        let gb = jsonObj(p.handle(req("GET", "/agent/commands", ["Authorization": "Bearer " + b.agent])))
        XCTAssertEqual((gb["commands"] as! [Any]).count, 1)
        // owner token is not an agent token and vice versa
        XCTAssertEqual(p.handle(req("GET", "/agent/commands", ["Authorization": "Bearer " + a.owner])).status, 401)
        XCTAssertTrue(loginAs(p, a.agent) == nil)
    }

    func testAdminRequiresTokenAndIsHiddenWithout() {
        let p = makePanel()
        XCTAssertEqual(p.handle(req("GET", "/admin/tenants")).status, 401)
        XCTAssertEqual(p.handle(adminReq("GET", "/admin/tenants", token: "wrong")).status, 401)
        XCTAssertEqual(p.handle(adminReq("GET", "/admin/tenants")).status, 200)
        XCTAssertEqual(p.handle(adminReq("POST", "/admin/tenants", #"{"name":""}"#)).status, 400)
        let noAdmin = Panel(PanelConfig(ownerToken: owner, agentToken: agent, now: { self.t }))
        XCTAssertEqual(noAdmin.handle(adminReq("GET", "/admin/tenants")).status, 404)   // admin API does not exist
    }

    func testPlanIsPushedToTheAgent() {
        let p = makePanel()
        let a = newTenant(p, "Acme")
        let tok = ["Authorization": "Bearer " + a.agent]
        XCTAssertEqual((jsonObj(p.handle(req("GET", "/agent/commands", tok)))["plan"] as! [String: Any])["status"] as? String, "inactive")
        XCTAssertEqual(p.handle(adminReq("POST", "/admin/tenants/\(a.id)/plan", #"{"status":"active","active_until":1900000000}"#)).status, 200)
        let plan = jsonObj(p.handle(req("GET", "/agent/commands", tok)))["plan"] as! [String: Any]
        XCTAssertEqual(plan["status"] as? String, "active"); XCTAssertEqual(plan["active_until"] as? Double, 1900000000)
        XCTAssertEqual(p.handle(adminReq("POST", "/admin/tenants/\(a.id)/plan", #"{"status":"nope","active_until":1}"#)).status, 400)
    }

    func testDisableAndRotateCutAccessImmediately() {
        let p = makePanel()
        let a = newTenant(p, "Acme")
        let cookie = loginAs(p, a.owner)!
        XCTAssertEqual(p.handle(req("GET", "/api/state", ["Cookie": cookie])).status, 200)
        _ = p.handle(adminReq("POST", "/admin/tenants/\(a.id)/disable"))
        XCTAssertEqual(p.handle(req("GET", "/api/state", ["Cookie": cookie])).status, 401)
        XCTAssertTrue(loginAs(p, a.owner) == nil)
        XCTAssertEqual(p.handle(req("GET", "/agent/commands", ["Authorization": "Bearer " + a.agent])).status, 401)
        _ = p.handle(adminReq("POST", "/admin/tenants/\(a.id)/enable"))
        XCTAssertTrue(loginAs(p, a.owner) != nil)
        let n = jsonObj(p.handle(adminReq("POST", "/admin/tenants/\(a.id)/rotate")))
        XCTAssertTrue(loginAs(p, a.owner) == nil)
        XCTAssertTrue(loginAs(p, n["owner_token"] as! String) != nil)
        XCTAssertEqual(p.handle(req("GET", "/agent/commands", ["Authorization": "Bearer " + a.agent])).status, 401)
    }

    func testStoreKeepsHashesNotTokensAndSurvivesRestart() throws {
        let path = NSTemporaryDirectory() + "door-tenants-\(UUID().uuidString).json"
        defer { try? FileManager.default.removeItem(atPath: path) }
        let p = makePanel(path: path)
        let a = newTenant(p, "Acme")
        _ = p.handle(adminReq("POST", "/admin/tenants/\(a.id)/plan", #"{"status":"active","active_until":1900000000}"#))
        let raw = String(data: FileManager.default.contents(atPath: path)!, encoding: .utf8)!
        XCTAssertFalse(raw.contains(a.owner)); XCTAssertFalse(raw.contains(a.agent))
        let perms = (try FileManager.default.attributesOfItem(atPath: path)[.posixPermissions] as! NSNumber).intValue
        XCTAssertEqual(perms, 0o600)
        let p2 = makePanel(path: path)           // "restart"
        XCTAssertTrue(loginAs(p2, a.owner) != nil)
        XCTAssertEqual((jsonObj(p2.handle(req("GET", "/agent/commands", ["Authorization": "Bearer " + a.agent])))["plan"] as! [String: Any])["status"] as? String, "active")
    }

    func testInviteAndAccessCommands() {
        let c = login()
        let post = { (b: String) in self.panel.handle(self.req("POST", "/api/command", self.json.merging(["Cookie": c]) { $1 }, b)).status }
        XCTAssertEqual(post(#"{"type":"invite","display_name":"Ana","days":30}"#), 200)
        XCTAssertEqual(post(#"{"type":"invite"}"#), 200)                                   // defaults: 30 days, valid 7 days
        XCTAssertEqual(post(#"{"type":"revoke_invite","code":"K7M2-9QXP"}"#), 200)
        XCTAssertEqual(post(#"{"type":"allow_access","phone":"+15551234567"}"#), 200)
        XCTAssertEqual(post(#"{"type":"ignore_access","phone":"+15551234567"}"#), 200)
        for bad in [#"{"type":"invite","days":0}"#, #"{"type":"invite","days":91}"#, #"{"type":"invite","ttl_days":31}"#,
                    #"{"type":"revoke_invite","code":"../x"}"#, #"{"type":"revoke_invite"}"#,
                    #"{"type":"allow_access","phone":"15551234567"}"#, #"{"type":"allow_access"}"#] {
            XCTAssertEqual(post(bad), 400, bad)
        }
        let got = try! JSONSerialization.jsonObject(with: panel.handle(req("GET", "/agent/commands", A())).body) as! [String: Any]
        let types = (got["commands"] as! [[String: Any]]).map { $0["type"] as! String }
        XCTAssertEqual(types, ["invite", "invite", "revoke_invite", "allow_access", "ignore_access"])
        let first = (got["commands"] as! [[String: Any]])[0]
        XCTAssertEqual(first["days"] as? Int, 30); XCTAssertEqual(first["ttl_days"] as? Int, 7)
    }

    // MARK: guest chat links
    func makeLink(_ p: Panel, _ cookie: String, name: String = "Cy", days: Int = 30, ttl: Int = 7) -> (id: String, token: String) {
        let r = p.handle(req("POST", "/api/command", json.merging(["Cookie": cookie]) { $1 },
                             #"{"type":"web_link","display_name":"\#(name)","days":\#(days),"ttl_days":\#(ttl)}"#))
        XCTAssertEqual(r.status, 200)
        let o = jsonObj(r)
        return (o["link_id"] as! String, String((o["path"] as! String).dropFirst(3)))
    }
    func guestCookie(_ r: HTTPResponse) -> String? { r.headers["Set-Cookie"]?.components(separatedBy: ";")[0] }

    func testChatLinkBindsToTheFirstBrowser() {
        let p = Panel(PanelConfig(ownerToken: owner, agentToken: agent, now: { self.t }))
        let (id, tok) = makeLink(p, loginAs(p, owner)!)
        XCTAssertEqual(tok.count, 48)
        let first = p.handle(req("GET", "/c/" + tok))
        XCTAssertEqual(first.status, 200)
        XCTAssertTrue(String(data: first.body, encoding: .utf8)!.contains("Ask anything"))
        let ck = guestCookie(first)!
        XCTAssertTrue(ck.hasPrefix("dg_" + id + "="))
        XCTAssertEqual(p.handle(req("GET", "/c/" + tok, ["Cookie": ck])).status, 200)          // same browser: fine
        XCTAssertEqual(p.handle(req("GET", "/c/" + tok)).status, 403)                            // another browser: already used
        XCTAssertEqual(p.handle(req("GET", "/chat/" + tok + "/messages")).status, 403)           // and no API without the cookie
        XCTAssertEqual(p.handle(req("GET", "/c/" + String(repeating: "0", count: 48))).status, 404)
        XCTAssertEqual(p.handle(req("GET", "/c/not-a-token")).status, 404)
    }

    func testChatRoundTripWithTheAgentAndLimits() {
        let p = Panel(PanelConfig(ownerToken: owner, agentToken: agent, now: { self.t }))
        let (id, tok) = makeLink(p, loginAs(p, owner)!)
        let ck = guestCookie(p.handle(req("GET", "/c/" + tok)))!
        let post = { (b: String) in p.handle(self.req("POST", "/chat/" + tok + "/send", self.json.merging(["Cookie": ck, "X-Door-Chat": "1"]) { $1 }, b)) }
        XCTAssertEqual(post(#"{"text":"How do I deploy?"}"#).status, 200)
        XCTAssertEqual(post(#"{"text":"   "}"#).status, 400)
        XCTAssertEqual(post(String(data: try! JSONSerialization.data(withJSONObject: ["text": String(repeating: "a", count: 1601)]), encoding: .utf8)!).status, 400)
        XCTAssertEqual(p.handle(req("POST", "/chat/" + tok + "/send", ["Cookie": ck, "Content-Type": "application/json"], #"{"text":"x"}"#)).status, 403)  // no X-Door-Chat
        let a = ["Authorization": "Bearer " + agent]
        let inbox = (jsonObj(p.handle(req("GET", "/agent/inbox", a)))["messages"] as! [[String: Any]])
        XCTAssertEqual(inbox.count, 1); XCTAssertEqual(inbox[0]["text"] as? String, "How do I deploy?")
        XCTAssertEqual(inbox[0]["link_id"] as? String, id); XCTAssertEqual(inbox[0]["name"] as? String, "Cy")
        XCTAssertEqual(p.handle(req("POST", "/agent/chat", a, #"{"link_id":"\#(id)","text":"Received.","kind":"system"}"#)).status, 200)
        XCTAssertEqual(p.handle(req("POST", "/agent/chat", a, #"{"link_id":"\#(id)","text":"Use the deploy script.","kind":"agent"}"#)).status, 200)
        let msgs = jsonObj(p.handle(req("GET", "/chat/" + tok + "/messages", ["Cookie": ck])))["messages"] as! [[String: Any]]
        XCTAssertEqual(msgs.map { $0["role"] as! String }, ["guest", "system", "agent"])
        let after = jsonObj(p.handle(HTTPRequest(method: "GET", path: "/chat/" + tok + "/messages", query: ["after": "2"], headers: ["Cookie": ck])))["messages"] as! [[String: Any]]
        XCTAssertEqual(after.count, 1)
        _ = p.handle(req("POST", "/agent/inbox/ack", a, #"{"ids":["\#(id):1"]}"#))
        XCTAssertEqual((jsonObj(p.handle(req("GET", "/agent/inbox", a)))["messages"] as! [Any]).count, 0)
        // 20 messages a minute at most
        var codes: [Int] = []
        for _ in 0..<25 { codes.append(post(#"{"text":"spam"}"#).status) }
        XCTAssertTrue(codes.contains(429)); XCTAssertEqual(p.handle(req("POST", "/agent/chat", ["Authorization": "Bearer nope"], "{}")).status, 401)
    }

    func testRevokedAndExpiredLinksStopWorkingAndTheAgentIsTold() {
        let p = Panel(PanelConfig(ownerToken: owner, agentToken: agent, now: { self.t }))
        let oc = loginAs(p, owner)!
        let (id, tok) = makeLink(p, oc, ttl: 1)
        let ck = guestCookie(p.handle(req("GET", "/c/" + tok)))!
        XCTAssertEqual(p.handle(req("POST", "/api/command", json.merging(["Cookie": oc]) { $1 }, #"{"type":"revoke_link","link_id":"\#(id)"}"#)).status, 200)
        XCTAssertEqual(p.handle(req("GET", "/chat/" + tok + "/messages", ["Cookie": ck])).status, 404)
        XCTAssertEqual(p.handle(req("GET", "/c/" + tok, ["Cookie": ck])).status, 404)
        let cmds = jsonObj(p.handle(req("GET", "/agent/commands", ["Authorization": "Bearer " + agent])))["commands"] as! [[String: Any]]
        XCTAssertEqual(cmds.last?["type"] as? String, "link_revoked"); XCTAssertEqual(cmds.last?["link_id"] as? String, id)
        let (_, tok2) = makeLink(p, oc, ttl: 1)
        XCTAssertEqual(p.handle(req("POST", "/api/command", json.merging(["Cookie": oc]) { $1 }, #"{"type":"web_link","days":0}"#)).status, 400)
        XCTAssertEqual(p.handle(req("POST", "/api/command", json.merging(["Cookie": oc]) { $1 }, #"{"type":"revoke_link","link_id":"../x"}"#)).status, 400)
        t += 2 * 86400
        XCTAssertEqual(p.handle(req("GET", "/c/" + tok2)).status, 404)
    }

    func testChatLinksAreIsolatedPerCustomerAndSurviveRestart() throws {
        let path = NSTemporaryDirectory() + "door-links-\(UUID().uuidString).json"
        defer { try? FileManager.default.removeItem(atPath: path) }
        let p = makePanel(path: path)
        let a = newTenant(p, "Acme"), b = newTenant(p, "Beta")
        let (ida, toka) = makeLink(p, loginAs(p, a.owner)!)
        let ck = guestCookie(p.handle(req("GET", "/c/" + toka)))!
        _ = p.handle(req("POST", "/chat/" + toka + "/send", json.merging(["Cookie": ck, "X-Door-Chat": "1"]) { $1 }, #"{"text":"for Acme"}"#))
        XCTAssertEqual((jsonObj(p.handle(req("GET", "/agent/inbox", ["Authorization": "Bearer " + b.agent])))["messages"] as! [Any]).count, 0)
        XCTAssertEqual((jsonObj(p.handle(req("GET", "/agent/inbox", ["Authorization": "Bearer " + a.agent])))["messages"] as! [Any]).count, 1)
        XCTAssertEqual(p.handle(req("POST", "/agent/chat", ["Authorization": "Bearer " + b.agent], #"{"link_id":"\#(ida)","text":"x"}"#)).status, 404)
        let raw = String(data: FileManager.default.contents(atPath: path)!, encoding: .utf8)!
        XCTAssertFalse(raw.contains(toka))                                    // only the hash is stored
        let p2 = makePanel(path: path)                                        // "restart": link still bound to the same browser
        XCTAssertEqual(p2.handle(req("GET", "/c/" + toka, ["Cookie": ck])).status, 200)
        XCTAssertEqual(p2.handle(req("GET", "/c/" + toka)).status, 403)
    }

    func testApprovalCommands() {
        let c = login()
        let post = { (b: String) in self.panel.handle(self.req("POST", "/api/command", self.json.merging(["Cookie": c]) { $1 }, b)).status }
        XCTAssertEqual(post(#"{"type":"set_approval","mode":"auto"}"#), 200)
        XCTAssertEqual(post(#"{"type":"set_approval","mode":"each"}"#), 200)
        XCTAssertEqual(post(#"{"type":"guest_approval","guest_id":"01ARZ3NDEKTSV4RRFFQ69G5FAZ","mode":"default"}"#), 200)
        for bad in [#"{"type":"set_approval","mode":"whenever"}"#, #"{"type":"set_approval"}"#,
                    #"{"type":"guest_approval","guest_id":"x","mode":"auto"}"#, #"{"type":"guest_approval","guest_id":"01ARZ3NDEKTSV4RRFFQ69G5FAZ","mode":"maybe"}"#] {
            XCTAssertEqual(post(bad), 400, bad)
        }
    }

    func testSettingsCommandsKeepToTheFixedShape() {
        let c = login()
        let post = { (b: String) in self.panel.handle(self.req("POST", "/api/command", self.json.merging(["Cookie": c]) { $1 }, b)).status }
        for ok in [#"{"type":"settings","change":{"op":"budget.set","monthly":25}}"#, #"{"type":"settings","change":{"op":"project.add","path":"/Users/you/code/app"}}"#,
                   #"{"type":"settings","change":{"op":"project.remove","name":"app"}}"#, #"{"type":"settings","change":{"op":"model.set","access":"anthropic","model":"claude-sonnet-5-5"}}"#,
                   #"{"type":"settings","change":{"op":"tasks.set","enabled":false}}"#,
                   #"{"type":"settings","change":{"op":"tasks.set","enabled":true,"project_name":"app","bash":"ask","open_on_mac":"allow","owner_steps":"auto","allow_commands":["npm test"],"checks":["npm test"]}}"#] {
            XCTAssertEqual(post(ok), 200, ok)
        }
        for bad in [#"{"type":"settings"}"#, #"{"type":"settings","change":"x"}"#, #"{"type":"settings","change":{"op":"sudo"}}"#, #"{"type":"settings","change":{"op":"budget.set","monthly":0}}"#,
                    #"{"type":"settings","change":{"op":"budget.set","monthly":999999}}"#, #"{"type":"settings","change":{"op":"model.set","access":"evil"}}"#,
                    #"{"type":"settings","change":{"op":"model.set","access":"openai","model":"a b"}}"#, #"{"type":"settings","change":{"op":"project.add","path":""}}"#,
                    #"{"type":"settings","change":{"op":"tasks.set","enabled":true}}"#, #"{"type":"settings","change":{"op":"tasks.set","enabled":true,"project_name":"a","bash":"rm"}}"#,
                    #"{"type":"settings","change":{"op":"tasks.set","enabled":true,"project_name":"a","allow_commands":[1]}}"#,
                    #"{"type":"settings","change":{"op":"project.add","path":"/a\nb"}}"#] {
            XCTAssertEqual(post(bad), 400, bad)
        }
        let agentCmds = jsonObj(panel.handle(req("GET", "/agent/commands", A())))["commands"] as! [[String: Any]]
        let change = (agentCmds.first { ($0["type"] as? String) == "settings" }?["change"] as? [String: Any])
        XCTAssertEqual(change?["op"] as? String, "budget.set")                       // what reaches the agent is the checked shape, not the raw input
        XCTAssertTrue(change?["extra"] == nil)
    }

    // MARK: kanban
    func ownerPost(_ p: Panel, _ cookie: String, _ body: String) -> HTTPResponse {
        p.handle(req("POST", "/api/command", json.merging(["Cookie": cookie]) { $1 }, body))
    }
    func cardsOf(_ p: Panel, _ cookie: String) -> [[String: Any]] { jsonObj(p.handle(req("GET", "/api/state", ["Cookie": cookie])))["cards"] as! [[String: Any]] }

    func testOwnerKanban() throws {
        let path = NSTemporaryDirectory() + "door-cards-\(UUID().uuidString).json"
        defer { try? FileManager.default.removeItem(atPath: path) }
        let p = makePanel(path: path)
        let a = newTenant(p, "Acme"); let c = loginAs(p, a.owner)!
        let added = jsonObj(ownerPost(p, c, #"{"type":"card_add","title":"Write docs","note":"README first","urgent":true,"important":true}"#))
        let id = added["card_id"] as! String
        XCTAssertTrue(id.hasPrefix("k_"))
        XCTAssertEqual(ownerPost(p, c, #"{"type":"card_move","card_id":"\#(id)","column":"doing"}"#).status, 200)
        XCTAssertEqual(ownerPost(p, c, #"{"type":"card_update","card_id":"\#(id)","urgent":false,"title":"Write the docs"}"#).status, 200)
        let card = cardsOf(p, c)[0]
        XCTAssertEqual("\(card["column"] ?? "") \(card["urgent"] ?? "") \(card["important"] ?? "") \(card["title"] ?? "") \(card["owner"] ?? "")", "doing 0 1 Write the docs owner")
        for bad in [#"{"type":"card_add"}"#, #"{"type":"card_add","title":"   "}"#, #"{"type":"card_add","title":"x","column":"later"}"#,
                    #"{"type":"card_move","card_id":"\#(id)","column":"nowhere"}"#, #"{"type":"card_move","card_id":"bad","column":"done"}"#,
                    #"{"type":"card_update","card_id":"\#(id)","urgent":"yes"}"#, #"{"type":"card_update","card_id":"\#(id)","title":""}"#,
                    #"{"type":"card_delete"}"#] {
            XCTAssertEqual(ownerPost(p, c, bad).status, 400, bad)
        }
        XCTAssertEqual(ownerPost(p, c, #"{"type":"card_move","card_id":"k_00000000","column":"done"}"#).status, 404)
        XCTAssertEqual(ownerPost(p, c, String(data: try JSONSerialization.data(withJSONObject: ["type": "card_add", "title": String(repeating: "t", count: 121)]), encoding: .utf8)!).status, 400)
        let p2 = makePanel(path: path)                                              // restart: the board is still there
        XCTAssertEqual(cardsOf(p2, loginAs(p2, a.owner)!).first?["title"] as? String, "Write the docs")
        XCTAssertEqual(ownerPost(p, c, #"{"type":"card_delete","card_id":"\#(id)"}"#).status, 200)
        XCTAssertEqual(cardsOf(p, c).count, 0)
    }

    func testGuestBoardIsTheirOwnAndTheyChoosePriority() {
        let p = Panel(PanelConfig(ownerToken: owner, agentToken: agent, now: { self.t }))
        let oc = loginAs(p, owner)!
        let (_, tokA) = makeLink(p, oc, name: "Ana"), (_, tokB) = makeLink(p, oc, name: "Bob")
        let ca = guestCookie(p.handle(req("GET", "/c/" + tokA)))!, cb = guestCookie(p.handle(req("GET", "/c/" + tokB)))!
        let post = { (tok: String, ck: String, b: String) in p.handle(self.req("POST", "/chat/" + tok + "/card", self.json.merging(["Cookie": ck, "X-Door-Chat": "1"]) { $1 }, b)) }
        let mine = jsonObj(post(tokA, ca, #"{"op":"add","title":"Fix login bug","urgent":true,"important":false}"#))["card_id"] as! String
        _ = post(tokB, cb, #"{"op":"add","title":"Bob's idea"}"#)
        let boardA = jsonObj(p.handle(req("GET", "/chat/" + tokA + "/board", ["Cookie": ca])))["cards"] as! [[String: Any]]
        XCTAssertEqual(boardA.map { $0["title"] as! String }, ["Fix login bug"])                                       // only their own
        XCTAssertEqual(cardsOf(p, oc).count, 2)                                                                          // the owner sees both
        XCTAssertEqual(post(tokA, ca, #"{"op":"update","card_id":"\#(mine)","important":true,"urgent":false}"#).status, 200)   // they set their own priority
        let c = (jsonObj(p.handle(req("GET", "/chat/" + tokA + "/board", ["Cookie": ca])))["cards"] as! [[String: Any]])[0]
        XCTAssertEqual("\(c["urgent"] ?? "") \(c["important"] ?? "")", "0 1")
        XCTAssertEqual(post(tokA, ca, #"{"op":"update","card_id":"\#(mine)","column":"done"}"#).status, 200)               // a column in the body is ignored, never applied
        XCTAssertEqual((jsonObj(p.handle(req("GET", "/chat/" + tokA + "/board", ["Cookie": ca])))["cards"] as! [[String: Any]])[0]["column"] as? String, "todo")
        XCTAssertEqual(post(tokB, cb, #"{"op":"update","card_id":"\#(mine)","title":"hijack"}"#).status, 404)             // not someone else's card
        XCTAssertEqual(post(tokB, cb, #"{"op":"delete","card_id":"\#(mine)"}"#).status, 404)
        XCTAssertEqual(p.handle(req("POST", "/chat/" + tokA + "/card", ["Cookie": ca, "Content-Type": "application/json"], #"{"op":"add","title":"x"}"#)).status, 403)   // header required
        XCTAssertEqual(p.handle(req("GET", "/chat/" + tokA + "/board")).status, 403)                                       // and the browser cookie
        XCTAssertEqual(post(tokA, ca, #"{"op":"add","title":""}"#).status, 400)
        XCTAssertEqual(post(tokA, ca, #"{"op":"explode"}"#).status, 400)
        XCTAssertEqual(post(tokA, ca, #"{"op":"delete","card_id":"\#(mine)"}"#).status, 200)                               // not started: they can remove it
        XCTAssertEqual((jsonObj(p.handle(req("GET", "/chat/" + tokA + "/board", ["Cookie": ca])))["cards"] as! [[String: Any]]).count, 0)
    }

    func testStartingACardSendsATaskToTheAgentAndTheAgentMovesIt() {
        let p = Panel(PanelConfig(ownerToken: owner, agentToken: agent, now: { self.t }))
        let oc = loginAs(p, owner)!
        let (lid, tok) = makeLink(p, oc, name: "Ana")
        let ck = guestCookie(p.handle(req("GET", "/c/" + tok)))!
        let post = { (b: String) in p.handle(self.req("POST", "/chat/" + tok + "/card", self.json.merging(["Cookie": ck, "X-Door-Chat": "1"]) { $1 }, b)) }
        let id = jsonObj(post(#"{"op":"add","title":"Add a footer","note":"with the year"}"#))["card_id"] as! String
        XCTAssertEqual(post(#"{"op":"run","card_id":"\#(id)"}"#).status, 200)
        let a = ["Authorization": "Bearer " + agent]
        let inbox = jsonObj(p.handle(req("GET", "/agent/inbox", a)))["messages"] as! [[String: Any]]
        XCTAssertEqual("\(inbox[0]["kind"] ?? "")|\(inbox[0]["card_id"] ?? "")|\(inbox[0]["text"] ?? "")", "task|\(id)|Add a footer\nwith the year")
        // the agent starts it, then finishes it with a verdict and proof
        XCTAssertEqual(p.handle(req("POST", "/agent/card", a, #"{"op":"update","card_id":"\#(id)","request_id":"01ARZ3NDEKTSV4RRFFQ69G5FAV","column":"doing"}"#)).status, 200)
        XCTAssertEqual(post(#"{"op":"run","card_id":"\#(id)"}"#).status, 400)                                         // cannot start twice
        XCTAssertEqual(p.handle(req("POST", "/agent/card", a, #"{"op":"update","request_id":"01ARZ3NDEKTSV4RRFFQ69G5FAV","column":"done","verdict":"verified","proof":"Changed: footer.html\nCheck npm test: passed"}"#)).status, 200)
        let done = (jsonObj(p.handle(req("GET", "/chat/" + tok + "/board", ["Cookie": ck])))["cards"] as! [[String: Any]])[0]
        XCTAssertEqual("\(done["column"] ?? "") \(done["verdict"] ?? "") \((done["proof"] as? String)?.contains("npm test") ?? false)", "done verified true")
        XCTAssertEqual(post(#"{"op":"update","card_id":"\#(id)","title":"changed after done"}"#).status, 400)         // a finished card is frozen for the guest
        XCTAssertEqual(post(#"{"op":"delete","card_id":"\#(id)"}"#).status, 400)
        _ = lid
    }

    func testAgentCardApiChecksWhoIsAsking() {
        let p = makePanel()
        let a = newTenant(p, "Acme"), b = newTenant(p, "Beta")
        let ha = ["Authorization": "Bearer " + a.agent], hb = ["Authorization": "Bearer " + b.agent]
        let created = jsonObj(p.handle(req("POST", "/agent/card", ha, #"{"op":"add","owner":"owner","title":"Task from a text message","request_id":"R1"}"#)))
        let id = created["card_id"] as! String
        XCTAssertEqual(p.handle(req("POST", "/agent/card", hb, #"{"op":"update","card_id":"\#(id)","column":"done"}"#)).status, 404)       // another customer's agent
        XCTAssertEqual(p.handle(req("POST", "/agent/card", [:], #"{"op":"add","title":"x"}"#)).status, 401)
        XCTAssertEqual(p.handle(req("POST", "/agent/card", ["Authorization": "Bearer " + a.owner], #"{"op":"add","title":"x"}"#)).status, 401)
        XCTAssertEqual(p.handle(req("POST", "/agent/card", ha, #"{"op":"add","owner":"l_unknown00000","title":"x"}"#)).status, 400)
        XCTAssertEqual(p.handle(req("POST", "/agent/card", ha, #"{"op":"update","card_id":"\#(id)","column":"nope"}"#)).status, 400)
        XCTAssertEqual(p.handle(req("POST", "/agent/card", ha, #"{"op":"update","request_id":"R1","column":"review","verdict":"failed_checks"}"#)).status, 200)
        let cards = jsonObj(p.handle(req("GET", "/api/state", ["Cookie": loginAs(p, a.owner)!])))["cards"] as! [[String: Any]]
        XCTAssertEqual("\(cards[0]["column"] ?? "") \(cards[0]["verdict"] ?? "") \(cards[0]["owner"] ?? "")", "review failed_checks owner")
        XCTAssertEqual((jsonObj(p.handle(req("GET", "/api/state", ["Cookie": loginAs(p, b.owner)!])))["cards"] as! [Any]).count, 0)
    }

    func testLevelAndStepCommands() {
        let c = login()
        let post = { (b: String) in self.panel.handle(self.req("POST", "/api/command", self.json.merging(["Cookie": c]) { $1 }, b)).status }
        XCTAssertEqual(post(#"{"type":"guest_level","guest_id":"01ARZ3NDEKTSV4RRFFQ69G5FAZ","level":"act"}"#), 200)
        XCTAssertEqual(post(#"{"type":"action_allow","request_id":"01ARZ3NDEKTSV4RRFFQ69G5FAV","action_id":"a_0a1b2c3d"}"#), 200)
        XCTAssertEqual(post(#"{"type":"action_deny","request_id":"01ARZ3NDEKTSV4RRFFQ69G5FAV","action_id":"a_0a1b2c3d"}"#), 200)
        for bad in [#"{"type":"guest_level","guest_id":"01ARZ3NDEKTSV4RRFFQ69G5FAZ","level":"root"}"#, #"{"type":"guest_level","guest_id":"x","level":"act"}"#,
                    #"{"type":"action_allow","request_id":"01ARZ3NDEKTSV4RRFFQ69G5FAV","action_id":"../x"}"#, #"{"type":"action_allow","action_id":"a_0a1b2c3d"}"#] {
            XCTAssertEqual(post(bad), 400, bad)
        }
    }

    func testAgentCanMakeLinksAndSignInLinks() {
        let p = Panel(PanelConfig(ownerToken: owner, agentToken: agent, now: { self.t }))
        let a = ["Authorization": "Bearer " + agent]
        // a link made by the agent works exactly like one made in the panel
        let made = jsonObj(p.handle(req("POST", "/agent/links", a, #"{"name":"Ana","days":14,"ttl_days":3}"#)))
        let path = made["path"] as! String
        XCTAssertTrue(path.hasPrefix("/c/")); XCTAssertEqual(p.handle(req("GET", path)).status, 200)
        XCTAssertEqual(p.handle(req("POST", "/agent/links", a, #"{"days":0}"#)).status, 400)
        XCTAssertEqual(p.handle(req("POST", "/agent/links", [:], "{}")).status, 401)
        XCTAssertEqual(p.handle(req("POST", "/agent/links", ["Authorization": "Bearer " + owner], "{}")).status, 401)
        // the owner's one-time sign-in link
        let sp = jsonObj(p.handle(req("POST", "/agent/signin", a)))["path"] as! String
        XCTAssertTrue(sp.hasPrefix("/signin/"))
        let r1 = p.handle(req("GET", sp))
        XCTAssertEqual(r1.status, 302)
        let cookie = r1.headers["Set-Cookie"]!.components(separatedBy: ";")[0]
        XCTAssertEqual(p.handle(req("GET", "/api/state", ["Cookie": cookie])).status, 200)                      // a real owner session
        XCTAssertEqual(p.handle(req("GET", sp)).status, 401)                                                      // single use
        let sp2 = jsonObj(p.handle(req("POST", "/agent/signin", a)))["path"] as! String
        t += 601
        XCTAssertEqual(p.handle(req("GET", sp2)).status, 401)                                                     // expires after 10 minutes
        XCTAssertEqual(p.handle(req("GET", "/signin/" + String(repeating: "0", count: 48))).status, 401)
        XCTAssertEqual(p.handle(req("GET", "/signin/short")).status, 401)
        XCTAssertEqual(p.handle(req("POST", "/agent/signin", [:])).status, 401)
    }

    func testSignInLinksBelongToTheirOwnCustomer() {
        let p = makePanel()
        let a = newTenant(p, "Acme"), b = newTenant(p, "Beta")
        let path = jsonObj(p.handle(req("POST", "/agent/signin", ["Authorization": "Bearer " + a.agent])))["path"] as! String
        let cookie = p.handle(req("GET", path)).headers["Set-Cookie"]!.components(separatedBy: ";")[0]
        XCTAssertTrue(String(data: p.handle(req("GET", "/api/state", ["Cookie": cookie])).body, encoding: .utf8)!.contains("Acme"))
        _ = b
    }

    func testStrangersCannotLockTheOwnerOut() {
        let p = Panel(PanelConfig(ownerToken: owner, agentToken: agent, now: { self.t }))
        let attacker = { HTTPRequest(method: "POST", path: "/login", headers: ["Content-Type": "application/x-www-form-urlencoded"], body: Data("token=guess".utf8), peer: "203.0.113.9") }
        for _ in 0..<5 { XCTAssertEqual(p.handle(attacker()).status, 401) }
        XCTAssertEqual(p.handle(attacker()).status, 429)                                                   // the attacker is throttled...
        let me = HTTPRequest(method: "POST", path: "/login", headers: ["Content-Type": "application/x-www-form-urlencoded"], body: Data("token=\(owner)".utf8), peer: "198.51.100.7")
        XCTAssertEqual(p.handle(me).status, 302)                                                           // ...and the owner, from elsewhere, still gets in
        t += 61
        XCTAssertEqual(p.handle(attacker()).status, 401)                                                   // the lockout ends by itself
        // behind our own proxy the client is the forwarded address, but only when the operator says the proxy is trusted
        let spoof = { (ip: String) in HTTPRequest(method: "POST", path: "/login", headers: ["Content-Type": "application/x-www-form-urlencoded", "X-Forwarded-For": ip],
                                                  body: Data("token=guess".utf8), peer: "10.0.0.1") }
        for i in 0..<8 { _ = p.handle(spoof("198.51.100.\(i)")) }
        XCTAssertEqual(p.handle(spoof("198.51.100.99")).status, 429)                                       // untrusted header: everyone behind the proxy shares one budget
        let trusting = Panel(PanelConfig(ownerToken: owner, agentToken: agent, trustProxy: true, now: { self.t }))
        for _ in 0..<5 { _ = trusting.handle(spoof("203.0.113.9")) }
        XCTAssertEqual(trusting.handle(spoof("203.0.113.9")).status, 429)
        XCTAssertEqual(trusting.handle(spoof("198.51.100.7")).status, 401)                                 // a different client is not affected
    }

    func testGuessingSignInLinksIsThrottledToo() {
        let p = Panel(PanelConfig(ownerToken: owner, agentToken: agent, now: { self.t }))
        let bad = { HTTPRequest(method: "GET", path: "/signin/" + String(repeating: "1", count: 48), peer: "203.0.113.9") }
        for _ in 0..<5 { XCTAssertEqual(p.handle(bad()).status, 401) }
        XCTAssertEqual(p.handle(bad()).status, 429)
        let sp = jsonObj(p.handle(req("POST", "/agent/signin", ["Authorization": "Bearer " + agent])))["path"] as! String
        XCTAssertEqual(p.handle(HTTPRequest(method: "GET", path: sp, peer: "198.51.100.7")).status, 302)     // the real link still works for the owner
    }

    func testStayingSignedInSurvivesARestartAndNeverStoresTheCookie() throws {
        let path = NSTemporaryDirectory() + "door-sessions-\(UUID().uuidString).json"
        defer { try? FileManager.default.removeItem(atPath: path) }
        let p = makePanel(path: path); let a = newTenant(p, "Acme")
        let cookie = loginAs(p, a.owner)!
        let sid = String(cookie.split(separator: "=")[1])
        XCTAssertFalse(String(data: FileManager.default.contents(atPath: path)!, encoding: .utf8)!.contains(sid))      // only a hash is kept
        t += 5 * 86400
        let p2 = makePanel(path: path)                                                                                  // "the container restarted"
        XCTAssertEqual(p2.handle(req("GET", "/api/state", ["Cookie": cookie])).status, 200)
        _ = p2.handle(req("POST", "/logout", ["Cookie": cookie, "X-Door-Panel": "1"]))
        XCTAssertEqual(makePanel(path: path).handle(req("GET", "/api/state", ["Cookie": cookie])).status, 401)         // signing out really signs out
        let c2 = loginAs(p2, a.owner)!; t += 31 * 86400
        XCTAssertEqual(makePanel(path: path).handle(req("GET", "/api/state", ["Cookie": c2])).status, 401)             // expired sessions are dropped
    }
}
