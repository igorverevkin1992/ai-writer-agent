import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "./api";
import type { Notify } from "./App";

interface Step { n: number; name: string; text: string; chapters?: string }
interface Circle { scope: string; key: number | null; title: string; steps: Step[]; weak_spot?: string; summary?: string; generated?: string }
interface Part { part: number; title: string; from_chapter: number; to_chapter: number }
interface Act { act: number; title: string; from_chapter: number; to_chapter: number; parts: string; steps: string }
interface CirclesData {
  circles: Circle[];
  parts: Part[];
  acts: Act[];
  prompts: string[];
  canon_status: Record<string, string>;
  in_canon: number;
}

const SCOPE_LABEL: Record<string, string> = { книга: "Книга", акт: "Акты", глава: "Главы" };

function stemOf(c: Circle): string {
  if (c.scope === "книга") return "книга";
  if (c.scope === "акт") return `акт_${c.key}`;
  return `глава_${String(c.key ?? 0).padStart(2, "0")}`;
}

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

  const nActs = data.acts.length;
  const generate = async (scope: string, redo = false) => {
    const count = scope === "книга" ? 1 : scope === "акты" ? nActs : scope === "главы" ? 46 : 1 + nActs + 46;
    if (!window.confirm(`Построить круги истории: ${scope} (${count} вызов(ов) модели${redo ? ", с пересчётом" : ""})?`)) return;
    await runCommand("story-circles", undefined, { scope, redo });
  };

  const pending = Object.values(data.canon_status).filter((s) => s !== "в каноне").length;

  const toCanon = async () => {
    if (!window.confirm(
      `Внести ${data.circles.length} круг(ов) в документ 2.1 библиотеки (21_Круги_истории_Том1.md) и закоммитить канон? ` +
      "После этого окна глав получат секцию «Драматургия», а Э2 — проверку 4.4. (Д-8)"
    )) return;
    await runCommand("circles-canon");
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
    const m = manualStem.match(/^(книга|акт|глава)_?(\d+)?$/);
    if (!m) return notify("Выберите промпт (книга / акт_N / глава_NN).");
    try {
      await apiPost("/api/circles/manual", { scope: m[1], key: m[2] ? +m[2] : null, text: pasted });
      notify("Круг принят.", "ok");
      setPasted("");
      load();
    } catch (e) {
      notify(String(e));
    }
  };

  const groups = ["книга", "акт", "глава"].map((s) => ({ scope: s, items: data.circles.filter((c) => c.scope === s) }));

  return (
    <>
      <h1>Круги истории — каркас драматургии</h1>
      <p className="muted">
        Круг истории (Р-020) — несущий каркас драматургии и темпа: круг тома → круги {nActs} актов (Р-021) →
        круги глав; каждый уровень строится внутри шага уровня выше. Черновики лежат в <code>круги_истории/</code>;
        после внесения в канон (документ 2.1) они попадают в окно Писателя («Драматургия главы») и в проверку Э2 (4.4).
        {" "}В каноне сейчас: <strong>{data.in_canon}</strong> круг(ов)
        {pending > 0 && <>, не внесено или изменено: <strong>{pending}</strong></>}.
      </p>
      {nActs > 0 && (
        <table>
          <thead><tr><th>Акт</th><th>Название</th><th>Главы</th><th>Части</th><th>Шаги круга тома</th></tr></thead>
          <tbody>
            {data.acts.map((a) => (
              <tr key={a.act}>
                <td>{a.act}</td><td>«{a.title}»</td><td>{a.from_chapter}–{a.to_chapter}</td><td>{a.parts}</td><td>{a.steps}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="actions">
        <button className="primary" disabled={busy} onClick={() => generate("всё")}>Построить все круги</button>
        <button disabled={busy} onClick={() => generate("книга")}>Книга</button>
        <button disabled={busy} onClick={() => generate("акты")}>Акты</button>
        <button disabled={busy} onClick={() => generate("главы")}>Главы</button>
        <button disabled={busy} onClick={() => generate("всё", true)}>Пересчитать всё</button>
        <button className={pending > 0 ? "primary" : ""} disabled={busy || data.circles.length === 0} onClick={toCanon}>
          Внести в канон{pending > 0 ? ` (${pending})` : ""}
        </button>
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

      {data.circles.length === 0 && <p className="muted">Кругов ещё нет — нажмите «Построить все круги» (сначала строится том, затем акты внутри тома, затем главы внутри актов).</p>}

      {groups.map(({ scope, items }) => items.length > 0 && (
        <div key={scope}>
          <h2>{SCOPE_LABEL[scope]}{scope !== "книга" ? ` (${items.length})` : ""}</h2>
          {items.map((c) => {
            const id = `${c.scope}_${c.key ?? ""}`;
            const act = c.scope === "акт" ? data.acts.find((a) => a.act === c.key) : undefined;
            const actTitle = act ? ` · «${act.title}» (гл. ${act.from_chapter}–${act.to_chapter})` : "";
            const status = data.canon_status[stemOf(c)] ?? "не в каноне";
            return (
              <div className="card" key={id}>
                <div className="row" style={{ display: "flex", justifyContent: "space-between", cursor: "pointer" }}
                  onClick={() => setOpen(open === id ? null : id)}>
                  <strong>
                    {c.title}{c.title.includes("«") ? "" : actTitle}{" "}
                    <span className={"badge" + (status === "в каноне" ? " b-зафиксировано" : "")}>{status}</span>
                  </strong>
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
