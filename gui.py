"""
gui.py – PySide6 desktop GUI for the Job Agent.

Perplexity-inspired dark minimal design.
On Windows 11, the native Acrylic backdrop (real frosted-glass blur) is
enabled automatically via the DWM API.

Launch:  python gui.py
"""

import ctypes
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger("job_agent")

from dotenv import dotenv_values, set_key
from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt, QThread, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPen, QPixmap, QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDoubleSpinBox, QFormLayout, QFrame,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QPlainTextEdit, QScrollArea, QSizePolicy, QSpinBox,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

# ── Paths ─────────────────────────────────────────────────────────────────────
_PROJECT_DIR  = Path(__file__).parent.resolve()
_ENV_FILE     = _PROJECT_DIR / ".env"
_CONFIG_FILE  = _PROJECT_DIR / "config.py"
_PROFILE_FILE = _PROJECT_DIR / "PROFILE.md"
# Prefer a project-local virtualenv Python if available (cross-platform),
# otherwise fall back to the current interpreter.
_win_venv_python  = _PROJECT_DIR / "job_agent" / "Scripts" / "python.exe"
_unix_venv_python = _PROJECT_DIR / "job_agent" / "bin" / "python"

_PYTHON = None
for _candidate in (_win_venv_python, _unix_venv_python):
    if _candidate.exists():
        _PYTHON = _candidate
        break

if _PYTHON is None:
    _PYTHON = Path(sys.executable)

# ── Perplexity-inspired palette ───────────────────────────────────────────────
_C = {
    "bg":        "#0C0C0C",
    "surface":   "#111111",
    "surface2":  "#1a1a1a",
    "border":    "rgba(255,255,255,0.07)",
    "border_h":  "rgba(255,255,255,0.14)",
    "text":      "#FFFFFF",
    "text2":     "#C2C2C2",
    "text3":     "#6B6B6B",
    "accent":    "#20B8CD",
    "accent_bg": "rgba(32,184,205,0.10)",
    "accent_b":  "rgba(32,184,205,0.22)",
    "green":     "#4ade80",
    "green_bg":  "rgba(74,222,128,0.09)",
    "green_b":   "rgba(74,222,128,0.28)",
    "red":       "#f87171",
    "red_bg":    "rgba(248,113,113,0.09)",
    "red_b":     "rgba(248,113,113,0.28)",
}

# ── Checkmark SVG (for checkbox) ──────────────────────────────────────────────
_CHK_FILE = Path(tempfile.gettempdir()) / "ja_check.svg"
_CHK_FILE.write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18">'
    '<polyline points="3,9.5 7,13.5 15,4.5" stroke="#0C0C0C" stroke-width="2.5"'
    ' fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    encoding="utf-8",
)
_CHK = str(_CHK_FILE).replace("\\", "/")


def _ui_font() -> str:
    families = QFontDatabase.families()
    for f in ("Inter", "Inter Display", "Segoe UI Variable", "Segoe UI"):
        if f in families:
            return f
    return "Arial"


