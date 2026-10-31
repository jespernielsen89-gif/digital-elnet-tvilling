import os
import requests
from neo4j import GraphDatabase

def fetch_energidataservice():
    # Opdateret og korrekt API endpoint for EnergiDataService (f.eks. Elspotpriser eller strømforbrug/generation)
    url = "https://api.energidataservice.dk/dataset/Elspotprices"
    
    print(f"Henter data fra EnergiDataService på {url}...")
    try:
        response = requests.get(url, params={"limit": 5})
        if response.status_code == 404:
            # Fallback til et andet essentielt dataset hvis det første ikke findes
            url = "https://api.energidataservice.dk/dataset/PowerSystemPub"
            response = requests.get(url, params={"limit": 5})
            
        response.raise_for_status()
        data = response.json()
        records = data.get("records", [])
        print(f"-> Fandt {len(records)} poster fra EnergiDataService.")
        return records
    except Exception as e:
        print(f"-> Fejl ved hentning af data fra EnergiDataService: {e}")
        return []

def sync_to_neo4j(records):
    if not records:
        print("Ingen EnergiDataService-data at synkronisere.")
        return

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    if not uri or not user or not password:
        print("FEJL: Neo4j miljøvariabler mangler!")
        return

    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as session:
        print(f"Synkroniserer {len(records)} poster til Neo4j...")
        # Eksempel på lagring af markedsdata / systemdata
        for rec in records:
            session.run(
                """
                MERge (m:MarketData {id: toString($id)})
                SET m.timestamp = $time,
                    m.source = "EnergiDataService",
                    m.confidence_tier = 1
                """,
                id=rec.get("HourUTC", "unknown"),
                time=str(rec.get("HourUTC", ""))
            )
    driver.close()
    print("Succes med EnergiDataService synkronisering!")

if __name__ == "__main__":
    recs = fetch_energidataservice()
    sync_to_neo4j(recs)
