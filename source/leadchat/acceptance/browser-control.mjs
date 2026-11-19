import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { extname, resolve, sep } from "node:path";
import { createInterface } from "node:readline";
import { pathToFileURL } from "node:url";

const { chromium } = await import(pathToFileURL(process.env.C175_PLAYWRIGHT));
const [design, root, action, author] = process.argv.slice(2);
assert.ok(design === "classic" || design === "new");
const origin = "https://leadbot-c175.invalid";
const base = "/api/v1/bot-dialogs/assistant/native-run";
const assetPrefix = "/assets/leadbot-settings-c180-20261118-v1/" + design + "/";
const web = resolve(root, "usr/share/nginx/html");
const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".woff2": "font/woff2", ".svg": "image/svg+xml" };

const replies = createInterface({ input: process.stdin });
const waiting = new Map();
let counter = 0;
replies.on("line", line => {
  const reply = JSON.parse(line);
  const callback = waiting.get(reply.id);
  assert.ok(callback);
  waiting.delete(reply.id);
  callback(reply);
});

function bridge(data) {
  const id = ++counter;
  return new Promise(resolveReply => {
    waiting.set(id, resolveReply);
    process.stdout.write(JSON.stringify({ id, ...data }) + "\n");
  });
}

const mutations = [];
const browserErrors = [];
const bridgeErrors = [];
let latestView;
const browser = await chromium.launch({ headless: true, args: [
  "--disable-background-networking", "--disable-component-update", "--no-proxy-server",
  "--host-resolver-rules=MAP * ~NOTFOUND",
] });
const context = await browser.newContext({ serviceWorkers: "block" });
context.on("page", page => page.on("pageerror", error => browserErrors.push(error.message)));
await context.routeWebSocket("**/*", ws => ws.close());
await context.route("**/*", async route => {
  const request = route.request();
  const url = new URL(request.url());
  if (url.origin !== origin) return route.abort("blockedbyclient");
  const path = url.pathname;
  if (path.startsWith("/api/v1/")) {
    const result = await bridge({
      kind: "http",
      path: path + url.search,
      method: request.method(),
      authorization: await request.headerValue("authorization"),
      body: request.postDataJSON(),
    });
    if (result.error) {
      bridgeErrors.push(result.error);
      return route.abort();
    }
    if (path === base && request.method() === "GET" && result.status === 200) {
      latestView = JSON.parse(result.body);
    }
    if (request.method() === "POST" && (path === base + "/start" || path === base + "/stop")) {
      const body = JSON.parse(result.body);
      mutations.push([path, result.status, body.generation, body.run_id]);
    }
    return route.fulfill({ status: result.status, body: result.body, contentType: result.content_type });
  }

  const file = path.startsWith(assetPrefix) ? resolve(web, "." + path)
    : path === "/settings/leadbot" ? resolve(root, "srv/leadchat-design", design + ".html") : null;
  if (file === null || (path.startsWith(assetPrefix) && !file.startsWith(web + sep)))
    return route.fulfill({ status: 404 });
  try {
    return await route.fulfill({ body: await readFile(file), contentType: mime[extname(file)] });
  } catch {
    return route.fulfill({ status: 404 });
  }
});

try {
  assert.ok(["start", "stop", "blocked", "duplicate"].includes(action));
  const page = await context.newPage();
  await page.goto(origin + "/settings/leadbot", { waitUntil: "domcontentloaded" });
  const panel = page.getByRole("region", { name: "Серверный LeadBot" });
  if (action === "start") {
    const choice = panel.getByRole("textbox", { name: "От чьего имени отвечать" });
    await choice.click();
    await page.getByRole("option", { name: author, exact: true }).click();
    await panel.getByRole("button", { name: "Подготовить запуск" }).click();
    assert.deepEqual(mutations, []);
    await panel.getByRole("button", { name: "Подтверждаю запуск авто" }).click();
    await panel.getByText("Бот работает на сервере", { exact: true }).waitFor();
  } else if (action === "stop") {
    await panel.getByText("Бот работает на сервере", { exact: true }).waitFor();
    await panel.getByRole("button", { name: "Остановить запуск" }).click();
    await panel.getByText("Серверный бот остановлен", { exact: true }).waitFor();
  } else if (action === "blocked") {
    await panel.getByText("Запуск остановлен после ошибки", { exact: true }).waitFor();
    assert.equal(latestView?.state, "blocked");
  } else {
    await panel.getByText("Бот работает на сервере", { exact: true }).waitFor();
    const queue = panel.getByRole("region", { name: "Очередь серверного бота" });
    const label = queue.getByText("CRM нашла открытую заявку. Создание остановлено.", { exact: true });
    await label.waitFor();
    assert.equal(await label.count(), 1);
  }
  const readOnly = action === "blocked" || action === "duplicate";
  assert.deepEqual(mutations.map(([path, status]) => [path, status]),
    readOnly ? [] : [[base + "/" + action, 200]]);
  assert.deepEqual(browserErrors, []);
  assert.deepEqual(bridgeErrors, []);
  const [, , generation, runId] = readOnly
    ? [null, null, latestView.generation, latestView.run_id]
    : mutations[0];
  process.stdout.write(JSON.stringify({ kind: "passed", action, generation, runId }) + "\n");
} finally {
  await browser.close();
  replies.close();
  process.stdin.pause();
}

