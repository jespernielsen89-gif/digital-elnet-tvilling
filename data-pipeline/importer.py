import os
import json
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Bounding box for Danmark: Syd, Vest, Nord, Øst
# Henter både substations (nodes/ways) og højspændingsledninger (ways)
OVERPASS_QUERY = """
[out:json][timeout:60];
(
  node["power"="substation"](54.5, 8.0, 57.8, 15.2);
  way["power"="line"](54.5, 8.0, 57.8, 15.2);
);
out body;
>;
out skel qt;
"""

def fetch_and_save_geojson():
    print("Henter substations og power lines fra OpenStreetMap...")
    headers = {'User-Agent': 'DigitalElnetTvillingMVP/1.0'}
    response = requests.post(OVERPASS_URL, data={'data': OVERPASS_QUERY}, headers=headers)
    response.raise_for_status()
    data = response.json()

    # Gem noder i et opslagsværk til brug for linjer
    nodes_coords = {}
    for element in data.get('elements', []):
        if element.get('type') == 'node':
            nodes_coords[element['id']] = (float(element['lon']), float(element['lat']))

    features = []

    for element in data.get('elements', []):
        tags = element.get('tags', {})
        
        # 1. Behandl transformerstationer (Points)
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

        # 2. Behandl højspændingsledninger (LineStrings)
        elif element.get('type') == 'way' and tags.get('power') == 'line':
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
    """Hjælpefunktion til at trække det højeste spændingstal ud til farvekodning"""
    if not voltage_str:
        return 0
    try:
        # Håndterer f.eks. "400000;150000" eller "400 kV"
        cleaned = voltage_str.replace('kV', '000').replace(' ', '')
        numbers = [int(s) for s in cleaned.replace(';', ' ').split() if s.isdigit()]
        return max(numbers) if numbers else 0
    except Exception:
        return 0

if __name__ == "__main__":
    fetch_and_save_geojson()
