import os
import json
import requests
import time

OVERPASS_URL = "https://overpass.kumi.systems/api/interpreter"

# Vi opdeler Danmark i tre geografiske zoner for at undgå timeouts på store forespørgsler
REGIONS = [
    {"name": "Jylland", "box": "(54.5, 8.0, 57.8, 9.5)"},
    {"name": "Fyn & Midt", "box": "(54.8, 9.5, 57.8, 11.0)"},
    {"name": "Sjælland & Øer", "box": "(54.5, 11.0, 57.8, 15.2)"}
]

def query_overpass(query):
    headers = {'User-Agent': 'DigitalElnetTvillingMVP/1.0'}
    for attempt in range(3):
        try:
            response = requests.post(OVERPASS_URL, data={'data': query}, headers=headers, timeout=60)
            if response.status_code == 200:
                return response.json()
            print(f"Forsøg {attempt + 1} gav status {response.status_code}, prøver igen...")
        except Exception as e:
            print(f"Netværksfejl ved forsøg {attempt + 1}: {e}")
        time.sleep(3)
    return None

def fetch_and_save_geojson():
    all_elements = []
    
    # 1. Hent stationer zone for zone
    print("Henter transformerstationer zone for zone...")
    for reg in REGIONS:
        print(f" -> Henter {reg['name']}...")
        query = f"""
        [out:json][timeout:30];
        node["power"="substation"]{reg['box']};
        out body;
        """
        data = query_overpass(query)
        if data and 'elements' in data:
            all_elements.extend(data['elements'])
        time.sleep(2) # Skånsom pause mellem zoner

    # 2. Hent højspændingsledninger (kun de vigtigste spændinger)
    print("Henter højspændingsledninger for landet...")
    line_query = """
    [out:json][timeout:60];
    (
      way["power"="line"]["voltage"~"132000|150000|400000"](54.5, 8.0, 57.8, 15.2);
      way["power"="line"][!"voltage"](54.5, 8.0, 57.8, 15.2);
    );
    out body;
    >;
    out skel qt;
    """
    line_data = query_overpass(line_query)
    if line_data and 'elements' in line_data:
        all_elements.extend(line_data['elements'])

    if not all_elements:
        raise Exception("Kunne ikke hente nogen data fra Overpass API.")

    # Fjern duplikater baseret på element ID
    seen_ids = set()
    unique_elements = []
    for el in all_elements:
        if el['id'] not in seen_ids:
            seen_ids.add(el['id'])
            unique_elements.append(el)

    # Utræk noder til koordinater for ledninger
    nodes_coords = {}
    for element in unique_elements:
        if element.get('type') == 'node':
            nodes_coords[element['id']] = (float(element['lon']), float(element['lat']))

    features = []

    for element in unique_elements:
        tags = element.get('tags', {})
        
        # Behandl stationer (Points)
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

        # Behandl ledninger (LineStrings)
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
        
    print(f"Succes! {len(features)} elementer fordelt på stationer og ledninger gemt i {file_path}")

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
