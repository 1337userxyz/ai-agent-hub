{ config, pkgs, ... }:

let
  aiderLauncher = pkgs.writeScriptBin "aider" ''
    #!${pkgs.bash}/bin/bash
    export REAL_AIDER="${pkgs.aider-chat}/bin/aider"
    exec ${pkgs.perl}/bin/perl /etc/nixos/aider-launcher.pl "$@"
  '';

  aidrLauncher = pkgs.writeScriptBin "aidr" ''
    #!${pkgs.bash}/bin/bash
    exec ${aiderLauncher}/bin/aider "$@"
  '';

  # Open Interpreter Starter für System- & PC-Administration
  interpreterLauncher = pkgs.writeScriptBin "interpreter" ''
    #!${pkgs.bash}/bin/bash
    if [ $# -eq 0 ]; then
      exec /home/tristan/.local/share/open-interpreter/bin/interpreter --model ollama/qwen2.5-coder:14b
    else
      exec /home/tristan/.local/share/open-interpreter/bin/interpreter "$@"
    fi
  '';

  oiLauncher = pkgs.writeScriptBin "oi" ''
    #!${pkgs.bash}/bin/bash
    exec ${interpreterLauncher}/bin/interpreter "$@"
  '';

  # Python-Umgebung mit PyQt6 für das KDE AI Agent Hub Control Center
  pythonWithPyQt = pkgs.python3.withPackages (ps: [
    ps.pyqt6
  ]);

  aiHubLauncher = pkgs.writeScriptBin "ai-hub" ''
    #!${pkgs.bash}/bin/bash
    exec ${pythonWithPyQt}/bin/python3 /etc/nixos/ai-agent-hub.py "$@"
  '';

  aiGuiLauncher = pkgs.writeScriptBin "ai-gui" ''
    #!${pkgs.bash}/bin/bash
    exec ${aiHubLauncher}/bin/ai-hub "$@"
  '';
in
{
  # 1. Ollama Systemdienst für lokale KI-Modelle
  services.ollama = {
    enable = true;
    # Explizit das CPU-optimierte Paket mit AVX-512 für deinen Ryzen 9 7900X3D
    package = pkgs.ollama-cpu;
    host = "127.0.0.1";
    port = 11434;
    # Einstellungen für maximale Geschwindigkeit und Multi-Modell-Betrieb
    environmentVariables = {
      OLLAMA_MAX_TRANSFER_STREAMS = "16";
      OLLAMA_DEBUG = "1";
      # Erlaube bis zu 4 Modelle gleichzeitig im RAM (bei 64 GB DDR5 ideal!)
      OLLAMA_MAX_LOADED_MODELS = "4";
      # Parallele Anfragen erlauben (z. B. wenn Aider und Open Interpreter parallel laufen)
      OLLAMA_NUM_PARALLEL = "2";
      # Modelle dauerhaft im RAM behalten, statt sie nach 5 Min Inaktivität zu entladen
      OLLAMA_KEEP_ALIVE = "24h";
    };
  };

  # 2. Werkzeuge für die Kommandozeile
  environment.systemPackages = with pkgs; [
    git                 # Versionskontrolle - elementar für Aider und NixOS!
    gh                  # GitHub CLI für 'gh auth login' und automatische Repo-Verwaltung
    ollama-cpu          # Ollama CLI für 'ollama run', 'ollama list', etc.
    gollama             # Interaktives Terminal-Menü (TUI) zur Verwaltung und Auswahl von Modellen
    aiderLauncher       # Unser interaktiver Aider-Starter mit Modellauswahl & Gollama
    aidrLauncher        # Typo-Alias 'aidr'
    interpreterLauncher # Open Interpreter (Befehl: 'interpreter')
    oiLauncher          # Schneller Alias 'oi' für Open Interpreter
    aiHubLauncher       # PyQt6 KDE Control Center für Agenten & Downloads (Befehl: 'ai-hub')
    aiGuiLauncher       # Alias 'ai-gui'
    uv                  # Extrem schneller Python Package Runner
  ];
}

