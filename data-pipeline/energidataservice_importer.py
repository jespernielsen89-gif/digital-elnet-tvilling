import os
import requests
from neo4j import GraphDatabase

def fetch_energidataservice_data():
    url = "https://api.energidataservice.dk/dataset/ElectricityProdEx?limit=50"
    
    print("Henter data fra EnergiDataService...")
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        records = data.get("records", [])
        print(f"Hentede {len(records)} rækker data fra EnergiDataService.")
        return records
    else:
        print(f"Fejl ved hentning af data: {response.status_code}")
        return []

def sync_energy_data_to_neo4j(records):
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    if not uri or not user or not password:
        print("FEJL: Neo4j miljøvariabler ikke fundet!")
        return

    print("Forbinder til Neo4j AuraDB for at synkronisere marked- og produktionsdata...")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        count = 0
        for r in records:
            session.run(
                """
                MERGE (z:BiddingZone {zoneId: $zone})
                SET z.last_update = $utc_time,
                    z.solar_power = $solar,
                    z.wind_power = $wind,
                    z.confidence_tier = 1,
                    z.source = "EnergiDataService"
                """,
                zone=r.get("PriceArea", "DK"),
                utc_time=r.get("HourUTC"),
                solar=r.get("SolarPower", 0.0),
                wind=r.get("WindPower", 0.0)
            )
            count += 1
        print(f"Succes! Opdaterede {count} poster i Neo4j med data fra EnergiDataService.")

    driver.close()

if __name__ == "__main__":
    records = fetch_energidataservice_data()
    if records:
        sync_energy_data_to_neo4j(records)
