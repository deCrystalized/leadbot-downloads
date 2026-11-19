import { useEffect, useState } from "react";
import { Button, Group, Select, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { http } from "@/shared/api/http";
import { Private } from "@/shared/ui/Private";

interface Preview {
  body: string; direction: string; sender_type: string;
  voice_transcript: string; voice_transcript_status: string | null; has_attachments: boolean;
  body_truncated?: boolean; voice_transcript_truncated?: boolean;
}
interface Observation { stage: string; observed_at: number; observation_only: true }
interface Row {
  id: string; principal_id: string; operator_id: string; state: string;
  client_name?: string | null; account_title?: string | null;
  preview?: Preview | null; observation?: Observation | null;
  crm_stop_reason?: string | null;
}
interface Page { items: Row[]; total: number; more: boolean; next_offset: number; view: string }
const UUID = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
const records: Record<string, string> = {
  waiting: "Передан боту", paused: "Передан человеку", completed: "Заявка уже есть",
  closed: "Диалог закрыт", released: "Ответственный изменился",
};
const stages: Record<string, string> = {
  waiting_original_delivery: "Проверял прежнюю отправку", research_pending: "Запрос ответа ожидал завершения",
  collecting_messages: "Ожидал остальные сообщения", source_review: "Требовалась проверка источника",
  waiting_transcription: "Ожидал расшифровку", screening: "Проверка условий ожидала завершения",
  wait: "Ожидал клиента", needs_operator: "Требовался сотрудник", prior_attempt_review: "Требовалась проверка прежнего запроса",
  waiting_executor: "Форма подготовлена · ожидал исполнителя", source_changed: "Данные изменились",
  technical_stop: "Техническая остановка", queued: "Запрос в очереди", reserve_action: "Ожидал разрешение действия",
  consume_action: "Ожидал подтверждение исходного действия", apply: "Обрабатывал подтверждение", dispatch: "Проверял отправку",
  queue_observing: "Проверял очередь отправки", queue_unknown: "Результат отправки неизвестен",
  delivered: "Получил подтверждение отправки", delivery_stopped: "Отправка остановлена",
  blocked: "Остановлен после ошибки", stopped: "Остановлен", expired: "Время запроса истекло",
};

const nullableText = (value: unknown) => value == null || typeof value === "string";
const optionalFlag = (value: unknown) => value === undefined || typeof value === "boolean";
function validRow(row: Row, principal: string, operator: string) {
  return row && typeof row === "object" && typeof row.id === "string" && UUID.test(row.id)
    && row.principal_id === principal && row.operator_id === operator
    && typeof row.state === "string" && Object.hasOwn(records, row.state)
    && nullableText(row.client_name) && nullableText(row.account_title)
    && (row.preview == null || typeof row.preview === "object"
      && typeof row.preview.body === "string" && typeof row.preview.voice_transcript === "string"
      && typeof row.preview.direction === "string" && typeof row.preview.sender_type === "string"
      && nullableText(row.preview.voice_transcript_status) && typeof row.preview.has_attachments === "boolean"
      && optionalFlag(row.preview.body_truncated) && optionalFlag(row.preview.voice_transcript_truncated));
}

function previewText(row: Row) {
  const p = row.preview;
  if (!p) return { who: "История", text: "Сообщений пока нет" };
  const who = p.sender_type === "system" ? "Система" : p.sender_type === "bot" ? "Автоответ"
    : p.direction === "in" && p.sender_type === "client" ? "Клиент" : "Сотрудник";
  if (p.voice_transcript_status === "done" && p.voice_transcript) return { who, text: "Расшифровка: " + p.voice_transcript + (p.voice_transcript_truncated ? "…" : "") };
  if (p.body) return { who, text: p.body + (p.body_truncated ? "…" : "") };
  if (["running", "pending", "queued", "processing", "transcribing"].includes(p.voice_transcript_status ?? "")) return { who, text: "Голосовое сообщение · расшифровка ещё готовится" };
  return { who, text: p.has_attachments ? "Вложение" : "Сообщение без текста" };
}

/** SQL queue belongs to the actual admin/author. Observations grant no actions. */
export function NativeDialogQueue({ principal, operator, enabled }: { principal: string; operator: string; enabled: boolean }) {
  const [view, setView] = useState("active");
  const [limit, setLimit] = useState("25");
  const [offset, setOffset] = useState(0);
  const ready = enabled && UUID.test(principal) && UUID.test(operator);
  const query = useQuery({
    queryKey: ["native-assistant-dialogs", principal, operator, view, limit, offset],
    enabled: ready,
    retry: false, staleTime: 0, refetchInterval: 5000, refetchOnWindowFocus: true,
    queryFn: async ({ signal }) => {
      if (!ready) throw Error("Аккаунт и автор не подтверждены");
      const value = await http.get<Page>(`/bot-dialogs/assistant/dialogs?view=${view}&operator_id=${encodeURIComponent(operator)}&limit=${limit}&offset=${offset}`, { signal });
      if (!value || !Array.isArray(value.items) || value.items.length > Number(limit)
          || value.view !== view || !Number.isSafeInteger(value.total) || value.total < 0
          || typeof value.more !== "boolean" || value.next_offset !== offset + value.items.length
          || value.items.some((row) => !validRow(row, principal, operator))
          || new Set(value.items.map(row => row.id)).size !== value.items.length) {
        throw Error("Сервер не подтвердил эту очередь");
      }
      return value;
    },
  });
  const data = ready ? query.data : undefined;
  useEffect(() => {
    if (data && !query.isError && offset > 0 && offset >= data.total) {
      setOffset(Math.max(0, Math.floor((data.total - 1) / Number(limit)) * Number(limit)));
    }
  }, [data, query.isError, offset, limit]);
  return (
    <section className="native-queue" aria-label="Очередь серверного бота">
      <div className="native-queue__head">
        <h3>Диалоги серверного бота</h3>
        <Text size="sm">{!ready || !data || query.isError ? "Количество не подтверждено" : `В этой очереди: ${data.total}`}</Text>
      </div>
      <Group className="native-queue__controls" gap="sm" align="end" wrap="wrap">
        <Select label="Очередь" value={view} allowDeselect={false}
          data={[{ value: "active", label: "Активные" }, { value: "archive", label: "Архив" }, { value: "all", label: "Все записи" }]}
          onChange={(v) => { if (v) { setView(v); setOffset(0); } }} />
        <Select label="Диалогов на странице" value={limit} allowDeselect={false}
          data={["10", "25", "50", "100"]} onChange={(v) => { if (v) { setLimit(v); setOffset(0); } }} />
        <Button variant="default" disabled={!ready || query.isFetching} onClick={() => void query.refetch()}>Обновить список</Button>
      </Group>
      {!ready && <Text size="sm">Список появится после проверки аккаунта и автора.</Text>}
      {ready && query.isError && <Text role="alert" c="var(--lc-warning-text)">
        Не удалось подтвердить очередь. {data ? "Показаны последние полученные записи." : "Список пока неизвестен."}
      </Text>}
      {ready && query.isPending && <Text role="status">Проверяем очередь…</Text>}
      {ready && data && <>
        <ul className="native-queue__grid" aria-label="Переданные диалоги" aria-busy={query.isFetching}>
          {data.items.map((row) => {
            const preview = previewText(row);
            const observation = row.observation;
            const stage = observation?.observation_only === true && typeof observation.stage === "string" && Object.hasOwn(stages, observation.stage)
              && Number.isFinite(observation.observed_at) && observation.observed_at > 0 && observation.observed_at <= 8.64e12 ? observation : null;
            return <li key={row.id} className="native-queue__dialog">
              <div className="native-queue__identity">
                <strong><Private kind="person">{row.client_name || `Диалог ${row.id.slice(0, 8)}`}</Private></strong>
                <Text size="xs" c="dimmed">{row.account_title || "Источник не указан"}</Text>
              </div>
              <Text size="xs" className="native-queue__state">{records[row.state]}</Text>
              <blockquote><small>{preview.who}</small><Private kind="text">{preview.text}</Private></blockquote>
              <Text size="sm">{!query.isError && row.crm_stop_reason === "crm_existing_request"
                ? "CRM нашла открытую заявку. Создание остановлено."
                : !query.isError && stage
                  ? `Последний этап: ${stages[stage.stage]}`
                  : "Текущий этап не подтверждён"}</Text>
              {!query.isError && stage && <Text size="xs" c="dimmed">Наблюдение: {new Date(stage.observed_at * 1000).toLocaleTimeString("ru-RU")}</Text>}
              <Link className="native-queue__open" to={`/chats/${row.id}`}>Открыть диалог</Link>
            </li>;
          })}
        </ul>
        {!query.isError && data.total === 0 && <Text size="sm">В этой очереди пока нет диалогов.</Text>}
        <Group className="native-queue__pages" gap="sm" justify="space-between">
          <Button variant="default" disabled={offset === 0 || query.isFetching} onClick={() => setOffset(Math.max(0, offset - Number(limit)))}>Предыдущая страница</Button>
          <Text size="sm">Страница {Math.floor(offset / Number(limit)) + 1}</Text>
          <Button variant="default" disabled={!data.more || query.isFetching || query.isError} onClick={() => setOffset(data.next_offset)}>Следующая страница</Button>
        </Group>
      </>}
      {ready && data && <Text size="xs" c="dimmed">{query.isError ? "Последние данные" : "Список получен"}: {new Date(query.dataUpdatedAt).toLocaleTimeString("ru-RU")}. Этап наблюдения не подтверждает создание заявки или отписку.</Text>}
    </section>
  );
}
