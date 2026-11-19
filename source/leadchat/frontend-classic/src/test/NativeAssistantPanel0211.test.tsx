import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NativeAssistantPanel } from "@/features/bot-dialogs/NativeAssistantPanel";
import { LeadbotTab } from "@/features/settings/leadbot/LeadbotTab";
import { useSessionStore } from "@/shared/stores/sessionStore";
import { fakeUser, resetSessionStore } from "./helpers";
import { renderWithProviders } from "./render";

const owner = fakeUser.id;
const author = "33333333-3333-4333-8333-333333333333";
const runId = "44444444-4444-4444-8444-444444444444";
const nativePath = "/bot-dialogs/assistant/native-run";
function stopped() {
  return { principal_id: owner, run_id: null as string | null, operator_id: null as string | null,
    state: "stopped", generation: 0, mode: "auto", auto_enabled: false,
    native_supported: true, configured: true, worker_ready: true, start_available: true,
    observer_disconnect_stops_run: false };
}
function running(mode = "auto") {
  return { ...stopped(), run_id: runId, operator_id: owner, generation: 1,
    state: "running", auto_enabled: mode === "auto", mode };
}
type Request = { path: string; method: string; body: Record<string, unknown> | null };
let requests: Request[];
let value: ReturnType<typeof stopped>;
let readError: boolean;
let unknownStart: boolean;
let capabilitiesOwner: string;
let pendingRead: Promise<Response> | null;

beforeEach(() => {
  requests = []; value = stopped(); readError = false; unknownStart = false;
  capabilitiesOwner = owner; pendingRead = null;
  resetSessionStore({ user: { ...fakeUser, role: "admin" }, accessToken: "synthetic", permissions: ["bots:manage"] });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).replace("/api/v1", "");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    requests.push({ path, method, body });
    const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
    if (path === "/leadbot" && method === "GET") return json({
      connection: { url: "", token_set: false, source: "env" },
      is_ready: false, enabled: false, mode: "suggest", context_messages: 30,
      account_ids: [], accounts: [],
    });
    if (path.startsWith("/leadbot/") && method === "GET") return json({ items: [], in_progress: [], silent: [] });
    if (path === "/auth/me") return json({ id: useSessionStore.getState().user?.id, role: "admin" });
    if (path.endsWith("/capabilities")) return json({ principal: { id: capabilitiesOwner }, authors: [
      { id: owner, full_name: "Анна" }, { id: author, full_name: "Анна" },
    ] });
    if (path.startsWith("/bot-dialogs/assistant/dialogs?")) {
      const query = new URLSearchParams(path.split("?")[1]);
      return json({ items: [], total: 0, more: false, next_offset: Number(query.get("offset")), view: query.get("view") });
    }
    if (path === nativePath && method === "GET") {
      if (pendingRead) return pendingRead;
      if (readError) return json({ error: { code: "unavailable", message: "opaque_internal_error" } }, 503);
      return json(value);
    }
    if (path === nativePath + "/start") {
      value = { ...running(), operator_id: String(body.operator_id) };
      if (unknownStart) throw new TypeError("lost acknowledgement");
      return json(value);
    }
    if (path === nativePath + "/stop") {
      value = { ...value, state: "stopped", auto_enabled: false, generation: value.generation + 1 };
      return json(value);
    }
    throw Error("Unexpected route " + path);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const mutations = () => requests.filter((r) => r.method !== "GET");
async function mount() {
  const rendered = renderWithProviders(<NativeAssistantPanel />);
  await screen.findByText("Серверный бот остановлен");
  await waitFor(() => expect(screen.getByRole("button", { name: "Подготовить запуск" })).toBeEnabled());
  return rendered;
}

it("mount, explicit refresh and unmount observe without a Run or business write", async () => {
  const ui = await mount();
  await userEvent.click(screen.getByRole("button", { name: "Обновить состояние" }));
  ui.unmount();
  expect(mutations()).toEqual([]);
  expect(requests.every((r) => ["/auth/me", nativePath, "/bot-dialogs/assistant/capabilities", "/bot-dialogs/assistant/dialogs"].includes(r.path.split("?")[0]))).toBe(true);
});

it("only confirmed explicit launch posts actual principal, selected author and generation", async () => {
  const ui = await mount();
  await userEvent.click(screen.getByRole("button", { name: "Подготовить запуск" }));
  expect(mutations()).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: "Подтверждаю запуск авто" }));
  await screen.findByText("Бот работает на сервере");
  expect(mutations()).toEqual([{ path: nativePath + "/start", method: "POST",
    body: { expected_principal_id: owner, operator_id: owner, expected_generation: 0 } }]);
  ui.unmount();
  expect(value.state).toBe("running");
  expect(mutations()).toHaveLength(1);
});

