import os
import requests
from neo4j import GraphDatabase

# Hent database-forbindelse fra GitHub Secrets via miljøvariabler
URI = os.environ.get("NEO4J_URI")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD")

if not URI or not PASSWORD:
    raise ValueError("Miljøvariablerne NEO4J_URI og NEO4J_PASSWORD skal være angivet!")

# Overpass API endpoint med HTTPS
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_QUERY = """
[out:json][timeout:25];
area[name="Danmark"]->.searchArea;
(
  way["power"="line"]["voltage"~"150000|400000"](area.searchArea);
  node["power"="substation"](area.searchArea);
);
out body;
>;
out skel qt;
"""

def fetch_osm_data():
    print("Henter transmissionsdata fra OpenStreetMap...")
    # Overpass kræver en User-Agent header, ellers afvises forespørgslen (406)
    headers = {'User-Agent': 'DigitalElnetTvillingMVP/1.0'}
    response = requests.post(OVERPASS_URL, data={'data': OVERPASS_QUERY}, headers=headers)
    response.raise_for_status()
    return response.json()

def seed_database(data):
    print(f"Forbinder til Neo4j i skyen på {URI}...")
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    
    with driver.session() as session:
        print("Rydder eksisterende test-data i grafen...")
        session.run("MATCH (n) DETACH DELETE n")
        
        print("Indlæser substations i Neo4j med Confidence Tier 1...")
        count = 0
        for element in data.get('elements', []):
            if element.get('type') == 'node' and 'tags' in element and element['tags'].get('power') == 'substation':
                session.run(
                    """
                    CREATE (s:Substation {
                        mRID: $id,
                        name: $name,
                        voltage: $voltage,
                        lat: $lat,
                        lon: $lon,
                        confidence_tier: 1,
                        data_provenance: 'OpenStreetMap_Verified'
                    })
                    """,
                    id=str(element['id']),
                    name=element['tags'].get('name', 'Ukendt Station'),
                    voltage=element['tags'].get('voltage', '150kV/400kV'),
                    lat=element.get('lat'),
                    lon=element.get('lon')
                )
                count += 1
                
        print(f"Succes! {count} substations blev indlæst i graf-databasen i skyen.")
        
    driver.close()

if __name__ == "__main__":
    raw_data = fetch_osm_data()
    seed_database(raw_data)
