import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { apiGet, apiPost } from "./api";
import { ChapterView } from "./ChapterView";
import { Circles } from "./Circles";
import { useConfirm } from "./Confirm";
import { usePending } from "./hooks";
import type { ApiLogRow, AppState, Job } from "./types";

type View =
  | { kind: "глава"; n: number }
  | { kind: "дашборд" }
  | { kind: "журнал" }
  | { kind: "круги" }
  | { kind: "поиск"; q: string };

export type Notify = (text: string, kind?: "ok" | "err") => void;
export type RunCommand = (cmd: string, chapter?: number, params?: Record<string, unknown>) => Promise<void>;

// опрос /api/state: раз в секунду пока идёт задача, иначе — раз в 2,5 с
const POLL_RUNNING_MS = 1000;
const POLL_IDLE_MS = 2500;

export default function App() {
  const [state, setState] = useState<AppState | null>(null);
  const [view, setView] = useState<View | null>(null);
  const [toast, setToast] = useState<{ text: string; kind: "ok" | "err" } | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const [query, setQuery] = useState("");
  // 5.1: предыдущая задача — в ref, а не в state: иначе refresh пересоздавался бы
  // на каждый ответ, а useEffect с интервалом перезапускался бы без задержки
  const prevJob = useRef<Job | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);
  const [confirm, confirmDialog] = useConfirm();
  const [pending, run] = usePending();

  const notify: Notify = useCallback((text, kind = "err") => {
    window.clearTimeout(toastTimer.current);
    setToast({ text: text.replace(/^Error:\s*/, ""), kind });
    if (kind === "ok") toastTimer.current = window.setTimeout(() => setToast(null), 3500);
  }, []);
  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  const refresh = useCallback(async () => {
    try {
      const s = await apiGet<AppState>("/api/state");
      setState(s);
      // 5.2: задача завершилась — сменился started (новая задача уже закончилась,
      // например быстрый compile) или статус ушёл из «выполняется» → перечитать карточку
      const was = prevJob.current;
      const now = s.job;
      if (now && now.status !== "выполняется" && (!was || was.started !== now.started || was.status === "выполняется")) {
        setRefreshTick((t) => t + 1);
      }
      prevJob.current = now;
    } catch (e) {
      notify(String(e));
    }
  }, [notify]);

  const running = state?.job?.status === "выполняется";
  useEffect(() => {
    // зависимости — стабильный колбэк и булево: эффект перезапускается только
    // при смене «идёт/не идёт», а не на каждый ответ сервера
    refresh();
    const id = window.setInterval(refresh, running ? POLL_RUNNING_MS : POLL_IDLE_MS);
    return () => window.clearInterval(id);
  }, [refresh, running]);

  useEffect(() => {
    if (!view && state) {
      const first = state.chapters[0]?.chapter ?? state.briefs[0]?.chapter;
      if (first !== undefined) setView({ kind: "глава", n: first });
    }
  }, [state, view]);

  const runCommand: RunCommand = useCallback(
    async (cmd, chapter, params) => {
      try {
        const r = await apiPost<{ job: Job }>("/api/command", { cmd, chapter, params });
        // ответ POST уже несёт задачу — кнопки блокируются сразу, не дожидаясь опроса
        setState((s) => (s ? { ...s, job: r.job } : s));
      } catch (e) {
        notify(String(e));
      }
    },
    [notify],
  );

  if (!state) return <div style={{ padding: 30 }}>Подключение к конвейеру…</div>;

  const known = new Set(state.chapters.map((c) => c.chapter));
  const notStarted = state.briefs.filter((b) => !known.has(b.chapter));
  const busy = running || pending;
  const isActive = (n: number) => view?.kind === "глава" && view.n === n;

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">КОНВЕЙЕР УГАР</div>
        <div className="muted">
          Писатель: {state.models.writer}
          <br />
          Регрессия:{" "}
          {state.regression_green === null ? "не запускалась" : state.regression_green ? "зелёная ✓" : "КРАСНАЯ ✗"}
        </div>
        <div className="sidebtns">
          <button disabled={busy} onClick={() => run(() => runCommand("export"))}>Экспорт канона</button>
          <button disabled={busy} onClick={() => run(() => runCommand("regress"))}>Регрессия</button>
          <button className={view?.kind === "дашборд" ? "primary" : ""} onClick={() => setView({ kind: "дашборд" })}>
            Дашборд
          </button>
          <button className={view?.kind === "журнал" ? "primary" : ""} onClick={() => setView({ kind: "журнал" })}>
            Журнал API
          </button>
          <button className={view?.kind === "круги" ? "primary" : ""} onClick={() => setView({ kind: "круги" })}>
            Круги истории
          </button>
        </div>

        <form
          className="sidebtns"
          onSubmit={(e) => {
            e.preventDefault();
            if (query.trim()) setView({ kind: "поиск", q: query.trim() });
          }}
        >
          <input
            className="search"
            placeholder="Поиск по канону…"
            aria-label="Поиск по канону"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </form>

        <div className="muted" style={{ margin: "6px 0" }} id="queue-title">Очередь глав</div>
        <div role="list" aria-labelledby="queue-title">
          {state.chapters.map((c) => (
            <QueueItem key={c.chapter} active={isActive(c.chapter)} onOpen={() => setView({ kind: "глава", n: c.chapter })}>
              <div className="row">
                <strong>Глава {c.chapter}</strong>
                <span className={`badge b-${c.state}`}>{c.state}</span>
              </div>
              <div className="muted">
                черновик {c.draft} · Э1: {c.e1} · Э2: {c.e2}
                {c.author_min > 0 && <> · автор {c.author_min} мин</>}
              </div>
            </QueueItem>
          ))}
          {notStarted.map((b) => (
            <QueueItem key={b.chapter} active={isActive(b.chapter)} onOpen={() => setView({ kind: "глава", n: b.chapter })}>
              <div className="row">
                <strong>Глава {b.chapter}</strong>
                <span className="badge">не начата</span>
              </div>
              <div className="muted">том {b.volume} · фокал {b.focal}</div>
            </QueueItem>
          ))}
        </div>
      </aside>

      <main className="main">
        {view?.kind === "дашборд" && (
          <>
            <h1>Дашборд</h1>
            <iframe className="dash" src="/dashboard" title="Дашборд" />
          </>
        )}
        {view?.kind === "журнал" && <ApiJournal />}
        {view?.kind === "круги" && (
          <Circles
            busy={running}
            runCommand={runCommand}
            notify={notify}
            confirm={confirm}
            refreshTick={refreshTick}
            chapterCount={state.briefs.length}
          />
        )}
        {view?.kind === "поиск" && <SearchView q={view.q} notify={notify} />}
        {view?.kind === "глава" && (
          <ChapterView
            key={view.n}
            chapter={view.n}
            job={state.job}
            refreshTick={refreshTick}
            runCommand={runCommand}
            notify={notify}
            confirm={confirm}
          />
        )}
      </main>

      {/* область объявлений существует всегда — так скринридер замечает появление текста */}
      <div role="status" aria-live={toast?.kind === "err" ? "assertive" : "polite"} className="toast-region">
        {toast && (
          <div className={`toast ${toast.kind}`} onClick={() => setToast(null)}>
            {toast.text}
          </div>
        )}
      </div>
      {confirmDialog}
    </div>
  );
}

