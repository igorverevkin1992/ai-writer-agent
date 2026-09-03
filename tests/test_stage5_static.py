"""Этап 5 аудита: статические гарантии — «порогов в коде нет» (критерий 6), «записи мимо guard нет» (FR-K3),
детерминизм окна и выгрузок между процессами (FR-C4/FR-X3)."""

import ast
import hashlib
import os
import subprocess
import sys
from pathlib import Path

UGAR = Path(__file__).resolve().parent.parent / "ugar"


def _enclosing_functions(tree: ast.AST) -> dict[int, str]:
    """Номер строки → имя функции верхнего уровня, в которой она находится."""
    spans: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                spans.setdefault(line, node.name)
    return spans


def test_в_верификаторе_нет_числовых_порогов():
    """Критерий приёмки 6: все пороги Э1 — из norms.json. В сравнениях verifier1.py допустимы только 0 и 1
    (индексы/пустота), остальные числа — только через _norm_value()."""
    src = (UGAR / "verifier1.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for comp in [node.left, *node.comparators]:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, (int, float)) and comp.value not in (0, 1):
                    if "# не порог" not in lines[node.lineno - 1]:
                        offenders.append(f"verifier1.py:{node.lineno}: {lines[node.lineno - 1].strip()}")
    assert not offenders, "\n".join(offenders)


def test_нет_записи_файлов_мимо_guard():
    """FR-K3: единственная точка записи — guard.write_text/append_text. Прямые записи допустимы только
    в перечисленных функциях, и все они пишут вне библиотеки (init копирует демо-библиотеку до её защиты)."""
    allowed = {
        "cli.py": {"cmd_init", "cmd_retest", "cmd_apply_edits"},
    }
    writers = {"write_text", "write_bytes", "copyfile", "copytree", "move", "copy", "copy2"}
    offenders = []
    for path in sorted(UGAR.glob("*.py")):
        if path.name == "guard.py":
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        spans = _enclosing_functions(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            raw_write = False
            if name in writers:
                owner = func.value if isinstance(func, ast.Attribute) else None
                if not (isinstance(owner, ast.Name) and owner.id == "guard"):
                    raw_write = True
            elif name == "open":
                modes = [a for a in node.args[1:2]] + [k.value for k in node.keywords if k.arg == "mode"]
                if any(isinstance(m, ast.Constant) and isinstance(m.value, str) and set(m.value) & {"w", "a"} for m in modes):
                    raw_write = True
            if raw_write and spans.get(node.lineno) not in allowed.get(path.name, set()):
                offenders.append(f"{path.name}:{node.lineno}: {name}")
    assert not offenders, "\n".join(offenders)


def test_детерминированность_между_процессами(ws, library):
    """FR-C4/FR-X3: окно и выгрузки не зависят от хэш-сида процесса."""
    results = []
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONUTF8": "1"}
        for args in (["export"], ["compile", "1"]):
            subprocess.run([sys.executable, "-m", "ugar", *args], cwd=ws.root, env=env, check=True, capture_output=True)
        window = ws.window_path(1).read_bytes()
        manifest = (ws.exports / "manifest.json").read_bytes()
        results.append((hashlib.sha256(window).hexdigest(), hashlib.sha256(manifest).hexdigest()))
    assert results[0] == results[1]
