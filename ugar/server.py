"""Локальный сервер панели (этап 3): JSON-API поверх пайплайна + статика React.

Контур остаётся локальным (§1.3): сервер слушает ТОЛЬКО 127.0.0.1, наружу
ничего не ходит, все операции — те же функции, что у CLI (FSM, guard и
подтверждения сохраняются). Изменяющие запросы требуют заголовка
`X-Ugar-Panel: 1` — браузерный cross-origin не может его послать без
CORS-преflight, который мы не разрешаем.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

import typer

from . import exporter, review, timing, verifier2
from .config import Config
from .fsm import ChapterState, all_states
from .paths import Workspace
from .schemas import Resolution

# команды такта, доступные из панели (белый список)
COMMANDS = {
    "run", "export", "compile", "write", "verify1", "verify2", "review",
    "apply-edits", "diff-check", "regress", "canonize", "canonize-apply", "story-circles",
    "circles-canon",
}


class _LiveBuffer(io.TextIOBase):
    """Пишет вывод задачи сразу в job['output'] — панель видит лог по ходу."""

    def __init__(self, job: dict, lock: threading.Lock):
        self.job = job
        self.lock = lock

    def write(self, s: str) -> int:
        with self.lock:
            self.job["output"] += _strip_ansi(s)
        return len(s)


class JobRunner:
    """Одна задача за раз (Д-5: однопользовательский режим, без гонок FSM).

    redirect_stdout глобален для процесса, поэтому пока задача идёт,
    другие захватывающие вывод операции (accept/rollback/ручной режим)
    отклоняются через ensure_idle().
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.job: dict | None = None

    @property
    def busy(self) -> bool:
        return bool(self.job and self.job["status"] == "выполняется")

    def ensure_idle(self) -> None:
        if self.busy:
            raise RuntimeError(f"дождитесь завершения задачи «{self.job['name']}»")  # type: ignore[index]

    def start(self, name: str, chapter: int | None, fn) -> dict:
        with self._lock:
            self.ensure_idle()
            self.job = {
                "name": name,
                "chapter": chapter,
                "status": "выполняется",
                "output": "",
                "started": datetime.now(timezone.utc).isoformat(),
            }
        threading.Thread(target=self._run, args=(fn,), daemon=True).start()
        return self.job

    def _run(self, fn) -> None:
        assert self.job is not None
        buf = _LiveBuffer(self.job, self._lock)
        status = "готово"
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                fn()
        except typer.Exit as e:
            code = getattr(e, "exit_code", 1)
            status = "готово" if code == 0 else ("ручной-режим" if code == 2 else "ошибка")
        except SystemExit as e:
            status = "готово" if not e.code else "ошибка"
        except Exception as e:  # показываем автору, не роняем сервер
            buf.write(f"\nОШИБКА: {e}")
            status = "ошибка"
        self.job["status"] = status
        self.job["finished"] = datetime.now(timezone.utc).isoformat()


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


