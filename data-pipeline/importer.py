import os
import json
from pyrosm import OSM, get_data

def fetch_and_save_geojson():
    print("Henter Danmarks OpenStreetMap-data fra Geofabrik (lokalt uden API-timeouts)...")
    
    # Henter automatisk den seneste PBF-fil for Danmark (og cachen håndteres af pyrosm)
    fp = get_data("Denmark", directory="data")
    osm = OSM(fp)

    print("Udtrækker transformerstationer og højspændingsledninger lokalt...")
    
    # 1. Hent transformerstationer (punkter/polygoner)
    substations_gdf = osm.get_data(custom_filter={"power": ["substation"]})
    
    # 2. Hent højspændingsledninger (linjer)
    lines_gdf = osm.get_data(custom_filter={"power": ["line"]})

    features = []

    # Behandl stationer
    if not substations_gdf.empty:
        for _, row in substations_gdf.iterrows():
            geom = row.geometry
            if geom is not None:
                if geom.geom_type in ['Polygon', 'MultiPolygon']:
                    geom = geom.centroid
                
                if geom.geom_type == 'Point':
                    voltage_str = str(row.get('voltage', ''))
                    features.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [float(geom.x), float(geom.y)]
                        },
                        "properties": {
                            "mRID": str(row.get('id', '')),
                            "name": str(row.get('name', 'Ukendt Station')),
                            "voltage": voltage_str if voltage_str != 'nan' else 'Ukendt',
                            "voltage_int": parse_voltage(voltage_str),
                            "type": "substation",
                            "operator": str(row.get('operator', 'Ukendt operatør'))
                        }
                    })

    # Behandl højspændingsledninger
    if not lines_gdf.empty:
        for _, row in lines_gdf.iterrows():
            geom = row.geometry
            if geom is not None and geom.geom_type in ['LineString', 'MultiLineString']:
                coords = []
                if geom.geom_type == 'LineString':
                    coords = list(geom.coords)
                elif geom.geom_type == 'MultiLineString':
                    for part in geom.geoms:
                        coords.extend(list(part.coords))
                
                if len(coords) >= 2:
                    voltage_str = str(row.get('voltage', ''))
                    voltage_val = parse_voltage(voltage_str)
                    
                    # Behold højspænding og udefinerede linjer
                    if voltage_val == 0 or voltage_val >= 132000:
                        features.append({
                            "type": "Feature",
                            "geometry": {
                                "type": "LineString",
                                "coordinates": [[float(c[0]), float(c[1])] for c in coords]
                            },
                            "properties": {
                                "mRID": str(row.get('id', '')),
                                "name": str(row.get('name', 'Højspændingsledning')),
                                "voltage": voltage_str if voltage_str != 'nan' else 'Ukendt',
                                "voltage_int": voltage_val,
                                "type": "line",
                                "operator": str(row.get('operator', 'Ukendt operatør'))
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
        
    print(f"Succes! {len(features)} elementer gemt i {file_path}")

def parse_voltage(voltage_str):
    if not voltage_str or voltage_str == 'nan':
        return 0
    try:
        cleaned = voltage_str.replace('kV', '000').replace(' ', '')
        numbers = [int(s) for s in cleaned.replace(';', ' ').split() if s.isdigit()]
        return max(numbers) if numbers else 0
    except Exception:
        return 0

if __name__ == "__main__":
    fetch_and_save_geojson()
