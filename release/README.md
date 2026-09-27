# Feldarmbrust Release 1.1

## Downloads

- `Feldarmbrust_Server_Windows.zip`: Windows-Server als fertiges Paket. ZIP vollständig entpacken und `Feldarmbrust_Server.exe` starten.
- `Feldarmbrust_Tablet_App-debug.apk`: Android-Tablet-App für die manuelle Installation.
- `Feldarmbrust_Installationsanleitung.docx`: Schritt-für-Schritt-Anleitung für Server, Zertifikat, Tablet und geänderte Netzwerke.

## Hinweise

- Die Debug-APK ist nicht für den Play Store signiert, aber für die manuelle Installation geeignet.
- Beim ersten Serverstart richtet die EXE den Server ein, erzeugt automatisch HTTPS-Zertifikate und fragt nach einem Server-Passwort/API-Key. Enter verwendet `1234`.
- Die Tablet-Setup-Seite ist unter `https://<Server-IP>:8000/setup` erreichbar.
- Am Tablet zuerst `https://<Server-IP>:8000/ca.cer` öffnen und das Zertifikat als CA-Zertifikat installieren.
- Danach in der App `https://<Server-IP>:8000` und das Server-Passwort/API-Key eintragen.
- Server und Tablet müssen im selben Netzwerk sein. Ändert sich die IP-Adresse, Server neu starten und die Adresse in der App aktualisieren.

## SHA-256

- `Feldarmbrust_Server_Windows.zip`: `441BA64C8922E645E72AF21A847638A00A32D500AA141D2D3548D8C8A3C4CB8C`
- `Feldarmbrust_Tablet_App-debug.apk`: `8875AFB48FD9AA8C8554494A9141FF0EB53EE461B8B4854E563B51886CDE3C5B`
