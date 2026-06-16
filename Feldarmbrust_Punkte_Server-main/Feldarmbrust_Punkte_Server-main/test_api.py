#!/usr/bin/env python3
"""
Testskript für die API-Endpunkte des Feldarmbrust Punkteerfassungssystems
"""

import requests
import json
import time

# Server URL
BASE_URL = "http://localhost:8000"

def test_api():
    """Testet alle wichtigen API-Endpunkte"""
    
    print("API-Test für Feldarmbrust Punkteerfassung")
    print("=" * 50)
    
    # 1. Health Check
    print("1. Health Check...")
    try:
        response = requests.get(f"{BASE_URL}/health", headers={"X-API-KEY": "1234"})
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.json()}")
    except Exception as e:
        print(f"   Fehler: {e}")
        return
    
    # 2. Schützen anlegen
    print("\n2. Schützen anlegen...")
    shooters = [
        {"id": "shooter001", "name": "Max Mustermann", "club": "SC Waldheim", "start_number": "201"},
        {"id": "shooter002", "name": "Erika Musterfrau", "club": "BSC Bergstadt", "start_number": "202"},
        {"id": "shooter003", "name": "Fritz Testmann", "club": "SV Talbach", "start_number": "203"}
    ]
    
    for shooter in shooters:
        try:
            response = requests.post(f"{BASE_URL}/shooters", json=shooter, headers={"X-API-KEY": "1234"})
            print(f"   {shooter['name']}: {response.status_code} - {response.json()}")
        except Exception as e:
            print(f"   Fehler bei {shooter['name']}: {e}")
    
    # 3. Serien anlegen
    print("\n3. Serien anlegen...")
    series = [
        {"id": "series001", "shooter_id": "shooter001", "round_number": 1, "shots_per_series": 6},
        {"id": "series002", "shooter_id": "shooter002", "round_number": 1, "shots_per_series": 6},
        {"id": "series003", "shooter_id": "shooter001", "round_number": 2, "shots_per_series": 6}
    ]
    
    for s in series:
        try:
            response = requests.post(f"{BASE_URL}/series", json=s, headers={"X-API-KEY": "1234"})
            print(f"   Serie {s['id']}: {response.status_code} - {response.json()}")
        except Exception as e:
            print(f"   Fehler bei Serie {s['id']}: {e}")
    
    # 4. Schüsse eintragen
    print("\n4. Schüsse eintragen...")
    shots = [
        {"series_id": "series001", "shot_number": 1, "score": 9.5},
        {"series_id": "series001", "shot_number": 2, "score": 8.0},
        {"series_id": "series001", "shot_number": 3, "score": 10.0},
        {"series_id": "series001", "shot_number": 4, "score": 7.5},
        {"series_id": "series001", "shot_number": 5, "score": 9.0},
        {"series_id": "series001", "shot_number": 6, "score": 8.5},
        
        {"series_id": "series002", "shot_number": 1, "score": 8.5},
        {"series_id": "series002", "shot_number": 2, "score": 9.0},
        {"series_id": "series002", "shot_number": 3, "score": 7.0},
        {"series_id": "series002", "shot_number": 4, "score": 9.5},
        {"series_id": "series002", "shot_number": 5, "score": 8.0},
        {"series_id": "series002", "shot_number": 6, "score": 10.0},
    ]
    
    for shot in shots:
        try:
            response = requests.post(f"{BASE_URL}/series/{shot['series_id']}/shot", 
                                   json={"shot_number": shot["shot_number"], "score": shot["score"]},
                                   headers={"X-API-KEY": "1234"})
            print(f"   Schuss {shot['shot_number']} (Serie {shot['series_id']}): {response.status_code}")
        except Exception as e:
            print(f"   Fehler bei Schuss {shot['shot_number']}: {e}")
    
    # 5. Wettkampfzustand abrufen
    print("\n5. Wettkampfzustand abrufen...")
    try:
        response = requests.get(f"{BASE_URL}/state", headers={"X-API-KEY": "1234"})
        if response.status_code == 200:
            state = response.json()
            stats = state["statistics"]
            leaderboard = state["leaderboard"]
            
            print(f"   Schützen: {stats['total_shooters']}")
            print(f"   Serien: {stats['total_series']}")
            print(f"   Schüsse: {stats['total_shots']}")
            print(f"   Ø Punktzahl: {stats['average_score']:.2f}")
            
            print("\n   Bestenliste:")
            for i, entry in enumerate(leaderboard, 1):
                start_no = entry['shooter'].get('start_number', '-')
                print(f"   {i}. [{start_no}] {entry['shooter']['name']} ({entry['shooter'].get('country', '-')}): {entry['total_score']:.1f}")
        else:
            print(f"   Fehler: {response.status_code}")
    except Exception as e:
        print(f"   Fehler: {e}")
    
    # 6. Excel-Export testen
    print("\n6. Excel-Export testen...")
    try:
        response = requests.get(f"{BASE_URL}/export", headers={"X-API-KEY": "1234"})
        if response.status_code == 200:
            print(f"   Excel-Export erfolgreich: {len(response.content)} Bytes")
            # Speichern als Testdatei
            with open("test_export.xlsx", "wb") as f:
                f.write(response.content)
            print("   Als 'test_export.xlsx' gespeichert")
        else:
            print(f"   Fehler: {response.status_code}")
    except Exception as e:
        print(f"   Fehler: {e}")
    
    print("\n" + "=" * 50)
    print("API-Test abgeschlossen!")
    print("Öffnen Sie http://localhost:8000 im Browser für die Web-UI")

if __name__ == "__main__":
    test_api()