class PanelAPI:
    """Собирает JSON-ответы; хендлер остаётся тонким."""

    def __init__(self, ws: Workspace, cfg: Config, library: Path):
        self.ws = ws
        self.cfg = cfg
        self.library = library
        self.jobs = JobRunner()

    # ------------------------------------------------------------- чтение

    def state(self) -> dict:
        from . import regression
        from .cli import NEXT_STEP, _chapter_flags_summary

        chapters = []
        for st in all_states(self.ws):
            e1, e2 = _chapter_flags_summary(self.ws, st.chapter)
            machine_s, author_s = timing.chapter_times(st.data.get("история", []))
            chapters.append(
                {
                    "chapter": st.chapter,
                    "state": st.state,
                    "draft": st.draft,
                    "e1": e1,
                    "e2": e2,
                    "author_min": round(author_s / 60, 1),
                    "machine_min": round(machine_s / 60, 1),
                    "next": NEXT_STEP.get(st.state, "").format(n=st.chapter),
                }
            )
        try:
            briefs = [
                {"chapter": b.chapter, "volume": b.volume, "focal": b.focal, "date": b.date}
                for b in exporter.load_briefs(self.ws.exports)
            ]
        except FileNotFoundError:
            briefs = []
        return {
            "workspace": str(self.ws.root),
            "chapters": chapters,
            "briefs": briefs,
            "regression_green": regression.is_green(self.ws),
            "models": {"writer": self.cfg.writer.model, "verifier2": self.cfg.verifier2.model},
            "job": self.jobs.job,
        }

    def chapter(self, n: int) -> dict:
        st = ChapterState(self.ws, n)
        chdir = self.ws.chapter_dir(n)

        def read_json(name):
            p = chdir / name
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

        draft_path = self.ws.draft_path(n, st.draft)
        text = draft_path.read_text(encoding="utf-8") if draft_path.exists() else None
        edits_md_path = chdir / "edits.md"
        edits_parsed = []
        for e in review.load_edits(self.ws, n):
            found = bool(text and e.before and e.before in text)
            edits_parsed.append(
                {"seq": e.seq, "before": e.before, "after": e.after, "note": e.note, "found": found or not e.before}
            )
        machine_s, author_s = timing.chapter_times(st.data.get("история", []))
        canon_batch = chdir / "canon_batch.md"
        from .cli import NEXT_STEP

        return {
            "chapter": n,
            "state": st.state,
            "draft": st.draft,
            "retries": st.data.get("авто_повторов", 0),
            "iterations": st.data.get("итераций_правок", 0),
            "history": st.data.get("история", []),
            "verdict": read_json("verdict.json"),
            "flags": [f.model_dump() for f in verifier2.load_flags(self.ws, n)],
            "resolutions": [r.model_dump() for r in review.load_resolutions(self.ws, n)],
            "diff_report": read_json("diff_report.json"),
            "text": text,
            "drafts": sorted(
                int(m.group(1)) for p in chdir.glob("draft_*.md") if (m := re.match(r"draft_(\d+)\.md", p.name))
            ) if chdir.exists() else [],
            "edits_md": edits_md_path.read_text(encoding="utf-8") if edits_md_path.exists() else None,
            "edits_parsed": edits_parsed,
            "canon_batch": canon_batch.read_text(encoding="utf-8") if canon_batch.exists() else None,
            "author_min": round(author_s / 60, 1),
            "machine_min": round(machine_s / 60, 1),
            "next": NEXT_STEP.get(st.state, "").format(n=n),
        }

    def draft(self, n: int, k: int) -> dict:
        return {"chapter": n, "draft": k, "text": self.ws.draft_path(n, k).read_text(encoding="utf-8")}

    def diff(self, n: int, k1: int, k2: int) -> dict:
        import difflib

        a = self.ws.draft_path(n, k1).read_text(encoding="utf-8").splitlines()
        b = self.ws.draft_path(n, k2).read_text(encoding="utf-8").splitlines()
        return {"lines": list(difflib.unified_diff(a, b, f"draft_{k1}", f"draft_{k2}", lineterm="", n=2))}

    def api_log(self, n: int = 30) -> list[dict]:
        from .apilog import read_log

        return read_log(self.ws.logs)[-n:]

    def window(self, n: int) -> dict:
        """Окно контекста главы + флаг превышения лимита (FR-C5)."""
        path = self.ws.window_path(n)
        flag = self.ws.chapter_dir(n) / "window_size_флаг.md"
        return {
            "text": path.read_text(encoding="utf-8") if path.exists() else None,
            "size_flag": flag.read_text(encoding="utf-8") if flag.exists() else None,
        }

    def prompt(self, n: int, kind: str) -> dict:
        """Промпт для ручного прогона (NFR-3): verify2 строится по требованию."""
        if kind == "verify2":
            from . import guard

            system, user = verifier2.build_prompt(self.ws, n, ChapterState(self.ws, n).draft)
            text = f"<!-- system -->\n{system}\n\n<!-- user -->\n{user}\n"
            guard.write_text(self.ws.chapter_dir(n) / "verify2_prompt.md", text)
            return {"text": text, "target": "flags.json"}
        if kind == "edits":
            p = self.ws.chapter_dir(n) / "apply_edits_prompt.md"
            if not p.exists():
                # промпт правок собирается из текущих правок и черновика
                from . import writer

                edits = review.load_edits(self.ws, n)
                text = writer.edit_prompt(self.ws, n, ChapterState(self.ws, n).draft, edits)
            else:
                text = p.read_text(encoding="utf-8")
            return {"text": text, "target": f"draft_{ChapterState(self.ws, n).draft + 1}.md"}
        raise ValueError(f"неизвестный промпт: {kind}")

    def find(self, query: str) -> dict:
        from . import search

        groups = search.grouped(search.find(self.ws.exports, self.library, query))
        return {k: [{"ref": h.ref, "text": h.text} for h in v] for k, v in groups.items()}

    # ---------------------------------------------------------- изменения

    def save_edits(self, n: int, text: str) -> dict:
        from . import guard

        guard.write_text(self.ws.chapter_dir(n) / "edits.md", text)
        edits = review.parse_edits_md(self.ws, n)
        return {"parsed": len(edits)}

    def resolve(self, n: int, flag_id: str, decision: str, registry: str | None) -> dict:
        if decision not in ("вычеркнуть", "канонизировать"):
            raise ValueError("решение: «вычеркнуть» или «канонизировать»")
        resolutions = review.load_resolutions(self.ws, n)
        for r in resolutions:
            if r.flag_id == flag_id:
                r.decision = decision  # type: ignore[assignment]
                r.target_registry = registry if decision == "канонизировать" else None
                review.save_resolutions(self.ws, n, resolutions)
                return {"ok": True}
        raise ValueError(f"самоволка {flag_id} не найдена")

    def save_canon_batch(self, n: int, text: str) -> dict:
        from . import guard

        guard.write_text(self.ws.chapter_dir(n) / "canon_batch.md", text)
        return {"ok": True}

    def manual_draft(self, n: int, text: str) -> dict:
        """Ручной режим (NFR-3): вставленный ответ Писателя → следующий черновик.

        По состоянию FSM выбирается регистрация: генерация (write --manual)
        или внесение правок (apply-edits --manual).
        """
        self.jobs.ensure_idle()
        if not text.strip():
            raise ValueError("пустой текст черновика")
        from . import guard
        from .cli import cmd_apply_edits, cmd_write

        st = ChapterState(self.ws, n)
        k = st.draft + 1
        guard.write_text(self.ws.draft_path(n, k), text)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                if st.state in ("собрано", "сгенерировано"):
                    cmd_write(n, manual=True)
                elif st.state in ("на-приёмке", "дифф-контроль"):
                    cmd_apply_edits(n, manual=True)
                else:
                    raise ValueError(f"из состояния «{st.state}» черновик руками не принимается")
        except typer.Exit as e:
            if getattr(e, "exit_code", 1):
                raise RuntimeError(_strip_ansi(buf.getvalue()).strip() or "черновик не принят")
        return {"ok": True, "draft": k, "output": _strip_ansi(buf.getvalue())}

    def manual_flags(self, n: int, text: str) -> dict:
        """Ручной режим Э2: вставленный ответ Верификатора-2 → flags.json + verify2 --manual."""
        self.jobs.ensure_idle()
        from .cli import cmd_verify2

        flags = verifier2.parse_flags(text)  # понимает JSON в прозе/```-блоке
        verifier2.save_flags(self.ws, n, flags)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                cmd_verify2(n, manual=True)
        except typer.Exit as e:
            if getattr(e, "exit_code", 1):
                raise RuntimeError(_strip_ansi(buf.getvalue()).strip() or "флаги не приняты")
        return {"ok": True, "flags": len(flags)}

    def accept(self, n: int) -> dict:
        """Приёмка: подтверждение автор дал кнопкой + диалогом в панели (Д-8)."""
        self.jobs.ensure_idle()
        from .cli import cmd_accept

        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                cmd_accept(n, yes=True)
        except typer.Exit as e:
            if getattr(e, "exit_code", 1):
                raise RuntimeError(_strip_ansi(buf.getvalue()).strip() or "приёмка отклонена")
        return {"ok": True, "output": _strip_ansi(buf.getvalue())}

    def rollback(self, n: int, to: str | None) -> dict:
        self.jobs.ensure_idle()
        from .cli import cmd_rollback

        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                cmd_rollback(n, to=to, yes=True)
        except typer.Exit as e:
            if getattr(e, "exit_code", 1):
                raise RuntimeError(_strip_ansi(buf.getvalue()).strip() or "откат отклонён")
        return {"ok": True, "output": _strip_ansi(buf.getvalue())}

    def circles(self) -> dict:
        from . import circles as circles_mod

        prompts_dir = self.ws.root / "круги_истории" / "промпты"
        try:
            parts = exporter.load_parts(self.ws.exports)
        except FileNotFoundError:
            parts = []
        return {
            "circles": circles_mod.list_circles(self.ws),
            "canon_status": circles_mod.canon_status(self.ws),
            "in_canon": len(circles_mod.canon_circles(self.ws)),
            "parts": parts,
            "prompts": sorted(p.name for p in prompts_dir.glob("*.md")) if prompts_dir.exists() else [],
        }

    def circle_prompt(self, stem: str) -> dict:
        path = self.ws.root / "круги_истории" / "промпты" / f"{stem}.md"
        return {"text": path.read_text(encoding="utf-8")}

    def manual_circle(self, scope: str, key: int | None, text: str) -> dict:
        from . import circles as circles_mod

        path = circles_mod.accept_manual(self.ws, scope, key, text)
        return {"ok": True, "path": str(path)}

    def run_command(self, cmd: str, chapter: int | None, params: dict | None = None) -> dict:
        """Долгие шаги такта — фоновой задачей с захватом вывода."""
        if cmd not in COMMANDS:
            raise ValueError(f"неизвестная команда: {cmd}")
        from . import cli

        params = params or {}
        fns = {
            "story-circles": lambda: cli.cmd_circles(
                params.get("scope", "всё"), chapter=params.get("chapter"), redo=bool(params.get("redo")),
                to_canon=False, yes=True,
            ),
            # подтверждение автор дал диалогом в панели (Д-8)
            "circles-canon": lambda: cli.cmd_circles("всё", chapter=None, redo=False, to_canon=True, yes=True),
            "run": lambda: cli.cmd_run(chapter),  # машинные шаги до паузы автора (FR-O1)
            "export": lambda: cli.cmd_export(),
            "compile": lambda: cli.cmd_compile(chapter),
            "write": lambda: cli.cmd_write(chapter, manual=False),
            "verify1": lambda: cli.cmd_verify1(chapter),
            "verify2": lambda: cli.cmd_verify2(chapter, manual=False),
            "review": lambda: cli.cmd_review(chapter),
            "apply-edits": lambda: cli.cmd_apply_edits(chapter, manual=False),
            "diff-check": lambda: cli.cmd_diff_check(chapter, author_fix=False),
            "regress": lambda: cli.cmd_regress(llm=False),
            "canonize": lambda: cli.cmd_canonize(chapter, apply=False, yes=True),
            # подтверждение автор дал кнопкой + диалогом в панели (Д-8)
            "canonize-apply": lambda: cli.cmd_canonize(chapter, apply=True, yes=True),
        }
        return self.jobs.start(cmd, chapter, fns[cmd])


