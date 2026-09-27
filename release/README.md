# Feldarmbrust Release-Artefakte

## Downloads

- `Feldarmbrust_Server_Windows.zip`: Windows-Server als fertiges Paket. ZIP entpacken und `Feldarmbrust_Server.exe` starten.
- `Feldarmbrust_Tablet_App-debug.apk`: Android-Tablet-App als Debug-APK zum direkten Installieren auf einem Tablet.

## Hinweise

- Die Debug-APK ist nicht fuer den Play Store signiert, aber zum manuellen Installieren geeignet.
- Beim ersten Serverstart richtet die EXE den Server ein, erzeugt automatisch HTTPS-Zertifikate und fragt nach einem Server-Passwort/API-Key. Enter verwendet `1234`.
- Der Server oeffnet bzw. zeigt eine Tablet-Setup-Seite unter `https://<Laptop-IP>:8000/setup`.
- Am Tablet zuerst das Zertifikat von `https://<Laptop-IP>:8000/ca.cer` herunterladen und als CA-Zertifikat installieren.
- Danach in der App die Server-URL `https://<Laptop-IP>:8000` und das Server-Passwort/API-Key eintragen.
- Server und Tablet muessen im selben Netzwerk sein.

## SHA256

- `Feldarmbrust_Server_Windows.zip`: `BE4C8A9D3963E928A105E1FB5367982719BA4F40695AB446BF86C9D9300B6EBB`
- `Feldarmbrust_Tablet_App-debug.apk`: `5A2BBB82EDBFADFA0C76E02761FF6F8982CD1451249791B7446E28A0A9B6455E`
