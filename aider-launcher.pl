#!/usr/bin/env perl
use strict;
use warnings;
use Term::ANSIColor qw(:constants);

my $REAL_AIDER = $ENV{REAL_AIDER} || "/run/current-system/sw/bin/aider";
# Falls $REAL_AIDER auf sich selbst zeigt, echten Aider-Pfad ermitteln
if (-l $REAL_AIDER || ! -x $REAL_AIDER || $REAL_AIDER eq $0) {
    my $store_aider = `/run/current-system/sw/bin/which aider 2>/dev/null`;
    chomp $store_aider if $store_aider;
    my @candidates = glob("/nix/store/*aider-chat*/bin/aider");
    if (@candidates && -x $candidates[0]) {
        $REAL_AIDER = $candidates[0];
    }
}

$ENV{OLLAMA_API_BASE} = "http://127.0.0.1:11434";

my $LOG_DIR = "/tmp/ollama-pulls";
system("mkdir -p $LOG_DIR 2>/dev/null");

sub get_safe_name {
    my ($name) = @_;
    $name =~ s/[^a-zA-Z0-9_\-\.]/_/g;
    return $name;
}

# Hardware-Informationen abrufen
sub get_hw_info {
    my $ram_free = "54 GB";
    if (open my $fh, "<", "/proc/meminfo") {
        my ($avail) = (0);
        while (<$fh>) {
            if (/MemAvailable:\s+(\d+)\s+kB/) {
                $avail = $1;
                $ram_free = sprintf("%.1f GB", $avail / 1024 / 1024);
                last;
            }
        }
        close $fh;
    }
    return "AMD Ryzen 9 7900X3D (12C/24T • AVX-512) • 64 GB DDR5 ($ram_free frei)";
}

# Installierte Modelle abfragen
sub get_installed_models {
    my %installed;
    my $out = `ollama list 2>/dev/null`;
    if ($out) {
        for my $line (split /\n/, $out) {
            next if $line =~ /^NAME\s+/ || $line =~ /^\s*$/;
            my ($name, $id, $size) = split /\s+/, $line;
            $name =~ s/:latest$//;
            $installed{$name} = $size || "OK";
        }
    }
    return \%installed;
}

# Prüfen, ob ein Hintergrund-Download für dieses Modell läuft (zuverlässig via /proc und PID)
sub get_bg_pull_info {
    my ($model) = @_;
    my $safe = get_safe_name($model);
    my $log_file = "$LOG_DIR/$safe.log";
    my $pid_file = "$LOG_DIR/$safe.pid";

    my $pid = 0;
    if (-f $pid_file) {
        if (open my $fh, "<", $pid_file) {
            my $line = <$fh>;
            close $fh;
            $pid = $1 if $line && $line =~ /(\d+)/;
        }
    }

    if ($pid) {
        if (! -d "/proc/$pid") {
            $pid = 0;
            unlink $pid_file;
        } else {
            if (open my $fh, "<", "/proc/$pid/cmdline") {
                local $/;
                my $cmd = <$fh>;
                close $fh;
                if (!$cmd || $cmd !~ /ollama\0pull/) {
                    $pid = 0;
                    unlink $pid_file;
                }
            }
        }
    }

    # Falls nicht über PID-File gefunden, einmalig /proc durchsuchen
    if (!$pid) {
        for my $p (glob("/proc/[0-9]*")) {
            next unless -d $p;
            my ($proc_pid) = $p =~ /(\d+)$/;
            next if $proc_pid == $$;
            if (open my $fh, "<", "$p/cmdline") {
                local $/;
                my $cmd = <$fh>;
                close $fh;
                if ($cmd && $cmd =~ /ollama\0pull\0\Q$model\E/) {
                    $pid = $proc_pid;
                    # PID-File nachpflegen
                    if (open my $pfh, ">", $pid_file) {
                        print $pfh "$pid\n";
                        close $pfh;
                    }
                    last;
                }
            }
        }
    }

    return undef unless $pid;

    my $progress_text = "";
    if (-f $log_file) {
        if (open my $fh, "<", $log_file) {
            seek($fh, -4000, 2) if -s $log_file > 4000;
            my $content = do { local $/; <$fh> };
            close $fh;

            if ($content) {
                while ($content =~ /(\d+%)\s+.*?([\d\.]+\s+[MG]B\/[\d\.]+\s+[MG]B)(?:\s+([\d\.]+\s+[MG]B\/s))?/g) {
                    my ($pct, $bytes, $speed) = ($1, $2, $3);
                    $progress_text = "$pct ($bytes" . ($speed ? " • $speed" : "") . ")";
                }
            }
        }
    }

    return {
        running => 1,
        pid     => $pid,
        text    => $progress_text || "Download startet...",
        log     => $log_file,
    };
}

