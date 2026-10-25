import os
import json
import osmium
from pyrosm import get_data
from neo4j import GraphDatabase

class PowerHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.features = []
        self.substation_node_ids = set()
        self.lines_topology = []

    def node(self, n):
        if 'power' in n.tags and n.tags['power'] == 'substation':
            if n.location.valid():
                voltage_str = n.tags.get('voltage', '')
                voltage_val = parse_voltage(voltage_str)
                confidence_tier = 1 if 'Energinet' in n.tags.get('operator', '') else 3

                sub_mRID = f"substation-{n.id}"
                self.substation_node_ids.add(n.id)

                self.features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [n.location.lon, n.location.lat]
                    },
                    "properties": {
                        "mRID": sub_mRID,
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
                way_substations = []

                for nd in w.nodes:
                    if nd.location.valid():
                        coords.append([nd.location.lon, nd.location.lat])
                    
                    # Tjek om denne node i linjen også er en transformerstation
                    if nd.ref in self.substation_node_ids:
                        sub_id = f"substation-{nd.ref}"
                        if sub_id not in way_substations:
                            way_substations.append(sub_id)
                
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

                    # Hvis linjen berører 2 eller flere stationer, danner den relationer imellem dem
                    if len(way_substations) >= 2:
                        for i in range(len(way_substations) - 1):
                            self.lines_topology.append({
                                "line_mRID": f"line-{w.id}",
                                "name": w.tags.get('name', 'Højspændingsledning'),
                                "voltage_int": voltage_val,
                                "source_sub": way_substations[i],
                                "target_sub": way_substations[i+1]
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

def sync_to_neo4j(features, lines_topology):
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

        # 2. Opret CONNECTS_TO relationer baseret på delte node-id'er
        print(f"Opretter {len(lines_topology)} topologiske CONNECTS_TO relationer...")
        session.run(
            """
            UNWIND $topology AS t
            MATCH (s1:Substation {mRID: t.source_sub})
            MATCH (s2:Substation {mRID: t.target_sub})
            MERGE (s1)-[r:CONNECTS_TO {line_mRID: t.line_mRID}]->(s2)
            SET r.name = t.name,
                r.voltage_int = t.voltage_int
            """
        , topology=lines_topology)
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
    sync_to_neo4j(handler.features, handler.lines_topology)

if __name__ == "__main__":
    fetch_and_save_geojson()
