import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "./api";
import type { Notify } from "./App";

interface Step { n: number; name: string; text: string; chapters?: string }
interface Circle { scope: string; key: number | null; title: string; steps: Step[]; weak_spot?: string; summary?: string; generated?: string }
interface Part { part: number; title: string; from_chapter: number; to_chapter: number }
interface CirclesData { circles: Circle[]; parts: Part[]; prompts: string[] }

const SCOPE_LABEL: Record<string, string> = { книга: "Книга", часть: "Часть", глава: "Глава" };

export function Circles(props: {
  busy: boolean;
  runCommand: (cmd: string, chapter?: number, params?: Record<string, unknown>) => Promise<void>;
  notify: Notify;
  refreshTick: number;
}) {
  const { busy, runCommand, notify, refreshTick } = props;
  const [data, setData] = useState<CirclesData | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [manualStem, setManualStem] = useState<string>("");
  const [pasted, setPasted] = useState("");

  const load = useCallback(() => {
    apiGet<CirclesData>("/api/circles").then(setData).catch((e) => notify(String(e)));
  }, [notify]);
  useEffect(load, [load, refreshTick]);

  if (!data) return <p>Загрузка…</p>;

  const generate = async (scope: string, redo = false) => {
    const count = scope === "книга" ? 1 : scope === "части" ? data.parts.length : scope === "главы" ? 46 : 1 + data.parts.length + 46;
    if (!window.confirm(`Построить круги истории: ${scope} (${count} вызов(ов) модели${redo ? ", с пересчётом" : ""})?`)) return;
    await runCommand("story-circles", undefined, { scope, redo });
  };

  const copyPrompt = async (stem: string) => {
    try {
      const r = await apiGet<{ text: string }>(`/api/circles/prompt/${stem}`);
      await navigator.clipboard.writeText(r.text);
      notify(`Промпт «${stem}» скопирован — вставьте ответ модели ниже.`, "ok");
      setManualStem(stem);
    } catch (e) {
      notify(String(e));
    }
  };

  const acceptManual = async () => {
    const m = manualStem.match(/^(книга|часть|глава)_?(\d+)?$/);
    if (!m) return notify("Выберите промпт (книга / часть_N / глава_NN).");
    try {
      await apiPost("/api/circles/manual", { scope: m[1], key: m[2] ? +m[2] : null, text: pasted });
      notify("Круг принят.", "ok");
      setPasted("");
      load();
    } catch (e) {
      notify(String(e));
    }
  };

  const groups = ["книга", "часть", "глава"].map((s) => ({ scope: s, items: data.circles.filter((c) => c.scope === s) }));

  return (
    <>
      <h1>Круги истории</h1>
      <p className="muted">
        Восемь шагов («Ты → Потребность → Переход → Поиск → Обретение → Расплата → Возвращение → Изменение»)
        по материалу канона — для книги, каждой части ({data.parts.length}) и каждой главы. Черновики
        лежат в <code>круги_истории/</code>; в канон вносятся через canon-commit.
      </p>
      <div className="actions">
        <button className="primary" disabled={busy} onClick={() => generate("всё")}>Построить все круги</button>
        <button disabled={busy} onClick={() => generate("книга")}>Книга</button>
        <button disabled={busy} onClick={() => generate("части")}>Части</button>
        <button disabled={busy} onClick={() => generate("главы")}>Главы</button>
        <button disabled={busy} onClick={() => generate("всё", true)}>Пересчитать всё</button>
      </div>

      {data.prompts.length > 0 && (
        <details className="card">
          <summary>Ручной режим: промпты без ответа ({data.prompts.length})</summary>
          <div className="actions">
            {data.prompts.map((p) => {
              const stem = p.replace(/\.md$/, "");
              return <button key={p} onClick={() => copyPrompt(stem)}>{stem}</button>;
            })}
          </div>
          {manualStem && (
            <>
              <p className="muted">Ответ модели для «{manualStem}»:</p>
              <textarea value={pasted} onChange={(e) => setPasted(e.target.value)} placeholder="Вставьте JSON-ответ модели" />
              <div className="actions"><button className="primary" disabled={!pasted.trim()} onClick={acceptManual}>Принять круг</button></div>
            </>
          )}
        </details>
      )}

      {data.circles.length === 0 && <p className="muted">Кругов ещё нет — нажмите «Построить все круги».</p>}

      {groups.map(({ scope, items }) => items.length > 0 && (
        <div key={scope}>
          <h2>{SCOPE_LABEL[scope]}{scope !== "книга" ? ` (${items.length})` : ""}</h2>
          {items.map((c) => {
            const id = `${c.scope}_${c.key ?? ""}`;
            const partTitle = c.scope === "часть" ? data.parts.find((p) => p.part === c.key)?.title : "";
            return (
              <div className="card" key={id}>
                <div className="row" style={{ display: "flex", justifyContent: "space-between", cursor: "pointer" }}
                  onClick={() => setOpen(open === id ? null : id)}>
                  <strong>{c.title}{partTitle ? ` · «${partTitle}»` : ""}</strong>
                  <span className="muted">{c.summary}</span>
                </div>
                {open === id && (
                  <ol className="circle">
                    {c.steps.map((s) => (
                      <li key={s.n}>
                        <strong>{s.name}</strong>{s.chapters ? <span className="muted"> · {s.chapters}</span> : null}
                        <div>{s.text}</div>
                      </li>
                    ))}
                  </ol>
                )}
                {open === id && c.weak_spot && (
                  <div className="bad" style={{ marginTop: 6 }}><strong>Слабое место:</strong> {c.weak_spot}</div>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </>
  );
}
