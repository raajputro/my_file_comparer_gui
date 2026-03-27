#!/usr/bin/env python3
"""
compare_gui.py — File & Folder Comparison Tool  (Desktop UI)
Requires only Python 3.8+ standard library (tkinter, hashlib, difflib, …)

Run:  python compare_gui.py
"""

import sys
import os
import csv
import json
import uuid
import fnmatch
import hashlib
import logging
import difflib
import datetime
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
# THEMES  — dark (default) and light
# ══════════════════════════════════════════════════════════════════════════════
_FONT_UI    = ("Segoe UI", 10)    if sys.platform == "win32" else ("SF Pro Text", 10)
_FONT_HEAD  = ("Segoe UI Semibold", 11) if sys.platform == "win32" else ("SF Pro Display", 11)
_FONT_MONO  = ("Courier New", 10)
_FONT_TITLE = ("Courier New", 13, "bold")

THEMES = {
    "dark": {
        "bg":       "#0d0f14",
        "panel":    "#13161e",
        "border":   "#1e2330",
        "surface":  "#181c26",
        "accent":   "#00c8ff",
        "accent2":  "#00ffb3",
        "warn":     "#ffb347",
        "danger":   "#ff4f6d",
        "success":  "#39d98a",
        "text":     "#d8dce8",
        "text_dim": "#5a6070",
        "text_mid": "#8890a4",
        "add_a":    "#d97b0a",
        "add_b":    "#5b9cf6",
        "diff_bg":  "#1a0d10",
        "diff_add": "#0d1f14",
        "diff_del": "#1f0d10",
        "tree_sel_fg": "#0d0f14",
    },
    "light": {
        "bg":       "#f0f2f5",
        "panel":    "#ffffff",
        "border":   "#d0d5de",
        "surface":  "#e8ebf0",
        "accent":   "#0077cc",
        "accent2":  "#00a86b",
        "warn":     "#c06000",
        "danger":   "#cc2244",
        "success":  "#1a7a42",
        "text":     "#1a1d26",
        "text_dim": "#7a8090",
        "text_mid": "#4a5060",
        "add_a":    "#904000",
        "add_b":    "#1a4fa0",
        "diff_bg":  "#fff5f5",
        "diff_add": "#f0fff4",
        "diff_del": "#fff0f0",
        "tree_sel_fg": "#ffffff",
    },
}

# Live theme dict — mutated in-place when switching
TH = {
    **THEMES["dark"],
    "font_mono":  _FONT_MONO,
    "font_ui":    _FONT_UI,
    "font_head":  _FONT_HEAD,
    "font_title": _FONT_TITLE,
}

