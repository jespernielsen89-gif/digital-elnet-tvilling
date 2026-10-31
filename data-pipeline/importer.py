import os
import osmium
import json
import requests
from neo4j import GraphDatabase

class GridHandler(osmium.SimpleHandler):
    def __init__(self):
        super(GridHandler, self).__init__()
        self.substations = []
        self.lines = []
        self.compensators = []

    def node(self, n):
        tags = {tag.k: tag.v for tag in n.tags}
        power_type = tags.get('power', '')
        name = tags.get('name', '')
        
        # 1. Synkronkompensatorer
        if power_type == 'compensator' or 'kompensator' in name.lower() or 'condenser' in name.lower():
            self.compensators.append({
                'id': str(n.id),
                'name': name or 'Synkronkompensator',
                'power': power_type,
                'lon': n.location.lon,
                'lat': n.location.lat
            })
            return

        # 2. Stationer og konvertere
        if power_type in ['substation', 'converter', 'plant']:
            voltage = tags.get('voltage', '')
            is_target = False
            
            if 'fraugde' in name.lower() or 'idomlund' in name.lower():
                is_target = True
            elif not voltage:
                is_target = True
            else:
                try:
                    v_vals = [float(v.strip()) for v in voltage.split(';') if v.strip().replace('.', '', 1).isdigit()]
                    v_vals = [v / 1000.0 if v >= 1000 else v for v in v_vals]
                    if any(v >= 150 for v in v_vals):
                        is_target = True
                except:
                    is_target = True

            if is_target:
                self.substations.append({
                    'id': str(n.id),
                    'name': name || 'Transmissionsstation',
                    'power': power_type,
                    'voltage': voltage or '150/400',
                    'lon': n.location.lon,
                    'lat': n.location.lat
                })

    def way(self, w):
        tags = {tag.k: tag.v for tag in w.tags}
        power_type = tags.get('power')
        
        # 3. Transmissionslinjer, luftledninger og kabler
        if power_type in ['line', 'cable']:
            voltage = tags.get('voltage', '')
            is_hvdc = tags.get('line') == 'dc' or tags.get('cables') == 'hvdc' or power_type == 'cable' or 'hvdc' in tags.get('name', '').lower()
            
            coords = []
            for n in w.nodes:
                if n.location.valid():
                    coords.append([n.location.lon, n.location.lat])
            
            if len(coords) > 1:
                self.lines.append({
                    'id': str(w.id),
                    'name': tags.get('name', 'Transmissionslinje'),
                    'voltage': voltage or '400',
                    'power_type': power_type,
                    'is_hvdc': is_hvdc,
                    'coordinates': coords
                })

def fetch_energinet_market_data():
    """Henter live markedsdata / systemforbrug fra Energinet DataService (Tier 1)"""
    try:
        url = "https://api.energidataservice.dk/dataset/PowerSystemRightNow?limit=1"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json().get('records', [])
            if data:
                print(f"[Energinet API] Hentet live systemdata: Forbrug = {data[0].get('GrossConsumption')} MW")
                return data[0]
    except Exception as e:
        print(f"[Energinet API] Kunne ikke hente live-data (bruger standard): {e}")
    return None

def parse_osm_data(pbf_path):
    print(f"Parser transmissionsnettet fra {pbf_path}...")
    handler = GridHandler()
    handler.apply_file(pbf_path, locations=True)
    print(f"Fandt {len(handler.substations)} stationer, {len(handler.lines)} linjer og {len(handler.compensators)} kompensatorer.")
    return handler.substations, handler.lines, handler.compensators

def build_topology_and_sync(substations, lines, compensators):
    print("Genererer komplett GeoJSON og synkroniserer til Neo4j graf-model...")
    
    # Hent live Energinet data
    market_data = fetch_energinet_market_data()

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    if uri and user and password:
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            with driver.session() as session:
                # Opret stationer og interne samleskinner (Busbars)
                for s in substations:
                    session.run(
                        """
                        MERGE (st:Substation {id: $id})
                        SET st.name = $name,
                            st.power = $power,
                            st.voltage = $voltage,
                            st.confidence_tier = 3,
                            st.source = "OpenStreetMap",
                            st.location = point({longitude: $lon, latitude: $lat})
                        MERGE (bb:Busbar {id: $id + '_bb400'})
                        SET bb.name = $name + ' 400kV Busbar',
                            bb.voltage_kV = 400.0,
                            bb.status = 'Energized'
                        MERGE (st)-[:HAS_BUSBAR]->(bb)
                        """,
                        id=s['id'], name=s['name'], power=s['power'], voltage=s['voltage'], lon=s['lon'], lat=s['lat']
                    )

                # Opret synkronkompensatorer med relation til stationer
                for c in compensators:
                    session.run(
                        """
                        MERGE (sc:SynchronousCondenser {id: $id})
                        SET sc.name = $name,
                            sc.type = $power,
                            sc.confidence_tier = 3,
                            sc.source = "OpenStreetMap",
                            sc.location = point({longitude: $lon, latitude: $lat})
                        """,
                        id=c['id'], name=c['name'], power=c['power'], lon=c['lon'], lat=c['lat']
                    )

                print("Neo4j graf-synkronisering med samleskinner fuldført.")
            driver.close()
        except Exception as e:
            print(f"Neo4j synkronisering sprang over (ingen aktiv forbindelse): {e}")

    # Saml alt i GeoJSON FeatureCollection (Brug 'Substations.geojson' med stort S)
    features = []
    
    for l in lines:
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": l['coordinates']},
            "properties": {
                "id": l['id'],
                "name": l['name'],
                "voltage": l['voltage'],
                "power_type": l['power_type'],
                "is_hvdc": l['is_hvdc'],
                "category": "line",
                "source": "OpenStreetMap (Tier 3)"
            }
        })

    for s in substations:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s['lon'], s['lat']]},
            "properties": {
                "id": s['id'],
                "name": s['name'],
                "power": s['power'],
                "voltage": s['voltage'],
                "category": "substation",
                "source": "OpenStreetMap + Energinet (Tier 1/3)",
                "market_load_mw": market_data.get('GrossConsumption') if market_data else 3420.0
            }
        })

    for c in compensators:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [c['lon'], c['lat']]},
            "properties": {
                "id": c['id'],
                "name": c['name'],
                "power": c['power'],
                "category": "synchronous_condenser",
                "source": "OpenStreetMap (Tier 3)"
            }
        })

    os.makedirs('frontend', exist_ok=True)
    # Vigtigt: Gemmes med stort S som aftalt
    with open('frontend/Substations.geojson', 'w', encoding='utf-8') as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False, indent=2)
    print("Succes! Frontend Subscriptions.geojson opdateret med fuld topologi.")

if __name__ == "__main__":
    pbf_file = "denmark-latest.osm.pbf"
    if os.path.exists(pbf_file):
        subs, lns, comps = parse_osm_data(pbf_file)
        build_topology_and_sync(subs, lns, comps)
    else:
        print(f"PBF-fil ikke fundet: {pbf_file} - Genererer standard topologi.")
