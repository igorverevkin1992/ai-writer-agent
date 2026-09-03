import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "./api";
import type { Notify } from "./App";
import type { ChapterDetail, Flag, Job, Resolution } from "./types";

// кнопки такта по состоянию FSM (сценарий А, §3.2)
const ACTIONS: Record<string, { label: string; cmd: string; primary?: boolean; confirm?: string }[]> = {
  "не-начато": [{ label: "Собрать окно", cmd: "compile", primary: true }],
  "собрано": [
    { label: "Написать главу", cmd: "write", primary: true },
    { label: "Пересобрать окно", cmd: "compile" },
  ],
  "сгенерировано": [{ label: "Проверить Э1", cmd: "verify1", primary: true }],
  "верифицировано-1": [{ label: "Проверить Э2", cmd: "verify2", primary: true }],
  "верифицировано-2": [{ label: "Пакет приёмки", cmd: "review", primary: true }],
  "на-приёмке": [{ label: "Внести правки Писателем", cmd: "apply-edits", primary: true }],
  "правки": [{ label: "Дифф-контроль", cmd: "diff-check", primary: true }],
  "дифф-контроль": [{ label: "Повторить правки", cmd: "apply-edits" }],
  "принято": [
    { label: "Пакет в канон", cmd: "canonize", primary: true },
    {
      label: "Применить пакет + коммит",
      cmd: "canonize-apply",
      confirm: "Применить пакет к УГАР_Библиотеке и сделать git-коммит? (Д-8)",
    },
  ],
  "зафиксировано": [],
};

// состояния, где «Продолжить такт» выполняет машинные шаги до паузы автора (FR-O1)
const MACHINE_STATES = new Set([
  "не-начато", "собрано", "сгенерировано", "верифицировано-1", "верифицировано-2", "правки",
]);

export function ChapterView(props: {
  chapter: number;
  job: Job | null;
  refreshTick: number;
  runCommand: (cmd: string, chapter?: number) => Promise<void>;
  notify: Notify;
}) {
  const { chapter, job, refreshTick, runCommand, notify } = props;
  const [d, setD] = useState<ChapterDetail | null>(null);
  const [tab, setTab] = useState<"чтение" | "правки" | "приёмка" | "ручной" | "история">("чтение");

  const load = useCallback(() => {
    apiGet<ChapterDetail>(`/api/chapter/${chapter}`).then(setD).catch((e) => notify(String(e)));
  }, [chapter, notify]);

  useEffect(load, [load, refreshTick]);

  if (!d) return <p>Загрузка главы {chapter}…</p>;

  const busy = job?.status === "выполняется";
  const actions = ACTIONS[d.state] ?? [];
  const diffClean = d.diff_report && d.diff_report.not_applied.length === 0 && d.diff_report.unauthorized.length === 0;
  const unresolved = d.resolutions.filter((r) => !r.decision).length;

  const act = async (a: { cmd: string; confirm?: string }) => {
    if (a.confirm && !window.confirm(a.confirm)) return;
    await runCommand(a.cmd, chapter);
  };

  const accept = async () => {
    if (!window.confirm(`Принять главу ${chapter}? (FR-E4, явное подтверждение)`)) return;
    try {
      await apiPost(`/api/chapter/${chapter}/accept`);
      load();
    } catch (e) {
      notify(String(e));
    }
  };

  const rollback = async () => {
    if (!window.confirm("Откатить главу на шаг назад?")) return;
    try {
      await apiPost(`/api/chapter/${chapter}/rollback`, {});
      load();
    } catch (e) {
      notify(String(e));
    }
  };

  return (
    <>
      <h1>
        Глава {chapter} <span className={`badge b-${d.state}`}>{d.state}</span>
      </h1>
      <div className="muted">
        черновик {d.draft} · авто-повторов {d.retries} · итераций правок {d.iterations}
        {(d.author_min > 0 || d.machine_min > 0) && (
          <>
            {" "}· время автора {d.author_min} мин {d.author_min > 40 ? "⚠ (цель ≤40)" : ""} · машинное {d.machine_min} мин
          </>
        )}
      </div>
      <div className="muted">Дальше: {d.next}</div>

      <div className="actions">
        {MACHINE_STATES.has(d.state) && (
          <button className="primary" disabled={busy} onClick={() => runCommand("run", chapter)}
            title="Выполнить машинные шаги такта до следующей паузы автора (FR-O1)">
            Продолжить такт ▶
          </button>
        )}
        {actions.map((a) => (
          <button key={a.cmd} className={a.primary ? "primary" : ""} disabled={busy} onClick={() => act(a)}>
            {a.label}
          </button>
        ))}
        {d.state === "дифф-контроль" && (
          <button className="primary" disabled={busy || !diffClean || unresolved > 0} onClick={accept}
            title={!diffClean ? "дифф-контроль не чист" : unresolved ? "есть самоволки без решения" : ""}>
            Принять главу
          </button>
        )}
        {d.state !== "не-начато" && d.state !== "зафиксировано" && (
          <button className="danger" disabled={busy} onClick={rollback}>Откат на шаг</button>
        )}
        {d.state === "зафиксировано" && <span className="ok">Такт завершён ✓</span>}
      </div>

      {job && (job.chapter === chapter || job.chapter == null) && <JobBox job={job} />}

      <div className="tabs">
        {(["чтение", "правки", "приёмка", "ручной", "история"] as const).map((t) => (
          <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
            {t === "чтение" ? "Чтение с флагами" : t === "правки" ? "Правки" : t === "приёмка" ? "Приёмка"
              : t === "ручной" ? "Окно / ручной режим" : "История"}
          </button>
        ))}
      </div>

      {tab === "чтение" && <Reading d={d} reload={load} notify={notify} />}
      {tab === "правки" && <Edits d={d} reload={load} notify={notify} />}
      {tab === "приёмка" && <Acceptance d={d} reload={load} notify={notify} unresolved={unresolved} />}
      {tab === "ручной" && <ManualTab d={d} reload={load} notify={notify} />}
      {tab === "история" && <History d={d} />}
    </>
  );
}

