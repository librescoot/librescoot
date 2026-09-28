# Nächster Librescoot-Testing-Build – was zu testen ist

Geplante Änderungen gegenüber [`testing-20260927T212059`](https://github.com/librescoot/librescoot/releases/tag/testing-20260927T212059). Diese Liste gilt erst nach Veröffentlichung eines neuen Testing-Builds mit den vorbereiteten `stable.env`-Versionen. Bitte Build-ID, Board (MDB/DBC), Schritte, erwartetes und beobachtetes Verhalten sowie nach Möglichkeit Foto oder Log-Paket angeben.

## Regionale Offline-Karten und Routenwiederaufnahme

- Auf einem Testroller mit bisheriger Einzelregion nach dem Update prüfen, ob Karte, Offline-Routing und der integrierte Karten-Updater weiterhin funktionieren. Eine funktionierende Karte nicht eigens für einen Fehlertest löschen.
- Auf einem **Prüfaufbau** im USB-Updatemodus zwei passende Paare aus `maps/tiles_<slug>.mbtiles` und `maps/valhalla_tiles_<slug>.tar[.zst]` installieren. Beide Pakete sollen erhalten bleiben; mit aktuellem GPS-Fix die Auswahl der jeweiligen Region, Anzeige, Routing und Adresssuche prüfen. Ein Paket ersetzen und nach Neustart erneut prüfen. Die Auswahl beruht auf rechteckigen Kartengrenzen; stark überlappende Regionen können verzögert wechseln. Routen über Regionsgrenzen werden nicht unterstützt.
- Ein einzelnes benanntes Paar auf einem bisherigen USB-Stick soll weiterhin die Einzelregion aktualisieren. Für genau ein regionales Paar zusätzlich eine leere Datei `maps/regional-packs` anlegen. **Einen genutzten Roller nicht nur für diesen Test migrieren:** Eine vorhandene reguläre `/data/valhalla/tiles.tar` bleibt erhalten und erfordert eine bewusste Migration, bevor automatischer Routing-Wechsel aktiv ist. Siehe [Navigationsanleitung](https://librescoot.org/docs/dev/navigation.html).
- Bei einer noch nicht abgeschlossenen Route mit mehreren Stopps im sicheren Stand den Tacho neu starten und prüfen, ob die Zielführung wiederaufgenommen wird, sobald der Routing-Dienst bereit ist. Den fahrbereiten Zustand verlassen, dann parken: Die offene Route soll ohne erneute Zielauswahl wiederaufnehmbar sein. Während der Fahrt keine Menüs bedienen.

## ECU-Verbindung und optionaler Cloud-Client

- Bei normaler Nutzung auf unbegründete `E20`-Verbindungsfehler bei ruhigem, aber erreichbarem Controller achten. Nach einem tatsächlichen Verbindungsausfall dürfen bisherige ECU-Fehler nicht als aktuell stehen bleiben. Bei Auffälligkeiten CAN-Verbindungszustand und Logs melden. **Auf einem im Straßenverkehr genutzten Roller weder Controller-Versorgung noch CAN eigens unterbrechen.** Auf dem Prüfaufbau soll erst anhaltender Empfang oder eine Antwort auf eine Wiederherstellungsanfrage E20 löschen, nicht ein einzelnes beliebiges Datenpaket.
- Falls der optionale Cloud-Client installiert ist, normale Telemetrie und Fernbefehle prüfen. Die ECU-Firmwarekennung soll korrekt übertragen werden, wenn der Controller sie meldet. Ungültige Befehle und fehlerhafte gespeicherte Konfiguration dürfen den Client nicht abstürzen lassen; solche Eingaben nur in einer kontrollierten Testumgebung erzeugen.

Die Prüfungen des [vorigen Testing-Builds](https://github.com/librescoot/librescoot/releases/tag/testing-20260927T212059) bleiben wichtig: Routenwahl am Tacho, Web-Oberfläche und Update-Schätzung, NFC-/Akkuanzeige und MDB-Netzwerk. Eine funktionierende physische Schlüsselkarte als Reserve behalten. Kein Update nur zum Test des Upload-Formulars installieren.
