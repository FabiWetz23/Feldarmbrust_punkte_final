# Feldarmbrust Punkteerfassungssystem

Ein zentraler Server für die drahtlose Punkteerfassung bei Feldarmbrust-Wettkämpfen mit Excel-Auswertung.

## Projektstruktur

```
windsurf-project/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI Server mit allen Endpunkten
│   ├── models.py            # Pydantic Datenmodelle
│   ├── excel_export.py      # Excel-Export Logik
│   └── static/
│       └── index.html       # Admin Web-UI
├── start_server.py          # Einfaches Startskript
├── test_api.py             # API-Testskript
├── requirements.txt
└── README.md
```

## Installation (Windows)

### 1. Python installieren
- Python 3.8+ von [python.org](https://python.org) herunterladen
- Bei Installation "Add Python to PATH" aktivieren

### 2. Virtuelle Umgebung erstellen
```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Abhängigkeiten installieren
```bash
pip install -r requirements.txt
```

### 4. Server starten
```bash
python start_server.py
```

Oder alternativ:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Verwendung

### Server-Zugriffe
- **Web-UI**: http://localhost:8000
- **API-Dokumentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

### API-Endpunkte

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| GET | `/state` | Gesamter Wettkampfzustand |
| POST | `/shooters` | Schützen anlegen/ändern |
| POST | `/shooters/{id}` | Schützen aktualisieren |
| DELETE | `/shooters/{id}` | Schützen löschen |
| POST | `/series` | Serie anlegen/ändern |
| DELETE | `/series/{id}` | Serie löschen |
| POST | `/series/{id}/shot` | Schuss setzen/korrigieren |
| DELETE | `/series/{id}/shot/{num}` | Schuss löschen |
| GET | `/export` | Excel-Datei herunterladen |

### Testen der API
```bash
python test_api.py
```

## Tablet-Verbindung

Tablets verbinden sich über WLAN mit dem Server:

1. **Server-IP ermitteln**: In Windows-Eingabeaufforderung `ipconfig` ausführen
2. **Tablet-Verbindung**: Browser auf Tablet öffnen und `http://<SERVER-IP>:8000` aufrufen
3. **Daten senden**: Über HTTP-POST an die API-Endpunkte senden

### Beispiel für Tablet-Client
### Sichere Tablet-Verbindung mit HTTPS

1. **Server-IP ermitteln**: In Windows-Eingabeaufforderung `ipconfig` ausfuehren
2. **TLS-Zertifikat erzeugen**: In WSL im Server-Verzeichnis `bash scripts/create_tls_cert.sh <SERVER-IP>` ausfuehren
3. **Server mit HTTPS starten**:
   ```bash
   export FELDARMBRUST_API_KEY="ein-langes-geheimes-passwort"
   export FELDARMBRUST_TLS_CERTFILE="certs/server.crt"
   export FELDARMBRUST_TLS_KEYFILE="certs/server.key"
   python start_server.py
   ```
4. **Tablet-Verbindung**: Im Tablet-Client `https://<SERVER-IP>:8000` als Server-URL eintragen

Wichtig: Bei einem selbstsignierten Zertifikat muss das Tablet dem Zertifikat einmal vertrauen. Ohne vertrauenswuerdiges Zertifikat kann der Browser nicht sicher erkennen, ob er wirklich mit dem Laptop spricht.

Geschuetzte API-Endpunkte blockieren unverschluesselte WLAN-Zugriffe automatisch. Nur lokale Aufrufe vom Laptop selbst duerfen HTTP fuer Tests verwenden. Fuer unsichere Entwicklung kann temporaer `FELDARMBRUST_ALLOW_INSECURE_HTTP=1` gesetzt werden.

```javascript
// Schützen anlegen
fetch('https://192.168.1.100:8000/shooters', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        id: 'tablet001',
        name: 'Tablet Schütze',
        club: 'Tablet Verein'
    })
});

// Schuss eintragen
fetch('https://192.168.1.100:8000/series/series001/shot', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        shot_number: 1,
        score: 9.5
    })
});
```

## Features

### ✅ Implementiert
- **Server**: FastAPI mit REST-API
- **Datenmodelle**: Pydantic mit Validierung
- **Excel-Export**: openpyxl mit Formatierung
- **Web-UI**: Live-Anzeige und Admin-Interface
- **Validierung**: Punktewerte in 0.5-Schritten
- **Berechnungen**: Automatische Summen und Bestenliste
- **Korrekturen**: Schüsse nachträglich bearbeitbar

### 🔧 Technische Details
- **In-Memory-Speicher**: Keine Datenbank erforderlich
- **Auto-Reload**: Entwicklung mit Live-Neustart
- **CORS-fähig**: Tablets können von überall im WLAN zugreifen
- **Fehlerbehandlung**: Detaillierte HTTP-Statuscodes
- **Logging**: Automatische Protokollierung

## Excel-Export Format

Die Excel-Datei enthält:
- **Metadaten**: Wettkampfname, Exportzeitpunkt
- **Überschriften**: Name, Verein, Durchgang, Schuss 1-n, Serien-Summe, Gesamt-Summe
- **Formatierung**: Professionelles Layout mit Farben und Rahmen
- **Berechnungen**: Automatische Summenbildung

## Fehlerbehebung

### Port 8000 belegt
```bash
# Anderen Port verwenden
uvicorn app.main:app --port 8001
```

### Firewall-Probleme
- Windows Firewall für Port 8000 zulassen
- Antivirus-Software temporär deaktivieren

### Tablets können nicht verbinden
1. Server-IP überprüfen (`ipconfig`)
2. Ping-Test von Tablet aus
3. Firewall-Einstellungen prüfen

## Lizenz

Dieses Projekt ist Open Source und kann frei für Feldarmbrust-Wettkämpfe verwendet werden.