my @MODELS = (
    {
        name   => "qwen2.5-coder:14b",
        title  => "Qwen 2.5 Coder 14B",
        size   => "9.0 GB",
        speed  => "~8 Tok/s",
        tag    => "Empfehlung",
        desc   => "Bester Allround-Coder: Exzellent für Refactorings, Diffs & NixOS",
    },
    {
        name   => "qwen2.5-coder:7b",
        title  => "Qwen 2.5 Coder 7B",
        size   => "4.7 GB",
        speed  => "~16 Tok/s",
        tag    => "Schnell",
        desc   => "Sehr flüssig & flott: Ideal für kleinere Skripte & Routine",
    },
    {
        name   => "qwen2.5-coder:1.5b",
        title  => "Qwen 2.5 Coder 1.5B",
        size   => "986 MB",
        speed  => "~35 Tok/s",
        tag    => "Sofort-Test",
        desc   => "Ultra-Leichtgewicht: Lädt in ~4 Min! Perfekt zum Sofort-Ausprobieren",
    },
    {
        name   => "deepseek-r1:14b",
        title  => "DeepSeek R1 14B",
        size   => "9.0 GB",
        speed  => "~7 Tok/s",
        tag    => "Reasoning",
        desc   => "Denkmodell: Reflektiert vor der Antwort intensiv über die Logik",
    },
    {
        name   => "qwen2.5-coder:32b",
        title  => "Qwen 2.5 Coder 32B",
        size   => "20 GB",
        speed  => "~3 Tok/s",
        tag    => "Architektur",
        desc   => "Maximale Code-Tiefe & komplexe Software-Architektur",
    },
    {
        name   => "llama3.1:8b",
        title  => "Llama 3.1 8B",
        size   => "4.7 GB",
        speed  => "~15 Tok/s",
        tag    => "Allrounder",
        desc   => "Sehr stark in natürlicher Konversation, Konzepten & Deutsch",
    },
);

# Hintergrund-Download starten (ermöglicht parallele Downloads)
sub start_background_pull {
    my ($model, $silent) = @_;
    my $safe = get_safe_name($model);
    my $log_file = "$LOG_DIR/$safe.log";
    my $pid_file = "$LOG_DIR/$safe.pid";

    my $bg = get_bg_pull_info($model);
    return if ($bg && $bg->{running});

    # Vorheriges Log leeren
    unlink $log_file;

    system("setsid ollama pull '$model' > '$log_file' 2>&1 & echo \$! > '$pid_file'");
    if (!$silent) {
        print "\n\033[1;32m✔ Hintergrund-Download für '$model' gestartet!\033[0m\n";
        print "\033[90mDer Download läuft jetzt parallel im Hintergrund weiter.\033[0m\n";
        print "\033[90mDu kannst im Menü weiterarbeiten oder weitere Modelle parallel starten.\033[0m\n";
        sleep 2;
    }
}