# ── QSS ───────────────────────────────────────────────────────────────────────
def _make_qss(font: str) -> str:
    c = _C
    return f"""
* {{ font-family: "{font}", "Segoe UI", Arial, sans-serif; font-size: 14px; outline: none; }}
QMainWindow {{ background: transparent; }}
QWidget      {{ background: transparent; color: {c['text']}; }}

QFrame#sidebar {{
    background: rgba(10,10,10,0.96);
    border-right: 1px solid {c['border']};
}}
QLabel#app_name   {{ color: {c['text']}; font-size: 16px; font-weight: 700; background: transparent; letter-spacing: -0.3px; }}
QLabel#app_tag    {{ color: {c['text3']}; font-size: 11px; background: transparent; }}
QPushButton#nav_btn {{
    background: transparent; border: none;
    border-left: 2px solid transparent; border-radius: 0;
    color: {c['text2']}; text-align: left; padding: 11px 20px;
    font-size: 13px; font-weight: 400; min-width: 190px;
}}
QPushButton#nav_btn:hover {{
    background: rgba(255,255,255,0.04); color: {c['text']};
    border-left: 2px solid rgba(32,184,205,0.35);
}}
QPushButton#nav_btn[active=true] {{
    background: rgba(32,184,205,0.08); color: {c['accent']};
    border-left: 2px solid {c['accent']}; font-weight: 500;
}}

QWidget#content_bg {{
    background: rgba(12,12,12,0.82);
    border-left: 1px solid {c['border']};
}}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 5px; border-radius: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.10); border-radius: 2px; min-height: 20px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(32,184,205,0.30); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QLabel#page_title {{ font-size: 22px; font-weight: 600; letter-spacing: -0.5px; color: {c['text']}; background: transparent; }}
QLabel#page_desc  {{ font-size: 13px; color: {c['text3']}; background: transparent; }}
QLabel            {{ color: {c['text2']}; background: transparent; }}

QGroupBox {{
    background: rgba(17,17,17,0.88); border: 1px solid {c['border']};
    border-radius: 8px; margin-top: 14px; padding: 16px 18px 18px 18px;
}}
QGroupBox:hover {{ border-color: rgba(32,184,205,0.20); }}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 14px; padding: 0 8px;
    color: {c['text3']}; background: rgba(17,17,17,0.88);
    font-size: 10px; font-weight: 600; letter-spacing: 1.2px;
}}

QLineEdit {{
    background: rgba(26,26,26,0.95); border: 1px solid {c['border']};
    border-radius: 6px; padding: 8px 12px; color: {c['text']};
    selection-background-color: {c['accent']}; selection-color: {c['bg']};
}}
QLineEdit:hover {{ border-color: {c['border_h']}; }}
QLineEdit:focus {{ border-color: rgba(32,184,205,0.55); background: rgba(26,26,26,1.0); }}

QPlainTextEdit, QTextEdit {{
    background: rgba(26,26,26,0.95); border: 1px solid {c['border']};
    border-radius: 6px; padding: 10px 12px; color: {c['text']};
    selection-background-color: {c['accent']}; selection-color: {c['bg']};
}}
QPlainTextEdit:focus, QTextEdit:focus {{ border-color: rgba(32,184,205,0.55); }}

QSpinBox, QDoubleSpinBox {{
    background: rgba(26,26,26,0.95); border: 1px solid {c['border']};
    border-radius: 6px; padding: 7px 10px; color: {c['text']}; min-width: 90px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: rgba(32,184,205,0.55); }}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: rgba(255,255,255,0.05); border: none; width: 18px; border-radius: 3px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: rgba(32,184,205,0.15);
}}

QCheckBox {{ color: {c['text']}; spacing: 9px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid rgba(255,255,255,0.18); border-radius: 4px;
    background: rgba(26,26,26,0.95);
}}
QCheckBox::indicator:hover {{ border-color: rgba(32,184,205,0.55); }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url("{_CHK}"); }}

QListWidget {{
    background: rgba(26,26,26,0.90); border: 1px solid {c['border']};
    border-radius: 6px; padding: 4px; color: {c['text']}; outline: none;
    alternate-background-color: rgba(30,30,30,0.50);
}}
QListWidget::item {{ padding: 5px 10px; border-radius: 4px; }}
QListWidget::item:selected {{ background: {c['accent_bg']}; color: {c['accent']}; border: 1px solid {c['accent_b']}; }}
QListWidget::item:hover {{ background: rgba(255,255,255,0.04); }}

QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255,255,255,0.09), stop:1 rgba(255,255,255,0.03));
    color: {c['text']};
    border: 1px solid rgba(255,255,255,0.10);
    border-top: 1px solid rgba(255,255,255,0.22);
    border-radius: 6px;
    padding: 7px 16px; font-size: 14px; font-weight: 500; min-height: 30px;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255,255,255,0.15), stop:1 rgba(255,255,255,0.06));
    border-color: rgba(255,255,255,0.16); border-top-color: rgba(255,255,255,0.32);
}}
QPushButton:pressed {{ background: rgba(255,255,255,0.02); color: {c['text']}; border-color: rgba(255,255,255,0.07); }}
QPushButton:disabled {{ background: rgba(18,18,18,0.50); color: {c['text3']}; border-color: rgba(255,255,255,0.04); }}

QPushButton#nav_btn {{ background: transparent; border: none; border-left: 2px solid transparent; border-radius: 0; }}
QPushButton#save_btn {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(44,204,224,0.96), stop:1 rgba(24,168,188,0.88));
    color: #030D0F; border: 1px solid rgba(32,184,205,0.25);
    border-top: 1px solid rgba(255,255,255,0.38); font-weight: 600; border-radius: 7px;
}}
QPushButton#run_btn  {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(44,204,224,0.96), stop:1 rgba(24,168,188,0.88));
    color: #030D0F; border: 1px solid rgba(32,184,205,0.25);
    border-top: 1px solid rgba(255,255,255,0.38);
    font-size: 14px; font-weight: 700; min-height: 44px; border-radius: 8px; padding: 10px 32px;
}}
QPushButton#run_btn:disabled {{ background: rgba(26,26,26,0.70); color: {c['text3']}; border-color: rgba(255,255,255,0.04); }}
QPushButton#stop_btn {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(248,113,113,0.14), stop:1 rgba(248,113,113,0.07));
    color: {c['red']}; border: 1px solid rgba(248,113,113,0.22);
    border-top: 1px solid rgba(248,113,113,0.38);
    font-weight: 500; min-height: 44px; border-radius: 8px;
}}
QPushButton#stop_btn:disabled {{ color: {c['text3']}; border-color: {c['border']}; background: transparent; }}
QPushButton#add_btn  {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(74,222,128,0.13), stop:1 rgba(74,222,128,0.06));
    color: {c['green']}; border: 1px solid rgba(74,222,128,0.22);
    border-top: 1px solid rgba(74,222,128,0.40);
    border-radius: 5px; padding: 4px 14px; font-size: 13px; min-height: 24px;
}}
QPushButton#rem_btn  {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(248,113,113,0.13), stop:1 rgba(248,113,113,0.06));
    color: {c['red']}; border: 1px solid rgba(248,113,113,0.22);
    border-top: 1px solid rgba(248,113,113,0.40);
    border-radius: 5px; padding: 4px 14px; font-size: 13px; min-height: 24px;
}}
QPushButton#clear_btn {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255,255,255,0.08), stop:1 rgba(255,255,255,0.02));
    color: {c['text2']}; border: 1px solid rgba(255,255,255,0.10);
    border-top: 1px solid rgba(255,255,255,0.20);
    border-radius: 5px; padding: 5px 16px; font-size: 13px; min-height: 26px;
}}

QFrame[frameShape="4"] {{ border: none; border-top: 1px solid {c['border']}; max-height: 1px; background: {c['border']}; }}

QToolTip {{ background: rgba(26,26,26,0.98); color: {c['text']}; border: 1px solid {c['border_h']}; border-radius: 5px; padding: 5px 10px; font-size: 12px; }}
QMessageBox {{ background: {c['surface']}; }}
QMessageBox QLabel {{ color: {c['text']}; }}
QMessageBox QPushButton {{ min-width: 80px; }}
"""


