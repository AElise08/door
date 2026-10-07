import Foundation
import DoorPanelKit

let env = ProcessInfo.processInfo.environment
let host = env["DOOR_PANEL_HOST"] ?? "127.0.0.1"
let port = UInt16(env["DOOR_PANEL_PORT"] ?? "9630") ?? 9630

func fail(_ m: String) -> Never { FileHandle.standardError.write(Data("[door-panel] \(m)\n".utf8)); exit(2) }

let owner = env["DOOR_PANEL_OWNER_TOKEN"], agent = env["DOOR_PANEL_AGENT_TOKEN"], admin = env["DOOR_PANEL_ADMIN_TOKEN"]
let dataFile = env["DOOR_PANEL_DATA"]
// Single-tenant: owner + agent tokens. Multi-tenant: admin token + data file. Either, or both.
if owner != nil || agent != nil {
    guard let o = owner, let a = agent, o.count >= 24, a.count >= 24 else { fail("set both DOOR_PANEL_OWNER_TOKEN and DOOR_PANEL_AGENT_TOKEN (min. 24 characters each)") }
    guard o != a else { fail("the two tokens must differ") }
}
if let a = admin, a.count < 32 { fail("DOOR_PANEL_ADMIN_TOKEN must have at least 32 characters") }
if owner == nil && (admin == nil || dataFile == nil) { fail("set owner+agent tokens, or DOOR_PANEL_ADMIN_TOKEN together with DOOR_PANEL_DATA") }
let loopback = host == "127.0.0.1" || host == "::1"
if !loopback && env["DOOR_PANEL_ALLOW_REMOTE_BIND"] != "1" {
    fail("refusing to bind outside 127.0.0.1; put TLS (nginx) in front")
}

let panel = Panel(PanelConfig(ownerToken: owner, agentToken: agent, adminToken: admin, storePath: dataFile, secureCookie: env["DOOR_PANEL_SECURE"] == "1", trustProxy: env["DOOR_PANEL_TRUST_PROXY"] == "1"))
let server = HTTPServer(handler: panel.handle)
do { try server.start(host: host, port: port) } catch { fail("could not open \(host):\(port)") }
print("door-panel: http://\(host):\(server.port)")
signal(SIGPIPE, SIG_IGN)
dispatchMain()