# Hintergrund-Download stoppen
sub stop_background_pull {
    my ($model, $info) = @_;
    my $safe = get_safe_name($model);
    my $pid_file = "$LOG_DIR/$safe.pid";
    if ($info && $info->{pid}) {
        kill('TERM', $info->{pid});
        unlink $pid_file;
        print "\n\033[1;33m✔ Hintergrund-Download von '$model' wurde gestoppt.\033[0m\n";
        print "\033[90mBisher heruntergeladene Chunks bleiben auf der Festplatte erhalten.\033[0m\n";
        sleep 2;
    }
}

# Live-Beobachtung eines Hintergrund-Downloads
sub watch_background_pull {
    my ($model, $info, $autostart) = @_;
    print "\n\033[1;36m👀 Beobachte Download von $model...\033[0m\n";
    print "\033[90mDrücke [Enter] oder [Strg+C], um zum Menü zurückzukehren (Download läuft ungestört im Hintergrund weiter).\033[0m\n\n";

    if (! -t STDIN) {
        return 0;
    }

    my $stop_watching = 0;
    local $SIG{INT} = sub {
        $stop_watching = 1;
    };

    while (!$stop_watching) {
        my $bg = get_bg_pull_info($model);
        if (!$bg || !$bg->{running}) {
            my $inst = get_installed_models();
            if (exists $inst->{$model} || exists $inst->{"$model:latest"}) {
                print "\n\n\033[1;32m✔ Download von '$model' erfolgreich abgeschlossen!\033[0m\n";
                if ($autostart) {
                    print "\033[1;36m🚀 Starte Aider Coding-Agent mit ollama/$model...\033[0m\n\n";
                    sleep 1;
                    exec $REAL_AIDER, "--model", "ollama/$model", @ARGV;
                    exit 0;
                }
                print "Möchtest du Aider jetzt mit '$model' starten? [\033[1;32mEnter = Ja\033[0m / n = Menü]: ";
                my $ans = <STDIN>;
                chomp $ans if defined $ans;
                if (!defined $ans || $ans eq "" || $ans =~ /^[jJyY]/) {
                    exec $REAL_AIDER, "--model", "ollama/$model", @ARGV;
                    exit 0;
                }
                return 1;
            } else {
                print "\n\n\033[1;31m✖ Download wurde beendet oder abgebrochen.\033[0m\n";
                sleep 2;
                return 0;
            }
        }

        printf "\r\033[1;33m⏳ Fortschritt: %-65s\033[0m", $bg->{text};

        my ($rin, $rout) = ('', '');
        vec($rin, fileno(STDIN), 1) = 1;
        my $ready = select($rout = $rin, undef, undef, 1.0);
        if ($ready > 0) {
            my $in = <STDIN>;
            $stop_watching = 1;
        }
    }

    print "\n\n\033[90mZurück zum Menü (Download läuft im Hintergrund weiter)...\033[0m\n";
    sleep 1;
    return 0;
}

# Vordergrund-Download: Startet im Hintergrund und beobachtet live (kein Datenverlust bei Unterbrechung)
sub run_foreground_pull {
    my ($model, $autostart) = @_;
    print "\n\033[1;36m⬇ Starte Download von $model (im Hintergrund, Live-Ansicht aktiv)...\033[0m\n\n";

    my $bg = get_bg_pull_info($model);
    if (!$bg || !$bg->{running}) {
        start_background_pull($model, 1);
    }

    return watch_background_pull($model, undef, $autostart);
}

# Falls Argumente wie --model oder -m übergeben wurden, vorab prüfen
sub check_commandline_model {
    for my $i (0 .. $#ARGV) {
        my $arg = $ARGV[$i];
        my $model = "";
        if ($arg =~ /^--model=(.+)$/) {
            $model = $1;
        } elsif (($arg eq "-m" || $arg eq "--model") && $i + 1 <= $#ARGV) {
            $model = $ARGV[$i + 1];
        }
        if ($model && $model =~ /^ollama\/(.+)$/) {
            my $ollama_model = $1;
            my $installed = get_installed_models();
            if (!exists $installed->{$ollama_model} && !exists $installed->{"$ollama_model:latest"}) {
                print "\n\033[1;33m⚠ Modell '$ollama_model' ist noch nicht installiert!\033[0m\n";
                print "\033[1;36m⬇ Starte Hintergrund-Download und zeige Live-Fortschritt...\033[0m\n\n";
                start_background_pull($ollama_model, 1);
                watch_background_pull($ollama_model, undef, 1);
                exit 0;
            }
        }
        if ($arg =~ /^--model/ || $arg =~ /^-m/) {
            exec $REAL_AIDER, @ARGV;
        }
    }
}

