#!/usr/bin/env python3
"""
KI Agent Hub — Professionelles KDE Plasma 6 Desktop Control Center
Verwaltet Aider, Open Interpreter, Multi-Agent Workflows, System-Monitoring,
Prompt-Copilot & LLM-Router sowie parallele Modell-Downloads über Ollama.
"""

import sys
import os
import subprocess
import json
import time
import urllib.request
import urllib.error
import re
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QComboBox, QLineEdit, QFileDialog,
    QProgressBar, QCheckBox, QGroupBox, QListWidget, QListWidgetItem,
    QStatusBar, QMessageBox, QFrame, QScrollArea, QGridLayout, QTextEdit
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QClipboard

CONFIG_DIR = Path.home() / ".config" / "ai-agent-hub"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "default_workdir": str(Path.home()),
    "recent_dirs": [str(Path.home()), "/etc/nixos"],
    "terminal": "konsole",
    "ollama_url": "http://127.0.0.1:11434",
    "refresh_seconds": 3,
    "default_copilot_model": "qwen2.5-coder:1.5b"
}

def load_config():
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in data:
                    data[k] = v
            return data
    except Exception:
        return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern der Konfiguration: {e}", file=sys.stderr)


# ============================================================================
# Background Worker: Prompt-Copilot & Modell-Router
# ============================================================================
class CopilotWorker(QThread):
    finished_signal = pyqtSignal(list, str)  # (options_list, error_message)

    def __init__(self, raw_thought, copilot_model, ollama_url):
        super().__init__()
        self.raw_thought = raw_thought
        self.copilot_model = copilot_model
        self.ollama_url = ollama_url.rstrip("/")

    def run(self):
        system_instruction = (
            "Du bist ein erfahrener KI-Systemarchitekt und Prompt-Engineer. "
            "Der Benutzer gibt dir einen rohen Gedanken für eine Software- oder Systemaufgabe. "
            "Erstelle daraus genau 3 präzise, meisterhaft formulierte Handlungsoptionen:\n\n"
            "Option 1: Architektur & Planung (für DeepSeek R1). Analytischer Denk-Prompt für Aider Ask-Modus.\n"
            "Option 2: Direkte Code-Umsetzung (für Qwen 2.5 Coder 32B). Konkrete, technische Anweisung für Aider.\n"
            "Option 3: System- & Shell-Aktion (für Open Interpreter). Praktische Terminal-Befehle / System-Check.\n\n"
            "Antworte als JSON-Objekt mit dem Schlüssel 'options' als Array von 3 Objekten:\n"
            "{\n"
            '  "options": [\n'
            '    {"role": "Architektur & Konzept (DeepSeek R1)", "model": "deepseek-r1:14b", "tool": "aider-ask", "prompt": "..."},\n'
            '    {"role": "Direkte Code-Umsetzung (Qwen 32B)", "model": "qwen2.5-coder:32b", "tool": "aider", "prompt": "..."},\n'
            '    {"role": "PC- & Terminal-Aktion (Open Interpreter)", "model": "qwen2.5-coder:14b", "tool": "oi", "prompt": "..."}\n'
            "  ]\n"
            "}"
        )

        prompt = f"{system_instruction}\n\nRoher Gedanke des Nutzers:\n\"{self.raw_thought}\""
        payload = json.dumps({
            "model": self.copilot_model,
            "prompt": prompt,
            "format": "json",
            "stream": False
        }).encode("utf-8")

        url = f"{self.ollama_url}/api/generate"
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                resp_text = data.get("response", "")
                parsed = json.loads(resp_text)
                options = []
                if isinstance(parsed, dict) and "options" in parsed:
                    options = parsed["options"]
                elif isinstance(parsed, list):
                    options = parsed
                elif isinstance(parsed, dict):
                    options = [parsed]
                self.finished_signal.emit(options, "")
        except Exception as e:
            self.finished_signal.emit([], str(e))