# ── Windows 11 Acrylic + dark title bar ───────────────────────────────────────
def _apply_win11_acrylic(hwnd: int) -> None:
    if sys.platform != "win32":
        logger.debug(
            "Acrylic backdrop not applied: platform is '%s' (Windows-only feature).",
            sys.platform,
        )
        return
    try:
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
        acrylic = ctypes.c_int(3)
        dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(acrylic), ctypes.sizeof(acrylic))
    except Exception as exc:
        logger.debug("Acrylic backdrop unavailable (DWM call failed): %s", exc)


# ── App icon ──────────────────────────────────────────────────────────────────
def _make_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        s = float(size)
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0, 0, s, s), s * 0.18, s * 0.18)
        p.fillPath(bg, QColor("#0C0C0C"))
        bx, by, bw, bh = s*0.14, s*0.38, s*0.72, s*0.44
        body = QPainterPath()
        body.addRoundedRect(QRectF(bx, by, bw, bh), s*0.07, s*0.07)
        p.fillPath(body, QColor(_C["accent"]))
        pen = QPen(QColor(_C["accent"]), max(1.0, s * 0.075))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        hw, hh = s*0.32, s*0.17
        p.drawArc(QRectF((s-hw)/2, by-hh, hw, hh*2+s*0.02), 0, 180*16)
        pen2 = QPen(QColor("#0C0C0C"), max(1.0, s*0.06))
        pen2.setCapStyle(Qt.FlatCap); p.setPen(pen2)
        cy = int(by + bh * 0.46)
        p.drawLine(int(bx), cy, int(bx+bw), cy)
        p.end()
        icon.addPixmap(pix)
    return icon