/** Элемент очереди глав: доступен с клавиатуры (Tab, Enter/Space) — аудит 5.7. */
function QueueItem({ active, onOpen, children }: { active: boolean; onOpen: () => void; children: ReactNode }) {
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen();
    }
  };
  return (
    <div
      role="listitem"
      className={"qitem" + (active ? " active" : "")}
      tabIndex={0}
      aria-current={active ? "true" : undefined}
      onClick={onOpen}
      onKeyDown={onKey}
    >
      {children}
    </div>
  );
}

function SearchView({ q, notify }: { q: string; notify: Notify }) {
  const [groups, setGroups] = useState<Record<string, { ref: string; text: string }[]> | null>(null);
  useEffect(() => {
    apiGet<Record<string, { ref: string; text: string }[]>>(`/api/find?q=${encodeURIComponent(q)}`)
      .then(setGroups)
      .catch((e) => notify(String(e)));
  }, [q, notify]);
  if (!groups) return <p>Поиск «{q}»…</p>;
  const kinds = Object.keys(groups);
  return (
    <>
      <h1>Поиск: «{q}»</h1>
      {kinds.length === 0 && <p className="muted">Ничего не найдено.</p>}
      {kinds.map((kind) => (
        <div key={kind}>
          <h2>{kind} ({groups[kind].length})</h2>
          {groups[kind].map((h, i) => (
            <div className="editrow" key={i}>
              <strong>[{h.ref}]</strong> <span>{h.text}</span>
            </div>
          ))}
        </div>
      ))}
    </>
  );
}

function ApiJournal() {
  const [rows, setRows] = useState<ApiLogRow[]>([]);
  useEffect(() => {
    apiGet<ApiLogRow[]>("/api/log").then(setRows).catch(() => setRows([]));
  }, []);
  const total = rows.reduce((s, r) => s + (r.cost_est ?? 0), 0);
  return (
    <>
      <h1>Журнал API-вызовов</h1>
      <p className="muted">logs/api.jsonl (§6.3){total > 0 && <> · стоимость показанных: ${total.toFixed(4)}</>}</p>
      <table>
        <thead>
          <tr><th>Время</th><th>Роль</th><th>Модель</th><th>Глава</th><th>Токены</th><th>$</th><th>Сек</th><th></th></tr>
        </thead>
        <tbody>
          {rows.slice().reverse().map((r, i) => (
            <tr key={i}>
              <td>{r.ts?.slice(0, 19).replace("T", " ")}</td>
              <td>{r.role}</td>
              <td>{r.model}</td>
              <td>{r.chapter ?? "—"}</td>
              <td>{r.tokens_in ?? "?"} / {r.tokens_out ?? "?"}</td>
              <td>{r.cost_est != null ? r.cost_est.toFixed(4) : "—"}</td>
              <td>{r.duration ?? "—"}</td>
              <td className={r.error ? "bad" : "ok"}>{r.error ? "ошибка" : "✓"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <p className="muted">Вызовов пока не было.</p>}
    </>
  );
}