function JobBox({ job }: { job: Job }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="jobbox">
      {job.status === "выполняется" ? <span className="spin" /> : null}
      <strong>{job.name}</strong> <span className={`badge b-${job.status}`}>{job.status}</span>{" "}
      {job.output && (
        <button style={{ marginLeft: 8 }} onClick={() => setOpen(!open)}>
          {open ? "скрыть вывод" : "показать вывод"}
        </button>
      )}
      {open && job.output && <pre>{job.output}</pre>}
    </div>
  );
}

// ------------------------------------------------------------ Чтение с флагами

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function Reading({ d, reload, notify }: { d: ChapterDetail; reload: () => void; notify: Notify }) {
  const html = useMemo(() => {
    if (!d.text) return null;
    let h = esc(d.text);
    const wrap = (quote: string, cls: string, id: string, title: string) => {
      const q = esc(quote.trim());
      if (q && h.includes(q) && !h.includes(`id="${id}"`)) {
        const safeId = esc(id).replace(/"/g, "&quot;");
        h = h.replace(q, () => `<mark id="${safeId}" class="m-${cls}" title="${esc(title).replace(/"/g, "&quot;")}">${q}</mark>`);
      }
    };
    for (const c of d.verdict?.checks ?? []) {
      if (c.status === "PASS") continue;
      c.quotes.slice(0, 3).forEach((q, j) => wrap(q, c.status, `a-${c.check_id}-${j}`, `${c.check_id}: порог ${c.threshold}, факт ${c.actual}`));
    }
    for (const f of d.flags) wrap(f.quote, f.kind, `a-${f.flag_id}`, `${f.flag_id} · ${f.type}: ${f.rule}. ${f.recommendation}`);
    return h;
  }, [d]);

  return (
    <>
      {d.verdict && (
        <>
          <h2>Формальные проверки (Э1)</h2>
          <table>
            <thead><tr><th></th><th>Проверка</th><th>Факт</th><th>Порог</th></tr></thead>
            <tbody>
              {d.verdict.checks.map((c) => (
                <tr key={c.check_id + c.actual}>
                  <td><span className={`badge b-${c.status}`}>{c.status}</span></td>
                  <td>{c.check_id}</td>
                  <td>{c.actual}</td>
                  <td>{c.threshold}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <h2>Смысловые флаги (Э2)</h2>
      {d.flags.length === 0 && <p className="muted">Флагов нет{d.state === "сгенерировано" || d.state === "собрано" ? " (Э2 ещё не запускался)" : ""}.</p>}
      {d.flags.map((f) => (
        <FlagCard key={f.flag_id} f={f} chapter={d.chapter}
          resolution={d.resolutions.find((r) => r.flag_id === f.flag_id)} reload={reload} notify={notify} />
      ))}

      {html ? (
        <>
          <h2>Текст главы (черновик {d.draft})</h2>
          <div className="prose" dangerouslySetInnerHTML={{ __html: html }} />
        </>
      ) : (
        <p className="muted">Черновика ещё нет — начните такт кнопками выше.</p>
      )}
    </>
  );
}

function FlagCard(props: {
  f: Flag; chapter: number; resolution?: Resolution; reload: () => void; notify: Notify;
}) {
  const { f, chapter, resolution, reload, notify } = props;
  const [registry, setRegistry] = useState("3.1");
  const decide = async (decision: string) => {
    try {
      await apiPost(`/api/chapter/${chapter}/resolve`, { flag_id: f.flag_id, decision, registry });
      reload();
    } catch (e) {
      notify(String(e));
    }
  };
  const badge = f.kind === "samovolka" ? "самоволка" : f.severity;
  const showType = f.type.trim().toLowerCase() !== badge.toLowerCase();
  return (
    <div className="card">
      <span className={`badge b-${f.kind}`}>{badge}</span>{" "}
      <strong>{f.flag_id}</strong>
      {showType && <> · {f.type}</>} <a href={`#a-${f.flag_id}`}>¶</a>
      <blockquote>{f.quote}</blockquote>
      <div className="muted">{f.rule}. {f.recommendation}</div>
      {f.kind === "samovolka" && (
        resolution?.decision ? (
          <div className="resolved">
            решение: {resolution.decision}
            {resolution.target_registry ? ` → ${resolution.target_registry}` : ""}
          </div>
        ) : (
          <div className="resolvebtns">
            <span className="unresolved">решение автора:</span>
            <button onClick={() => decide("вычеркнуть")}>Вычеркнуть</button>
            <button onClick={() => decide("канонизировать")}>Канонизировать →</button>
            <select value={registry} onChange={(e) => setRegistry(e.target.value)}>
              {["3.1", "3.2", "3.3", "1.2"].map((r) => <option key={r}>{r}</option>)}
            </select>
          </div>
        )
      )}
    </div>
  );
}

// ------------------------------------------------------------------- Правки

function Edits({ d, reload, notify }: { d: ChapterDetail; reload: () => void; notify: Notify }) {
  const [text, setText] = useState(d.edits_md ?? "БЫЛО: \nСТАЛО: \n\nУКАЗАНИЕ: \n");
  const [k1, setK1] = useState<number | null>(null);
  const [k2, setK2] = useState<number | null>(null);
  const [diff, setDiff] = useState<string[] | null>(null);

  useEffect(() => setText(d.edits_md ?? "БЫЛО: \nСТАЛО: \n\nУКАЗАНИЕ: \n"), [d.edits_md]);

  const save = async () => {
    try {
      const r = await apiPost<{ parsed: number }>(`/api/chapter/${d.chapter}/edits`, { text });
      notify(`Сохранено: распознано правок — ${r.parsed}`, "ok");
      reload();
    } catch (e) {
      notify(String(e));
    }
  };

  const showDiff = async () => {
    const a = k1 ?? d.drafts[d.drafts.length - 2];
    const b = k2 ?? d.draft;
    if (a == null || b == null) return;
    try {
      const r = await apiGet<{ lines: string[] }>(`/api/chapter/${d.chapter}/diff/${a}/${b}`);
      setDiff(r.lines);
    } catch (e) {
      notify(String(e));
    }
  };

  return (
    <>
      <h2>edits.md — пары «БЫЛО/СТАЛО» и строки «УКАЗАНИЕ:»</h2>
      <textarea value={text} onChange={(e) => setText(e.target.value)} />
      <div className="actions">
        <button className="primary" onClick={save}>Сохранить правки</button>
      </div>

      {d.edits_parsed.length > 0 && (
        <>
          <h2>Как парсер понял правки</h2>
          {d.edits_parsed.map((e) => (
            <div className="editrow" key={e.seq}>
              <span className={e.found ? "ok" : "bad"}>{e.found ? "✓" : "✗"}</span>
              <span>
                <strong>{e.seq}.</strong>{" "}
                {e.before ? <>БЫЛО: {e.before} → СТАЛО: {e.after}</> : <>УКАЗАНИЕ: {e.after}</>}
                {!e.found && <span className="bad"> — «было» не найдено в черновике дословно</span>}
              </span>
            </div>
          ))}
        </>
      )}

      {d.drafts.length >= 2 && (
        <>
          <h2>Дифф черновиков</h2>
          <div className="actions">
            <select value={k1 ?? d.drafts[d.drafts.length - 2]} onChange={(e) => setK1(+e.target.value)}>
              {d.drafts.map((k) => <option key={k} value={k}>draft_{k}</option>)}
            </select>
            →
            <select value={k2 ?? d.draft} onChange={(e) => setK2(+e.target.value)}>
              {d.drafts.map((k) => <option key={k} value={k}>draft_{k}</option>)}
            </select>
            <button onClick={showDiff}>Показать дифф</button>
          </div>
          {diff && (
            <div className="diff">
              {diff.map((l, i) => (
                <div key={i} className={l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : ""}>
                  {l}
                </div>
              ))}
              {diff.length === 0 && "черновики идентичны"}
            </div>
          )}
        </>
      )}
    </>
  );
}

// ------------------------------------------------------------------ Приёмка

function Acceptance(props: { d: ChapterDetail; reload: () => void; notify: Notify; unresolved: number }) {
  const { d, reload, notify, unresolved } = props;
  const [batch, setBatch] = useState(d.canon_batch ?? "");
  useEffect(() => setBatch(d.canon_batch ?? ""), [d.canon_batch]);

  const saveBatch = async () => {
    try {
      await apiPost(`/api/chapter/${d.chapter}/canon-batch`, { text: batch });
      notify("Пакет сохранён.", "ok");
      reload();
    } catch (e) {
      notify(String(e));
    }
  };

  return (
    <>
      <h2>Дифф-контроль</h2>
      {d.diff_report ? (
        <ul>
          <li>внесено правок: {(d.diff_report.applied_share * 100).toFixed(0)}%</li>
          <li className={d.diff_report.not_applied.length ? "bad" : "ok"}>
            не внесено: {d.diff_report.not_applied.join(", ") || "—"}
          </li>
          <li className={d.diff_report.unauthorized.length ? "bad" : "ok"}>
            самовольных изменений: {d.diff_report.unauthorized.length}
          </li>
          {d.diff_report.unverifiable.length > 0 && (
            <li>свободные указания {d.diff_report.unverifiable.join(", ")} — проверьте глазами</li>
          )}
        </ul>
      ) : (
        <p className="muted">Дифф-контроль ещё не выполнялся.</p>
      )}
      {d.diff_report?.unauthorized.map((u, i) => <div className="card" key={i}>{u}</div>)}

      {unresolved > 0 && (
        <p className="unresolved">Самоволок без решения: {unresolved} — вкладка «Чтение с флагами».</p>
      )}

      <h2>Пакет записей в канон (canon_batch.md)</h2>
      {d.canon_batch != null ? (
        <>
          <p className="muted">Удалите строки, которые не принимаете, и сохраните — затем «Применить пакет + коммит».</p>
          <textarea style={{ minHeight: 260 }} value={batch} onChange={(e) => setBatch(e.target.value)} />
          <div className="actions">
            <button className="primary" onClick={saveBatch}>Сохранить пакет</button>
          </div>
        </>
      ) : (
        <p className="muted">Пакета ещё нет — после приёмки нажмите «Пакет в канон».</p>
      )}
    </>
  );
}

// ------------------------------------------------------------------- История

function History({ d }: { d: ChapterDetail }) {
  return (
    <>
      <h2>История переходов FSM</h2>
      <table>
        <thead><tr><th>Время</th><th>Из</th><th>В</th><th>Команда</th></tr></thead>
        <tbody>
          {d.history.slice().reverse().map((h, i) => (
            <tr key={i}>
              <td>{h.время?.slice(0, 19).replace("T", " ")}</td>
              <td>{h.из}</td>
              <td>{h.в}</td>
              <td>{h.команда}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {d.history.length === 0 && <p className="muted">Переходов ещё не было.</p>}
    </>
  );
}


// -------------------------------------------------- Окно контекста и ручной режим

function ManualTab({ d, reload, notify }: { d: ChapterDetail; reload: () => void; notify: Notify }) {
  const [win, setWin] = useState<{ text: string | null; size_flag: string | null } | null>(null);
  const [pasted, setPasted] = useState("");

  useEffect(() => {
    apiGet<{ text: string | null; size_flag: string | null }>(`/api/chapter/${d.chapter}/window`)
      .then(setWin)
      .catch(() => setWin({ text: null, size_flag: null }));
  }, [d.chapter, d.state]);

  const copy = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text);
      notify(`${what} — скопировано в буфер.`, "ok");
    } catch {
      notify("Буфер обмена недоступен — выделите текст ниже вручную.");
    }
  };

  const copyPrompt = async (kind: "verify2" | "edits", what: string) => {
    try {
      const r = await apiGet<{ text: string }>(`/api/chapter/${d.chapter}/prompt/${kind}`);
      await copy(r.text, what);
    } catch (e) {
      notify(String(e));
    }
  };

  const sendDraft = async () => {
    try {
      const r = await apiPost<{ draft: number }>(`/api/chapter/${d.chapter}/manual-draft`, { text: pasted });
      notify(`Черновик принят как draft_${r.draft}.`, "ok");
      setPasted("");
      reload();
    } catch (e) {
      notify(String(e));
    }
  };

  const sendFlags = async () => {
    try {
      const r = await apiPost<{ flags: number }>(`/api/chapter/${d.chapter}/manual-flags`, { text: pasted });
      notify(`Принято флагов Э2: ${r.flags}.`, "ok");
      setPasted("");
      reload();
    } catch (e) {
      notify(String(e));
    }
  };

  const needDraft = ["собрано", "сгенерировано", "на-приёмке", "дифф-контроль"].includes(d.state);
  const needFlags = d.state === "верифицировано-1";

  return (
    <>
      <p className="muted">
        Ручной режим (NFR-3): если API недоступен, скопируйте промпт в чат модели и вставьте её ответ сюда —
        такт продолжится штатно, FSM и проверки сохраняются.
      </p>

      {needDraft && (
        <>
          <h2>{d.state === "собрано" || d.state === "сгенерировано" ? "Генерация главы вручную" : "Внесение правок вручную"}</h2>
          <div className="actions">
            {(d.state === "собрано" || d.state === "сгенерировано") && win?.text && (
              <button onClick={() => copy(win.text!, "Окно контекста")}>Скопировать окно контекста</button>
            )}
            {(d.state === "на-приёмке" || d.state === "дифф-контроль") && (
              <button onClick={() => copyPrompt("edits", "Промпт правок")}>Скопировать промпт правок</button>
            )}
          </div>
          <textarea placeholder={`Вставьте текст главы — будет сохранён как draft_${d.draft + 1}.md`}
            value={pasted} onChange={(e) => setPasted(e.target.value)} />
          <div className="actions">
            <button className="primary" disabled={!pasted.trim()} onClick={sendDraft}>
              Принять как draft_{d.draft + 1}
            </button>
          </div>
        </>
      )}

      {needFlags && (
        <>
          <h2>Проверка Э2 вручную</h2>
          <div className="actions">
            <button onClick={() => copyPrompt("verify2", "Промпт Верификатора-2")}>
              Сформировать и скопировать промпт Э2
            </button>
          </div>
          <textarea placeholder="Вставьте JSON-ответ модели (можно вместе с пояснениями — массив будет найден)"
            value={pasted} onChange={(e) => setPasted(e.target.value)} />
          <div className="actions">
            <button className="primary" disabled={!pasted.trim()} onClick={sendFlags}>Принять флаги Э2</button>
          </div>
        </>
      )}

      {!needDraft && !needFlags && (
        <p className="muted">В состоянии «{d.state}» ручной ввод не требуется.</p>
      )}

      {win?.size_flag && <div className="card bad">{win.size_flag}</div>}
      {win?.text ? (
        <>
          <h2>Окно контекста (window.md)</h2>
          <pre className="window">{win.text}</pre>
        </>
      ) : (
        <p className="muted">Окно ещё не собрано.</p>
      )}
    </>
  );
}