# ── AnimatedButton ────────────────────────────────────────────────────────────
class AnimatedButton(QPushButton):
    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self._op: float = 0.0
        self._anim = QPropertyAnimation(self, b"hoverOp", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _g(self) -> float: return self._op
    def _s(self, v: float) -> None: self._op = v; self.update()
    hoverOp = Property(float, _g, _s)

    def enterEvent(self, e):
        self._anim.stop(); self._anim.setStartValue(self._op)
        self._anim.setEndValue(1.0); self._anim.start(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._anim.stop(); self._anim.setStartValue(self._op)
        self._anim.setEndValue(0.0); self._anim.start(); super().leaveEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._op > 0.001:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            c = QColor(255, 255, 255); c.setAlphaF(self._op * 0.06)
            path = QPainterPath()
            r = 8.0 if self.objectName() in ("run_btn","stop_btn","save_btn") else 6.0
            path.addRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1), r, r)
            p.fillPath(path, c)


# ── Worker thread ─────────────────────────────────────────────────────────────
class _RunWorker(QThread):
    line_ready = Signal(str)
    finished   = Signal(int)

    def run(self) -> None:
        try:
            proc = subprocess.Popen(
                [str(_PYTHON), "main.py"], cwd=str(_PROJECT_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
            for line in proc.stdout: self.line_ready.emit(line)
            proc.wait(); self.finished.emit(proc.returncode)
        except Exception as exc:
            self.line_ready.emit(f"[ERROR] {exc}\n"); self.finished.emit(1)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _scroll(w: QWidget) -> QScrollArea:
    a = QScrollArea(); a.setWidgetResizable(True); a.setWidget(w)
    a.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); return a

def _hline() -> QFrame:
    f = QFrame(); f.setFrameShape(QFrame.HLine); return f

def _header(title: str, desc: str) -> QWidget:
    w = QWidget(); lay = QVBoxLayout(w)
    lay.setContentsMargins(0,0,0,4); lay.setSpacing(3)
    t = QLabel(title); t.setObjectName("page_title")
    d = QLabel(desc);  d.setObjectName("page_desc")
    lay.addWidget(t); lay.addWidget(d); lay.addSpacing(6); lay.addWidget(_hline())
    return w


# ── Page 1 – Credentials ──────────────────────────────────────────────────────
class CredentialsPage(QWidget):
    def __init__(self):
        super().__init__()
        self._fields: dict[str, QLineEdit] = {}
        self._thr = QSpinBox()
        self._build(); self._load()

    def _build(self):
        root = QVBoxLayout(self); root.setContentsMargins(32,28,32,20); root.setSpacing(0)
        root.addWidget(_header("Credentials","API keys and email settings — stored in .env"))
        root.addSpacing(18)
        inner = QWidget(); lay = QVBoxLayout(inner); lay.setContentsMargins(0,0,10,0); lay.setSpacing(12)

        em = QGroupBox("EMAIL / SMTP"); ef = QFormLayout(em); ef.setSpacing(10)
        self._field(ef,"GMAIL_USER","Gmail sender address",False)
        self._field(ef,"GMAIL_PASSWORD","App password",True)
        self._field(ef,"RECIPIENT_EMAIL","Recipient address",False)
        lay.addWidget(em)

        k = QGroupBox("LLM API KEYS"); kf = QFormLayout(k); kf.setSpacing(10)
        self._field(kf,"OPENAI_API_KEY","OpenAI",True)
        self._field(kf,"ANTHROPIC_API_KEY","Anthropic",True)
        self._field(kf,"GEMINI_API_KEY","Gemini",True)
        lay.addWidget(k)

        s = QGroupBox("LLM SETTINGS"); sf = QFormLayout(s); sf.setSpacing(10)
        self._field(sf,"LLM_MODEL","Model  (e.g. gpt-4o-mini)",False)
        self._thr.setRange(1,10); self._thr.setValue(6)
        self._thr.setToolTip("Minimum AI score (1–10) to include a job in the email")
        sf.addRow("Match threshold  (1–10)", self._thr)
        lay.addWidget(s); lay.addStretch()

        root.addWidget(_scroll(inner), stretch=1); root.addSpacing(14)
        btn = AnimatedButton("  Save Credentials"); btn.setObjectName("save_btn")
        btn.setFixedHeight(40); btn.clicked.connect(self._save); root.addWidget(btn)

    def _field(self, form, key, label, secret):
        e = QLineEdit(); e.setPlaceholderText(f"Enter {label.lower()}")
        if secret: e.setEchoMode(QLineEdit.Password)
        self._fields[key] = e; form.addRow(label, e)

    def _load(self):
        env = dotenv_values(str(_ENV_FILE)) if _ENV_FILE.exists() else {}
        for k, e in self._fields.items(): e.setText(env.get(k,""))
        try: self._thr.setValue(int(env.get("LLM_MATCH_THRESHOLD","6")))
        except ValueError: pass

    def _save(self):
        if not _ENV_FILE.exists(): _ENV_FILE.touch()
        for k, e in self._fields.items(): set_key(str(_ENV_FILE), k, e.text())
        set_key(str(_ENV_FILE),"LLM_MATCH_THRESHOLD",str(self._thr.value()))
        QMessageBox.information(self,"Saved","Credentials saved to .env")


# ── Page 2 – Configuration ────────────────────────────────────────────────────
class ConfigPage(QWidget):
    def __init__(self):
        super().__init__()
        self._cb_li  = QCheckBox("LinkedIn")
        self._cb_ss  = QCheckBox("StepStone")
        self._cb_ba  = QCheckBox("BA Jobbörse")
        self._lw_li  = QListWidget()
        self._lw_ss  = QListWidget()
        self._lw_ba  = QListWidget()
        self._s_age  = QSpinBox(); self._s_pg = QSpinBox(); self._s_det = QSpinBox()
        self._s_min  = QDoubleSpinBox(); self._s_max = QDoubleSpinBox()
        self._prof   = QPlainTextEdit()
        self._build(); self._load()

    def _build(self):
        root = QVBoxLayout(self); root.setContentsMargins(32,28,32,20); root.setSpacing(0)
        root.addWidget(_header("Configuration",
            "Candidate profile, search queries, platform toggles, scraping parameters"))
        root.addSpacing(18)
        inner = QWidget(); lay = QVBoxLayout(inner); lay.setContentsMargins(0,0,10,0); lay.setSpacing(12)

        pf = QGroupBox("CANDIDATE PROFILE  (PROFILE.md)"); pl = QVBoxLayout(pf)
        self._prof.setPlaceholderText("Paste your CV / skills / preferences here.\nThe AI uses this to evaluate job fit.")
        self._prof.setMinimumHeight(150); pl.addWidget(self._prof); lay.addWidget(pf)

        pt = QGroupBox("ENABLED PLATFORMS"); ptl = QHBoxLayout(pt); ptl.setSpacing(28)
        for cb in (self._cb_li, self._cb_ss, self._cb_ba): ptl.addWidget(cb)
        ptl.addStretch(); lay.addWidget(pt)

        lay.addWidget(self._qgroup("LINKEDIN QUERIES",    self._lw_li))
        lay.addWidget(self._qgroup("STEPSTONE QUERIES",   self._lw_ss))
        lay.addWidget(self._qgroup("BA JOBBÖRSE QUERIES", self._lw_ba))

        sp = QGroupBox("SCRAPING PARAMETERS"); sf = QFormLayout(sp); sf.setSpacing(10)
        self._s_age.setRange(1,168); self._s_age.setSuffix("  h"); sf.addRow("Max posting age", self._s_age)
        self._s_pg.setRange(1,20);  sf.addRow("Pages per query", self._s_pg)
        self._s_det.setRange(1,100); sf.addRow("Max detail pages", self._s_det)
        self._s_min.setRange(0.5,10.0); self._s_min.setSingleStep(0.5); self._s_min.setSuffix("  s"); sf.addRow("Min delay", self._s_min)
        self._s_max.setRange(1.0,20.0); self._s_max.setSingleStep(0.5); self._s_max.setSuffix("  s"); sf.addRow("Max delay", self._s_max)
        lay.addWidget(sp); lay.addStretch()

        root.addWidget(_scroll(inner), stretch=1); root.addSpacing(14)
        btn = AnimatedButton("  Save Configuration"); btn.setObjectName("save_btn")
        btn.setFixedHeight(40); btn.clicked.connect(self._save); root.addWidget(btn)

    @staticmethod
    def _qgroup(title, lw):
        box = QGroupBox(title); bl = QVBoxLayout(box)
        lw.setAlternatingRowColors(True); lw.setFixedHeight(120); bl.addWidget(lw)
        row = QHBoxLayout()
        add = AnimatedButton("+ Add"); add.setObjectName("add_btn")
        rem = AnimatedButton("− Remove"); rem.setObjectName("rem_btn")
        def _a():
            i = QListWidgetItem("New query")
            i.setFlags(i.flags() | i.flags().__class__.ItemIsEditable)
            lw.addItem(i); lw.editItem(i)
        add.clicked.connect(_a)
        rem.clicked.connect(lambda: [lw.takeItem(lw.row(s)) for s in lw.selectedItems()])
        row.addWidget(add); row.addWidget(rem); row.addStretch(); bl.addLayout(row)
        return box

    def _load(self):
        if _PROFILE_FILE.exists(): self._prof.setPlainText(_PROFILE_FILE.read_text(encoding="utf-8"))
        if not _CONFIG_FILE.exists(): return
        t = _CONFIG_FILE.read_text(encoding="utf-8")
        self._cb_li.setChecked(self._b(t,"LINKEDIN_ENABLED",True))
        self._cb_ss.setChecked(self._b(t,"STEPSTONE_ENABLED",True))
        self._cb_ba.setChecked(self._b(t,"BA_ENABLED",True))
        self._s_age.setValue(self._i(t,"MAX_POSTING_AGE_HOURS",36))
        self._s_pg.setValue(self._i(t,"MAX_PAGES_PER_QUERY",2))
        self._s_det.setValue(self._i(t,"MAX_DETAIL_PAGES_PER_QUERY",20))
        self._s_min.setValue(self._f(t,"MIN_DELAY",1.5))
        self._s_max.setValue(self._f(t,"MAX_DELAY",3.5))
        self._fill(self._lw_li, self._lst(t,"LINKEDIN_SEARCH_QUERIES"))
        self._fill(self._lw_ss, self._lst(t,"STEPSTONE_SEARCH_QUERIES"))
        self._fill(self._lw_ba, self._lst(t,"BA_SEARCH_QUERIES"))

    @staticmethod
    def _b(t,v,d):
        m=re.search(rf"^{v}\b[^=\n]*=\s*(\w+)",t,re.M); return m.group(1).lower()=="true" if m else d
    @staticmethod
    def _i(t,v,d):
        m=re.search(rf"^{v}\b[^=\n]*=\s*(\d+)",t,re.M); return int(m.group(1)) if m else d
    @staticmethod
    def _f(t,v,d):
        m=re.search(rf"^{v}\b[^=\n]*=\s*([\d.]+)",t,re.M); return float(m.group(1)) if m else d
    @staticmethod
    def _lst(t,v):
        m=re.search(rf"{v}[^=]*=\s*\[([^\]]*)\]",t,re.DOTALL)
        return re.findall(r'"([^"]+)"',m.group(1)) if m else []
    @staticmethod
    def _fill(lw,items):
        lw.clear()
        for q in items:
            i=QListWidgetItem(q); i.setFlags(i.flags()|i.flags().__class__.ItemIsEditable); lw.addItem(i)

    def _save(self):
        _PROFILE_FILE.write_text(self._prof.toPlainText(), encoding="utf-8")
        if not _CONFIG_FILE.exists(): QMessageBox.warning(self,"Error","config.py not found."); return
        t = _CONFIG_FILE.read_text(encoding="utf-8")
        for v,val in [("LINKEDIN_ENABLED",self._cb_li.isChecked()),("STEPSTONE_ENABLED",self._cb_ss.isChecked()),("BA_ENABLED",self._cb_ba.isChecked())]:
            t = re.sub(rf"^({v}\s*:\s*bool\s*=\s*).*",rf"\g<1>{val}",t,flags=re.M)
        for v,val in [("MAX_POSTING_AGE_HOURS",self._s_age.value()),("MAX_PAGES_PER_QUERY",self._s_pg.value()),("MAX_DETAIL_PAGES_PER_QUERY",self._s_det.value())]:
            t = re.sub(rf"^({v}\s*:\s*int\s*=\s*).*",rf"\g<1>{val}",t,flags=re.M)
        for v,val in [("MIN_DELAY",self._s_min.value()),("MAX_DELAY",self._s_max.value())]:
            t = re.sub(rf"^({v}\s*:\s*float\s*=\s*).*",rf"\g<1>{val}",t,flags=re.M)
        for v,lw in [("LINKEDIN_SEARCH_QUERIES",self._lw_li),("STEPSTONE_SEARCH_QUERIES",self._lw_ss),("BA_SEARCH_QUERIES",self._lw_ba)]:
            items=[lw.item(i).text() for i in range(lw.count()) if lw.item(i).text().strip()]
            body="\n"+"".join(f'    "{q}",\n' for q in items)
            t=re.sub(rf"({v}[^=]*=\s*\[)[^\]]*(\])",rf"\g<1>{body}\g<2>",t,flags=re.DOTALL)
        _CONFIG_FILE.write_text(t, encoding="utf-8")
        QMessageBox.information(self,"Saved","Configuration saved.")


# ── Page 3 – Run Pipeline ─────────────────────────────────────────────────────
class RunPage(QWidget):
    def __init__(self):
        super().__init__()
        self._worker: _RunWorker | None = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self); root.setContentsMargins(32,28,32,24); root.setSpacing(0)
        root.addWidget(_header("Run Pipeline","Scrape  →  AI evaluate  →  Deduplicate  →  Send email"))
        root.addSpacing(20)

        info = QLabel(
            f"<b style='color:#fff'>Python:</b> <span style='color:#4a4a4a;font-family:Consolas'>{_PYTHON}</span><br>"
            f"<b style='color:#fff'>Dir:</b> <span style='color:#4a4a4a;font-family:Consolas'>{_PROJECT_DIR}</span>")
        info.setWordWrap(True); info.setStyleSheet("font-size:11px;")
        root.addWidget(info); root.addSpacing(20)

        row = QHBoxLayout(); row.setSpacing(10)
        self._run = AnimatedButton("▶   Run Now"); self._run.setObjectName("run_btn")
        self._run.setMinimumWidth(150); self._run.clicked.connect(self._do_run)
        self._stop = AnimatedButton("■   Stop"); self._stop.setObjectName("stop_btn")
        self._stop.setMinimumWidth(110); self._stop.setEnabled(False); self._stop.clicked.connect(self._do_stop)
        row.addWidget(self._run); row.addWidget(self._stop); row.addStretch()
        root.addLayout(row); root.addSpacing(12)

        self._status = QLabel(""); self._status.setStyleSheet("font-size:12px;font-weight:500;")
        root.addWidget(self._status); root.addSpacing(10)

        out_row = QHBoxLayout()
        lbl = QLabel("OUTPUT"); lbl.setStyleSheet(f"color:{_C['text3']};font-size:10px;font-weight:600;letter-spacing:1.2px;")
        out_row.addWidget(lbl); out_row.addStretch()
        clr = AnimatedButton("Clear"); clr.setObjectName("clear_btn"); clr.clicked.connect(self._clear)
        out_row.addWidget(clr); root.addLayout(out_row); root.addSpacing(6)

        self._out = QTextEdit(); self._out.setReadOnly(True)
        self._out.setFont(QFont("Consolas", 9))
        self._out.setStyleSheet(
            f"background:rgba(14,14,14,0.95);border:1px solid {_C['border']};"
            f"border-radius:6px;padding:10px;color:{_C['text2']};")
        self._out.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._out, stretch=1)

    def _do_run(self):
        if self._worker and self._worker.isRunning(): return
        self._out.clear(); self._status.setText("Running…")
        self._status.setStyleSheet(f"font-size:12px;font-weight:500;color:{_C['accent']};")
        self._run.setEnabled(False); self._stop.setEnabled(True)
        self._worker = _RunWorker()
        self._worker.line_ready.connect(self._append)
        self._worker.finished.connect(self._done)
        self._worker.start()

    def _do_stop(self):
        if self._worker: self._worker.terminate()
        self._status.setText("Stopped by user.")
        self._status.setStyleSheet(f"font-size:12px;font-weight:500;color:{_C['red']};")
        self._run.setEnabled(True); self._stop.setEnabled(False)

    def _append(self, line):
        self._out.moveCursor(QTextCursor.End); self._out.insertPlainText(line); self._out.moveCursor(QTextCursor.End)

    def _done(self, code):
        self._run.setEnabled(True); self._stop.setEnabled(False)
        if code == 0:
            self._status.setText("Finished successfully  ✓")
            self._status.setStyleSheet(f"font-size:12px;font-weight:500;color:{_C['green']};")
        else:
            self._status.setText(f"Failed  (exit code {code})")
            self._status.setStyleSheet(f"font-size:12px;font-weight:500;color:{_C['red']};")

    def _clear(self): self._out.clear(); self._status.clear()