# ============================================================================
# Background Worker für Streaming-Downloads via Ollama API
# ============================================================================
class ModelPullWorker(QThread):
    progress_signal = pyqtSignal(str, float, str, str)  # (model_name, percent, speed_text, status_text)
    finished_signal = pyqtSignal(str, bool, str)        # (model_name, success, error_message)

    def __init__(self, model_name, ollama_url):
        super().__init__()
        self.model_name = model_name
        self.ollama_url = ollama_url.rstrip("/")
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        url = f"{self.ollama_url}/api/pull"
        payload = json.dumps({"name": self.model_name, "stream": True}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

        last_bytes = 0
        last_time = time.time()
        speed_text = ""

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                for line in resp:
                    if self._is_cancelled:
                        self.finished_signal.emit(self.model_name, False, "Abgebrochen durch Benutzer")
                        return

                    if not line:
                        continue
                    try:
                        data = json.loads(line.decode("utf-8"))
                    except Exception:
                        continue

                    status = data.get("status", "")
                    total = data.get("total", 0)
                    completed = data.get("completed", 0)

                    pct = 0.0
                    if total > 0:
                        pct = (completed / total) * 100.0

                        now = time.time()
                        dt = now - last_time
                        if dt >= 0.8:
                            diff_bytes = completed - last_bytes
                            speed_mb = (diff_bytes / dt) / (1024 * 1024)
                            if speed_mb >= 0:
                                speed_text = f"{speed_mb:.1f} MB/s"
                            last_bytes = completed
                            last_time = now

                        comp_gb = completed / (1024 * 1024 * 1024)
                        tot_gb = total / (1024 * 1024 * 1024)
                        status_detail = f"{status} • {comp_gb:.1f} GB / {tot_gb:.1f} GB"
                    else:
                        status_detail = status

                    self.progress_signal.emit(self.model_name, pct, speed_text, status_detail)

            if not self._is_cancelled:
                self.finished_signal.emit(self.model_name, True, "Erfolgreich geladen!")
        except Exception as e:
            if not self._is_cancelled:
                self.finished_signal.emit(self.model_name, False, str(e))


# ============================================================================
# Widget für einen einzelnen Download-Eintrag in der Liste
# ============================================================================
class DownloadItemWidget(QFrame):
    cancel_requested = pyqtSignal(str)

    def __init__(self, model_name):
        super().__init__()
        self.model_name = model_name
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            DownloadItemWidget {
                background-color: #272a2e;
                border: 1px solid #3daee9;
                border-radius: 8px;
                padding: 8px;
                margin-bottom: 6px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        h_row = QHBoxLayout()
        self.lbl_title = QLabel(f"📦 <b>{model_name}</b>")
        self.lbl_title.setStyleSheet("font-size: 14px; color: #eff0f1;")

        self.lbl_speed = QLabel("")
        self.lbl_speed.setStyleSheet("color: #3daee9; font-weight: bold;")

        self.btn_cancel = QPushButton("✖ Abbrechen")
        self.btn_cancel.setStyleSheet("background-color: #c0392b; color: white; padding: 4px 10px; font-size: 11px;")
        self.btn_cancel.clicked.connect(lambda: self.cancel_requested.emit(self.model_name))

        h_row.addWidget(self.lbl_title, stretch=1)
        h_row.addWidget(self.lbl_speed)
        h_row.addWidget(self.btn_cancel)
        layout.addLayout(h_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #31363b;
                border-radius: 5px;
                background-color: #1a1c1e;
                text-align: center;
                height: 18px;
                font-weight: bold;
                color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: #2980b9;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Warte auf Download...")
        self.lbl_status.setStyleSheet("color: #95a5a6; font-size: 11px;")
        layout.addWidget(self.lbl_status)

    def update_progress(self, percent, speed_text, status_text):
        self.progress_bar.setValue(int(percent))
        if speed_text:
            self.lbl_speed.setText(speed_text)
        self.lbl_status.setText(status_text)

    def set_finished(self, success, message):
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setText("Fertig" if success else "Fehlgeschlagen")
        if success:
            self.progress_bar.setValue(100)
            self.progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #27ae60; }")
            self.lbl_speed.setText("✔ Fertig")
            self.lbl_speed.setStyleSheet("color: #2ecc71; font-weight: bold;")
            self.lbl_status.setText("Erfolgreich installiert!")
            self.lbl_status.setStyleSheet("color: #2ecc71; font-size: 11px;")
        else:
            self.progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #c0392b; }")
            self.lbl_speed.setText("Fehler")
            self.lbl_speed.setStyleSheet("color: #e74c3c; font-weight: bold;")
            self.lbl_status.setText(message)
            self.lbl_status.setStyleSheet("color: #e74c3c; font-size: 11px;")


# ============================================================================
# Hauptfenster: KI Agent Hub
# ============================================================================
class AIAgentHub(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🤖 KI Agent Hub — KDE Plasma Control Center")
        self.setMinimumSize(960, 750)
        self.config = load_config()

        self.active_workers = {}
        self.download_widgets = {}
        self.copilot_worker = None

        self.init_ui()
        self.apply_theme()
        self.refresh_all()

        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self.refresh_ram)
        self.monitor_timer.start(int(self.config.get("refresh_seconds", 3)) * 1000)

    def apply_theme(self):
        dark_qss = """
        QMainWindow, QWidget {
            background-color: #1e2022;
            color: #eff0f1;
            font-family: 'Noto Sans', 'Segoe UI', sans-serif;
            font-size: 13px;
        }
        QGroupBox {
            border: 1px solid #31363b;
            border-radius: 8px;
            margin-top: 1.2em;
            padding-top: 12px;
            font-weight: bold;
            color: #3daee9;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 6px;
        }
        QTabWidget::pane {
            border: 1px solid #31363b;
            border-radius: 8px;
            background-color: #232629;
            padding: 14px;
        }
        QTabBar::tab {
            background: #1a1c1e;
            color: #bdc3c7;
            padding: 10px 18px;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            margin-right: 4px;
            font-weight: 500;
        }
        QTabBar::tab:selected {
            background: #232629;
            color: #3daee9;
            border-bottom: 2px solid #3daee9;
            font-weight: bold;
        }
        QTabBar::tab:hover {
            color: #ffffff;
            background: #272a2e;
        }
        QPushButton {
            background-color: #2d3238;
            border: 1px solid #3daee9;
            border-radius: 6px;
            color: #eff0f1;
            padding: 8px 16px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #3daee9;
            color: #ffffff;
        }
        QPushButton:pressed {
            background-color: #1d99f3;
        }
        QComboBox, QLineEdit, QTextEdit {
            background-color: #181a1c;
            border: 1px solid #31363b;
            border-radius: 6px;
            padding: 6px 12px;
            color: #eff0f1;
        }
        QComboBox:focus, QLineEdit:focus, QTextEdit:focus {
            border: 1px solid #3daee9;
        }
        QProgressBar {
            border: 1px solid #31363b;
            border-radius: 6px;
            text-align: center;
            background-color: #181a1c;
            color: #ffffff;
            font-weight: bold;
            height: 22px;
        }
        QProgressBar::chunk {
            background-color: #27ae60;
            border-radius: 5px;
        }
        QStatusBar {
            background-color: #181a1c;
            color: #7f8c8d;
        }
        """
        self.setStyleSheet(dark_qss)

    def init_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(14, 14, 14, 14)

        # 1. HEADER: Hardware & Live RAM Monitor
        header_group = QGroupBox("⚡ System & Hardware Dashboard (AMD Ryzen 9 7900X3D • 64 GB DDR5)")
        header_layout = QVBoxLayout(header_group)
        header_layout.setSpacing(8)

        ram_row = QHBoxLayout()
        self.lbl_ram = QLabel("Arbeitsspeicher:")
        self.lbl_ram.setFixedWidth(120)
        self.bar_ram = QProgressBar()
        self.bar_ram.setRange(0, 100)
        self.bar_ram.setValue(20)

        self.btn_free_ram = QPushButton("🧹 RAM freigeben")
        self.btn_free_ram.setToolTip("Entlädt alle ruhenden Modelle aus dem Arbeitsspeicher")
        self.btn_free_ram.clicked.connect(self.action_free_ram)

        self.btn_refresh = QPushButton("🔄 Aktualisieren")
        self.btn_refresh.clicked.connect(self.refresh_all)

        ram_row.addWidget(self.lbl_ram)
        ram_row.addWidget(self.bar_ram, stretch=1)
        ram_row.addWidget(self.btn_free_ram)
        ram_row.addWidget(self.btn_refresh)
        header_layout.addLayout(ram_row)

        info_row = QHBoxLayout()
        self.lbl_active_models = QLabel("Geladene Modelle im RAM: Keine")
        self.lbl_active_models.setStyleSheet("color: #27ae60; font-size: 12px;")
        self.lbl_server_status = QLabel("🟢 Ollama Server: Online")
        self.lbl_server_status.setStyleSheet("color: #2ecc71; font-weight: bold; font-size: 12px;")
        info_row.addWidget(self.lbl_active_models, stretch=1)
        info_row.addWidget(self.lbl_server_status)
        header_layout.addLayout(info_row)

        main_layout.addWidget(header_group)

        # 2. TABS
        self.tabs = QTabWidget()

        # TAB 1: PROMPT-COPILOT & ROUTER (Neu & Im Fokus!)
        self.tabs.addTab(self.create_tab_copilot(), "🧠 Prompt-Copilot & Router")

        # TAB 2: AIDER (Coding Agent)
        self.tabs.addTab(self.create_tab_aider(), "💻 Coding Agent (Aider)")

        # TAB 3: OPEN INTERPRETER (OS & Admin)
        self.tabs.addTab(self.create_tab_oi(), "🐧 OS & Admin (Open Interpreter)")

        # TAB 4: SELF-DEV (Tuning)
        self.tabs.addTab(self.create_tab_self_dev(), "🛠️ Self-Dev (Tuning)")

        # TAB 5: MULTI-AGENT WORKFLOWS
        self.tabs.addTab(self.create_tab_multi_agent(), "👥 Multi-Agent (Parallel)")

        # TAB 6: DOWNLOADER & MULTI-DOWNLOAD
        self.tabs.addTab(self.create_tab_downloader(), "📥 Modell-Downloader & Queue")

        # TAB 7: EINSTELLUNGEN & PFADE
        self.tabs.addTab(self.create_tab_settings(), "⚙️ Pfade & Optionen")

        main_layout.addWidget(self.tabs)
        self.setCentralWidget(main_widget)

        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Bereit")

    # =========================================================================
    # TAB 1: Prompt-Copilot & LLM-Router
    # =========================================================================
    def create_tab_copilot(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        info = QLabel(
            "🧠 <b>Gedanken- & Prompt-Helfer (Schnell-Analyse via lokalem LLM)</b><br>"
            "Schreib einfach drauflos, was du im Kopf hast. Ein schlankes, schnelles Modell analysiert deinen Gedanken "
            "und formuliert 3 geschärfte Handlungsvorschläge für die passenden Spezial-Modelle aus!"
        )
        info.setStyleSheet("color: #3daee9; padding: 4px; font-size: 12px;")
        layout.addWidget(info)

        # Copilot-Modell Auswählen
        copilot_model_group = QGroupBox("⚡ Denk- & Router-Modell (Leichtgewicht für Sofort-Antwort)")
        copilot_m_layout = QHBoxLayout(copilot_model_group)

        copilot_m_layout.addWidget(QLabel("Router-Modell:"))
        self.combo_copilot_model = QComboBox()
        copilot_m_layout.addWidget(self.combo_copilot_model, stretch=1)

        btn_apply_default = QPushButton("Als Standard speichern")
        btn_apply_default.clicked.connect(self.save_default_copilot_model)
        copilot_m_layout.addWidget(btn_apply_default)
        layout.addWidget(copilot_model_group)

        # Eingabefeld für rohe Gedanken
        thought_group = QGroupBox("📝 Dein roher Gedanke / Ziel")
        thought_layout = QVBoxLayout(thought_group)

        self.txt_raw_thought = QTextEdit()
        self.txt_raw_thought.setPlaceholderText(
            "Beispiel: Ich möchte, dass der Launcher farbige Boxen hat, beim Start prüft, "
            "ob die GPU-Treiber richtig geladen sind, und mir die GPU-Temperatur anzeigt."
        )
        self.txt_raw_thought.setMaximumHeight(85)
        thought_layout.addWidget(self.txt_raw_thought)

        btn_row = QHBoxLayout()
        self.btn_analyze_thought = QPushButton("⚡ Gedanken analysieren & Optionen generieren")
        self.btn_analyze_thought.setStyleSheet("background-color: #8e44ad; color: white; font-size: 13px; padding: 9px;")
        self.btn_analyze_thought.clicked.connect(self.action_analyze_thought)
        btn_row.addWidget(self.btn_analyze_thought, stretch=1)

        self.lbl_copilot_status = QLabel("")
        self.lbl_copilot_status.setStyleSheet("color: #f39c12; font-weight: bold;")
        btn_row.addWidget(self.lbl_copilot_status)
        thought_layout.addLayout(btn_row)

        layout.addWidget(thought_group)

        # Ergebnis-Bereich (Dynamische Karten)
        results_group = QGroupBox("💡 Generierte Vorschläge & Routen (Mit 1 Klick starten)")
        results_layout = QVBoxLayout(results_group)

        self.scroll_copilot = QScrollArea()
        self.scroll_copilot.setWidgetResizable(True)
        self.scroll_copilot_content = QWidget()
        self.copilot_cards_layout = QVBoxLayout(self.scroll_copilot_content)
        self.copilot_cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_copilot.setWidget(self.scroll_copilot_content)

        # Platzhalter Text
        self.lbl_placeholder = QLabel("Hier erscheinen nach Klick auf 'Analysieren' deine geschärften Prompts mit passenden Modell-Buttons.")
        self.lbl_placeholder.setStyleSheet("color: #7f8c8d; padding: 20px; font-style: italic;")
        self.lbl_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.copilot_cards_layout.addWidget(self.lbl_placeholder)

        results_layout.addWidget(self.scroll_copilot)
        layout.addWidget(results_group, stretch=1)

        return tab

    def save_default_copilot_model(self):
        m = self.combo_copilot_model.currentData()
        if m:
            self.config["default_copilot_model"] = m
            save_config(self.config)
            self.statusBar.showMessage(f"Standard-Copilot-Modell gespeichert: {m}", 3000)

    def action_analyze_thought(self):
        thought = self.txt_raw_thought.toPlainText().strip()
        if not thought:
            QMessageBox.information(self, "Eingabe leer", "Bitte gib zuerst einen Gedanken oder Wunsch ein!")
            return

        model = self.combo_copilot_model.currentData() or "qwen2.5-coder:1.5b"
        ollama_url = self.config.get("ollama_url", "http://127.0.0.1:11434")

        self.btn_analyze_thought.setEnabled(False)
        self.lbl_copilot_status.setText("⏳ Modell denkt & schärft Prompts...")

        self.copilot_worker = CopilotWorker(thought, model, ollama_url)
        self.copilot_worker.finished_signal.connect(self.on_copilot_finished)
        self.copilot_worker.start()

    def on_copilot_finished(self, options, error_msg):
        self.btn_analyze_thought.setEnabled(True)
        self.lbl_copilot_status.setText("")

        if error_msg:
            QMessageBox.warning(self, "Fehler", f"Copilot-Anfrage fehlgeschlagen:\n{error_msg}")
            return

        # Alte Karten leeren
        while self.copilot_cards_layout.count():
            item = self.copilot_cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not options:
            lbl = QLabel("Konnte keine strukturierten Vorschläge parsen. Bitte formuliere den Gedanken etwas genauer.")
            lbl.setStyleSheet("color: #e74c3c; padding: 10px;")
            self.copilot_cards_layout.addWidget(lbl)
            return

        # Karten für jede Option rendern
        for idx, opt in enumerate(options):
            card = self.create_copilot_card(idx + 1, opt)
            self.copilot_cards_layout.addWidget(card)

        self.statusBar.showMessage("3 Handlungsoptionen erfolgreich generiert!", 4000)

    def create_copilot_card(self, num, opt):
        role = opt.get("role") or opt.get("title") or f"Option {num}"
        rec_model = opt.get("model", "qwen2.5-coder:32b")
        tool = opt.get("tool", "aider")
        prompt_text = opt.get("prompt", "")

        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setStyleSheet("""
            QFrame {
                background-color: #272a2e;
                border: 1px solid #3daee9;
                border-radius: 8px;
                padding: 10px;
                margin-bottom: 10px;
            }
        """)
        layout = QVBoxLayout(card)
        layout.setSpacing(8)

        # Header: Titel & Modell-Wahl
        h_row = QHBoxLayout()
        lbl_role = QLabel(f"<b>Option {num}: {role}</b>")
        lbl_role.setStyleSheet("font-size: 14px; color: #3daee9;")
        h_row.addWidget(lbl_role, stretch=1)

        h_row.addWidget(QLabel("Ziel-Modell:"))
        combo_target_model = QComboBox()
        # Vorhandene Modelle einfügen
        for i in range(self.combo_aider_model.count()):
            m_name = self.combo_aider_model.itemText(i)
            m_data = self.combo_aider_model.itemData(i)
            combo_target_model.addItem(m_name, m_data)

        # Empfohlenes Modell auswählen
        idx = combo_target_model.findData(rec_model)
        if idx >= 0:
            combo_target_model.setCurrentIndex(idx)
        h_row.addWidget(combo_target_model)
        layout.addLayout(h_row)

        # Editierbarer Prompt-Text
        txt_prompt = QTextEdit()
        txt_prompt.setPlainText(prompt_text)
        txt_prompt.setMaximumHeight(85)
        layout.addWidget(txt_prompt)

        # Buttons: Starten & Kopieren
        b_row = QHBoxLayout()
        btn_copy = QPushButton("📋 Prompt kopieren")
        btn_copy.setFixedWidth(130)
        btn_copy.clicked.connect(lambda: self.copy_to_clipboard(txt_prompt.toPlainText()))
        b_row.addWidget(btn_copy)

        btn_run = QPushButton(f"🚀 Mit {role.split('(')[0].strip()} starten")
        btn_run.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 7px;")
        btn_run.clicked.connect(lambda: self.launch_from_copilot(tool, combo_target_model.currentData(), txt_prompt.toPlainText()))
        b_row.addWidget(btn_run, stretch=1)

        layout.addLayout(b_row)
        return card

    def copy_to_clipboard(self, text):
        QApplication.clipboard().setText(text)
        self.statusBar.showMessage("Prompt in die Zwischenablage kopiert!", 3000)

    def launch_from_copilot(self, tool, model, prompt):
        clean_prompt = prompt.replace('"', '\\"').replace("'", "\\'")
        if tool == "oi":
            cmd = f'interpreter --model ollama/{model} --message "{clean_prompt}"'
            self.run_in_terminal(cmd)
        elif tool == "aider-ask":
            workdir = self.combo_recent_dirs.currentText().strip() or str(Path.home())
            cmd = f'aider --model ollama/{model} --chat-mode ask --message "{clean_prompt}"'
            self.run_in_terminal(cmd, workdir=workdir)
        else:
            workdir = self.combo_recent_dirs.currentText().strip() or str(Path.home())
            cmd = f'aider --model ollama/{model} --message "{clean_prompt}"'
            self.run_in_terminal(cmd, workdir=workdir)

    # =========================================================================
    # TAB 2: Aider Coding Agent
    # =========================================================================
    def create_tab_aider(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)

        dir_group = QGroupBox("📁 Projekt-Verzeichnis (Git Repository)")
        dir_layout = QVBoxLayout(dir_group)

        row_picker = QHBoxLayout()
        self.combo_recent_dirs = QComboBox()
        self.combo_recent_dirs.setEditable(True)
        for d in self.config.get("recent_dirs", []):
            self.combo_recent_dirs.addItem(d)
        self.combo_recent_dirs.currentTextChanged.connect(self.check_git_status)

        btn_browse = QPushButton("📂 Durchsuchen...")
        btn_browse.clicked.connect(self.browse_aider_dir)

        row_picker.addWidget(self.combo_recent_dirs, stretch=1)
        row_picker.addWidget(btn_browse)
        dir_layout.addLayout(row_picker)

        self.lbl_git_status = QLabel("Prüfe Git...")
        self.lbl_git_status.setStyleSheet("color: #f39c12; font-size: 11px;")
        dir_layout.addWidget(self.lbl_git_status)
        layout.addWidget(dir_group)

        model_group = QGroupBox("🧠 Modell & Arbeitsweise")
        model_layout = QVBoxLayout(model_group)

        m_row = QHBoxLayout()
        m_row.addWidget(QLabel("KI-Modell:"))
        self.combo_aider_model = QComboBox()
        m_row.addWidget(self.combo_aider_model, stretch=1)
        model_layout.addLayout(m_row)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Modus:"))
        self.combo_aider_mode = QComboBox()
        self.combo_aider_mode.addItem("⚡ Standard (Code schreiben, Refactoring, Git-Commits)", "")
        self.combo_aider_mode.addItem("🏛️ Architect Mode (Planung & Code getrennt)", "--architect")
        self.combo_aider_mode.addItem("💬 Nur Fragen / Diskutieren (/ask, keine Dateiedits)", "--chat-mode ask")
        mode_row.addWidget(self.combo_aider_mode, stretch=1)
        model_layout.addLayout(mode_row)

        self.chk_aider_auto_commit = QCheckBox("Git-Commits nach jedem Änderungsschritt automatisch anlegen")
        self.chk_aider_auto_commit.setChecked(True)
        model_layout.addWidget(self.chk_aider_auto_commit)

        layout.addWidget(model_group)

        btn_row = QHBoxLayout()
        btn_start = QPushButton("🚀 Aider in neuem Fenster starten")
        btn_start.setStyleSheet("background-color: #27ae60; color: white; font-size: 14px; padding: 10px;")
        btn_start.clicked.connect(lambda: self.launch_aider(in_tab=False))

        btn_start_tab = QPushButton("📑 In neuem Konsole-Tab starten")
        btn_start_tab.setStyleSheet("padding: 10px;")
        btn_start_tab.clicked.connect(lambda: self.launch_aider(in_tab=True))

        btn_row.addWidget(btn_start, stretch=2)
        btn_row.addWidget(btn_start_tab, stretch=1)
        layout.addLayout(btn_row)
        layout.addStretch()

        return tab

    # =========================================================================
    # TAB 3: Open Interpreter
    # =========================================================================
    def create_tab_oi(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)

        info = QLabel("Open Interpreter ist dein persönlicher System-Administrator.\n"
                     "Er führt Shell-Befehle, Python-Skripte und NixOS-Aufgaben interaktiv auf deinem System aus.")
        info.setStyleSheet("color: #3daee9; padding: 6px;")
        layout.addWidget(info)

        m_group = QGroupBox("🧠 Modell & Ausführung")
        m_layout = QVBoxLayout(m_group)

        row = QHBoxLayout()
        row.addWidget(QLabel("KI-Modell:"))
        self.combo_oi_model = QComboBox()
        row.addWidget(self.combo_oi_model, stretch=1)
        m_layout.addLayout(row)

        self.chk_oi_auto = QCheckBox("⚡ Auto-Run (-y): Befehle ohne manuelle [y/n]-Bestätigung direkt ausführen")
        self.chk_oi_auto.setStyleSheet("color: #e67e22; font-weight: bold;")
        m_layout.addWidget(self.chk_oi_auto)
        layout.addWidget(m_group)

        btn_start = QPushButton("🤖 Open Interpreter starten")
        btn_start.setStyleSheet("background-color: #2980b9; color: white; font-size: 14px; padding: 10px;")
        btn_start.clicked.connect(self.launch_oi)
        layout.addWidget(btn_start)
        layout.addStretch()

        return tab

    # =========================================================================
    # TAB 4: Self-Dev Modus
    # =========================================================================
    def create_tab_self_dev(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)

        info = QLabel("🛠️ Self-Dev: Verbessere diesen Launcher oder dein NixOS-System direkt per Sprachbefehl!\n"
                     "Aider lädt die gewählten Systemdateien in den Chat. Sag einfach: 'Ändere die Farben' oder 'Füge Feature X hinzu'.")
        info.setStyleSheet("color: #e056fd; font-weight: bold; padding: 6px;")
        layout.addWidget(info)

        files_group = QGroupBox("📁 Vorab geladene Dateien für Aider")
        files_layout = QVBoxLayout(files_group)
        self.chk_self_gui = QCheckBox("/etc/nixos/ai-agent-hub.py (Diese Desktop-GUI selbst!)")
        self.chk_self_gui.setChecked(True)
        self.chk_self_launcher = QCheckBox("/etc/nixos/aider-launcher.pl (Perl Terminal Launcher)")
        self.chk_self_launcher.setChecked(True)
        self.chk_self_ainix = QCheckBox("/etc/nixos/ai.nix (NixOS AI-Konfiguration)")
        self.chk_self_ainix.setChecked(True)
        self.chk_self_config = QCheckBox("/etc/nixos/configuration.nix (Gesamtes NixOS System)")

        files_layout.addWidget(self.chk_self_gui)
        files_layout.addWidget(self.chk_self_launcher)
        files_layout.addWidget(self.chk_self_ainix)
        files_layout.addWidget(self.chk_self_config)
        layout.addWidget(files_group)

        m_row = QHBoxLayout()
        m_row.addWidget(QLabel("KI-Modell (Empfehlung: Qwen 32B oder DeepSeek R1):"))
        self.combo_self_model = QComboBox()
        m_row.addWidget(self.combo_self_model, stretch=1)
        layout.addLayout(m_row)

        btn_start = QPushButton("🛠️ Self-Dev Sitzung starten")
        btn_start.setStyleSheet("background-color: #8e44ad; color: white; font-size: 14px; padding: 10px;")
        btn_start.clicked.connect(self.launch_self_dev)
        layout.addWidget(btn_start)
        layout.addStretch()

        return tab

    # =========================================================================
    # TAB 5: Multi-Agent Parallel Workflows
    # =========================================================================
    def create_tab_multi_agent(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)

        info = QLabel("🚀 Parallele Agenten-Workflows (Nutzt alle 24 CPU-Threads & 64 GB DDR5 RAM)")
        info.setStyleSheet("color: #f39c12; font-weight: bold; font-size: 14px;")
        layout.addWidget(info)

        btn_duo = QPushButton("👥 Duo-Modus: Aider (Coding) + Open Interpreter (System) in 2 Tabs")
        btn_duo.setStyleSheet("background-color: #d35400; color: white; padding: 12px; font-size: 13px;")
        btn_duo.clicked.connect(self.launch_duo)
        layout.addWidget(btn_duo)

        btn_thinker = QPushButton("🧠 Coder & Architekt: Qwen 32B (Editor) + DeepSeek R1 (Planung) in 2 Tabs")
        btn_thinker.setStyleSheet("background-color: #16a085; color: white; padding: 12px; font-size: 13px;")
        btn_thinker.clicked.connect(self.launch_thinker_duo)
        layout.addWidget(btn_thinker)

        btn_split = QPushButton("🔀 Split-Work: 2x Aider parallel für 2 unterschiedliche Projekte")
        btn_split.setStyleSheet("background-color: #2c3e50; color: white; padding: 12px; font-size: 13px;")
        btn_split.clicked.connect(self.launch_split_aider)
        layout.addWidget(btn_split)

        layout.addStretch()
        return tab

    # =========================================================================
    # TAB 6: Modell-Downloader & Multi-Download Queue
    # =========================================================================
    def create_tab_downloader(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        custom_group = QGroupBox("➕ Beliebiges Modell herunterladen")
        custom_layout = QHBoxLayout(custom_group)
        self.txt_custom_model = QLineEdit()
        self.txt_custom_model.setPlaceholderText("z. B. deepseek-r1:32b, codellama:13b oder hf.co/author/model")
        btn_add_pull = QPushButton("📥 Zur Download-Warteschlange")
        btn_add_pull.clicked.connect(self.action_add_custom_pull)
        custom_layout.addWidget(self.txt_custom_model, stretch=1)
        custom_layout.addWidget(btn_add_pull)
        layout.addWidget(custom_group)

        preset_group = QGroupBox("🌟 Beliebte Modelle (1-Klick-Download)")
        preset_layout = QGridLayout(preset_group)
        preset_layout.setSpacing(8)

        self.presets = [
            ("qwen2.5-coder:32b", "Qwen 2.5 Coder 32B (19 GB) — Coding-König"),
            ("deepseek-r1:14b", "DeepSeek R1 14B (9.0 GB) — Top Reasoning"),
            ("deepseek-r1:32b", "DeepSeek R1 32B (19 GB) — Tiefes Denken"),
            ("qwen2.5-coder:14b", "Qwen 2.5 Coder 14B (9.0 GB) — Allrounder"),
            ("qwen2.5-coder:7b", "Qwen 2.5 Coder 7B (4.7 GB) — Schnell"),
            ("llama3.3:70b", "Llama 3.3 70B (42 GB) — Monster-Modell (64GB RAM)")
        ]

        self.preset_buttons = {}
        for idx, (m_id, label) in enumerate(self.presets):
            row = idx // 2
            col = idx % 2
            h = QHBoxLayout()
            lbl = QLabel(label)
            btn = QPushButton("📥 Laden")
            btn.setFixedWidth(90)
            btn.clicked.connect(lambda checked, m=m_id: self.start_download(m))
            h.addWidget(lbl, stretch=1)
            h.addWidget(btn)
            self.preset_buttons[m_id] = btn
            preset_layout.addLayout(h, row, col)

        layout.addWidget(preset_group)

        queue_group = QGroupBox("📊 Aktive & abgeschlossene Downloads")
        queue_layout = QVBoxLayout(queue_group)

        self.scroll_queue = QScrollArea()
        self.scroll_queue.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.queue_items_layout = QVBoxLayout(self.scroll_content)
        self.queue_items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_queue.setWidget(self.scroll_content)

        queue_layout.addWidget(self.scroll_queue)
        layout.addWidget(queue_group, stretch=1)

        return tab

    # =========================================================================
    # TAB 7: Einstellungen & Pfade
    # =========================================================================
    def create_tab_settings(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)

        group = QGroupBox("⚙️ Pfade & Integration")
        g_layout = QVBoxLayout(group)

        term_row = QHBoxLayout()
        term_row.addWidget(QLabel("Terminal-Emulator:"))
        self.combo_term = QComboBox()
        self.combo_term.addItems(["konsole", "alacritty", "kitty", "xterm"])
        term_row.addWidget(self.combo_term, stretch=1)
        g_layout.addLayout(term_row)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("Ollama Server URL:"))
        self.txt_ollama_url = QLineEdit(self.config.get("ollama_url", "http://127.0.0.1:11434"))
        url_row.addWidget(self.txt_ollama_url, stretch=1)
        g_layout.addLayout(url_row)

        ref_row = QHBoxLayout()
        ref_row.addWidget(QLabel("RAM-Monitor Intervall (Sekunden):"))
        self.txt_refresh = QLineEdit(str(self.config.get("refresh_seconds", 3)))
        ref_row.addWidget(self.txt_refresh, stretch=1)
        g_layout.addLayout(ref_row)

        layout.addWidget(group)

        btn_save = QPushButton("💾 Einstellungen speichern")
        btn_save.setStyleSheet("background-color: #27ae60; color: white; padding: 10px;")
        btn_save.clicked.connect(self.save_settings)
        layout.addWidget(btn_save)
        layout.addStretch()

        return tab

    # =========================================================================
    # Download Logik
    # =========================================================================
    def action_add_custom_pull(self):
        model = self.txt_custom_model.text().strip()
        if not model:
            return
        self.txt_custom_model.clear()
        self.start_download(model)

    def start_download(self, model_name):
        if model_name in self.active_workers and self.active_workers[model_name].isRunning():
            QMessageBox.information(self, "Download läuft", f"Modell '{model_name}' lädt bereits!")
            return

        ollama_url = self.config.get("ollama_url", "http://127.0.0.1:11434")

        item_widget = DownloadItemWidget(model_name)
        item_widget.cancel_requested.connect(self.cancel_download)
        self.download_widgets[model_name] = item_widget
        self.queue_items_layout.addWidget(item_widget)

        worker = ModelPullWorker(model_name, ollama_url)
        worker.progress_signal.connect(self.on_download_progress)
        worker.finished_signal.connect(self.on_download_finished)
        self.active_workers[model_name] = worker
        worker.start()

        self.statusBar.showMessage(f"Download gestartet: {model_name}")

    def cancel_download(self, model_name):
        if model_name in self.active_workers:
            self.active_workers[model_name].cancel()
            self.statusBar.showMessage(f"Download abgebrochen: {model_name}")

    def on_download_progress(self, model_name, percent, speed_text, status_text):
        if model_name in self.download_widgets:
            self.download_widgets[model_name].update_progress(percent, speed_text, status_text)

    def on_download_finished(self, model_name, success, message):
        if model_name in self.download_widgets:
            self.download_widgets[model_name].set_finished(success, message)
        self.refresh_all()

    # =========================================================================
    # Terminal Launches
    # =========================================================================
    def browse_aider_dir(self):
        current = self.combo_recent_dirs.currentText() or str(Path.home())
        d = QFileDialog.getExistingDirectory(self, "Projektverzeichnis wählen", current)
        if d:
            self.combo_recent_dirs.setEditText(d)
            self.check_git_status(d)

    def check_git_status(self, path):
        path = path.strip()
        if not os.path.isdir(path):
            self.lbl_git_status.setText("Ordner existiert nicht")
            self.lbl_git_status.setStyleSheet("color: #e74c3c;")
            return

        git_dir = os.path.join(path, ".git")
        if os.path.exists(git_dir):
            try:
                branch = subprocess.check_output(["git", "-C", path, "branch", "--show-current"], text=True).strip()
                self.lbl_git_status.setText(f"✔ Git Repository erkannt (Branch: {branch or 'master'})")
                self.lbl_git_status.setStyleSheet("color: #2ecc71;")
            except Exception:
                self.lbl_git_status.setText("✔ Git Repository erkannt")
                self.lbl_git_status.setStyleSheet("color: #2ecc71;")
        else:
            self.lbl_git_status.setText("ℹ Kein Git-Repository (Aider kann auf Wunsch eines anlegen)")
            self.lbl_git_status.setStyleSheet("color: #95a5a6;")

    def add_recent_dir(self, d):
        recents = self.config.get("recent_dirs", [])
        if d in recents:
            recents.remove(d)
        recents.insert(0, d)
        self.config["recent_dirs"] = recents[:8]
        save_config(self.config)

    def run_in_terminal(self, cmd, workdir=None, in_tab=False):
        workdir = workdir or str(Path.home())
        term = self.config.get("terminal", "konsole")

        args = [term]
        if term == "konsole":
            if in_tab:
                args.append("--new-tab")
            args.extend(["--workdir", workdir, "-e", "bash", "-c", cmd])
        else:
            args.extend(["-e", "bash", "-c", f"cd '{workdir}' && {cmd}"])

        subprocess.Popen(args)
        self.statusBar.showMessage(f"Gestartet in {term}...", 3000)

    def launch_aider(self, in_tab=False):
        model = self.combo_aider_model.currentData() or "qwen2.5-coder:14b"
        workdir = self.combo_recent_dirs.currentText().strip() or str(Path.home())
        self.add_recent_dir(workdir)

        mode = self.combo_aider_mode.currentData() or ""
        auto_commit = "" if self.chk_aider_auto_commit.isChecked() else "--no-auto-commits"
        cmd = f"aider --model ollama/{model} {mode} {auto_commit}"
        self.run_in_terminal(cmd, workdir=workdir, in_tab=in_tab)

    def launch_oi(self):
        model = self.combo_oi_model.currentData() or "qwen2.5-coder:14b"
        auto = "-y" if self.chk_oi_auto.isChecked() else ""
        cmd = f"interpreter --model ollama/{model} {auto}"
        self.run_in_terminal(cmd)

    def launch_self_dev(self):
        model = self.combo_self_model.currentData() or "qwen2.5-coder:32b"
        files = []
        if self.chk_self_gui.isChecked():
            files.append("/etc/nixos/ai-agent-hub.py")
        if self.chk_self_launcher.isChecked():
            files.append("/etc/nixos/aider-launcher.pl")
        if self.chk_self_ainix.isChecked():
            files.append("/etc/nixos/ai.nix")
        if self.chk_self_config.isChecked():
            files.append("/etc/nixos/configuration.nix")

        files_str = " ".join(files)
        cmd = f"aider --model ollama/{model} {files_str}"
        self.run_in_terminal(cmd, workdir="/etc/nixos")

    def launch_duo(self):
        m1 = self.combo_aider_model.currentData() or "qwen2.5-coder:14b"
        m2 = self.combo_oi_model.currentData() or "qwen2.5-coder:14b"
        self.run_in_terminal(f"aider --model ollama/{m1}", in_tab=False)
        QTimer.singleShot(700, lambda: self.run_in_terminal(f"interpreter --model ollama/{m2}", in_tab=True))

    def launch_thinker_duo(self):
        self.run_in_terminal("aider --model ollama/qwen2.5-coder:32b", in_tab=False)
        QTimer.singleShot(700, lambda: self.run_in_terminal("aider --model ollama/deepseek-r1:14b --chat-mode ask", in_tab=True))

    def launch_split_aider(self):
        d1 = str(Path.home())
        d2 = "/etc/nixos"
        self.run_in_terminal("aider", workdir=d1, in_tab=False)
        QTimer.singleShot(700, lambda: self.run_in_terminal("aider", workdir=d2, in_tab=True))

    # =========================================================================
    # Monitoring
    # =========================================================================
    def refresh_ram(self):
        try:
            with open("/proc/meminfo") as f:
                mem = f.read()
            total_kb = int(re.search(r"MemTotal:\s+(\d+)", mem).group(1))
            avail_kb = int(re.search(r"MemAvailable:\s+(\d+)", mem).group(1))
            used_kb = total_kb - avail_kb

            total_gb = total_kb / 1024 / 1024
            used_gb = used_kb / 1024 / 1024
            free_gb = avail_kb / 1024 / 1024
            pct = int((used_kb / total_kb) * 100)

            self.bar_ram.setValue(pct)
            self.bar_ram.setFormat(f"{used_gb:.1f} GB / {total_gb:.1f} GB ({pct}%) • {free_gb:.1f} GB frei")

            if pct > 85:
                color = "#e74c3c"
            elif pct > 65:
                color = "#f39c12"
            else:
                color = "#27ae60"
            self.bar_ram.setStyleSheet(f"QProgressBar::chunk {{ background-color: {color}; }}")

            ollama_url = self.config.get("ollama_url", "http://127.0.0.1:11434")
            try:
                with urllib.request.urlopen(f"{ollama_url}/api/ps", timeout=2) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m.get("name", "").replace(":latest", "") for m in data.get("models", [])]
                    if models:
                        self.lbl_active_models.setText(f"Geladene Modelle im RAM: {' • '.join(models)}")
                        self.lbl_active_models.setStyleSheet("color: #2ecc71; font-weight: bold;")
                    else:
                        self.lbl_active_models.setText("Geladene Modelle im RAM: Keine (RAM ist frei)")
                        self.lbl_active_models.setStyleSheet("color: #7f8c8d;")
                    self.lbl_server_status.setText("🟢 Ollama Server: Online")
                    self.lbl_server_status.setStyleSheet("color: #2ecc71; font-weight: bold; font-size: 12px;")
            except Exception:
                self.lbl_server_status.setText("🔴 Ollama Server: Nicht erreichbar")
                self.lbl_server_status.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 12px;")
        except Exception:
            pass

    def refresh_models(self):
        models = []
        ollama_url = self.config.get("ollama_url", "http://127.0.0.1:11434")
        try:
            with urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for m in data.get("models", []):
                    name = m.get("name", "").replace(":latest", "")
                    size_b = m.get("size", 0)
                    size_gb = size_b / (1024 * 1024 * 1024)
                    size_str = f"{size_gb:.1f} GB" if size_gb >= 1.0 else f"{size_b / 1024 / 1024:.0f} MB"
                    models.append((name, f"{name} ({size_str})"))
        except Exception:
            pass

        if not models:
            models = [("qwen2.5-coder:1.5b", "qwen2.5-coder:1.5b"), ("qwen2.5-coder:14b", "qwen2.5-coder:14b"), ("qwen2.5-coder:32b", "qwen2.5-coder:32b")]

        for combo in [self.combo_aider_model, self.combo_oi_model, self.combo_self_model, self.combo_copilot_model]:
            cur = combo.currentData()
            combo.clear()
            for name, desc in models:
                combo.addItem(desc, name)
            if cur:
                idx = combo.findData(cur)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

        # Copilot Default setzen
        def_copilot = self.config.get("default_copilot_model", "qwen2.5-coder:1.5b")
        idx_cp = self.combo_copilot_model.findData(def_copilot)
        if idx_cp >= 0:
            self.combo_copilot_model.setCurrentIndex(idx_cp)

        installed_names = [m[0] for m in models]
        for m_id, btn in self.preset_buttons.items():
            if m_id in installed_names or f"{m_id}:latest" in installed_names:
                btn.setText("✔ Bereit")
                btn.setEnabled(False)
                btn.setStyleSheet("background-color: #27ae60; color: white;")
            else:
                btn.setText("📥 Laden")
                btn.setEnabled(True)
                btn.setStyleSheet("")

    def refresh_all(self):
        self.refresh_models()
        self.refresh_ram()
        self.check_git_status(self.combo_recent_dirs.currentText())

    def action_free_ram(self):
        try:
            subprocess.run(["gollama", "-u"], stderr=subprocess.DEVNULL)
        except Exception:
            pass
        self.refresh_ram()
        self.statusBar.showMessage("Arbeitsspeicher freigegeben!", 3000)

    def save_settings(self):
        self.config["terminal"] = self.combo_term.currentText()
        self.config["ollama_url"] = self.txt_ollama_url.text().strip()
        try:
            sec = int(self.txt_refresh.text().strip())
            self.config["refresh_seconds"] = max(1, sec)
            self.monitor_timer.setInterval(self.config["refresh_seconds"] * 1000)
        except Exception:
            pass
        save_config(self.config)
        QMessageBox.information(self, "Gespeichert", "Einstellungen erfolgreich gespeichert!")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AIAgentHub()
    window.show()
    sys.exit(app.exec())
