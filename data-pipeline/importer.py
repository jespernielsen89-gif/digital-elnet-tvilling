import os
import json
import osmium
from pyrosm import get_data
from neo4j import GraphDatabase
from shapely.geometry import Point

class PowerHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.features = []
        self.substations_list = []
        self.raw_lines = []

    def node(self, n):
        if 'power' in n.tags and n.tags['power'] == 'substation':
            if n.location.valid():
                voltage_str = n.tags.get('voltage', '')
                voltage_val = parse_voltage(voltage_str)
                confidence_tier = 1 if 'Energinet' in n.tags.get('operator', '') else 3

                sub_mRID = f"substation-{n.id}"
                
                self.substations_list.append({
                    "mRID": sub_mRID,
                    "lon": n.location.lon,
                    "lat": n.location.lat
                })

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
                for nd in w.nodes:
                    if nd.location.valid():
                        coords.append([nd.location.lon, nd.location.lat])
                
                if len(coords) >= 2:
                    confidence_tier = 1 if 'Energinet' in w.tags.get('operator', '') else 3

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

                    self.raw_lines.append({
                        "mRID": f"line-{w.id}",
                        "name": w.tags.get('name', 'Højspændingsledning'),
                        "voltage_int": voltage_val,
                        "start_coord": coords[0],
                        "end_coord": coords[-1]
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

def build_topology(raw_lines, substations):
    print(f"Analyserer topologi for {len(raw_lines)} linjer og {len(substations)} stationer...")
    if not substations or not raw_lines:
        print("Advarsel: Mangler enten stationer eller linjer til topologi-bygning!")
        return []

    sub_points = [(s["mRID"], Point(s["lon"], s["lat"])) for s in substations]
    topology = []
    max_dist_deg = 0.03 # Udvidet tolerance til ca. 3 km for bedre match

    match_count = 0
    for line in raw_lines:
        start_pt = Point(line["start_coord"][0], line["start_coord"][1])
        end_pt = Point(line["end_coord"][0], line["end_coord"][1])

        closest_start = None
        min_start_dist = float('inf')
        closest_end = None
        min_end_dist = float('inf')

        for sub_id, sub_pt in sub_points:
            d_start = start_pt.distance(sub_pt)
            if d_start < min_start_dist:
                min_start_dist = d_start
                closest_start = sub_id

            d_end = end_pt.distance(sub_pt)
            if d_end < min_end_dist:
                min_end_dist = d_end
                closest_end = sub_id

        if closest_start and closest_end and closest_start != closest_end:
            if min_start_dist <= max_dist_deg and min_end_dist <= max_dist_deg:
                topology.append({
                    "line_mRID": line["mRID"],
                    "name": line["name"],
                    "voltage_int": line["voltage_int"],
                    "source_sub": closest_start,
                    "target_sub": closest_end
                })
                match_count += 1

    print(f"Byg-topologi fuldført: Fandt {match_count} gyldige relationer ud af {len(raw_lines)} linjer.")
    return topology

def sync_to_neo4j(features, topology):
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    if not uri or not user or not password:
        print("Neo4j miljøvariabler ikke fundet. Springer database-synkronisering over.")
        return

    print("Forbinder til Neo4j AuraDB...")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        # 1. Opret noder
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

        # 2. Opret relationer hvis listen ikke er tom
        if topology:
            print(f"Skriver {len(topology)} CONNECTS_TO relationer til Neo4j...")
            result = session.run(
                """
                UNWIND $topology AS t
                MATCH (s1:Substation {mRID: t.source_sub})
                MATCH (s2:Substation {mRID: t.target_sub})
                MERGE (s1)-[r:CONNECTS_TO {line_mRID: t.line_mRID}]->(s2)
                SET r.name = t.name,
                    r.voltage_int = t.voltage_int
                RETURN count(r) as created_count
                """
            , topology=topology)
            record = result.single()
            print(f"Bekræftet: Oprettet/opdateret {record['created_count']} relationer i Neo4j.")
        else:
            print("Advarsel: Ingen topologi-relationer at skrive til Neo4j!")

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

    topology = build_topology(handler.raw_lines, handler.substations_list)
    sync_to_neo4j(handler.features, topology)

if __name__ == "__main__":
    fetch_and_save_geojson()