check_commandline_model();

sub show_model_guide {
    print "\n\033[1;34m╭──────────────────────────────────────────────────────────────────────────────────────────╮\033[0m\n";
    print "\033[1;34m│\033[0m  \033[1;37m🧠 MODELL-RATGEBER: WELCHES MODELL FÜR WELCHE AUFGABE?\033[0m                                  \033[1;34m│\033[0m\n";
    print "\033[1;34m╰──────────────────────────────────────────────────────────────────────────────────────────╯\033[0m\n\n";

    print "  \033[1;32m[1] Qwen 2.5 Coder 14B\033[0m  \033[90m(9.0 GB RAM • ~8 Tok/s)\033[0m  \033[1;33m★ ABSOLUTE ALLROUND-EMPFEHLUNG\033[0m\n";
    print "      • \033[1;37mEinsatzbereich:\033[0m Dein Standard für tägliche Programmierung und NixOS-Konfigurationen.\n";
    print "      • \033[1;37mStärken:\033[0m Exzellentes Code-Verständnis, saubere Git-Diffs, versteht Nix-Syntax & Bash.\n";
    print "      • \033[1;37mEmpfehlung:\033[0m Wenn du unsicher bist, nimm IMMER dieses Modell!\n\n";

    print "  \033[1;36m[2] Qwen 2.5 Coder 7B\033[0m   \033[90m(4.7 GB RAM • ~16 Tok/s)\033[0m  \033[1;36m⚡ DER SCHNELLE CODER\033[0m\n";
    print "      • \033[1;37mEinsatzbereich:\033[0m Kleine Skripte, schnelle Einzeiler, kleinere Fixes, Routineaufgaben.\n";
    print "      • \033[1;37mStärken:\033[0m Doppelt so schnell wie 14B, sehr reaktionsschnell bei wenig RAM-Bedarf.\n\n";

    print "  \033[1;37m[3] Qwen 2.5 Coder 1.5B\033[0m \033[90m(986 MB RAM • ~35 Tok/s)\033[0m  \033[1;37m🚀 ULTRA-LEICHTGEWICHT\033[0m\n";
    print "      • \033[1;37mEinsatzbereich:\033[0m Blitzschnelle Syntax-Checks, Test-Runs, Mini-Skripte.\n";
    print "      • \033[1;37mStärken:\033[0m Extrem schnell (~35 Tok/s), belegt unter 1 GB RAM.\n\n";

    print "  \033[1;35m[4] DeepSeek R1 14B\033[0m     \033[90m(9.0 GB RAM • ~7 Tok/s)\033[0m   \033[1;35m🧩 DAS DENK- & LOGIK-MODELL\033[0m\n";
    print "      • \033[1;37mEinsatzbereich:\033[0m Knifflige Bugs, komplexe Algorithmen, wenn andere Modelle scheitern.\n";
    print "      • \033[1;37mStärken:\033[0m Denkt vor der Antwort ausführlich nach (CoT - Chain of Thought),\n";
    print "        hinterfragt Annahmen und findet versteckte Logikfehler.\n\n";

    print "  \033[1;31m[5] Qwen 2.5 Coder 32B\033[0m  \033[90m(20 GB RAM • ~3 Tok/s)\033[0m    \033[1;31m🏛️ GROSSE SOFTWARE-ARCHITEKTUR\033[0m\n";
    print "      • \033[1;37mEinsatzbereich:\033[0m Große Codebasen, tiefgreifende Refactorings, Enterprise-Projekte.\n";
    print "      • \033[1;37mStärken:\033[0m Höchstes Programmierverständnis, braucht auf der CPU aber etwas mehr Zeit.\n\n";

    print "  \033[1;33m[6] Llama 3.1 8B\033[0m        \033[90m(4.7 GB RAM • ~15 Tok/s)\033[0m  \033[1;33m💬 SPRACH- & KONVERSATIONS-PROFI\033[0m\n";
    print "      • \033[1;37mWofür:\033[0m Allgemeine Fragen, Konzepte erklären, flüssige deutsche Texte & Dokumentation.\n";
    print "      • \033[1;37mStärken:\033[0m Kein reiner Coder, sondern das beste Allround-Sprachmodell.\n\n";

    print "  \033[90m" . ("─" x 88) . "\033[0m\n";
    print "  Drücke \033[1;32m[Enter]\033[0m, um zurück zum Hauptmenü zu gelangen... ";
    my $pause = <STDIN>;
}

