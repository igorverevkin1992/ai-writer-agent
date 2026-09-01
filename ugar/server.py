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
    "export", "compile", "write", "verify1", "verify2", "review",
    "apply-edits", "diff-check", "regress", "canonize", "canonize-apply",
}


class JobRunner:
    """Одна задача за раз (Д-5: однопользовательский режим, без гонок FSM)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.job: dict | None = None

    def start(self, name: str, chapter: int | None, fn) -> dict:
        with self._lock:
            if self.job and self.job["status"] == "выполняется":
                raise RuntimeError(f"уже выполняется: {self.job['name']}")
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
        buf = io.StringIO()
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
        assert self.job is not None
        self.job["output"] = _strip_ansi(buf.getvalue())
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

    def accept(self, n: int) -> dict:
        """Приёмка: подтверждение автор дал кнопкой + диалогом в панели (Д-8)."""
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
        from .cli import cmd_rollback

        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                cmd_rollback(n, to=to, yes=True)
        except typer.Exit as e:
            if getattr(e, "exit_code", 1):
                raise RuntimeError(_strip_ansi(buf.getvalue()).strip() or "откат отклонён")
        return {"ok": True, "output": _strip_ansi(buf.getvalue())}

    def run_command(self, cmd: str, chapter: int | None) -> dict:
        """Долгие шаги такта — фоновой задачей с захватом вывода."""
        if cmd not in COMMANDS:
            raise ValueError(f"неизвестная команда: {cmd}")
        from . import cli

        fns = {
            "export": lambda: cli.cmd_export(),
            "compile": lambda: cli.cmd_compile(chapter),
            "write": lambda: cli.cmd_write(chapter),
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
                    job = api.run_command(body.get("cmd", ""), body.get("chapter"))
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
