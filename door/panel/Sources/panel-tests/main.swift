import Foundation

var failures = 0
func XCTAssertEqual<T: Equatable>(_ a: T, _ b: T, _ m: String = "", line: Int = #line) {
    if a != b { failures += 1; print("  FAIL line \(line): \(a) != \(b) \(m)") }
}
func XCTAssertTrue(_ c: Bool, line: Int = #line) { if !c { failures += 1; print("  FAIL line \(line)") } }
func XCTAssertFalse(_ c: Bool, line: Int = #line) { XCTAssertTrue(!c, line: line) }
func assertThrows<T>(_ e: @autoclosure () throws -> T, line: Int = #line) { do { _ = try e(); failures += 1; print("  FAIL line \(line): did not throw") } catch {} }

let tests: [(String, (PanelTests) throws -> Void)] = [
    ("login required", { $0.testLoginRequiredAndWrongTokenFails() }),
    ("login from a browser form", { $0.testLoginFromBrowserFormWorks() }),
    ("login rate limit", { $0.testLoginRateLimit() }),
    ("session expires", { $0.testSessionExpires() }),
    ("cookie flags", { $0.testCookieFlags() }),
    ("commands: session, CSRF, validation", { $0.testCommandNeedsSessionHeaderAndValidShape() }),
    ("agent: snapshot, commands, ack", { $0.testAgentRoundTripWithAck() }),
    ("stale snapshot", { $0.testStaleSnapshotFlag() }),
    ("security headers", { $0.testSecurityHeadersAndNoInlineDataInHTML() }),
    ("invite / access commands", { $0.testInviteAndAccessCommands() }),
    ("chat link binds to the first browser", { $0.testChatLinkBindsToTheFirstBrowser() }),
    ("chat round trip and limits", { $0.testChatRoundTripWithTheAgentAndLimits() }),
    ("revoked / expired links", { $0.testRevokedAndExpiredLinksStopWorkingAndTheAgentIsTold() }),
    ("chat links: isolation and restart", { try $0.testChatLinksAreIsolatedPerCustomerAndSurviveRestart() }),
    ("approval commands", { $0.testApprovalCommands() }),
    ("owner kanban + persistence", { try $0.testOwnerKanban() }),
    ("guest board: own cards and priority", { $0.testGuestBoardIsTheirOwnAndTheyChoosePriority() }),
    ("card -> task -> verified Done", { $0.testStartingACardSendsATaskToTheAgentAndTheAgentMovesIt() }),
    ("agent card API checks who asks", { $0.testAgentCardApiChecksWhoIsAsking() }),
    ("level + step commands", { $0.testLevelAndStepCommands() }),
    ("agent makes links and sign-in links", { $0.testAgentCanMakeLinksAndSignInLinks() }),
    ("sign-in links belong to one customer", { $0.testSignInLinksBelongToTheirOwnCustomer() }),
    ("strangers cannot lock the owner out", { $0.testStrangersCannotLockTheOwnerOut() }),
    ("guessing sign-in links is throttled", { $0.testGuessingSignInLinksIsThrottledToo() }),
    ("stay signed in across restarts", { try $0.testStayingSignedInSurvivesARestartAndNeverStoresTheCookie() }),
    ("settings commands keep to the fixed shape", { $0.testSettingsCommandsKeepToTheFixedShape() }),
    ("HTTP parser", { try $0.testHTTPParsing() }),
    ("SHA-256 (known vectors)", { $0.testSha256Vectors() }),
    ("tenants are isolated", { $0.testTenantsAreIsolated() }),
    ("admin API protected / hidden", { $0.testAdminRequiresTokenAndIsHiddenWithout() }),
    ("plan is pushed to the agent", { $0.testPlanIsPushedToTheAgent() }),
    ("disable / rotate cut access", { $0.testDisableAndRotateCutAccessImmediately() }),
    ("store keeps hashes, survives restart", { try $0.testStoreKeepsHashesNotTokensAndSurvivesRestart() }),
    ("real socket", { try $0.testRealSocket() }),
]
for (name, body) in tests {
    let before = failures
    do { try body(PanelTests()) } catch { failures += 1; print("  error: \(error)") }
    print(failures == before ? "ok     \(name)" : "FAIL  \(name)")
}
print(failures == 0 ? "\n\(tests.count) checks passed" : "\n\(failures) failure(s)")
exit(failures == 0 ? 0 : 1)
