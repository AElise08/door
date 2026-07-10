import { chromium, webkit } from "playwright";
import fs from "node:fs";

const todoPort = process.env.TODO_PORT || "9933";
const hudPort = process.env.HUD_PORT || "9900";
const ttydBrowserPort = process.env.TTYD_BROWSER_PORT || "7681";
const origins = [`http://127.0.0.1:${todoPort}`, `http://127.0.0.1:${hudPort}`];
const videoDir = new URL("./videos/", import.meta.url).pathname;
fs.mkdirSync(videoDir, { recursive: true });

let failures = [];
for (const [engine, launcher] of [["chromium", chromium], ["webkit", webkit]]) {
  const browser = await launcher.launch({ headless: true });
  for (const origin of origins) {
    const context = await browser.newContext({ recordVideo: { dir: videoDir } });
    const page = await context.newPage();
    const errors = [];
    page.on("console", msg => { if (msg.type() === "error") errors.push(msg.text()); });
    page.on("pageerror", err => errors.push(String(err)));
    page.on("response", r => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
    const marker = `verify-browser-${engine}-${Date.now()}`;
    let taskId = null;
    try {
      await page.goto(origin + "/", { waitUntil: "networkidle" });
      await page.locator("h1", { hasText: "Priorities" }).waitFor();
      await page.locator("#addInput").fill(marker);
      await page.locator("#addInput").press("Enter");
      const row = page.locator("li.task", { hasText: marker });
      await row.waitFor();
      taskId = await row.getAttribute("data-id");
      await row.locator(".task-text").click();
      await page.locator("body.modal-open").waitFor();
      await page.locator("#composer").fill("browser verification comment");
      await page.locator(".composer .btn-volt").click();
      await page.locator(".ev-text", { hasText: "browser verification comment" }).waitFor();
      await page.keyboard.press("Escape");
      await page.locator("body:not(.modal-open)").waitFor();
      await page.locator('a[href="/dashboard"]').first().click();
      await page.locator("h1", { hasText: "MyPeople - HUD" }).waitFor();
      const attachHref = await page.locator("a.attach").first().getAttribute("href");
      if (!attachHref || new URL(attachHref).port !== ttydBrowserPort) {
        throw new Error(`attach port ${attachHref || "missing"}; expected ${ttydBrowserPort}`);
      }
      await page.locator('a[href="/"]').first().click();
      await page.locator("h1", { hasText: "Priorities" }).waitFor();
      if (errors.length) throw new Error(errors.join(" | "));
    } catch (err) {
      failures.push(`${engine} ${origin}: ${err}`);
    } finally {
      if (taskId) {
        await page.evaluate(async id => {
          await fetch("/todo/update", { method: "POST", credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ op: "del", id }) });
        }, taskId).catch(() => {});
      }
      await context.close();
    }
  }
  await browser.close();
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log(`browser journeys passed; videos: ${videoDir}`);