# ── Main window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Job Agent")
        self.setWindowIcon(_make_icon())
        self.resize(960, 760); self.setMinimumSize(780, 560)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._nav: list[QPushButton] = []
        self._build()

    def showEvent(self, e):
        super().showEvent(e); _apply_win11_acrylic(int(self.winId()))

    def _build(self):
        c = QWidget(); self.setCentralWidget(c)
        lay = QHBoxLayout(c); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        # Sidebar
        sb_frame = QFrame(); sb_frame.setObjectName("sidebar")
        sb_frame.setFixedWidth(215); sb_frame.setAttribute(Qt.WA_StyledBackground, True)
        sb = QVBoxLayout(sb_frame); sb.setContentsMargins(0,0,0,0); sb.setSpacing(0)

        hdr = QWidget(); hdr.setAttribute(Qt.WA_StyledBackground, True)
        hdr.setStyleSheet("background:transparent;")
        hl = QVBoxLayout(hdr); hl.setContentsMargins(20,24,20,18); hl.setSpacing(3)
        ico = QLabel(); ico.setPixmap(_make_icon().pixmap(30,30)); ico.setStyleSheet("background:transparent;")
        hl.addWidget(ico); hl.addSpacing(8)
        nm = QLabel("Job Agent"); nm.setObjectName("app_name")
        tg = QLabel("AI-powered job finder"); tg.setObjectName("app_tag")
        hl.addWidget(nm); hl.addWidget(tg)
        sb.addWidget(hdr); sb.addWidget(_hline()); sb.addSpacing(6)

        self._stack = QStackedWidget()
        for idx, (lbl, page) in enumerate([
            ("🔑   Credentials",   CredentialsPage()),
            ("⚙   Configuration", ConfigPage()),
            ("▶   Run Pipeline",  RunPage()),
        ]):
            self._stack.addWidget(page)
            btn = QPushButton(lbl); btn.setObjectName("nav_btn")
            btn.setProperty("active", idx == 0)
            btn.clicked.connect(lambda _, i=idx: self._go(i))
            sb.addWidget(btn); self._nav.append(btn)

        sb.addStretch(); sb.addWidget(_hline())
        ver = QLabel("v1.0"); ver.setAlignment(Qt.AlignCenter)
        ver.setStyleSheet(f"color:{_C['text3']};font-size:10px;padding:10px;background:transparent;")
        sb.addWidget(ver)

        # Content
        ct = QWidget(); ct.setObjectName("content_bg"); ct.setAttribute(Qt.WA_StyledBackground, True)
        cl = QVBoxLayout(ct); cl.setContentsMargins(0,0,0,0); cl.addWidget(self._stack)

        lay.addWidget(sb_frame); lay.addWidget(ct, stretch=1)

    def _go(self, idx: int):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav):
            btn.setProperty("active", i == idx)
            btn.style().unpolish(btn); btn.style().polish(btn); btn.update()


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setStyleSheet(_make_qss(_ui_font()))
    w = MainWindow(); w.show(); sys.exit(app.exec())


if __name__ == "__main__":
    main()
