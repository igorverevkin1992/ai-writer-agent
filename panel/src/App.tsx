import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "./api";
import { ChapterView } from "./ChapterView";
import type { ApiLogRow, AppState, Job } from "./types";

type View =
  | { kind: "глава"; n: number }
  | { kind: "дашборд" }
  | { kind: "журнал" }
  | { kind: "поиск"; q: string };

export type Notify = (text: string, kind?: "ok" | "err") => void;

export default function App() {
  const [state, setState] = useState<AppState | null>(null);
  const [view, setView] = useState<View | null>(null);
  const [toast, setToast] = useState<{ text: string; kind: "ok" | "err" } | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const [prevJob, setPrevJob] = useState<Job | null>(null);
  const [query, setQuery] = useState("");

  const notify: Notify = useCallback((text, kind = "err") => {
    setToast({ text: text.replace(/^Error:\s*/, ""), kind });
    if (kind === "ok") setTimeout(() => setToast(null), 3500);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const s = await apiGet<AppState>("/api/state");
      setState(s);
      // задача завершилась → перечитать карточку главы
      if (prevJob?.status === "выполняется" && s.job && s.job.status !== "выполняется") {
        setRefreshTick((t) => t + 1);
      }
      setPrevJob(s.job);
    } catch (e) {
      notify(String(e));
    }
  }, [prevJob, notify]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, state?.job?.status === "выполняется" ? 1000 : 2500);
    return () => clearInterval(id);
  }, [refresh, state?.job?.status]);

  useEffect(() => {
    if (!view && state) {
      const first = state.chapters[0]?.chapter ?? state.briefs[0]?.chapter;
      if (first !== undefined) setView({ kind: "глава", n: first });
    }
  }, [state, view]);

  const runCommand = async (cmd: string, chapter?: number) => {
    try {
      await apiPost("/api/command", { cmd, chapter });
      refresh();
    } catch (e) {
      notify(String(e));
    }
  };

  if (!state) return <div style={{ padding: 30 }}>Подключение к конвейеру…</div>;

  const known = new Set(state.chapters.map((c) => c.chapter));
  const notStarted = state.briefs.filter((b) => !known.has(b.chapter));
  const busy = state.job?.status === "выполняется";

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
          <button disabled={busy} onClick={() => runCommand("export")}>Экспорт канона</button>
          <button disabled={busy} onClick={() => runCommand("regress")}>Регрессия</button>
          <button className={view?.kind === "дашборд" ? "primary" : ""} onClick={() => setView({ kind: "дашборд" })}>
            Дашборд
          </button>
          <button className={view?.kind === "журнал" ? "primary" : ""} onClick={() => setView({ kind: "журнал" })}>
            Журнал API
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
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </form>

        <div className="muted" style={{ margin: "6px 0" }}>Очередь глав</div>
        {state.chapters.map((c) => (
          <div
            key={c.chapter}
            className={"qitem" + (view?.kind === "глава" && view.n === c.chapter ? " active" : "")}
            onClick={() => setView({ kind: "глава", n: c.chapter })}
          >
            <div className="row">
              <strong>Глава {c.chapter}</strong>
              <span className={`badge b-${c.state}`}>{c.state}</span>
            </div>
            <div className="muted">
              черновик {c.draft} · Э1: {c.e1} · Э2: {c.e2}
              {c.author_min > 0 && <> · автор {c.author_min} мин</>}
            </div>
          </div>
        ))}
        {notStarted.map((b) => (
          <div
            key={b.chapter}
            className={"qitem" + (view?.kind === "глава" && view.n === b.chapter ? " active" : "")}
            onClick={() => setView({ kind: "глава", n: b.chapter })}
          >
            <div className="row">
              <strong>Глава {b.chapter}</strong>
              <span className="badge">не начата</span>
            </div>
            <div className="muted">том {b.volume} · фокал {b.focal}</div>
          </div>
        ))}
      </aside>

      <main className="main">
        {view?.kind === "дашборд" && (
          <>
            <h1>Дашборд</h1>
            <iframe className="dash" src="/dashboard" title="Дашборд" />
          </>
        )}
        {view?.kind === "журнал" && <ApiJournal />}
        {view?.kind === "поиск" && <SearchView q={view.q} notify={notify} />}
        {view?.kind === "глава" && (
          <ChapterView
            key={view.n}
            chapter={view.n}
            job={state.job}
            refreshTick={refreshTick}
            runCommand={runCommand}
            notify={notify}
          />
        )}
      </main>

      {toast && (
        <div className={`toast ${toast.kind}`} onClick={() => setToast(null)}>
          {toast.text}
        </div>
      )}
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
