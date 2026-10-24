import os
import json
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Bruger en bounding box for Danmark (Syd, Vest, Nord, Øst) i stedet for 'area'
OVERPASS_QUERY = """
[out:json][timeout:30];
(
  node["power"="substation"](54.5, 8.0, 57.8, 15.2);
);
out body;
"""

def fetch_and_save_geojson():
    print("Henter substations fra OpenStreetMap...")
    headers = {'User-Agent': 'DigitalElnetTvillingMVP/1.0'}
    response = requests.post(OVERPASS_URL, data={'data': OVERPASS_QUERY}, headers=headers)
    response.raise_for_status()
    data = response.json()

    features = []
    for element in data.get('elements', []):
        if element.get('type') == 'node' and 'tags' in element:
            tags = element['tags']
            lat = element.get('lat')
            lon = element.get('lon')
            
            if lat and lon:
                feature = {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(lon), float(lat)]
                    },
                    "properties": {
                        "mRID": str(element['id']),
                        "name": tags.get('name', 'Ukendt Station'),
                        "voltage": tags.get('voltage', '150kV/400kV'),
                        "confidence_tier": 1,
                        "data_provenance": "OpenStreetMap_Verified"
                    }
                }
                features.append(feature)

    geojson_collection = {
        "type": "FeatureCollection",
        "features": features
    }

    os.makedirs("frontend", exist_ok=True)
    file_path = "frontend/substations.geojson"
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(geojson_collection, f, ensure_ascii=False, indent=2)
        
    print(f"Succes! {len(features)} substations gemt i {file_path}")

if __name__ == "__main__":
    fetch_and_save_geojson()
