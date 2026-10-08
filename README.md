# 🤖 KI Agent Hub & Launcher (NixOS / KDE Plasma 6)

Ein professionelles, natives **KDE Plasma 6 Control Center** und ein interaktiver **Terminal-Launcher** zur Orchestrierung lokaler KI-Coding- und System-Agenten (**Aider**, **Open Interpreter**, **Ollama**).

Entwickelt und optimiert für moderne High-End-Hardware: **AMD Ryzen 9 7900X3D (12C/24T • AVX-512)** und **64 GB DDR5 RAM**.

---

## 🌟 Hauptfunktionen

### 1. 🧠 Prompt-Copilot & LLM-Router
* **Gedanken-Refiner**: Tippe einfach einen rohen Gedanken oder Wunsch ein (z. B. *"Ich will das Menü schöner machen und Buttons hinzufügen"*).
* **Multi-LLM Dispatcher**: Ein schnelles, ressourcenschonendes Modell (z. B. `qwen2.5-coder:1.5b` mit über 80 Tok/s) analysiert deinen Gedanken in Sekundenbruchteilen und generiert **3 geschärfte Handlungsvorschläge** für die passenden Spezialisten:
  1. **Architektur & Konzept** (für *DeepSeek R1* – analytischer Plan für den Aider Ask-Modus)
  2. **Direkte Code-Umsetzung** (für *Qwen 2.5 Coder 32B* – präzise Code-Anweisung für Aider)
  3. **PC- & Terminal-Aktion** (für *Open Interpreter* – konkreter Shell-Befehl)
* **1-Klick-Ausführung**: Ein Klick auf die Karte startet direkt die richtige Sitzung mit dem fertigen Prompt!

### 2. ⚡ Live Hardware & System Monitor
* **Echtzeit-RAM-Balken**: Zeigt dynamisch den aktuellen Füllstand deiner 64 GB DDR5 RAM mit Farbwarnungen (Grün / Gelb / Rot).
* **Ollama RAM-Inspektor**: Fragt live ab, welche Modelle aktuell im Arbeitsspeicher residieren (`ollama ps`).
* **1-Klick RAM-Bereinigung**: Entlädt ruhende Modelle auf Knopfdruck aus dem Arbeitsspeicher.

### 3. 📥 Multi-Modell-Downloader mit Live-Stream
* **Echtzeit-Fortschritt**: Echte Prozentanzeige, Downloadgeschwindigkeit in **MB/s**, übertragene Gigabyte (`3.4 GB / 9.0 GB`) und Statusanzeige (*Pulling manifest*, *Verifying digest*).
* **Parallele Downloads**: Lade mehrere Modelle gleichzeitig herunter – jedes mit individuellem Balken und Abbrechen-Button.
* **1-Klick-Bibliothek**: Sofort-Downloads für Top-Modelle:
  * `qwen2.5-coder:32b` (19 GB – Coding-König)
  * `deepseek-r1:14b` (9.0 GB – Top Reasoning)
  * `deepseek-r1:32b` (19 GB – Tiefes Denken)
  * `qwen2.5-coder:14b` (9.0 GB – Schneller Allrounder)
  * `qwen2.5-coder:7b` (4.7 GB – Leichtgewicht)
  * `llama3.3:70b` (42 GB – Monster-Modell für 64 GB RAM)
* **Manuelles Feld**: Unterstützt alle Ollama-Tags und HuggingFace GGUFs (`hf.co/...`).

### 4. 💻 Coding Agent (Aider)
* **Projekt-Browser**: Verzeichnisauswahl mit Speicherung kürzlich genutzter Projekte.
* **Git-Erkennung**: Erkennt Repositories automatisch und zeigt den aktuellen Branch an.
* **Modi**: Standard, Architect-Modus (`--architect`) oder reiner Diskussionsmodus (`--chat-mode ask`).
* **Fenster-Wahl**: Startet wahlweise in einem neuen Konsole-Fenster oder als neuer Tab.

### 5. 🐧 OS & System Agent (Open Interpreter)
* Vollwertiger System-Administrator im Terminal.
* Schalter für automatische Ausführung (`-y`) oder interaktive Sicherheits-Rückfrage.

### 6. 🛠️ Self-Dev Modus (Starter- & System-Tuning)
* Lädt Systemdateien (`ai-agent-hub.py`, `aider-launcher.pl`, `ai.nix`, `configuration.nix`) direkt in Aider.
* Erlaubt es, diesen Launcher oder das NixOS-System per einfachem Sprachbefehl selbst zu erweitern.

### 7. 👥 Multi-Agent Parallel-Betrieb
* Nutzt die 24 Threads deiner CPU optimal aus:
  * **Duo-Modus**: Aider (Coding) + Open Interpreter (System) in zwei Konsole-Tabs nebeneinander.
  * **Thinker & Coder**: DeepSeek R1 (Architektur/Planung) + Qwen 32B (Code-Editor) parallel.
  * **Split-Work**: Zwei Aider-Instanzen für unterschiedliche Projekte.

---

## 📂 Projektstruktur

```
ai-agent-hub/
├── ai-agent-hub.py          # PyQt6 Desktop GUI Control Center & Prompt-Copilot
├── aider-launcher.pl        # Interaktiver Perl Terminal-Launcher
├── ai.nix                   # NixOS Modul (Ollama Systemdienst, Aider, Open Interpreter)
├── ai-agent-hub.desktop     # KDE Plasma Desktop-Verknüpfung
├── .gitignore               # Ignoriert Chat-Logs, Cache und temporäre Dateien
└── README.md                # Dokumentation
```

---

## 🚀 Starten & Benutzen

### Über die GUI (Desktop)
* **KDE Startmenü**: Drücke `Super` oder `Alt+Space` und suche nach `KI Agent Hub`.
* **Kommandozeile**:
  ```bash
  ai-hub
  # oder
  ai-gui
  ```

### Über das Terminal
* Starte den interaktiven Terminal-Launcher mit Modell-Auswahl:
  ```bash
  aider
  ```
  * Tippe `h` ein, um direkt in die Desktop-GUI zu wechseln.
  * Tippe `d` ein für den Self-Dev Modus.
  * Tippe `o` ein für Open Interpreter.

---

## ⚙️ NixOS Integration

In `/etc/nixos/configuration.nix` einfach das Modul einbinden:
```nix
imports = [
  ./hardware-configuration.nix
  ./ai.nix
];
```

Danach aktivieren:
```bash
sudo nixos-rebuild switch
```

---

## 📄 Lizenz
MIT License.
