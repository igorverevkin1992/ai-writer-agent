import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "./api";
import type { Notify, RunCommand } from "./App";
import type { Confirm } from "./Confirm";
import { usePending } from "./hooks";
import type { LintFinding, LintReport } from "./types";

interface CanonDoc { path: string; name: string; mtime: number; size: number }
interface LintData { report: LintReport | null; changed: string[]; running: boolean; pending: boolean }

const SEV_CLASS: Record<string, string> = { ошибка: "b-BRAK", предупреждение: "b-FLAG", заметка: "" };

/** Вид «Канон»: правка документов библиотеки в реальном времени и подсветка противоречий (линтер). */
export function Canon(props: {
  busy: boolean;
  runCommand: RunCommand;
  notify: Notify;
  confirm: Confirm;
  refreshTick: number;
}) {
  const { busy: jobBusy, runCommand, notify, confirm, refreshTick } = props;
  const [docs, setDocs] = useState<CanonDoc[]>([]);
  const [current, setCurrent] = useState<{ path: string; text: string; mtime: number } | null>(null);
  const [draft, setDraft] = useState("");
  const [lint, setLint] = useState<LintData | null>(null);
  const [filter, setFilter] = useState("");
  const [commitMsg, setCommitMsg] = useState("");
  const [pending, run] = usePending();
  const editor = useRef<HTMLTextAreaElement>(null);
  const busy = jobBusy || pending;
  const dirty = current !== null && draft !== current.text;

  const loadDocs = useCallback(() => {
    apiGet<{ docs: CanonDoc[] }>("/api/canon").then((r) => setDocs(r.docs)).catch((e) => notify(String(e)));
  }, [notify]);
  const loadLint = useCallback(() => {
    apiGet<LintData>("/api/lint").then(setLint).catch(() => undefined);
  }, []);

  useEffect(() => { loadDocs(); loadLint(); }, [loadDocs, loadLint, refreshTick]);
  useEffect(() => {
    const id = window.setInterval(loadLint, 3000); // наблюдатель сервера перепроверяет канон при правке файлов
    return () => window.clearInterval(id);
  }, [loadLint]);

  const open = useCallback(
    (path: string, line?: number) =>
      run(async () => {
        if (dirty && !(await confirm(`В «${current?.path}» есть несохранённые правки. Открыть другой документ и потерять их?`))) return;
        try {
          const d = await apiGet<{ path: string; text: string; mtime: number }>(`/api/canon/doc?path=${encodeURIComponent(path)}`);
          setCurrent(d);
          setDraft(d.text);
          if (line) window.setTimeout(() => jumpTo(d.text, line), 50);
        } catch (e) {
          notify(String(e));
        }
      }),
    [run, dirty, current, confirm, notify],
  );

  const jumpTo = (text: string, line: number) => {
    const el = editor.current;
    if (!el) return;
    const lines = text.split("\n");
    const start = lines.slice(0, line - 1).reduce((s, l) => s + l.length + 1, 0);
    const end = start + (lines[line - 1]?.length ?? 0);
    el.focus();
    el.setSelectionRange(start, end);
    const lineHeight = 18;
    el.scrollTop = Math.max(0, (line - 4) * lineHeight);
  };

  const save = () =>
    run(async () => {
      if (!current || !dirty) return;
      const ok = await confirm(
        `Сохранить «${current.path}» в библиотеку канона? Это правка канона автором (сценарий Б): файл перезапишется, ` +
        "выгрузки и проверка противоречий обновятся. Коммит — отдельной кнопкой. (Д-8)",
      );
      if (!ok) return;
      try {
        const r = await apiPost<{ saved: string; mtime: number; lint: LintReport | null }>("/api/canon/doc", {
          path: current.path, text: draft, mtime: current.mtime,
        });
        setCurrent({ path: current.path, text: draft, mtime: r.mtime });
        notify(`Сохранено: ${r.saved}`, "ok");
        loadLint();
        loadDocs();
      } catch (e) {
        notify(String(e));
      }
    });

  const applyFix = (index: number, f: LintFinding) =>
    run(async () => {
      if (!f.fix) return;
      const ok = await confirm(`Применить исправление в ${f.fix.file}:${f.fix.line}?\n«${f.fix.old}» → «${f.fix.new}»\n(${f.fix.note || "механическая правка"}; запись в библиотеку канона, Д-8)`);
      if (!ok) return;
      try {
        await apiPost("/api/lint/fix", { index });
        notify("Исправление применено — канон перепроверен.", "ok");
        loadLint();
        if (current && current.path === f.fix.file) {
          const d = await apiGet<{ path: string; text: string; mtime: number }>(`/api/canon/doc?path=${encodeURIComponent(current.path)}`);
          setCurrent(d); setDraft(d.text);
        }
      } catch (e) {
        notify(String(e));
      }
    });

  const lintLlm = () =>
    run(async () => {
      const n = current ? 1 : docs.filter((d) => !d.path.startsWith("ИНСТРУМЕНТ_") && !d.path.startsWith("ТЗ_") && !d.path.startsWith("Тест_Писателя/")).length;
      const ok = await confirm(`Проверить моделью ${current ? `документ «${current.path}»` : `все документы (${n} вызовов Anthropic)`} на смысловые противоречия?`);
      if (!ok) return;
      await runCommand("lint-llm", undefined, { files: current ? [current.path] : [] });
    });

  const commit = () =>
    run(async () => {
      const msg = commitMsg.trim();
      if (!msg) return notify("Введите сообщение коммита (при изменении норм — со ссылкой Р-№).");
      if (!(await confirm(`Закоммитить изменения библиотеки: «${msg}»? (Д-8)`))) return;
      await runCommand("canon-commit", undefined, { message: msg });
      setCommitMsg("");
    });

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      save();
    }
  };

  const report = lint?.report ?? null;
  const findings = (report?.findings ?? []).map((f, index) => ({ f, index }))
    .filter(({ f }) => !filter || f.file === filter);
  const visibleDocs = docs.filter((d) => d.path.endsWith(".md"));

  return (
    <>
      <h1>Канон — правка и проверка противоречий</h1>
      <p className="muted">
        Документы библиотеки правятся здесь или в любом редакторе на диске; сервер следит за папкой и перепроверяет канон
        при каждом изменении: хронология глав, границы актов, допустимость фокала, эпистемика брифов и прозы, реестр тайн
        против матрицы, диапазоны глав, возраст в досье, круги истории. Механические исправления применяются одной кнопкой,
        остальное — подсветка для вашего решения. Модельный слой ищет смысловые противоречия.
        {report && (
          <>
            {" "}Последняя проверка: {report.ts.slice(0, 19).replace("T", " ")} · документов {report.files_checked} ·{" "}
            <strong className={report.errors ? "bad" : "ok"}>ошибок {report.errors}</strong>, предупреждений {report.warnings}, заметок {report.notes}
            {lint?.running && <> · проверяю…</>}
            {lint?.pending && !lint.running && <> · есть непроверенные изменения (сервер занят)</>}
          </>
        )}
      </p>

      <div className="actions">
        <button className="primary" disabled={busy} onClick={() => run(() => runCommand("lint"))}>Проверить канон</button>
        <button disabled={busy} onClick={lintLlm}>Проверить моделью{current ? " (этот документ)" : " (все)"}</button>
        <input className="search" style={{ minWidth: 260 }} placeholder="сообщение коммита канона (Р-№ при смене норм)"
          value={commitMsg} onChange={(e) => setCommitMsg(e.target.value)} aria-label="Сообщение коммита" />
        <button disabled={busy || !commitMsg.trim()} onClick={commit}>Закоммитить канон</button>
      </div>

      <div className="canon-layout">
        <div className="canon-docs" role="list" aria-label="Документы канона">
          {visibleDocs.map((d) => {
            const n = (report?.findings ?? []).filter((f) => f.file === d.path).length;
            return (
              <div key={d.path} role="listitem" tabIndex={0}
                className={"qitem" + (current?.path === d.path ? " active" : "")}
                onClick={() => open(d.path)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(d.path); } }}>
                <div className="row"><span>{d.path}</span>{n > 0 && <span className="badge b-FLAG">{n}</span>}</div>
              </div>
            );
          })}
        </div>
        <div className="canon-editor">
          {current ? (
            <>
              <div className="row" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong>{current.path}{dirty ? " · не сохранено" : ""}</strong>
                <div className="actions" style={{ margin: 0 }}>
                  <button disabled={!dirty || busy} onClick={() => setDraft(current.text)}>Отменить правки</button>
                  <button className="primary" disabled={!dirty || busy} onClick={save}>Сохранить (Ctrl+S)</button>
                </div>
              </div>
              <textarea ref={editor} className="canon-text" value={draft} spellCheck={false}
                onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} aria-label={`Документ ${current.path}`} />
            </>
          ) : (
            <p className="muted">Выберите документ слева. Находки справа ведут к нужной строке.</p>
          )}
        </div>
      </div>

      <h2>
        Находки {report ? `(${findings.length}${filter ? ` в ${filter}` : ""})` : ""}
        {filter && <button style={{ marginLeft: 10 }} onClick={() => setFilter("")}>показать все</button>}
        {current && !filter && <button style={{ marginLeft: 10 }} onClick={() => setFilter(current.path)}>только этот документ</button>}
      </h2>
      {!report && <p className="muted">Проверка ещё не выполнялась — нажмите «Проверить канон».</p>}
      {report && findings.length === 0 && <p className="ok">Противоречий не найдено.</p>}
      {findings.map(({ f, index }) => (
        <div className="card" key={index}>
          <span className={"badge " + (SEV_CLASS[f.severity] ?? "")}>{f.severity}</span>{" "}
          <strong>{f.code}</strong>{f.source === "модель" && <span className="muted"> · модель</span>}{" "}
          <a href="#" onClick={(e) => { e.preventDefault(); open(f.file, f.line ?? undefined); }}>
            {f.file}{f.line ? `:${f.line}` : ""}
          </a>
          <div>{f.message}</div>
          {f.quote && <blockquote>{f.quote}</blockquote>}
          {f.fix && (
            <div className="resolvebtns">
              <span className="muted">«{f.fix.old}» → «{f.fix.new}»</span>
              <button disabled={busy} onClick={() => applyFix(index, f)}>Применить исправление</button>
            </div>
          )}
        </div>
      ))}
    </>
  );
}