sub render_menu {

    my $installed = get_installed_models();
    my $hw = get_hw_info();

    print "\n\033[1;36m╭──────────────────────────────────────────────────────────────────────────────────────────╮\033[0m\n";
    print "\033[1;36m│\033[0m  \033[1;37m🤖 AIDER CODING-AGENT — MODELL-ZENTRALE & DOWNLOADS\033[0m                                     \033[1;36m│\033[0m\n";
    printf "\033[1;36m│\033[0m  \033[90mSystem: %-78s\033[0m \033[1;36m│\033[0m\n", $hw;
    print "\033[1;36m╰──────────────────────────────────────────────────────────────────────────────────────────╯\033[0m\n\n";

    print "  \033[1;37mVerfügbare Modelle:\033[0m\n\n";

    for my $i (0 .. $#MODELS) {
        my $m = $MODELS[$i];
        my $num = $i + 1;
        my $name = $m->{name};
        my $title = $m->{title};
        my $is_inst = exists $installed->{$name} || exists $installed->{"$name:latest"};
        my $bg_info = get_bg_pull_info($name);

        my $status_str = "";
        if ($is_inst) {
            $status_str = "\033[1;32m● Bereit\033[0m";
        } elsif ($bg_info && $bg_info->{running}) {
            $status_str = "\033[1;33m⏳ Lädt im Hintergrund: " . $bg_info->{text} . "\033[0m";
        } else {
            $status_str = "\033[90m○ Nicht installiert\033[0m";
        }

        my $num_badge = ($num == 1) ? "\033[1;32m[$num]\033[0m ★" : "\033[1;37m[$num]\033[0m  ";
        my $title_str = ($num == 1) ? "\033[1;37m$title\033[0m" : "\033[0;37m$title\033[0m";

        printf "  %s %-22s \033[90m(%s | %s)\033[0m   %s\n",
            $num_badge, $title_str, $m->{size}, $m->{speed}, $status_str;
        printf "      \033[90m↳ %s\033[0m\n\n", $m->{desc};
    }

    print "  \033[90m" . ("─" x 88) . "\033[0m\n\n";

    print "  \033[1;37m⚡ SO STARTEST DU:\033[0m\n";
    print "     \033[1;32m[Enter]\033[0m   \033[1;37mAider Standard\033[0m                \033[90m→ Startet Aider mit Qwen 14B (Code-Editor & Git)\033[0m\n";
    print "     \033[1;32m[1 - 6]\033[0m   \033[1;37mAider mit Wunsch-Modell\033[0m       \033[90m→ Z.B. '4' startet Aider mit DeepSeek R1\033[0m\n";
    print "     \033[1;36m[o]\033[0m       \033[1;37mOpen Interpreter Standard\033[0m     \033[90m→ PC-Admin / OS-Agent mit Qwen 14B (Befehle echt ausführen)\033[0m\n";
    print "     \033[1;36m[o1 - o6]\033[0m \033[1;37mOpen Interpreter mit Modell\033[0m   \033[90m→ Z.B. 'o4' startet OI mit DeepSeek R1 (oder 'o2' mit Qwen 7B)\033[0m\n";
    print "     \033[1;35m[d]\033[0m       \033[1;37mSelf-Dev (Starter tunen)\033[0m      \033[90m→ Öffnet Aider direkt mit den Dateien dieses Launchers!\033[0m\n";
    print "     \033[1;35m[d1 - d6]\033[0m \033[1;37mSelf-Dev mit Modell 1-6\033[0m        \033[90m→ Z.B. 'd4' verbessert den Starter mit DeepSeek R1\033[0m\n";
    print "     \033[1;36m[h]\033[0m       \033[1;37mKI Agent Hub (KDE GUI)\033[0m        \033[90m→ Öffnet das grafische Desktop Control Center\033[0m\n";
    print "     \033[1;34m[m]\033[0m       \033[1;37mModell-Ratgeber (Welches wann?)\033[0m\033[90m→ Ausführliche Details & Empfehlungen zu allen 6 Modellen\033[0m\n";
    print "     \033[1;33m[g]\033[0m       \033[0;37mGollama TUI\033[0m                   \033[90m→ Interaktive Modell-Verwaltung\033[0m\n";
    print "     \033[1;35m[u]\033[0m       \033[0;37mRAM leeren\033[0m                    \033[90m→ Alle Modelle aus dem 64-GB-DDR5-Speicher entladen\033[0m\n";
    print "     \033[1;33m[r]\033[0m       \033[0;37mAktualisieren\033[0m                 \033[90m→ Ansicht / Download-Status neu laden\033[0m\n";
    print "     \033[1;31m[q]\033[0m       \033[0;37mBeenden\033[0m                       \033[90m→ Launcher schließen\033[0m\n\n";

    print "  \033[90m" . ("─" x 88) . "\033[0m\n\n";

    print "  \033[1;33m💡 SPICKZETTEL — BEFEHLE IM AIDER-CHAT (Code & Git-Assistent):\033[0m\n";
    print "     \033[1;32m!<befehl>\033[0m      \033[1;37mBefehl direkt ausführen\033[0m       \033[90m→ Wie im Terminal, z.B. !python app.py oder !./script.sh\033[0m\n";
    print "     \033[1;32m/run <cmd>\033[0m     \033[1;37mBefehl mit Auto-Fehler-Fix\033[0m    \033[90m→ Führt Befehl aus & füttert Output/Fehler direkt an die KI\033[0m\n";
    print "     \033[1;32m/ask <frage>\033[0m   \033[1;37mNur diskutieren & fragen\033[0m      \033[90m→ Reine Chat-Antwort, ohne gleich Code-Dateien umzuschreiben\033[0m\n";
    print "     \033[1;32m/test <cmd>\033[0m    \033[1;37mNixOS/Code-Testschleife\033[0m       \033[90m→ Z.B. /test sudo nixos-rebuild test (fixt Syntaxfehler selbst!)\033[0m\n";
    print "     \033[1;32m/add <datei>\033[0m   \033[1;37mDatei zum Bearbeiten laden\033[0m    \033[90m→ Gibt der KI die Datei zum Ändern frei (/drop zum Entfernen)\033[0m\n";
    print "     \033[1;32m/read <datei>\033[0m  \033[1;37mProjekt-Wissen ('Brain') laden\033[0m\033[90m→ Schreibgeschütztes Gedächtnis (Regeln/Architektur beachten)\033[0m\n\n";

    print "  \033[90m" . ("─" x 88) . "\033[0m\n\n";

    print "  \033[1;36m🐧 SPICKZETTEL — OPEN INTERPRETER (PC- & System-Admin):\033[0m\n";
    print "     \033[1;37mIm Terminal:\033[0m   Jederzeit \033[1;32moi\033[0m oder \033[1;32minterpreter\033[0m eingeben \033[90m(startet sofort ohne Umwege)\033[0m\n";
    print "     \033[1;37mArbeitsweise:\033[0m  Einfach auf Deutsch sagen: \033[36m\"Finde alle großen Dateien\"\033[0m oder \033[36m\"Ändere Hintergrund\"\033[0m\n";
    print "                    OI schreibt den Code, fragt dich kurz \033[1;32m[y/n]\033[0m und führt ihn echt auf dem PC aus!\n";
    print "     \033[1;37mMulti-Modell:\033[0m  Dank deiner 64 GB RAM kannst du Aider & OI in zwei Terminal-Tabs parallel\n";
    print "                    mit unterschiedlichen Modellen nutzen (bis zu 4 Modelle gleichzeitig im Speicher)!\n\n";
}