def _static_root() -> Path:
    return Path(str(resources.files("ugar").joinpath("data/панель")))


MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
        ".png": "image/png", ".ico": "image/x-icon", ".map": "application/json"}


def make_handler(api: PanelAPI):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # тихий сервер
            pass

        # ------------------------------------------------------- helpers

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code: int = 200) -> None:
            self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")

        def _error(self, message: str, code: int = 400) -> None:
            self._json({"error": message}, code)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")

        # --------------------------------------------------------- GET

        def do_GET(self) -> None:  # noqa: N802
            try:
                path = self.path.split("?")[0]
                if path == "/api/state":
                    return self._json(api.state())
                m = re.fullmatch(r"/api/chapter/(\d+)", path)
                if m:
                    return self._json(api.chapter(int(m.group(1))))
                m = re.fullmatch(r"/api/chapter/(\d+)/draft/(\d+)", path)
                if m:
                    return self._json(api.draft(int(m.group(1)), int(m.group(2))))
                m = re.fullmatch(r"/api/chapter/(\d+)/diff/(\d+)/(\d+)", path)
                if m:
                    return self._json(api.diff(int(m.group(1)), int(m.group(2)), int(m.group(3))))
                m = re.fullmatch(r"/api/chapter/(\d+)/window", path)
                if m:
                    return self._json(api.window(int(m.group(1))))
                m = re.fullmatch(r"/api/chapter/(\d+)/prompt/(\w+)", path)
                if m:
                    return self._json(api.prompt(int(m.group(1)), m.group(2)))
                if path == "/api/find":
                    from urllib.parse import parse_qs, urlparse

                    q = parse_qs(urlparse(self.path).query).get("q", [""])[0]
                    return self._json(api.find(q))
                if path == "/api/circles":
                    return self._json(api.circles())
                m = re.fullmatch(r"/api/circles/prompt/([\w\-]+)", path)
                if m:
                    return self._json(api.circle_prompt(m.group(1)))
                if path == "/api/log":
                    return self._json(api.api_log())
                if path == "/api/job":
                    return self._json(api.jobs.job or {})
                if path == "/dashboard":
                    from . import dashboard

                    out = dashboard.build_dashboard(api.ws)
                    return self._send(200, out.read_bytes(), "text/html")
                return self._static(path)
            except FileNotFoundError as e:
                self._error(str(e), 404)
            except Exception as e:
                self._error(str(e), 500)

        def _static(self, path: str) -> None:
            root = _static_root()
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            target = (root / rel).resolve()
            if root not in target.parents and target != root:
                return self._error("вне статики", 403)
            if not target.is_file():
                target = root / "index.html"  # SPA-роутинг
                if not target.is_file():
                    return self._error("панель не собрана (нет ugar/data/панель) — соберите panel/ или переустановите пакет", 404)
            self._send(200, target.read_bytes(), MIME.get(target.suffix, "application/octet-stream"))

        # --------------------------------------------------------- POST

        def do_POST(self) -> None:  # noqa: N802
            if self.headers.get("X-Ugar-Panel") != "1":
                return self._error("нет заголовка X-Ugar-Panel (защита от cross-origin)", 403)
            try:
                body = self._body()
                path = self.path.split("?")[0]
                if path == "/api/command":
                    job = api.run_command(body.get("cmd", ""), body.get("chapter"), body.get("params"))
                    return self._json({"job": job})
                m = re.fullmatch(r"/api/chapter/(\d+)/edits", path)
                if m:
                    return self._json(api.save_edits(int(m.group(1)), body.get("text", "")))
                m = re.fullmatch(r"/api/chapter/(\d+)/resolve", path)
                if m:
                    return self._json(
                        api.resolve(int(m.group(1)), body.get("flag_id", ""), body.get("decision", ""), body.get("registry"))
                    )
                m = re.fullmatch(r"/api/chapter/(\d+)/canon-batch", path)
                if m:
                    return self._json(api.save_canon_batch(int(m.group(1)), body.get("text", "")))
                if path == "/api/circles/manual":
                    return self._json(api.manual_circle(body.get("scope", ""), body.get("key"), body.get("text", "")))
                m = re.fullmatch(r"/api/chapter/(\d+)/manual-draft", path)
                if m:
                    return self._json(api.manual_draft(int(m.group(1)), body.get("text", "")))
                m = re.fullmatch(r"/api/chapter/(\d+)/manual-flags", path)
                if m:
                    return self._json(api.manual_flags(int(m.group(1)), body.get("text", "")))
                m = re.fullmatch(r"/api/chapter/(\d+)/accept", path)
                if m:
                    return self._json(api.accept(int(m.group(1))))
                m = re.fullmatch(r"/api/chapter/(\d+)/rollback", path)
                if m:
                    return self._json(api.rollback(int(m.group(1)), body.get("to")))
                return self._error("неизвестный путь", 404)
            except (ValueError, RuntimeError) as e:
                self._error(str(e), 400)
            except Exception as e:
                self._error(str(e), 500)

    return Handler


def serve(ws: Workspace, cfg: Config, library: Path, port: int = 8765) -> ThreadingHTTPServer:
    """Создаёт сервер на 127.0.0.1 (не запускает цикл — это делает вызывающий)."""
    api = PanelAPI(ws, cfg, library)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(api))
    return server
