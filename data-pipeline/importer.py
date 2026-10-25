import os
import json
import osmium
from pyrosm import get_data
from neo4j import GraphDatabase

class PowerHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.features = []
        self.lines_data = []

    def node(self, n):
        if 'power' in n.tags and n.tags['power'] == 'substation':
            if n.location.valid():
                voltage_str = n.tags.get('voltage', '')
                voltage_val = parse_voltage(voltage_str)
                confidence_tier = 1 if 'Energinet' in n.tags.get('operator', '') else 3

                self.features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [n.location.lon, n.location.lat]
                    },
                    "properties": {
                        "mRID": f"substation-{n.id}",
                        "name": n.tags.get('name', 'Ukendt Station'),
                        "voltage": voltage_str if voltage_str else 'Ukendt',
                        "voltage_int": voltage_val,
                        "type": "substation",
                        "operator": n.tags.get('operator', 'Ukendt operatør'),
                        "confidence_tier": confidence_tier,
                        "source": "OpenStreetMap"
                    }
                })

    def way(self, w):
        if 'power' in w.tags and w.tags['power'] == 'line':
            voltage_str = w.tags.get('voltage', '')
            voltage_val = parse_voltage(voltage_str)
            
            if voltage_val == 0 or voltage_val >= 132000:
                coords = []
                for nd in w.nodes:
                    if nd.location.valid():
                        coords.append([nd.location.lon, nd.location.lat])
                
                if len(coords) >= 2:
                    confidence_tier = 1 if 'Energinet' in w.tags.get('operator', '') else 3

                    # Gem til GeoJSON frontend
                    self.features.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": coords
                        },
                        "properties": {
                            "mRID": f"line-{w.id}",
                            "name": w.tags.get('name', 'Højspændingsledning'),
                            "voltage": voltage_str if voltage_str else 'Ukendt',
                            "voltage_int": voltage_val,
                            "type": "line",
                            "operator": w.tags.get('operator', 'Ukendt operatør'),
                            "confidence_tier": confidence_tier,
                            "source": "OpenStreetMap"
                        }
                    })

                    # Gem også metadata til topologi / CONNECTS_TO i Neo4j
                    # Vi gemmer start- og slutkoordinater for at kunne koble til nærmeste station
                    self.lines_data.append({
                        "mRID": f"line-{w.id}",
                        "name": w.tags.get('name', 'Højspændingsledning'),
                        "voltage_int": voltage_val,
                        "start_lat": coords[0][1],
                        "start_lon": coords[0][0],
                        "end_lat": coords[-1][1],
                        "end_lon": coords[-1][0]
                    })

def parse_voltage(voltage_str):
    if not voltage_str:
        return 0
    try:
        cleaned = voltage_str.replace('kV', '000').replace(' ', '')
        numbers = [int(s) for s in cleaned.replace(';', ' ').split() if s.isdigit()]
        return max(numbers) if numbers else 0
    except Exception:
        return 0

def sync_to_neo4j(features, lines_data):
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    if not uri or not user or not password:
        print("Neo4j miljøvariabler ikke fundet. Springer database-synkronisering over.")
        return

    print("Forbinder til Neo4j AuraDB for at synkronisere noder og topologi...")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        # 1. Opret substation-noder
        substation_count = 0
        for f in features:
            props = f["properties"]
            if props["type"] == "substation":
                lon, lat = f["geometry"]["coordinates"]
                session.run(
                    """
                    MERGE (s:Substation {mRID: $mRID})
                    SET s.name = $name,
                        s.voltage = $voltage,
                        s.voltage_int = $voltage_int,
                        s.operator = $operator,
                        s.confidence_tier = $confidence_tier,
                        s.source = $source,
                        s.lat = $lat,
                        s.lon = $lon
                    """,
                    mRID=props["mRID"],
                    name=props["name"],
                    voltage=props["voltage"],
                    voltage_int=props["voltage_int"],
                    operator=props["operator"],
                    confidence_tier=props["confidence_tier"],
                    source=props["source"],
                    lat=lat,
                    lon=lon
                )
                substation_count += 1
        print(f"Synkroniserede {substation_count} stationer til Neo4j.")

        # 2. Opret CONNECTS_TO relationer baseret på linjernes endepunkter og geografisk nærhed til stationer
        print("Opretter topologiske CONNECTS_TO relationer...")
        # Vi matcher linjens start/slut med stationer inden for ca. 1.5 km (~0.015 grader) for at binde nettet sammen
        session.run(
            """
            UNWIND $lines AS l
            MATCH (s1:Substation)
            WHERE abs(s1.lat - l.start_lat) < 0.015 AND abs(s1.lon - l.start_lon) < 0.015
            MATCH (s2:Substation)
            WHERE abs(s2.lat - l.end_lat) < 0.015 AND abs(s2.lon - l.end_lon) < 0.015 AND s1.mRID <> s2.mRID
            MERGE (s1)-[r:CONNECTS_TO {line_mRID: l.mRID}]->(s2)
            SET r.name = l.name,
                r.voltage_int = l.voltage_int
            """
        , lines=lines_data)
        print("Topologiske relationer oprettet succesfuldt!")

    driver.close()

def fetch_and_save_geojson():
    print("Henter Danmarks OpenStreetMap PBF-fil fra Geofabrik...")
    fp = get_data("Denmark", directory="data")
    
    print("Parser elnet-komponenter lokalt med osmium...")
    handler = PowerHandler()
    handler.apply_file(fp, locations=True)

    geojson_collection = {
        "type": "FeatureCollection",
        "features": handler.features
    }

    os.makedirs("frontend", exist_ok=True)
    file_path = "frontend/substations.geojson"
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(geojson_collection, f, ensure_ascii=False, indent=2)
        
    print(f"Succes! {len(handler.features)} elementer gemt i {file_path}")

    # Synkroniser noder og topologi til Neo4j AuraDB
    sync_to_neo4j(handler.features, handler.lines_data)

if __name__ == "__main__":
    fetch_and_save_geojson()