# Haupt-Workflow
while (1) {
    render_menu();

    print "\033[1;36mDeine Auswahl \033[1;32m[Enter = Aider | o = OI | d = Self-Dev | h = GUI | m = Ratgeber | 1-6]\033[1;36m: \033[0m";
    my $input = <STDIN>;
    last unless defined $input;
    chomp $input;
    $input =~ s/^\s+|\s+$//g;

    # Enter = Modell 1 (Qwen 14B)
    $input = "1" if $input eq "";

    if ($input =~ /^[qQ]$/) {
        print "Auf Wiedersehen!\n";
        exit 0;
    }

    if ($input =~ /^[rR]$/) {
        next;
    }

    if ($input =~ /^[hH]$/ || $input =~ /^gui$/i) {
        print "\n\033[90mÖffne grafisches KI Agent Hub Control Center...\033[0m\n";
        system("nix-shell -p python3Packages.pyqt6 --run 'python3 /etc/nixos/ai-agent-hub.py' >/dev/null 2>&1 &");
        next;
    }

    if ($input =~ /^[gG]$/) {
        print "\n\033[90mÖffne Gollama TUI...\033[0m\n";
        system("gollama");
        next;
    }

    if ($input =~ /^[uU]$/) {
        print "\n\033[90mEntlade alle Modelle aus dem Arbeitsspeicher...\033[0m\n";
        system("gollama -u 2>/dev/null || true");
        print "\033[1;32m✔ RAM freigegeben!\033[0m\n";
        sleep 1;
        next;
    }

    if ($input =~ /^[mM]$/) {
        show_model_guide();
        next;
    }

    my $target_app = "aider";
    my $model_choice = $input;

    if ($input =~ /^o(?:i)?(\d*)$/i) {
        $target_app = "oi";
        $model_choice = $1 || "1";
    } elsif ($input =~ /^d(?:ev)?(\d*)$/i) {
        $target_app = "self_dev";
        $model_choice = $1 || "1";
    }

    # Ausgewähltes Modell (1 .. 6)
    if ($model_choice =~ /^(\d+)$/ && $model_choice >= 1 && $model_choice <= scalar(@MODELS)) {
        my $idx = $model_choice - 1;
        my $m = $MODELS[$idx];
        my $chosen = $m->{name};
        my $installed = get_installed_models();

        # FALL 1: Modell ist bereits installiert
        if (exists $installed->{$chosen} || exists $installed->{"$chosen:latest"}) {
            print "\n\033[1;32m✔ Modell '$chosen' ist bereit!\033[0m\n";
            if ($target_app eq "oi") {
                print "\033[1;36m🤖 Starte Open Interpreter (OS & PC) mit ollama/$chosen...\033[0m\n\n";
                exec "/run/current-system/sw/bin/interpreter", "--model", "ollama/$chosen", @ARGV;
            } elsif ($target_app eq "self_dev") {
                print "\033[1;35m🛠️  Starte Aider im Self-Dev-Modus mit ollama/$chosen...\033[0m\n";
                print "\033[90m📁 Bereits geladen: /etc/nixos/aider-launcher.pl & /etc/nixos/ai.nix\033[0m\n\n";
                exec $REAL_AIDER, "--model", "ollama/$chosen", "/etc/nixos/aider-launcher.pl", "/etc/nixos/ai.nix", @ARGV;
            } else {
                print "\033[1;36m🚀 Starte Aider Coding-Agent (Git & Code) mit ollama/$chosen...\033[0m\n\n";
                exec $REAL_AIDER, "--model", "ollama/$chosen", @ARGV;
            }
            exit 0;
        }

        # FALL 2: Modell lädt gerade im Hintergrund
        my $bg_info = get_bg_pull_info($chosen);
        if ($bg_info && $bg_info->{running}) {
            print "\n\033[1;33mModell '$m->{title}' lädt bereits parallel im Hintergrund!\033[0m\n";
            print "Aktueller Stand: \033[1;37m" . $bg_info->{text} . "\033[0m\n\n";
            print "Was möchtest du tun?\n";
            print "  \033[1;32m[1]\033[0m Live zusehen & nach Download automatisch Aider starten\n";
            print "  \033[1;36m[2]\033[0m Live zusehen (nur beobachten, danach Menü)\n";
            print "  \033[1;31m[3]\033[0m Hintergrund-Download stoppen / abbrechen\n";
            print "  \033[1;37m[Enter]\033[0m Zurück zum Menü (lädt im Hintergrund weiter)\n\n";
            print "\033[1;36mAuswahl [Enter = Zurück]: \033[0m";

            my $action = <STDIN>;
            last unless defined $action;
            chomp $action;
            $action =~ s/^\s+|\s+$//g;

            if ($action eq "1") {
                watch_background_pull($chosen, $bg_info, 1);
                next;
            } elsif ($action eq "2") {
                watch_background_pull($chosen, $bg_info, 0);
                next;
            } elsif ($action eq "3") {
                stop_background_pull($chosen, $bg_info);
                next;
            } else {
                next;
            }
        }

        # FALL 3: Modell ist noch nicht da -> Geführte Optionen
        print "\n\033[1;33mModell '$m->{title}' ($m->{size}) ist noch nicht installiert.\033[0m\n\n";
        print "Wie möchtest du vorgehen?\n";
        print "  \033[1;32m[1]\033[0m Jetzt laden & danach sofort Aider starten \033[90m(Live-Balken, läuft im Hintergrund)\033[0m\n";
        print "  \033[1;36m[2]\033[0m Reiner Download im Vordergrund \033[90m(Live-Balken, danach zurück ins Menü)\033[0m\n";
        print "  \033[1;35m[3]\033[0m Reiner Download im Hintergrund \033[90m(parallel im Hintergrund, Menü bleibt frei)\033[0m\n";
        print "  \033[1;31m[q]\033[0m Abbrechen / Zurück zum Menü\n\n";
        print "\033[1;36mDeine Auswahl \033[1;32m[Enter = 1]\033[1;36m: \033[0m";

        my $opt = <STDIN>;
        last unless defined $opt;
        chomp $opt;
        $opt =~ s/^\s+|\s+$//g;

        $opt = "1" if $opt eq "";

        if ($opt =~ /^[qQ]$/) {
            next;
        }

        # Option 1: Laden & sofort Aider starten (echter Hintergrund-Download mit Live-Balken!)
        if ($opt eq "1") {
            run_foreground_pull($chosen, 1);
            next;
        }

        # Option 2: Reiner Download im Vordergrund (Live-Balken, danach zurück ins Menü)
        if ($opt eq "2") {
            my $ok = run_foreground_pull($chosen, 0);
            if ($ok) {
                print "\033[1;32m✔ Modell ist jetzt bereit! Zurück zum Menü...\033[0m\n";
                sleep 1;
            }
            next;
        }

        # Option 3: Reiner Download im Hintergrund (parallel!)
        if ($opt eq "3") {
            start_background_pull($chosen);
            next;
        }

        print "\033[31mUngültige Option. Zurück zum Menü...\033[0m\n";
        sleep 1;
        next;
    }

    print "\n\033[31mUngültige Eingabe '$input'. Bitte 1 bis " . scalar(@MODELS) . ", 'r', 'g' oder 'q' eingeben.\033[0m\n";
    sleep 1;
}
