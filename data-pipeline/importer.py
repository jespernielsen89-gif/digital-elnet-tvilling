import os
import json
import requests
import time

OVERPASS_URL = "https://overpass.kumi.systems/api/interpreter"

# 1. Forespørgsel udelukkende til transformerstationer (Points)
SUBSTATION_QUERY = """
[out:json][timeout:60];
node["power"="substation"](54.5, 8.0, 57.8, 15.2);
out body;
"""

# 2. Forespørgsel udelukkende til højspændingsledninger (LineStrings)
LINE_QUERY = """
[out:json][timeout:90];
(
  way["power"="line"]["voltage"~"132000|150000|400000"](54.5, 8.0, 57.8, 15.2);
  way["power"="line"][!"voltage"](54.5, 8.0, 57.8, 15.2);
);
out body;
>;
out skel qt;
"""

def query_overpass(query):
    headers = {'User-Agent': 'DigitalElnetTvillingMVP/1.0'}
    for attempt in range(3):
        try:
            response = requests.post(OVERPASS_URL, data={'data': query}, headers=headers, timeout=90)
            if response.status_code == 200:
                return response.json()
            print(f"Forsøg {attempt + 1} gav status {response.status_code}, prøver igen...")
        except Exception as e:
            print(f"Netværksfejl ved forsøg {attempt + 1}: {e}")
        time.sleep(5)
    return None

def fetch_and_save_geojson():
    print("Henter transformerstationer (punkt-data)...")
    sub_data = query_overpass(SUBSTATION_QUERY)
    if not sub_data:
        raise Exception("Kunne ikke hente stationer fra Overpass API.")

    print("Henter højspændingsledninger (linje-data)...")
    line_data = query_overpass(LINE_QUERY)
    if not line_data:
        raise Exception("Kunne ikke hente ledninger fra Overpass API.")

    features = []

    # Behandl stationer
    for element in sub_data.get('elements', []):
        tags = element.get('tags', {})
        if element.get('type') == 'node' and tags.get('power') == 'substation':
            lat = element.get('lat')
            lon = element.get('lon')
            if lat and lon:
                voltage_str = tags.get('voltage', '')
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(lon), float(lat)]
                    },
                    "properties": {
                        "mRID": str(element['id']),
                        "name": tags.get('name', 'Ukendt Station'),
                        "voltage": tags.get('voltage', 'Ukendt'),
                        "voltage_int": parse_voltage(voltage_str),
                        "type": "substation",
                        "operator": tags.get('operator', 'Ukendt operatør')
                    }
                })

    # Udtræk noder til koordinater for ledninger
    nodes_coords = {}
    for element in line_data.get('elements', []):
        if element.get('type') == 'node':
            nodes_coords[element['id']] = (float(element['lon']), float(element['lat']))

    # Behandl ledninger
    for element in line_data.get('elements', []):
        tags = element.get('tags', {})
        if element.get('type') == 'way' and tags.get('power') == 'line':
            way_nodes = element.get('nodes', [])
            coordinates = [nodes_coords[node_id] for node_id in way_nodes if node_id in nodes_coords]
            
            if len(coordinates) >= 2:
                voltage_str = tags.get('voltage', '')
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coordinates
                    },
                    "properties": {
                        "mRID": str(element['id']),
                        "name": tags.get('name', 'Højspændingsledning'),
                        "voltage": tags.get('voltage', 'Ukendt'),
                        "voltage_int": parse_voltage(voltage_str),
                        "type": "line",
                        "operator": tags.get('operator', 'Ukendt operatør')
                    }
                })

    geojson_collection = {
        "type": "FeatureCollection",
        "features": features
    }

    os.makedirs("frontend", exist_ok=True)
    file_path = "frontend/substations.geojson"
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(geojson_collection, f, ensure_ascii=False, indent=2)
        
    print(f"Succes! {len(features)} elementer (stationer og ledninger) gemt i {file_path}")

def parse_voltage(voltage_str):
    if not voltage_str:
        return 0
    try:
        cleaned = voltage_str.replace('kV', '000').replace(' ', '')
        numbers = [int(s) for s in cleaned.replace(';', ' ').split() if s.isdigit()]
        return max(numbers) if numbers else 0
    except Exception:
        return 0

if __name__ == "__main__":
    fetch_and_save_geojson()