it("explicit stop uses the displayed Run generation and closing never stops it", async () => {
  value = running();
  renderWithProviders(<NativeAssistantPanel />);
  await screen.findByText("Бот работает на сервере");
  await userEvent.click(screen.getByRole("button", { name: "Остановить запуск" }));
  await screen.findByText("Серверный бот остановлен");
  expect(mutations()).toEqual([{ path: nativePath + "/stop", method: "POST",
    body: { expected_principal_id: owner, expected_generation: 1 } }]);
});

it("failed status retains a visibly stale running Run and its stop control", async () => {
  value = running(); renderWithProviders(<NativeAssistantPanel />);
  await screen.findByText("Бот работает на сервере");
  readError = true;
  await userEvent.click(screen.getByRole("button", { name: "Обновить состояние" }));
  await screen.findByText("Связь потеряна · показано последнее подтверждённое состояние");
  expect(screen.getByRole("button", { name: "Остановить запуск" })).toBeEnabled();
  expect(screen.queryByText("Серверный бот остановлен")).not.toBeInTheDocument();
  expect(screen.queryByText("opaque_internal_error")).not.toBeInTheDocument();
  expect(mutations()).toEqual([]);
});

it("unknown launch is never resubmitted; GET can observe its original outcome", async () => {
  await mount(); unknownStart = true;
  await userEvent.click(screen.getByRole("button", { name: "Подготовить запуск" }));
  await userEvent.click(screen.getByRole("button", { name: "Подтверждаю запуск авто" }));
  await screen.findByText("Запуск пока не подтверждён. Автоматического повтора не было");
  expect(screen.getByRole("button", { name: "Подготовить запуск" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Обновить состояние" }));
  await screen.findByText("Бот работает на сервере");
  expect(screen.queryByText("Запуск пока не подтверждён. Автоматического повтора не было")).not.toBeInTheDocument();
  expect(mutations()).toHaveLength(1);
});

it("a persisted running Run with no ready worker is never green working and remains stoppable", async () => {
  value = { ...running(), worker_ready: false, start_available: false };
  renderWithProviders(<NativeAssistantPanel />);
  await screen.findByText("Авто включено · работа обработчика не подтверждена");
  expect(screen.getByRole("status")).not.toHaveAttribute("data-working");
  expect(screen.getByRole("button", { name: "Остановить запуск" })).toBeEnabled();
  expect(mutations()).toEqual([]);
});

it("stored server rehearsal is not advertised as working customer Auto", async () => {
  value = running("rehearsal"); renderWithProviders(<NativeAssistantPanel />);
  await screen.findByText("Серверный запуск без отправок");
  expect(screen.queryByText("Бот работает на сервере")).not.toBeInTheDocument();
  expect(mutations()).toEqual([]);
});

it("different capability principal never enables launch or substitutes authors", async () => {
  capabilitiesOwner = author; renderWithProviders(<NativeAssistantPanel />);
  await screen.findByText("Серверный бот остановлен");
  expect(screen.getByRole("button", { name: "Подготовить запуск" })).toBeDisabled();
  expect(mutations()).toEqual([]);
});

it("explicit refresh can recover author list after its initial principal mismatch", async () => {
  capabilitiesOwner = author; renderWithProviders(<NativeAssistantPanel />);
  await screen.findByText("Серверный бот остановлен");
  expect(screen.getByRole("button", { name: "Подготовить запуск" })).toBeDisabled();
  capabilitiesOwner = owner;
  await userEvent.click(screen.getByRole("button", { name: "Обновить состояние" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Подготовить запуск" })).toBeEnabled());
  expect(mutations()).toEqual([]);
});

it.each(["manager", "head", "observer"] as const)("%s cannot initialize admin controls or poll", (role) => {
  resetSessionStore({ user: { ...fakeUser, role }, permissions: [] });
  renderWithProviders(<NativeAssistantPanel />);
  expect(screen.queryByRole("region", { name: "Серверный LeadBot" })).not.toBeInTheDocument();
  expect(requests).toEqual([]);
});

it("admin without bots permission cannot initialize controls", () => {
  resetSessionStore({ user: { ...fakeUser, role: "admin" }, permissions: [] });
  renderWithProviders(<NativeAssistantPanel />);
  expect(requests).toEqual([]);
});

it("same-name authors remain distinct and the selected UUID is used", async () => {
  await mount();
  await userEvent.click(screen.getByRole("textbox", { name: "От чьего имени отвечать" }));
  await userEvent.click(await screen.findByRole("option", { name: "Анна · 33333333" }));
  await userEvent.click(screen.getByRole("button", { name: "Подготовить запуск" }));
  await userEvent.click(screen.getByRole("button", { name: "Подтверждаю запуск авто" }));
  await screen.findByText("Бот работает на сервере");
  expect(mutations()[0].body?.operator_id).toBe(author);
});

it("a new observed Run invalidates an older displayed confirmation", async () => {
  await mount();
  await userEvent.click(screen.getByRole("button", { name: "Подготовить запуск" }));
  expect(screen.getByRole("button", { name: "Подтверждаю запуск авто" })).toBeEnabled();
  value = running();
  await userEvent.click(screen.getByRole("button", { name: "Обновить состояние" }));
  await screen.findByText("Бот работает на сервере");
  expect(screen.queryByRole("button", { name: "Подтверждаю запуск авто" })).not.toBeInTheDocument();
  expect(mutations()).toEqual([]);
});

it("an account change discards prior confirmation without a stop or launch", async () => {
  await mount();
  await userEvent.click(screen.getByRole("button", { name: "Подготовить запуск" }));
  act(() => useSessionStore.setState({ user: { ...fakeUser, id: author, role: "manager" }, permissions: [] }));
  expect(screen.queryByRole("button", { name: "Подтверждаю запуск авто" })).not.toBeInTheDocument();
  expect(mutations()).toEqual([]);
});

it("unmount before a late status read does not start or stop anything", async () => {
  let resolve: (response: Response) => void = () => {};
  pendingRead = new Promise<Response>((done) => { resolve = done; });
  const ui = renderWithProviders(<NativeAssistantPanel />);
  await waitFor(() => expect(requests.some((r) => r.path === nativePath)).toBe(true));
  ui.unmount();
  await act(async () => resolve(new Response(JSON.stringify(running()), { status: 200 })));
  expect(mutations()).toEqual([]);
});

it("starts and stops the same native Run from the built-in LeadBot settings page", async () => {
  renderWithProviders(<LeadbotTab />, { route: "/settings/leadbot" });
  await screen.findByRole("region", { name: "Серверный LeadBot" });
  await waitFor(() => expect(screen.getByRole("button", { name: "Подготовить запуск" })).toBeEnabled());
  expect(mutations()).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: "Подготовить запуск" }));
  await userEvent.click(screen.getByRole("button", { name: "Подтверждаю запуск авто" }));
  await screen.findByText("Бот работает на сервере");
  await userEvent.click(screen.getByRole("button", { name: "Остановить запуск" }));
  await screen.findByText("Серверный бот остановлен");
  expect(mutations().map(({path, method}) => [method, path])).toEqual([
    ["POST", nativePath + "/start"], ["POST", nativePath + "/stop"],
  ]);
});
