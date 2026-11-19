import { useEffect, useRef, useState } from "react";
import { Button, Group, Select, Text } from "@mantine/core";
import { http } from "@/shared/api/http";
import { useSessionStore } from "@/shared/stores/sessionStore";
import { createRun, type NativeRunController, type NativeRunState, type StartTicket } from "./nativeRunController";
import { NativeDialogQueue } from "./NativeDialogQueue";
import "./native-assistant.css";

interface Author { id: string; full_name: string }
interface Capabilities { principal: Author; authors: Author[] }
interface PanelState {
  principal: string;
  run: NativeRunState;
  authors: Author[];
  authorsReady: boolean;
}

/** Observation owns only a poll. Only explicit buttons may change the SQL Run. */
export function NativeAssistantPanel() {
  const principal = useSessionStore((s) => s.user?.id ?? "");
  const allowed = useSessionStore((s) => s.user?.role === "admin" && s.permissions.includes("bots:manage"));
  const controller = useRef<NativeRunController | null>(null);
  const refreshAuthors = useRef<() => Promise<void>>(async () => {});
  const operator = useRef(principal);
  const [selected, setSelected] = useState(principal);
  const [panel, setPanel] = useState<PanelState | null>(null);
  const [ticket, setTicket] = useState<StartTicket | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!allowed) return;
    let closed = false;
    operator.current = principal;
    setSelected(principal); setTicket(null); setError("");
    let authors: Author[] = [], authorsReady = false;
    const currentPrincipal = () => useSessionStore.getState().user?.id ?? "";
    const publish = (run: NativeRunState) => {
      if (!closed && currentPrincipal() === principal) {
        if (!run.stale && !run.unknown && !run.error) setError("");
        setPanel({ principal, run: { ...run, view: run.view ? { ...run.view } : null }, authors, authorsReady });
      }
    };
    const run = createRun({
      get: (path) => http.get(path), post: (path, body) => http.post(path, body),
      identity: () => http.get("/auth/me"), principal: currentPrincipal,
      operator: () => operator.current, onChange: publish,
    });
    controller.current = run;
    publish(run.state);
    const loadAuthors = async () => {
      try {
        const value = await http.get<Capabilities>("/bot-dialogs/assistant/capabilities");
        if (closed || currentPrincipal() !== principal) return;
        if (value?.principal?.id !== principal || !Array.isArray(value.authors)
            || value.authors.some((a) => typeof a.id !== "string" || typeof a.full_name !== "string")) throw Error("Не подтверждён автор");
        authors = value.authors; authorsReady = true; publish(run.state);
      } catch {
        if (!closed && currentPrincipal() === principal) { authorsReady = false; publish(run.state); }
      }
    };
    refreshAuthors.current = loadAuthors;
    void loadAuthors();
    run.watch();
    return () => {
      closed = true; run.unwatch();
      if (controller.current === run) controller.current = null;
    };
  }, [allowed, principal]);

  if (!allowed) return null;
  const state = panel?.principal === principal ? panel.run : null;
  const view = state?.view?.principal_id === principal ? state.view : null;
  const active = view?.state === "running";
  const working = active && view.mode === "auto" && view.configured && view.worker_ready;
  const confirmed = !!view && !state?.stale;
  const authors = panel?.principal === principal ? panel.authors : [];
  const chosen = active ? view.operator_id : selected;
  const label = (author: Author) => {
    const sameName = authors.filter((a) => a.full_name === author.full_name);
    const prefix = author.id.slice(0, 8);
    const distinctId = sameName.some((a) => a.id !== author.id && a.id.startsWith(prefix)) ? author.id : prefix;
    return author.full_name + (sameName.length > 1 ? ` · ${distinctId}` : "")
      + (author.id === principal ? " (вы)" : "");
  };
  const author = authors.find((a) => a.id === chosen);
  const title = !view ? "Состояние сервера не подтверждено"
    : state?.stale ? "Связь потеряна · показано последнее подтверждённое состояние"
    : working ? "Бот работает на сервере"
    : active ? view.mode === "auto" ? "Авто включено · работа обработчика не подтверждена" : "Серверный запуск без отправок"
    : view.state === "blocked" ? "Запуск остановлен после ошибки" : "Серверный бот остановлен";
  const canStart = confirmed && !active && !state?.busy && !state?.unknown
    && view.start_available && panel?.authorsReady && !!author;
  const confirmationCurrent = ticket?.principal_id === principal && confirmed && !active
    && ticket.expected_generation === view.generation && ticket.operator_id === selected && view.start_available;
  const run = controller.current;
  const refresh = () => { void refreshAuthors.current(); void run?.inspect().catch(() => {}); };
  const prepare = async () => {
    setError(""); setTicket(null);
    try {
      const value = await run?.prepareStart();
      if (value && controller.current === run && useSessionStore.getState().user?.id === principal) setTicket(value);
    } catch { setError("Запуск не подготовлен. Проверьте состояние сервера и автора"); }
  };
  const start = async () => {
    const confirmedTicket = ticket; setTicket(null); setError("");
    if (!run || !confirmedTicket) return;
    try { await run.start(confirmedTicket); }
    catch { if (controller.current === run) setError("Запуск пока не подтверждён. Автоматического повтора не было"); }
  };
  const stop = async () => {
    setTicket(null); setError("");
    try { await run?.stop(); }
    catch { if (controller.current === run) setError("Остановка пока не подтверждена. Автоматического повтора не было"); }
  };

  return (
    <section className="lc-card native-assistant" aria-label="Серверный LeadBot">
      <div className="native-assistant__head">
        <div>
          <h2>LeadBot в LeadChat</h2>
          <p>Для оформления в CRM оставьте открытой обычную вкладку «Чаты» с расширением.</p>
        </div>
        <Text role="status" className="native-assistant__status" data-working={confirmed && working || undefined}>{title}</Text>
      </div>
      <div className="native-assistant__controls">
        <Select label="От чьего имени отвечать" className="lc-field" value={chosen}
          placeholder={active ? "Автор недоступен" : "Выберите сотрудника"}
          data={authors.map((a) => ({ value: a.id, label: label(a) }))}
          disabled={!confirmed || active || !!state?.busy || !!state?.unknown || !panel?.authorsReady}
          onChange={(id) => { if (id) { operator.current = id; setSelected(id); setTicket(null); } }} />
        <Group gap="xs">
          <Button variant="default" onClick={refresh} disabled={state?.busy}>Обновить состояние</Button>
          {active
            ? <Button color="red" onClick={() => void stop()} loading={state?.busy}
                disabled={!!state?.unknown}>Остановить запуск</Button>
            : <Button onClick={() => void prepare()} disabled={!canStart}>Подготовить запуск</Button>}
        </Group>
      </div>
      {active && <Text size="sm">Автор: {author ? label(author) : "недоступен"}</Text>}
      {confirmationCurrent && (
        <div className="native-assistant__confirmation" role="alert">
          <Text>Включить рабочий авто от имени «{author ? label(author) : "сотрудник"}»?</Text>
          <Text size="sm">Бот будет отвечать клиентам по новым обращениям. Заявки в работе, переносы и претензии остаются сотрудникам.</Text>
          <Group gap="xs">
            <Button variant="default" onClick={() => setTicket(null)}>Отмена</Button>
            <Button onClick={() => void start()} disabled={state?.busy || !!state?.unknown}>Подтверждаю запуск авто</Button>
          </Group>
        </div>
      )}
      {(error || state?.unknown || state?.error) && <Text role="alert" c="var(--lc-warning-text)">
        {error || (state?.unknown ? "Результат команды пока неизвестен. Повтор не отправляется — проверьте состояние" : "Связь с сервером не подтверждена. Последнее состояние сохранено")}
      </Text>}
      {confirmed && !active && !view.start_available && <Text size="sm">Серверный запуск ещё не подготовлен. Авто выключено.</Text>}
      <Text size="xs" c="dimmed">
        {state?.lastConfirmedAt ? `Сервер проверен: ${new Date(state.lastConfirmedAt).toLocaleTimeString("ru-RU")}. ` : ""}
        Закрытие этой страницы не останавливает бота. Для остановки используйте кнопку выше.
      </Text>
      <NativeDialogQueue key={`${principal}:${chosen}`} principal={principal} operator={chosen ?? ""}
        enabled={confirmed && !!panel?.authorsReady && !!author} />
    </section>
  );
}