APP_NAME = "DiffScope Enterprise"
APP_DIR = Path.home() / ".diffscope_enterprise"
LOG_DIR = APP_DIR / "logs"
REPORT_DIR = APP_DIR / "reports"
SETTINGS_FILE = APP_DIR / "settings.json"
DEFAULT_SETTINGS = {
    "theme": "dark",
    "mode": "hash",
    "algorithm": "sha256",
    "exclude_patterns": "*.pyc;__pycache__/*;.git/*;.idea/*;.venv/*",
    "output_dir": str(REPORT_DIR),
    "auto_open_report": True,
    "max_diff_lines": 3000,
}
for _d in (APP_DIR, LOG_DIR, REPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_DIR / "diffscope.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ══════════════════════════════════════════════════════════════════════════════
# CORE ENGINE  (no UI dependency)
# ══════════════════════════════════════════════════════════════════════════════

def file_hash(path: Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return "<unreadable>"


def parse_patterns(raw: str):
    return [p.strip() for p in (raw or "").replace(",", ";").split(";") if p.strip()]


def should_exclude(rel_path: str, patterns):
    rel = rel_path.replace(chr(92), "/")
    for pattern in patterns or []:
        pat = pattern.replace(chr(92), "/")
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(Path(rel).name, pat):
            return True
    return False


def compare_two_files(pa: Path, pb: Path, algorithm: str = "sha256", max_diff_lines: int = 3000):
    """Return rich dict describing comparison of two files."""
    r = dict(
        exists_a=pa.exists(), exists_b=pb.exists(),
        size_a=0, size_b=0,
        mtime_a="", mtime_b="",
        hash_a="", hash_b="",
        identical=False, binary=False,
        algorithm=algorithm,
        diff=[],
        diff_truncated=False,
        error="",
    )
    if not (r["exists_a"] and r["exists_b"]):
        return r
    try:
        r["size_a"] = pa.stat().st_size
        r["size_b"] = pb.stat().st_size
        r["mtime_a"] = datetime.datetime.fromtimestamp(pa.stat().st_mtime).isoformat(timespec="seconds")
        r["mtime_b"] = datetime.datetime.fromtimestamp(pb.stat().st_mtime).isoformat(timespec="seconds")
        r["hash_a"] = file_hash(pa, algorithm)
        r["hash_b"] = file_hash(pb, algorithm)
        r["identical"] = r["hash_a"] == r["hash_b"]
        if not r["identical"]:
            try:
                la = pa.read_text(errors="replace").splitlines(keepends=True)
                lb = pb.read_text(errors="replace").splitlines(keepends=True)
                diff_lines = list(difflib.unified_diff(la, lb, fromfile=str(pa), tofile=str(pb), n=3))
                if len(diff_lines) > max_diff_lines:
                    r["diff"] = diff_lines[:max_diff_lines]
                    r["diff_truncated"] = True
                else:
                    r["diff"] = diff_lines
            except Exception:
                r["binary"] = True
    except Exception as ex:
        r["error"] = str(ex)
    return r


def collect_files(root: Path, exclude_patterns=None) -> dict:
    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(root))
            if should_exclude(rel, exclude_patterns):
                continue
            out[rel] = p
    return out


def compare_two_dirs(dir_a: Path, dir_b: Path, mode: str,
                     progress_cb=None, file_done_cb=None,
                     exclude_patterns=None, algorithm="sha256",
                     cancel_event=None, max_diff_lines: int = 3000):
    """
    Compare two directories.
    progress_cb(i, total, rel)  — called before each file (progress bar).
    file_done_cb(detail, meta)  — called after each file with its result dict
                                  and meta = {only_a, only_b, total_common}.
                                  Also called once up-front with only_a/only_b info.
    """
    files_a = collect_files(dir_a, exclude_patterns)
    files_b = collect_files(dir_b, exclude_patterns)
    ka, kb = set(files_a), set(files_b)
    only_a = sorted(ka - kb)
    only_b = sorted(kb - ka)
    # Sort by size of the A-side file, smallest first
    common = sorted(ka & kb, key=lambda rel: files_a[rel].stat().st_size)

    # Emit the only-A / only-B counts immediately so UI can show them
    if file_done_cb:
        file_done_cb(None, {"only_a": only_a, "only_b": only_b,
                            "total_common": len(common),
                            "total_a": len(files_a),
                            "total_b": len(files_b),
                            "init": True})

    details = []
    for i, rel in enumerate(common):
        if cancel_event and cancel_event.is_set():
            break
        if progress_cb:
            progress_cb(i, len(common), rel)
        pa, pb = files_a[rel], files_b[rel]
        if mode == "size":
            sa, sb = pa.stat().st_size, pb.stat().st_size
            identical = sa == sb
            d = dict(rel=rel, identical=identical,
                     size_a=sa, size_b=sb, diff=[], binary=False)
        else:
            d = compare_two_files(pa, pb, algorithm=algorithm, max_diff_lines=max_diff_lines)
            d["rel"] = rel
        details.append(d)
        if file_done_cb:
            file_done_cb(d, {"only_a": only_a, "only_b": only_b,
                             "total_common": len(common),
                             "total_a": len(files_a),
                             "total_b": len(files_b),
                             "init": False})

    return dict(
        session_id=str(uuid.uuid4())[:8], dir_a=str(dir_a), dir_b=str(dir_b), mode=mode,
        algorithm=algorithm, exclude_patterns=exclude_patterns or [],
        cancelled=bool(cancel_event and cancel_event.is_set()),
        only_a=only_a, only_b=only_b, details=details,
        identical=[d["rel"] for d in details if d["identical"]],
        different=[d["rel"] for d in details if not d["identical"]],
        total_a=len(files_a), total_b=len(files_b),
    )


def generate_html(res: dict) -> str:
    rows = ""
    for f in res.get("different", []):
        rows += f'<tr class="diff"><td>✗</td><td>{f}</td><td>Different</td></tr>\n'
    for f in res.get("only_a", []):
        rows += f'<tr class="only-a"><td>+</td><td>{f}</td><td>Only in A</td></tr>\n'
    for f in res.get("only_b", []):
        rows += f'<tr class="only-b"><td>+</td><td>{f}</td><td>Only in B</td></tr>\n'
    for f in res.get("identical", []):
        rows += f'<tr class="same"><td>✔</td><td>{f}</td><td>Identical</td></tr>\n'
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>Compare Report</title>
<style>
body{{font-family:monospace;background:#0d0f14;color:#d8dce8;padding:2rem}}
h1{{color:#00c8ff}} table{{border-collapse:collapse;width:100%;margin-top:1.5rem}}
th{{background:#13161e;color:#00c8ff;padding:.6rem 1rem;text-align:left}}
td{{padding:.4rem 1rem;border-bottom:1px solid #1e2330}}
.diff td{{color:#ff4f6d}} .only-a td{{color:#ffb347}}
.only-b td{{color:#5b9cf6}} .same td{{color:#39d98a}}
.badge{{display:inline-block;padding:.2rem .8rem;border-radius:4px;margin:.3rem;font-size:.85rem}}
.br{{background:#3d1018}} .bg{{background:#0d2118}} .by{{background:#3d2800}} .bb{{background:#0d1a38}}
</style></head><body>
<h1>🗂 Comparison Report</h1>
<p>Generated: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
<p><b>A:</b> {res.get("dir_a","")}  <b>B:</b> {res.get("dir_b","")}</p>
<div>
<span class="badge br">✗ {len(res.get("different",[]))} different</span>
<span class="badge bg">✔ {len(res.get("identical",[]))} identical</span>
<span class="badge by">+ {len(res.get("only_a",[]))} only-A</span>
<span class="badge bb">+ {len(res.get("only_b",[]))} only-B</span>
</div>
<table><thead><tr><th>Status</th><th>File</th><th>Note</th></tr></thead>
<tbody>{rows}</tbody></table></body></html>"""




def generate_json_report(res: dict) -> str:
    return json.dumps(res, indent=2, ensure_ascii=False)


def generate_csv_report(res: dict) -> str:
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["status", "relative_path", "size_a", "size_b", "hash_a", "hash_b", "binary", "diff_truncated", "mtime_a", "mtime_b", "error"])
    for rel in res.get("only_a", []):
        writer.writerow(["only_a", rel, "", "", "", "", "", "", "", "", ""])
    for rel in res.get("only_b", []):
        writer.writerow(["only_b", rel, "", "", "", "", "", "", "", "", ""])
    for d in res.get("details", []):
        writer.writerow([
            "identical" if d.get("identical") else "different",
            d.get("rel", ""),
            d.get("size_a", ""),
            d.get("size_b", ""),
            d.get("hash_a", ""),
            d.get("hash_b", ""),
            d.get("binary", False),
            d.get("diff_truncated", False),
            d.get("mtime_a", ""),
            d.get("mtime_b", ""),
            d.get("error", ""),
        ])
    return buf.getvalue()


def save_text_report(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path

# ══════════════════════════════════════════════════════════════════════════════
# WIDGETS helpers
# ══════════════════════════════════════════════════════════════════════════════

def styled_btn(parent, text, command, accent=False, danger=False, small=False):
    bg  = TH["accent"] if accent else (TH["danger"] if danger else TH["surface"])
    fg  = TH["bg"] if accent or danger else TH["text"]
    fnt = (TH["font_ui"][0], 9 if small else 10)
    pad = (6, 3) if small else (12, 6)
    b = tk.Button(parent, text=text, command=command,
                  bg=bg, fg=fg, font=fnt,
                  relief="flat", bd=0, cursor="hand2",
                  activebackground=TH["accent2"] if accent else TH["border"],
                  activeforeground=TH["bg"] if accent else TH["text"],
                  padx=pad[0], pady=pad[1])
    return b


def sep(parent, vertical=False):
    orient = "vertical" if vertical else "horizontal"
    s = ttk.Separator(parent, orient=orient)
    return s


# ══════════════════════════════════════════════════════════════════════════════
# MAIN APPLICATION
# ══════════════════════════════════════════════════════════════════════════════

class CompareApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DIFFSCOPE Enterprise  —  File & Folder Comparer")
        self.geometry("1200x780")
        self.minsize(900, 600)
        self.configure(bg=TH["bg"])
        self._apply_ttk_theme()

        self.path_a    = tk.StringVar()
        self.path_b    = tk.StringVar()
        self.mode_var  = tk.StringVar(value="hash")
        self.result    = None
        self._diff_index = -1
        self._diff_files = []
        self._tree_data = []
        self._filter_btns = {}
        self._filter_counts = {}
        self._theme_mode = "dark"   # current theme name
        self._themed_widgets = []   # list of (widget, config_fn) for re-theming
        self._cancel_event = threading.Event()
        self._summary_update_job = None
        self._summary_vars = {}
        self._summary_info_var = tk.StringVar(value="")
        self.settings = self._load_settings()
        self._theme_mode = self.settings.get("theme", "dark")
        TH.update(THEMES.get(self._theme_mode, THEMES["dark"]))
        self.mode_var.set(self.settings.get("mode", "hash"))
        self._build_ui()
        self._apply_theme()

    # ── ttk style ────────────────────────────────────────────────────────────
    def _apply_ttk_theme(self):
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("TNotebook",       background=TH["bg"],   borderwidth=0)
        style.configure("TNotebook.Tab",   background=TH["panel"],
                        foreground=TH["text_mid"], padding=[14, 6],
                        font=TH["font_ui"])
        style.map("TNotebook.Tab",
                  background=[("selected", TH["surface"])],
                  foreground=[("selected", TH["accent"])])
        style.configure("Treeview",
                        background=TH["panel"], fieldbackground=TH["panel"],
                        foreground=TH["text"], rowheight=24,
                        font=TH["font_mono"], borderwidth=0)
        style.configure("Treeview.Heading",
                        background=TH["border"], foreground=TH["accent"],
                        font=(TH["font_ui"][0], 9, "bold"), relief="flat")
        style.map("Treeview",
                  background=[("selected", TH["accent"])],
                  foreground=[("selected", TH["bg"])])
        style.configure("Vertical.TScrollbar",
                        troughcolor=TH["panel"], background=TH["border"],
                        arrowcolor=TH["text_dim"])
        style.configure("TProgressbar",
                        troughcolor=TH["panel"], background=TH["accent"],
                        borderwidth=0, thickness=4)
        style.configure("TSeparator", background=TH["border"])

    def _load_settings(self):
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                merged = {**DEFAULT_SETTINGS, **data}
                return merged
        except Exception:
            logging.exception("Failed to load settings")
        return dict(DEFAULT_SETTINGS)

    def _save_settings(self):
        try:
            payload = {
                "theme": self._theme_mode,
                "mode": self.mode_var.get(),
                "algorithm": self.algorithm_var.get() if hasattr(self, "algorithm_var") else DEFAULT_SETTINGS["algorithm"],
                "exclude_patterns": self.exclude_var.get() if hasattr(self, "exclude_var") else DEFAULT_SETTINGS["exclude_patterns"],
                "output_dir": self.output_dir_var.get() if hasattr(self, "output_dir_var") else DEFAULT_SETTINGS["output_dir"],
                "auto_open_report": bool(self.auto_open_var.get()) if hasattr(self, "auto_open_var") else DEFAULT_SETTINGS["auto_open_report"],
                "max_diff_lines": int(self.max_diff_var.get()) if hasattr(self, "max_diff_var") and str(self.max_diff_var.get()).isdigit() else DEFAULT_SETTINGS["max_diff_lines"],
            }
            SETTINGS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            logging.exception("Failed to save settings")

    # ── UI layout ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.algorithm_var = tk.StringVar(value=self.settings.get("algorithm", "sha256"))
        self.exclude_var = tk.StringVar(value=self.settings.get("exclude_patterns", DEFAULT_SETTINGS["exclude_patterns"]))
        self.output_dir_var = tk.StringVar(value=self.settings.get("output_dir", str(REPORT_DIR)))
        self.auto_open_var = tk.BooleanVar(value=bool(self.settings.get("auto_open_report", True)))
        self.max_diff_var = tk.StringVar(value=str(self.settings.get("max_diff_lines", 3000)))
        # ── Title bar
        title_bar = tk.Frame(self, bg=TH["panel"], height=48)
        title_bar._th_role = "panel"
        title_bar.pack(fill="x", side="top")
        title_bar.pack_propagate(False)

        tk.Label(title_bar, text="◈  DIFFSCOPE", font=TH["font_title"],
                 bg=TH["panel"], fg=TH["accent"]).pack(side="left", padx=20, pady=10)
        tk.Label(title_bar, text="file & folder comparison tool",
                 font=(TH["font_ui"][0], 9), bg=TH["panel"],
                 fg=TH["text_dim"]).pack(side="left", pady=14)

        # Export buttons top-right
        self.export_btn = styled_btn(title_bar, "⬇ HTML", self._export_html, accent=False)
        self.export_btn.pack(side="right", padx=6, pady=8)
        self.export_btn.config(state="disabled")

        self.export_json_btn = styled_btn(title_bar, "⬇ JSON", self._export_json, accent=False)
        self.export_json_btn.pack(side="right", padx=6, pady=8)
        self.export_json_btn.config(state="disabled")

        self.export_csv_btn = styled_btn(title_bar, "⬇ CSV", self._export_csv, accent=False)
        self.export_csv_btn.pack(side="right", padx=6, pady=8)
        self.export_csv_btn.config(state="disabled")

        self.open_reports_btn = styled_btn(title_bar, "📂 Reports", self._open_reports_dir, accent=False)
        self.open_reports_btn.pack(side="right", padx=6, pady=8)

        # Theme toggle
        self.theme_btn = tk.Button(
            title_bar, text="☀  Light", command=self._toggle_theme,
            bg=TH["surface"], fg=TH["accent"],
            font=(_FONT_UI[0], 9), relief="flat", bd=0, cursor="hand2",
            activebackground=TH["border"], activeforeground=TH["accent"],
            padx=10, pady=4)
        self.theme_btn.pack(side="right", padx=4, pady=8)
        self._themed_widgets.append((self.theme_btn, lambda w: w.config(
            bg=TH["surface"], fg=TH["accent"],
            activebackground=TH["border"], activeforeground=TH["accent"])))

        # ── Path selection panel
        sel = tk.Frame(self, bg=TH["panel"], pady=12)
        sel._th_role = "panel"
        sel.pack(fill="x", padx=0)

        self._path_row(sel, "  PATH  A", self.path_a, self._browse_a, 0)
        self._path_row(sel, "  PATH  B", self.path_b, self._browse_b, 1)

        # Mode + compare button row
        ctrl = tk.Frame(sel, bg=TH["panel"])
        ctrl._th_role = "panel"
        ctrl.grid(row=2, column=0, columnspan=4, sticky="ew", padx=16, pady=(4, 4))

        tk.Label(ctrl, text="Mode:", font=TH["font_ui"],
                 bg=TH["panel"], fg=TH["text_mid"]).pack(side="left")
        for val, lbl in [("hash", "SHA-256 Hash"), ("size", "Size Only"), ("diff", "Full Diff")]:
            rb = tk.Radiobutton(ctrl, text=lbl, variable=self.mode_var, value=val,
                                bg=TH["panel"], fg=TH["text"], selectcolor=TH["bg"],
                                activebackground=TH["panel"], activeforeground=TH["accent"],
                                font=TH["font_ui"], relief="flat",
                                indicatoron=0, padx=10, pady=4,
                                cursor="hand2")
            rb.pack(side="left", padx=4)

        self.compare_btn = styled_btn(ctrl, "  ▶  Compare", self._start_compare, accent=True)
        self.compare_btn._th_accent = True
        self.compare_btn.pack(side="right", padx=4)

        styled_btn(ctrl, "✕ Clear", self._clear, small=True).pack(side="right", padx=4)
        self.cancel_btn = styled_btn(ctrl, "■ Cancel", self._cancel_compare, danger=True, small=True)
        self.cancel_btn.pack(side="right", padx=4)
        self.cancel_btn.config(state="disabled")

        # Enterprise options
        opts = tk.Frame(sel, bg=TH["panel"])
        opts._th_role = "panel"
        opts.grid(row=3, column=0, columnspan=4, sticky="ew", padx=16, pady=(2, 10))
        opts.columnconfigure(1, weight=1)
        opts.columnconfigure(3, weight=1)

        tk.Label(opts, text="Hash:", font=TH["font_ui"], bg=TH["panel"], fg=TH["text_mid"]).grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        algo = ttk.Combobox(opts, textvariable=self.algorithm_var, values=["sha256", "sha1", "md5"], state="readonly", width=10)
        algo.grid(row=0, column=1, sticky="w", padx=(0, 16), pady=4)
        tk.Label(opts, text="Max diff lines:", font=TH["font_ui"], bg=TH["panel"], fg=TH["text_mid"]).grid(row=0, column=2, sticky="e", padx=(0, 6), pady=4)
        tk.Entry(opts, textvariable=self.max_diff_var, bg=TH["surface"], fg=TH["text"], insertbackground=TH["accent"], relief="flat", bd=0, width=10, highlightthickness=1, highlightbackground=TH["border"], highlightcolor=TH["accent"]).grid(row=0, column=3, sticky="w", padx=(0, 16), pady=4, ipady=4)

        tk.Label(opts, text="Exclude:", font=TH["font_ui"], bg=TH["panel"], fg=TH["text_mid"]).grid(row=1, column=0, sticky="w", padx=(0, 6), pady=4)
        tk.Entry(opts, textvariable=self.exclude_var, bg=TH["surface"], fg=TH["text"], insertbackground=TH["accent"], relief="flat", bd=0, highlightthickness=1, highlightbackground=TH["border"], highlightcolor=TH["accent"]).grid(row=1, column=1, columnspan=3, sticky="ew", padx=(0, 16), pady=4, ipady=4)

        tk.Label(opts, text="Output dir:", font=TH["font_ui"], bg=TH["panel"], fg=TH["text_mid"]).grid(row=2, column=0, sticky="w", padx=(0, 6), pady=4)
        tk.Entry(opts, textvariable=self.output_dir_var, bg=TH["surface"], fg=TH["text"], insertbackground=TH["accent"], relief="flat", bd=0, highlightthickness=1, highlightbackground=TH["border"], highlightcolor=TH["accent"]).grid(row=2, column=1, columnspan=2, sticky="ew", padx=(0, 6), pady=4, ipady=4)
        styled_btn(opts, "Browse…", self._browse_output_dir, small=True).grid(row=2, column=3, sticky="w", pady=4)
        tk.Checkbutton(opts, text="Auto-open exported report", variable=self.auto_open_var, bg=TH["panel"], fg=TH["text_mid"], activebackground=TH["panel"], activeforeground=TH["accent"], selectcolor=TH["bg"], font=(_FONT_UI[0], 9)).grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # ── Progress bar (hidden by default)
        self.progress_frame = tk.Frame(self, bg=TH["bg"], height=6)
        self.progress_frame.pack(fill="x")
        self.progress = ttk.Progressbar(self.progress_frame, mode="determinate",
                                        style="TProgressbar")
        self.status_var = tk.StringVar(value="")

        # ── Status bar
        self.status_bar = tk.Frame(self, bg=TH["border"], height=24)
        self.status_bar._th_role = "border"
        self.status_bar.pack(fill="x", side="bottom")
        self.status_bar.pack_propagate(False)
        self._status_lbl = tk.Label(self.status_bar, textvariable=self.status_var,
                 bg=TH["border"], fg=TH["text_dim"],
                 font=(TH["font_mono"][0], 9))
        self._status_lbl.pack(side="left", padx=12)

        # ── Notebook (results tabs)
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=0, pady=0)

        self.tab_summary = tk.Frame(self.nb, bg=TH["bg"])
        self.tab_files   = tk.Frame(self.nb, bg=TH["bg"])
        self.tab_diff    = tk.Frame(self.nb, bg=TH["bg"])

        self.nb.add(self.tab_summary, text="  Summary  ")
        self.nb.add(self.tab_files,   text="  File List  ")
        self.nb.add(self.tab_diff,    text="  Diff View  ")

        self._build_summary_tab()
        self._build_files_tab()
        self._build_diff_tab()

    # ── Path row helper
    def _path_row(self, parent, label, var, browse_cmd, row):
        tk.Label(parent, text=label, font=(TH["font_ui"][0], 9, "bold"),
                 bg=TH["panel"], fg=TH["accent"], width=10,
                 anchor="e").grid(row=row, column=0, padx=(16, 6), pady=4)

        entry = tk.Entry(parent, textvariable=var, bg=TH["surface"],
                         fg=TH["text"], insertbackground=TH["accent"],
                         relief="flat", font=TH["font_mono"],
                         bd=0, highlightthickness=1,
                         highlightbackground=TH["border"],
                         highlightcolor=TH["accent"])
        entry.grid(row=row, column=1, sticky="ew", padx=4, pady=4, ipady=6)
        parent.columnconfigure(1, weight=1)

        styled_btn(parent, "File…",   lambda: self._browse_file(var),
                   small=True).grid(row=row, column=2, padx=2, pady=4)
        styled_btn(parent, "Folder…", browse_cmd,
                   small=True).grid(row=row, column=3, padx=(2, 16), pady=4)

    # ── Summary tab
    def _build_summary_tab(self):
        f = self.tab_summary
        self.stat_frame = tk.Frame(f, bg=TH["bg"])
        self.stat_frame.pack(fill="x", pady=(24, 0), padx=32)

        # create once; update values in-place to avoid flicker
        self._summary_vars = {
            "identical": tk.StringVar(value="0"),
            "different": tk.StringVar(value="0"),
            "only_a": tk.StringVar(value="0"),
            "only_b": tk.StringVar(value="0"),
            "total_a": tk.StringVar(value="0"),
            "total_b": tk.StringVar(value="0"),
        }

        row1 = tk.Frame(self.stat_frame, bg=TH["bg"])
        row1.pack(fill="x", pady=(0, 6))
        cards = [
            ("identical", "IDENTICAL", TH["success"], 30),
            ("different", "DIFFERENT", TH["danger"], 30),
            ("only_a", "ONLY IN A", TH["add_a"], 30),
            ("only_b", "ONLY IN B", TH["add_b"], 30),
        ]
        for key, label, color, font_size in cards:
            card = tk.Frame(row1, bg=TH["panel"],
                            highlightbackground=color, highlightthickness=1)
            card.pack(side="left", expand=True, fill="both", padx=8, pady=4, ipady=8)
            tk.Label(card, textvariable=self._summary_vars[key], font=("Courier New", font_size, "bold"),
                     bg=TH["panel"], fg=color).pack()
            tk.Label(card, text=label, font=(TH["font_ui"][0], 9),
                     bg=TH["panel"], fg=TH["text_dim"]).pack()

        row2 = tk.Frame(self.stat_frame, bg=TH["bg"])
        row2.pack(fill="x")
        totals = [("total_a", "TOTAL FILES IN A"), ("total_b", "TOTAL FILES IN B")]
        for key, label in totals:
            card = tk.Frame(row2, bg=TH["panel"],
                            highlightbackground=TH["text_dim"], highlightthickness=1)
            card.pack(side="left", expand=True, fill="both", padx=8, pady=4, ipady=6)
            inner = tk.Frame(card, bg=TH["panel"])
            inner.pack()
            tk.Label(inner, textvariable=self._summary_vars[key], font=("Courier New", 22, "bold"),
                     bg=TH["panel"], fg=TH["text_mid"]).pack()
            tk.Label(inner, text=label, font=(TH["font_ui"][0], 9),
                     bg=TH["panel"], fg=TH["text_dim"]).pack()

        self.info_text = tk.Text(f, bg=TH["panel"], fg=TH["text_mid"],
                                 font=TH["font_mono"], relief="flat",
                                 state="disabled", height=6,
                                 bd=0, padx=16, pady=12,
                                 highlightthickness=0)
        self.info_text.pack(fill="x", padx=32, pady=16)
        self._stat_cards()

    def _stat_cards(self, identical=0, different=0, only_a=0, only_b=0,
                    total_a=0, total_b=0):
        # update textvariables only; no widget recreation
        if not getattr(self, "_summary_vars", None):
            return
        self._summary_vars["identical"].set(str(identical))
        self._summary_vars["different"].set(str(different))
        self._summary_vars["only_a"].set(str(only_a))
        self._summary_vars["only_b"].set(str(only_b))
        self._summary_vars["total_a"].set(str(total_a))
        self._summary_vars["total_b"].set(str(total_b))

    def _schedule_summary_refresh(self, force=False):
        if force:
            if self._summary_update_job:
                try:
                    self.after_cancel(self._summary_update_job)
                except Exception:
                    pass
                self._summary_update_job = None
            self._refresh_summary_info()
            return

        if self._summary_update_job is None:
            self._summary_update_job = self.after(120, self._flush_summary_refresh)

    def _flush_summary_refresh(self):
        self._summary_update_job = None
        self._refresh_summary_info()

    def _refresh_summary_info(self):
        lv = getattr(self, "_live", {}) or {}
        dir_a = lv.get("dir_a", self.path_a.get().strip())
        dir_b = lv.get("dir_b", self.path_b.get().strip())
        total_a = lv.get("total_a", 0)
        total_b = lv.get("total_b", 0)
        compared_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mode = lv.get("mode", self.mode_var.get())
        algorithm = lv.get("algorithm", self.algorithm_var.get() if hasattr(self, "algorithm_var") else "sha256")
        compared = lv.get("compared", 0)
        total = lv.get("total", 0)
        identical = lv.get("identical", 0)
        different = lv.get("different", 0)
        only_a = lv.get("only_a", 0)
        only_b = lv.get("only_b", 0)
        lines = [
            f"  Compared at : {compared_at}",
            f"  Mode        : {mode}",
            f"  Algorithm   : {algorithm}",
            f"  Path A      : {dir_a}  ({total_a} files)",
            f"  Path B      : {dir_b}  ({total_b} files)",
            f"  Progress    : {compared}/{total if total else 0} compared",
            f"  Comparison  : {identical} identical · {different} different · {only_a} only-A · {only_b} only-B",
        ]
        self.info_text.config(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.insert("end", "\n".join(lines) + "\n")
        self.info_text.config(state="disabled")

    def _build_files_tab(self):
        f = self.tab_files

        # ── Filter + search bar ───────────────────────────────────────────────
        bar = tk.Frame(f, bg=TH["bg"])
        bar.pack(fill="x", padx=16, pady=(10, 6))

        tk.Label(bar, text="Filter:", bg=TH["bg"],
                 fg=TH["text_mid"], font=TH["font_ui"]).pack(side="left", padx=(0, 6))

        # Color-coded filter buttons: (value, label, active_bg, active_fg)
        self._filter_btns = {}
        filter_specs = [
            ("all",       "All",       TH["accent"],   TH["bg"]),
            ("diff",      "Different", TH["danger"],   "#fff"),
            ("same",      "Identical", TH["success"],  "#fff"),
            ("only_a",    "Only A",    TH["add_a"],    "#fff"),
            ("only_b",    "Only B",    TH["add_b"],    "#fff"),
        ]
        self.filter_var = tk.StringVar(value="all")
        for val, lbl, abg, afg in filter_specs:
            b = tk.Button(bar, text=lbl,
                          bg=TH["surface"], fg=TH["text_mid"],
                          font=(_FONT_UI[0], 9), relief="flat", bd=0,
                          cursor="hand2", padx=10, pady=4,
                          activebackground=abg, activeforeground=afg,
                          command=lambda v=val: self._set_filter(v))
            b.pack(side="left", padx=2)
            self._filter_btns[val] = (b, abg, afg)

        # Count labels next to buttons
        self._filter_counts = {}
        for val, lbl, abg, afg in filter_specs:
            lc = tk.Label(bar, text="", bg=TH["bg"],
                          fg=TH["text_dim"], font=(_FONT_MONO[0], 8))
            lc.pack(side="left", padx=(0, 6))
            self._filter_counts[val] = lc

        # Search box
        tk.Label(bar, text="Search:", bg=TH["bg"],
                 fg=TH["text_dim"], font=TH["font_ui"]).pack(side="left", padx=(8, 4))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_tree())
        se = tk.Entry(bar, textvariable=self.search_var, bg=TH["surface"],
                      fg=TH["text"], insertbackground=TH["accent"],
                      relief="flat", font=TH["font_mono"], width=22,
                      bd=0, highlightthickness=1,
                      highlightbackground=TH["border"],
                      highlightcolor=TH["accent"])
        se.pack(side="left", ipady=4, padx=2)

        # Clear search
        tk.Button(bar, text="✕", bg=TH["surface"], fg=TH["text_dim"],
                  font=(_FONT_UI[0], 9), relief="flat", bd=0, cursor="hand2",
                  padx=6, pady=4,
                  command=lambda: self.search_var.set("")).pack(side="left", padx=1)

        # Result count label
        self._list_count_lbl = tk.Label(bar, text="", bg=TH["bg"],
                                        fg=TH["text_dim"], font=(_FONT_MONO[0], 9))
        self._list_count_lbl.pack(side="right", padx=8)

        # ── Treeview ──────────────────────────────────────────────────────────
        tree_frame = tk.Frame(f, bg=TH["bg"])
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        cols = ("status", "file", "size_a", "size_b", "hash_a", "hash_b")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                 selectmode="browse")
        widths = [100, 400, 90, 90, 130, 130]
        heads  = ["Status", "File / Path", "Size A", "Size B", "Hash A (16)", "Hash B (16)"]
        for col, w, h in zip(cols, widths, heads):
            self.tree.heading(col, text=h, command=lambda c=col: self._sort_tree(c))
            self.tree.column(col, width=w, minwidth=60)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal",  command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self.tree.tag_configure("diff",   foreground=TH["danger"])
        self.tree.tag_configure("same",   foreground=TH["success"])
        self.tree.tag_configure("only_a", foreground=TH["add_a"])
        self.tree.tag_configure("only_b", foreground=TH["add_b"])

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree_data = []
        self._set_filter("all")   # initialise button states

    def _set_filter(self, val):
        """Switch active filter and repaint all filter buttons."""
        self.filter_var.set(val)
        for k, (btn, abg, afg) in self._filter_btns.items():
            if k == val:
                btn.config(bg=abg, fg=afg,
                           relief="flat", bd=0)
            else:
                btn.config(bg=TH["surface"], fg=TH["text_mid"],
                           relief="flat", bd=0)
        self._refresh_tree()

    def _update_filter_counts(self):
        """Recount rows per category and update the count badges."""
        counts = {"all": 0, "diff": 0, "same": 0, "only_a": 0, "only_b": 0}
        q = self.search_var.get().lower()
        for row in self._tree_data:
            tag = row[0]
            rel = row[2]
            if q and q not in rel.lower():
                continue
            counts["all"] += 1
            if tag in counts:
                counts[tag] += 1
        for k, lbl in self._filter_counts.items():
            n = counts.get(k, 0)
            lbl.config(text=f"({n})" if n else "")

    # ── Diff view tab
    def _build_diff_tab(self):
        f = self.tab_diff
        self._diff_index  = -1   # index into the currently-filtered diff-able files
        self._diff_files  = []   # list of detail dicts for diffable files in current filter

        # ── Top toolbar ───────────────────────────────────────────────────────
        toolbar = tk.Frame(f, bg=TH["panel"])
        toolbar._th_role = "panel"
        toolbar.pack(fill="x")

        # File path / status label
        self.diff_label = tk.Label(toolbar,
                                   text="  Select a file from File List  —  or use ◀ ▶ to navigate",
                                   bg=TH["panel"], fg=TH["text_dim"],
                                   font=(_FONT_UI[0], 9), anchor="w")
        self.diff_label.pack(side="left", padx=12, pady=8, fill="x", expand=True)

        # Nav buttons
        nav_frame = tk.Frame(toolbar, bg=TH["panel"])
        nav_frame._th_role = "panel"
        nav_frame.pack(side="right", padx=8, pady=6)

        self._diff_counter_lbl = tk.Label(nav_frame, text="",
                                          bg=TH["panel"], fg=TH["text_dim"],
                                          font=(_FONT_MONO[0], 9))
        self._diff_counter_lbl.pack(side="left", padx=6)

        self._prev_btn = tk.Button(nav_frame, text="◀ Prev",
                                   bg=TH["surface"], fg=TH["text"],
                                   font=(_FONT_UI[0], 9), relief="flat", bd=0,
                                   cursor="hand2", padx=10, pady=4,
                                   activebackground=TH["border"],
                                   activeforeground=TH["text"],
                                   command=self._diff_prev, state="disabled")
        self._prev_btn.pack(side="left", padx=2)

        self._next_btn = tk.Button(nav_frame, text="Next ▶",
                                   bg=TH["surface"], fg=TH["text"],
                                   font=(_FONT_UI[0], 9), relief="flat", bd=0,
                                   cursor="hand2", padx=10, pady=4,
                                   activebackground=TH["border"],
                                   activeforeground=TH["text"],
                                   command=self._diff_next, state="disabled")
        self._next_btn.pack(side="left", padx=2)

        tk.Button(nav_frame, text="⎘ Copy diff",
                  bg=TH["surface"], fg=TH["text_mid"],
                  font=(_FONT_UI[0], 9), relief="flat", bd=0,
                  cursor="hand2", padx=10, pady=4,
                  activebackground=TH["border"],
                  activeforeground=TH["text"],
                  command=self._copy_diff).pack(side="left", padx=(8, 2))

        # ── File meta strip ───────────────────────────────────────────────────
        self.diff_meta = tk.Frame(f, bg=TH["surface"])
        self.diff_meta.pack(fill="x")
        self._meta_a_lbl = tk.Label(self.diff_meta, text="",
                                    bg=TH["surface"], fg=TH["add_a"],
                                    font=(_FONT_MONO[0], 9), anchor="w")
        self._meta_a_lbl.pack(side="left", padx=12, pady=3)
        self._meta_b_lbl = tk.Label(self.diff_meta, text="",
                                    bg=TH["surface"], fg=TH["add_b"],
                                    font=(_FONT_MONO[0], 9), anchor="w")
        self._meta_b_lbl.pack(side="left", padx=12, pady=3)
        self._meta_status_lbl = tk.Label(self.diff_meta, text="",
                                         bg=TH["surface"], fg=TH["text_dim"],
                                         font=(_FONT_MONO[0], 9), anchor="e")
        self._meta_status_lbl.pack(side="right", padx=12, pady=3)

        # ── Diff text area ────────────────────────────────────────────────────
        diff_frame = tk.Frame(f, bg=TH["bg"])
        diff_frame.pack(fill="both", expand=True)

        # Line-number gutter
        self.diff_gutter = tk.Text(diff_frame, bg=TH["surface"], fg=TH["text_dim"],
                                   font=_FONT_MONO, relief="flat", state="disabled",
                                   width=5, wrap="none", bd=0,
                                   highlightthickness=0, padx=4, pady=8,
                                   cursor="arrow")
        self.diff_gutter.pack(side="left", fill="y")

        self.diff_text = tk.Text(diff_frame, bg=TH["diff_bg"], fg=TH["text"],
                                 font=_FONT_MONO, relief="flat",
                                 state="disabled", wrap="none",
                                 bd=0, padx=10, pady=8,
                                 highlightthickness=0,
                                 insertbackground=TH["accent"])
        vsb = ttk.Scrollbar(diff_frame, orient="vertical",  command=self._diff_scroll_both)
        hsb = ttk.Scrollbar(f,          orient="horizontal", command=self.diff_text.xview)
        self.diff_text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.diff_gutter.configure(yscrollcommand=lambda *a: None)

        self.diff_text.pack(side="left",  fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x", padx=0)

        self.diff_text.tag_config("add",    background=TH["diff_add"], foreground=TH["success"])
        self.diff_text.tag_config("del",    background=TH["diff_del"], foreground=TH["danger"])
        self.diff_text.tag_config("hdr",    foreground=TH["accent"],   font=(_FONT_MONO[0], 10, "bold"))
        self.diff_text.tag_config("meta",   foreground=TH["warn"])
        self.diff_text.tag_config("ctx",    foreground=TH["text_dim"])
        self.diff_text.tag_config("add_gutter", background=TH["diff_add"])
        self.diff_text.tag_config("del_gutter", background=TH["diff_del"])

        self.diff_text.bind("<MouseWheel>",    self._diff_mousewheel)
        self.diff_text.bind("<Button-4>",      self._diff_mousewheel)
        self.diff_text.bind("<Button-5>",      self._diff_mousewheel)

    def _diff_scroll_both(self, *args):
        self.diff_text.yview(*args)
        self.diff_gutter.yview(*args)

    def _diff_mousewheel(self, event):
        if event.num == 4 or event.delta > 0:
            self.diff_text.yview_scroll(-3, "units")
            self.diff_gutter.yview_scroll(-3, "units")
        else:
            self.diff_text.yview_scroll(3, "units")
            self.diff_gutter.yview_scroll(3, "units")

    # ══════════════════════════════════════════════════════════════════════════
    # Browse helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _browse_file(self, var):
        p = filedialog.askopenfilename(title="Select file")
        if p:
            var.set(p)

    def _browse_a(self):
        p = filedialog.askdirectory(title="Select Folder A")
        if p:
            self.path_a.set(p)

    def _browse_b(self):
        p = filedialog.askdirectory(title="Select Folder B")
        if p:
            self.path_b.set(p)

    def _browse_output_dir(self):
        p = filedialog.askdirectory(title="Select report output folder")
        if p:
            self.output_dir_var.set(p)
            self._save_settings()

    # ══════════════════════════════════════════════════════════════════════════
    # Compare logic  (runs in background thread)
    # ══════════════════════════════════════════════════════════════════════════

    def _start_compare(self):
        a_str = self.path_a.get().strip()
        b_str = self.path_b.get().strip()
        if not a_str or not b_str:
            messagebox.showwarning("Missing paths", "Please select both Path A and Path B.")
            return
        pa, pb = Path(a_str), Path(b_str)
        if not pa.exists():
            messagebox.showerror("Not found", f"Path A does not exist:\n{pa}")
            return
        if not pb.exists():
            messagebox.showerror("Not found", f"Path B does not exist:\n{pb}")
            return

        self._save_settings()
        self._cancel_event.clear()
        self.compare_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.export_btn.config(state="disabled")
        self.export_json_btn.config(state="disabled")
        self.export_csv_btn.config(state="disabled")
        self._set_status("Comparing…")
        self.progress.pack(fill="x")
        self.progress["value"] = 0

        # Reset live counters
        self._live = dict(compared=0, identical=0, different=0,
                          only_a=0, only_b=0, total=0,
                          total_a=0, total_b=0,
                          only_a_list=[], only_b_list=[],
                          dir_a=str(pa), dir_b=str(pb),
                          mode=self.mode_var.get(), details=[],
                          algorithm=self.algorithm_var.get(),
                          exclude_patterns=parse_patterns(self.exclude_var.get()))
        logging.info("Comparison started | A=%s | B=%s | mode=%s | algorithm=%s", pa, pb, self.mode_var.get(), self.algorithm_var.get())
        self._stat_cards(0, 0, 0, 0, 0, 0)
        if self._summary_update_job:
            try:
                self.after_cancel(self._summary_update_job)
            except Exception:
                pass
            self._summary_update_job = None
        self._schedule_summary_refresh(force=True)
        self._tree_data = []
        self.tree.delete(*self.tree.get_children())
        self.nb.select(self.tab_summary)

        def run():
            try:
                if pa.is_file() and pb.is_file():
                    r = compare_two_files(pa, pb, algorithm=self.algorithm_var.get(), max_diff_lines=int(self.max_diff_var.get() or 3000))
                    res = dict(
                        session_id=str(uuid.uuid4())[:8], dir_a=str(pa), dir_b=str(pb),
                        mode=self.mode_var.get(), algorithm=self.algorithm_var.get(),
                        exclude_patterns=parse_patterns(self.exclude_var.get()), cancelled=False,
                        only_a=[], only_b=[],
                        details=[{**r, "rel": pa.name}],
                        identical=[pa.name] if r["identical"] else [],
                        different=[] if r["identical"] else [pa.name],
                    )
                    self.after(0, lambda: self._display_results(res))
                elif pa.is_dir() and pb.is_dir():
                    def prog(i, total, rel):
                        pct = int((i / max(total, 1)) * 100)
                        self.after(0, lambda p=pct, r=rel: self._update_progress(p, r))

                    def on_file_done(detail, meta):
                        self.after(0, lambda d=detail, m=meta: self._live_update(d, m))

                    res = compare_two_dirs(
                        pa, pb, self.mode_var.get(), prog, on_file_done,
                        exclude_patterns=parse_patterns(self.exclude_var.get()),
                        algorithm=self.algorithm_var.get(),
                        cancel_event=self._cancel_event,
                        max_diff_lines=int(self.max_diff_var.get() or 3000),
                    )
                    self.after(0, lambda: self._finalize_results(res))
                else:
                    self.after(0, lambda: messagebox.showerror(
                        "Type mismatch", "Both paths must be the same type (both files or both folders)."))
                    return
            except Exception as ex:  # noqa: F841
                logging.exception("Comparison failed")
                self.after(0, lambda: messagebox.showerror("Error", str(ex)))  # noqa: F821
            finally:
                self.after(0, self._compare_done)

        threading.Thread(target=run, daemon=True).start()

    def _update_progress(self, pct, rel):
        self.progress["value"] = pct
        lv = self._live
        self._set_status(
            f"  ↻  {rel[:60]}   "
            f"compared: {lv['compared']}  "
            f"identical: {lv['identical']}  "
            f"different: {lv['different']}  "
            f"only-A: {lv['only_a']}  only-B: {lv['only_b']}"
        )

    def _live_update(self, detail, meta):
        """Called from main thread after each file is done."""
        lv = self._live

        if meta.get("init"):
            # Seed only-A / only-B counts immediately
            lv["only_a"]      = len(meta["only_a"])
            lv["only_b"]      = len(meta["only_b"])
            lv["only_a_list"] = meta["only_a"]
            lv["only_b_list"] = meta["only_b"]
            lv["total"]       = meta["total_common"] + lv["only_a"] + lv["only_b"]
            lv["total_a"]     = meta.get("total_a", 0)
            lv["total_b"]     = meta.get("total_b", 0)
            # Add only-A / only-B rows to tree immediately
            for rel in meta["only_a"]:
                row = ("only_a", "  ＋ Only A", rel, "—", "—", "", "", 0)
                self._tree_data.append(row)
                self.tree.insert("", "end", values=row[1:7], tags=("only_a",))
            for rel in meta["only_b"]:
                row = ("only_b", "  ＋ Only B", rel, "—", "—", "", "", 0)
                self._tree_data.append(row)
                self.tree.insert("", "end", values=row[1:7], tags=("only_b",))
            self._stat_cards(0, 0, lv["only_a"], lv["only_b"], lv["total_a"], lv["total_b"])
            self._schedule_summary_refresh(force=True)
            return

        # A real file result
        lv["compared"] += 1
        lv["details"].append(detail)
        if detail["identical"]:
            lv["identical"] += 1
            tag = "same"
            st = "  ✔ Identical"
        else:
            lv["different"] += 1
            tag = "diff" 
            st = "  ✗ Different"

        raw_sa = detail.get("size_a", 0)
        sa = f"{raw_sa:,}"
        sb = f"{detail.get('size_b', 0):,}"
        ha = detail.get("hash_a", "")[:16]
        hb = detail.get("hash_b", "")[:16]
        rel = detail.get("rel", "")

        # Insert row into tree (files arrive smallest-first, so order is preserved)
        row = (tag, st, rel, sa, sb, ha, hb, raw_sa)
        self._tree_data.append(row)
        self.tree.insert("", "end", values=row[1:7], tags=(tag,))

        # Update stat cards live
        self._stat_cards(lv["identical"], lv["different"], lv["only_a"], lv["only_b"],
                         lv["total_a"], lv["total_b"])
        self._schedule_summary_refresh()

        # Update status bar
        self._set_status(
            f"  compared: {lv['compared']}  ·  "
            f"identical: {lv['identical']}  ·  "
            f"different: {lv['different']}  ·  "
            f"only-A: {lv['only_a']}  ·  only-B: {lv['only_b']}"
        )

    def _finalize_results(self, res):
        """Called once background thread finishes — res is the complete dict."""
        self.result = res
        lv = self._live  # noqa: F841
        n_id = len(res.get("identical", []))
        n_df = len(res.get("different", []))
        n_oa = len(res.get("only_a",   []))
        n_ob = len(res.get("only_b",   []))
        total = n_id + n_df + n_oa + n_ob  # noqa: F841

        n_ta = res.get("total_a", n_id + n_df + n_oa)
        n_tb = res.get("total_b", n_id + n_df + n_ob)
        self._stat_cards(n_id, n_df, n_oa, n_ob, n_ta, n_tb)

        self._live.update({
            "compared": n_id + n_df,
            "identical": n_id,
            "different": n_df,
            "only_a": n_oa,
            "only_b": n_ob,
            "total_a": n_ta,
            "total_b": n_tb,
            "total": n_id + n_df + n_oa + n_ob,
            "dir_a": res["dir_a"],
            "dir_b": res["dir_b"],
            "mode": res["mode"],
            "algorithm": res.get("algorithm", self.algorithm_var.get()),
        })
        self._schedule_summary_refresh(force=True)

        self.export_btn.config(state="normal")
        self.export_json_btn.config(state="normal")
        self.export_csv_btn.config(state="normal")
        self.export_json_btn.config(state="normal")
        self.export_csv_btn.config(state="normal")
        self._set_status(
            f"  Done — compared: {n_id+n_df}  ·  "
            f"identical: {n_id}  ·  different: {n_df}  ·  "
            f"only-A: {n_oa}  ·  only-B: {n_ob}"
        )

    def _compare_done(self):
        self.progress.pack_forget()
        self.compare_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")

    def _set_status(self, msg):
        self.status_var.set(msg)

    # ══════════════════════════════════════════════════════════════════════════
    # Display results
    # ══════════════════════════════════════════════════════════════════════════

    def _display_results(self, res):
        self.result = res
        n_id  = len(res.get("identical", []))
        n_df  = len(res.get("different", []))
        n_oa  = len(res.get("only_a", []))
        n_ob  = len(res.get("only_b", []))
        total = n_id + n_df + n_oa + n_ob

        # Summary tab
        n_ta = res.get("total_a", total)
        n_tb = res.get("total_b", total)
        self._stat_cards(n_id, n_df, n_oa, n_ob, n_ta, n_tb)
        self.info_text.config(state="normal")
        self.info_text.delete("1.0", "end")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.info_text.insert("end",
            f"  Compared at : {now}\n"
            f"  Mode        : {res['mode']}\n"
            f"  Path A      : {res['dir_a']}  ({n_ta} files)\n"
            f"  Path B      : {res['dir_b']}  ({n_tb} files)\n"
            f"  Comparison  : {n_id} identical · {n_df} different · {n_oa} only-A · {n_ob} only-B\n"
        )
        self.info_text.config(state="disabled")



        # Build tree data
        # Each row: (tag, status_label, rel, size_a_str, size_b_str, hash_a, hash_b, raw_size_a)
        rows = []
        for rel in res.get("only_a", []):
            rows.append(("only_a", "  ＋ Only A", rel, "—", "—", "", "", 0))
        for rel in res.get("only_b", []):
            rows.append(("only_b", "  ＋ Only B", rel, "—", "—", "", "", 0))
        for d in res.get("details", []):
            rel = d.get("rel", "")
            if d.get("identical"):
                tag = "same"
                st = "  ✔ Identical"
            else:
                tag = "diff"
                st = "  ✗ Different"
            raw_sa = d.get("size_a", 0)
            sa = f"{raw_sa:,}"
            sb = f"{d.get('size_b', 0):,}"
            ha = d.get("hash_a", "")[:16]
            hb = d.get("hash_b", "")[:16]
            rows.append((tag, st, rel, sa, sb, ha, hb, raw_sa))

        # Default order: smallest file first (matches comparison order)
        rows.sort(key=lambda r: r[7])
        self._tree_data = rows
        self._refresh_tree()

        self._set_status(
            f"Done — {n_df} different · {n_id} identical · {n_oa} only-A · {n_ob} only-B")
        self.export_btn.config(state="normal")
        self.nb.select(self.tab_summary)

    def _refresh_tree(self):
        flt = self.filter_var.get()
        q   = self.search_var.get().lower()
        self.tree.delete(*self.tree.get_children())
        count = 0
        for row in self._tree_data:
            tag, st, rel, sa, sb, ha, hb, *_ = row
            if flt != "all" and tag != flt:
                continue
            if q and q not in rel.lower():
                continue
            self.tree.insert("", "end", values=(st, rel, sa, sb, ha, hb), tags=(tag,))
            count += 1
        # Update the count label and badge counts
        if hasattr(self, "_list_count_lbl"):
            total = len(self._tree_data)
            self._list_count_lbl.config(
                text=f"Showing {count} of {total}" if count != total else f"{total} files")
        if hasattr(self, "_update_filter_counts"):
            self._update_filter_counts()
        # Rebuild diff navigation list for current filter
        self._rebuild_diff_nav()

    def _sort_tree(self, col):
        # row: (tag, status, rel, size_a_str, size_b_str, hash_a, hash_b, raw_size_a)
        if col == "size_a":
            self._tree_data.sort(key=lambda r: r[7])
        elif col == "size_b":
            def _parse(v):
                try:
                    return int(v.replace(",", ""))
                except Exception:
                    return -1
            self._tree_data.sort(key=lambda r: _parse(r[4]))
        else:
            col_idx = {"status": 0, "file": 1, "hash_a": 4, "hash_b": 5}[col]
            self._tree_data.sort(key=lambda r: r[col_idx + 1])
        self._refresh_tree()

    def _on_tree_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        rel = vals[1].strip()
        # Find in details
        for d in (self.result or {}).get("details", []):
            if d.get("rel", "") == rel:
                # Update diff nav index to match this file
                for i, df in enumerate(self._diff_files):
                    if df.get("rel", "") == rel:
                        self._diff_index = i
                        break
                self._show_diff(d)
                self._update_diff_nav()
                self.nb.select(self.tab_diff)
                return

    def _show_diff(self, d):
        rel      = d.get("rel", "")
        size_a   = d.get("size_a", 0)
        size_b   = d.get("size_b", 0)
        hash_a   = d.get("hash_a", "")
        hash_b   = d.get("hash_b", "")
        is_same  = d.get("identical", False)
        is_bin   = d.get("binary", False)

        # ── Header label
        status_icon = "✔" if is_same else "✗"
        self.diff_label.config(
            text=f"  {status_icon}  {rel}",
            fg=TH["success"] if is_same else TH["danger"])

        # ── Meta strip
        self._meta_a_lbl.config(
            text=f"A: {size_a:,} bytes   {hash_a[:20]}…" if hash_a else f"A: {size_a:,} bytes",
            bg=TH["surface"])
        self._meta_b_lbl.config(
            text=f"B: {size_b:,} bytes   {hash_b[:20]}…" if hash_b else f"B: {size_b:,} bytes",
            bg=TH["surface"])
        if is_same:
            status_txt = "IDENTICAL"
            status_fg  = TH["success"]
        elif is_bin:
            status_txt = "BINARY — DIFFER"
            status_fg  = TH["warn"]
        else:
            lines = d.get("diff", [])
            adds = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
            dels = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
            status_txt = f"+{adds}  −{dels} lines"
            status_fg  = TH["danger"]
        self._meta_status_lbl.config(text=status_txt, fg=status_fg, bg=TH["surface"])
        self.diff_meta.config(bg=TH["surface"])

        # ── Gutter + text
        self.diff_text.config(state="normal")
        self.diff_gutter.config(state="normal")
        self.diff_text.delete("1.0", "end")
        self.diff_gutter.delete("1.0", "end")

        def ins(content, tag, gutter_tag=None, gutter_txt=""):
            self.diff_text.insert("end", content + "\n", tag)
            self.diff_gutter.insert("end", (gutter_txt or " ").rjust(4) + "\n",
                                    gutter_tag or tag)

        if is_same:
            ins("  Files are identical — no differences.", "ctx")
        elif is_bin:
            ins("  Binary files differ — cannot show text diff.", "meta")
        else:
            lines = d.get("diff", [])
            if not lines:
                ins("  (No diff available — switch mode to 'Full Diff' and re-compare)", "ctx")
            line_no = 0
            for line in lines:
                line_s = line.rstrip("\n")
                if line_s.startswith("+++") or line_s.startswith("---"):
                    ins(line_s, "hdr", gutter_txt="")
                elif line_s.startswith("@@"):
                    # Parse hunk header for starting line number
                    import re
                    m = re.search(r"\+(\d+)", line_s)
                    if m:
                        line_no = int(m.group(1)) - 1
                    ins(line_s, "meta", gutter_txt="@@")
                elif line_s.startswith("+"):
                    line_no += 1
                    ins(line_s, "add", gutter_txt=str(line_no))
                elif line_s.startswith("-"):
                    ins(line_s, "del", gutter_txt="−")
                else:
                    line_no += 1
                    ins(line_s, "ctx", gutter_txt=str(line_no))

        self.diff_text.config(state="disabled")
        self.diff_gutter.config(state="disabled")
        self.diff_text.yview_moveto(0)
        self.diff_gutter.yview_moveto(0)

    # ── Diff navigation helpers ───────────────────────────────────────────────

    def _rebuild_diff_nav(self):
        """Rebuild the list of diff-able files matching current filter."""
        flt = self.filter_var.get()
        q   = self.search_var.get().lower()
        self._diff_files = []
        for d in (self.result or {}).get("details", []):
            rel = d.get("rel", "")
            tag = "same" if d.get("identical") else "diff"
            if flt not in ("all", tag):
                continue
            if q and q not in rel.lower():
                continue
            self._diff_files.append(d)
        self._update_diff_nav()

    def _update_diff_nav(self):
        if not hasattr(self, "_diff_counter_lbl") or not hasattr(self, "_prev_btn") or not hasattr(self, "_next_btn"):
            return
        total = len(getattr(self, "_diff_files", []))
        idx   = getattr(self, "_diff_index", -1)
        if total == 0:
            self._diff_counter_lbl.config(text="")
            self._prev_btn.config(state="disabled")
            self._next_btn.config(state="disabled")
        else:
            n = idx + 1 if 0 <= idx < total else "—"
            self._diff_counter_lbl.config(text=f"{n} / {total}")
            self._prev_btn.config(state="normal" if idx > 0 else "disabled")
            self._next_btn.config(state="normal" if idx < total - 1 else "disabled")

    def _diff_prev(self):
        if self._diff_index > 0:
            self._diff_index -= 1
            self._show_diff(self._diff_files[self._diff_index])
            self._update_diff_nav()
            self._highlight_tree_row(self._diff_files[self._diff_index].get("rel", ""))

    def _diff_next(self):
        if self._diff_index < len(self._diff_files) - 1:
            self._diff_index += 1
            self._show_diff(self._diff_files[self._diff_index])
            self._update_diff_nav()
            self._highlight_tree_row(self._diff_files[self._diff_index].get("rel", ""))

    def _highlight_tree_row(self, rel):
        """Select the matching row in the file tree."""
        for iid in self.tree.get_children():
            vals = self.tree.item(iid, "values")
            if vals and vals[1].strip() == rel:
                self.tree.selection_set(iid)
                self.tree.see(iid)
                return

    def _copy_diff(self):
        content = self.diff_text.get("1.0", "end")
        self.clipboard_clear()
        self.clipboard_append(content)

    # ══════════════════════════════════════════════════════════════════════════
    # Actions
    # ══════════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════════
    # Theme switching
    # ══════════════════════════════════════════════════════════════════════════

    def _toggle_theme(self):
        self._theme_mode = "light" if self._theme_mode == "dark" else "dark"
        palette = THEMES[self._theme_mode]
        TH.update(palette)
        self._apply_theme()
        self._save_settings()

    def _apply_theme(self):
        """Repaint every registered widget and ttk style with current TH."""
        # ttk styles
        self._apply_ttk_theme()

        # Root window
        self.configure(bg=TH["bg"])

        # Walk all tk widgets and repaint by class
        self._repaint_widget(self)

        # Treeview tag colours
        self.tree.tag_configure("diff",   foreground=TH["danger"])
        self.tree.tag_configure("same",   foreground=TH["success"])
        self.tree.tag_configure("only_a", foreground=TH["add_a"])
        self.tree.tag_configure("only_b", foreground=TH["add_b"])

        # Diff text tag colours
        self.diff_text.config(bg=TH["diff_bg"], fg=TH["text"])
        self.diff_text.tag_config("add",  background=TH["diff_add"], foreground=TH["success"])
        self.diff_text.tag_config("del",  background=TH["diff_del"], foreground=TH["danger"])
        self.diff_text.tag_config("hdr",  foreground=TH["accent"])
        self.diff_text.tag_config("meta", foreground=TH["warn"])
        self.diff_text.tag_config("ctx",  foreground=TH["text_dim"])
        # Diff gutter + meta strip
        if hasattr(self, "diff_gutter"):
            self.diff_gutter.config(bg=TH["surface"], fg=TH["text_dim"])
        if hasattr(self, "diff_meta"):
            self.diff_meta.config(bg=TH["surface"])
            self._meta_a_lbl.config(bg=TH["surface"], fg=TH["add_a"])
            self._meta_b_lbl.config(bg=TH["surface"], fg=TH["add_b"])
            self._meta_status_lbl.config(bg=TH["surface"])
        # Recolor filter buttons
        if hasattr(self, "_filter_btns"):
            active = self.filter_var.get()
            filter_specs = [
                ("all",    TH["accent"],  TH["bg"]),
                ("diff",   TH["danger"],  "#fff"),
                ("same",   TH["success"], "#fff"),
                ("only_a", TH["add_a"],   "#fff"),
                ("only_b", TH["add_b"],   "#fff"),
            ]
            for val, abg, afg in filter_specs:
                if val in self._filter_btns:
                    btn, _, _ = self._filter_btns[val]
                    self._filter_btns[val] = (btn, abg, afg)
                    if val == active:
                        btn.config(bg=abg, fg=afg)
                    else:
                        btn.config(bg=TH["surface"], fg=TH["text_mid"])
        # Nav buttons
        for attr in ("_prev_btn", "_next_btn"):
            if hasattr(self, attr):
                getattr(self, attr).config(
                    bg=TH["surface"], fg=TH["text"],
                    activebackground=TH["border"], activeforeground=TH["text"])

        # Stat cards (rebuild with current theme)
        lv = getattr(self, "_live", {})
        self._stat_cards(
            lv.get("identical", 0), lv.get("different", 0),
            lv.get("only_a",    0), lv.get("only_b",    0),
            lv.get("total_a",   0), lv.get("total_b",   0),
        )

        # Status bar
        if hasattr(self, "status_bar"):
            self.status_bar.config(bg=TH["border"])
        if hasattr(self, "_status_lbl"):
            self._status_lbl.config(bg=TH["border"], fg=TH["text_dim"])

        # Toggle button label
        if self._theme_mode == "dark":
            self.theme_btn.config(text="☀  Light")
        else:
            self.theme_btn.config(text="☾  Dark")

    def _repaint_widget(self, widget):
        """Recursively repaint every tk widget using its class as a guide."""
        cls = widget.__class__.__name__

        # Map widget roles by stored tag or by class
        tag = getattr(widget, "_th_role", None)

        try:
            if cls == "Frame":
                bg = TH["panel"] if tag == "panel" else                      TH["border"] if tag == "border" else TH["bg"]
                widget.config(bg=bg)
            elif cls == "Label":
                bg   = TH["panel"] if tag in ("panel", "title") else TH["bg"]
                fg   = TH["accent"] if tag == "accent" else                        TH["text_dim"] if tag == "dim" else                        TH["text_mid"] if tag == "mid" else TH["text"]
                widget.config(bg=bg, fg=fg)
            elif cls == "Button":
                is_accent = getattr(widget, "_th_accent", False)
                bg = TH["accent"] if is_accent else TH["surface"]
                fg = TH["bg"]     if is_accent else TH["text"]
                widget.config(bg=bg, fg=fg,
                              activebackground=TH["accent2"] if is_accent else TH["border"],
                              activeforeground=TH["bg"] if is_accent else TH["text"])
            elif cls == "Entry":
                widget.config(bg=TH["surface"], fg=TH["text"],
                              insertbackground=TH["accent"],
                              highlightbackground=TH["border"],
                              highlightcolor=TH["accent"])
            elif cls == "Text":
                widget.config(bg=TH["panel"], fg=TH["text_mid"])
            elif cls == "Radiobutton":
                bg = TH["panel"] if tag == "panel" else TH["bg"]
                widget.config(bg=bg, fg=TH["text"],
                              selectcolor=TH["surface"] if tag != "panel" else TH["bg"],
                              activebackground=bg, activeforeground=TH["accent"])
        except tk.TclError:
            pass

        for child in widget.winfo_children():
            self._repaint_widget(child)


    def _cancel_compare(self):
        self._cancel_event.set()
        self._set_status("Cancellation requested...")
        logging.info("Comparison cancellation requested by user")

    def _open_reports_dir(self):
        out_dir = Path(self.output_dir_var.get() or REPORT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(out_dir))
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(out_dir)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(out_dir)])
        except Exception as ex:
            logging.exception("Failed to open reports directory")
            messagebox.showerror("Open Reports Folder", f"Could not open folder:\n{out_dir}\n\n{ex}")

    def _default_export_path(self, suffix: str) -> Path:
        out_dir = Path(self.output_dir_var.get() or REPORT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return out_dir / f"compare_report_{stamp}.{suffix}"

    def _export_json(self):
        if not self.result:
            return
        default_path = self._default_export_path("json")
        p = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON file", "*.json")],
            initialfile=default_path.name,
            initialdir=str(default_path.parent),
            title="Save JSON Report")
        if not p:
            return
        Path(p).write_text(json.dumps(self.result, indent=2, ensure_ascii=False), encoding="utf-8")
        if self.auto_open_var.get():
            try:
                webbrowser.open(Path(p).resolve().as_uri())
            except Exception:
                logging.exception("Failed to auto-open JSON report")
        messagebox.showinfo("Exported", f"JSON report saved:\n{p}")

    def _export_csv(self):
        if not self.result:
            return
        default_path = self._default_export_path("csv")
        p = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV file", "*.csv")],
            initialfile=default_path.name,
            initialdir=str(default_path.parent),
            title="Save CSV Report")
        if not p:
            return

        rows = []
        for rel in self.result.get("only_a", []):
            rows.append({
                "status": "only_a", "file": rel, "size_a": "", "size_b": "",
                "hash_a": "", "hash_b": "", "identical": False,
                "binary": False, "error": ""
            })
        for rel in self.result.get("only_b", []):
            rows.append({
                "status": "only_b", "file": rel, "size_a": "", "size_b": "",
                "hash_a": "", "hash_b": "", "identical": False,
                "binary": False, "error": ""
            })
        for d in self.result.get("details", []):
            rows.append({
                "status": "identical" if d.get("identical") else "different",
                "file": d.get("rel", ""),
                "size_a": d.get("size_a", ""),
                "size_b": d.get("size_b", ""),
                "hash_a": d.get("hash_a", ""),
                "hash_b": d.get("hash_b", ""),
                "identical": d.get("identical", False),
                "binary": d.get("binary", False),
                "error": d.get("error", ""),
            })

        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "status", "file", "size_a", "size_b", "hash_a", "hash_b",
                "identical", "binary", "error"
            ])
            writer.writeheader()
            writer.writerows(rows)

        if self.auto_open_var.get():
            try:
                webbrowser.open(Path(p).resolve().as_uri())
            except Exception:
                logging.exception("Failed to auto-open CSV report")
        messagebox.showinfo("Exported", f"CSV report saved:\n{p}")

    def _export_html(self):
        if not self.result:
            return
        p = filedialog.asksaveasfilename(
            defaultextension=".html",
            filetypes=[("HTML file", "*.html")],
            initialfile="compare_report.html",
            title="Save HTML Report")
        if not p:
            return
        html = generate_html(self.result)
        Path(p).write_text(html, encoding="utf-8")
        messagebox.showinfo("Exported", f"Report saved:\n{p}")

    def _clear(self):
        self.path_a.set("")
        self.path_b.set("")
        self.result = None
        self._tree_data = []
        self.tree.delete(*self.tree.get_children())
        self._stat_cards()
        self.info_text.config(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.config(state="disabled")
        self.diff_text.config(state="normal")
        self.diff_text.delete("1.0", "end")
        self.diff_text.config(state="disabled")
        self.diff_label.config(text="Select a file in the File List to view its diff.")
        self.export_btn.config(state="disabled")
        if hasattr(self, "export_json_btn"):
            self.export_json_btn.config(state="disabled")
        if hasattr(self, "export_csv_btn"):
            self.export_csv_btn.config(state="disabled")
        self._diff_files = []
        self._diff_index = -1
        self._set_status("")


# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = CompareApp()
    app.mainloop()
