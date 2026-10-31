import os
import pandas as pd
from entsoe import EntsoePandasClient
from neo4j import GraphDatabase

def fetch_entsoe_data():
    api_key = os.getenv("ENTSOE_API_KEY")
    if not api_key:
        print("FEJL: ENTSOE_API_KEY miljøvariabel ikke fundet!")
        return None

    client = EntsoePandasClient(api_key=api_key)
    
    end = pd.Timestamp.now(tz='UTC')
    start = end - pd.Timedelta(days=1)
    
    # Relevante grænseflader for det danske elnet (HVDC / AC korridorer)
    # DK_1 = Vestdanmark, DK_2 = Østdanmark, DE_LU = Tyskland, SE_3/SE_4 = Sverige, NL = Nederlandene, GB = Storbritannien
    interconnectors = [
        ("DK_1", "DE_LU", "DK1-DE"),
        ("DK_1", "NL", "DK1-NL"),
        ("DK_1", "GB", "DK1-GB"),
        ("DK_1", "SE_3", "DK1-SE3"),
        ("DK_2", "SE_4", "DK2-SE4"),
        ("DK_1", "DK_2", "DK1-DK2")
    ]
    
    all_flows = {}
    for code_from, code_to, label in interconnectors:
        print(f"Henter fysiske strømme fra ENTSO-E for {code_from} -> {code_to} ({label})...")
        try:
            df = client.query_physical_flows(code_from, code_to, start=start, end=end)
            if not df.empty:
                all_flows[label] = df
        except Exception as e:
            print(f"Kunne ikke hente {label}: {e}")
            
    return all_flows

def sync_entsoe_to_neo4j(all_flows):
    if not all_flows:
        print("Ingen ENTSO-E data at synkronisere.")
        return

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    if not uri or not user or not password:
        print("FEJL: Neo4j miljøvariabler ikke fundet!")
        return

    print("Forbinder til Neo4j AuraDB for at synkronisere HVDC & Interconnector markedsdata...")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        total_count = 0
        for label, df in all_flows.items():
            for timestamp, val in df.items():
                if pd.isna(val):
                    continue
                
                session.run(
                    """
                    MERGE (i:Interconnector {id: $interconnector_id})
                    SET i.last_update = $utc_time,
                        i.physical_flow_mw = $flow,
                        i.confidence_tier = 1,
                        i.source = "ENTSO-E Transparency Platform"
                    """,
                    interconnector_id=label,
                    utc_time=str(timestamp),
                    flow=float(val)
                )
                total_count += 1
                
        print(f"Succes! Opdaterede i alt {total_count} datapunkter på tværs af interconnectors i Neo4j.")

    driver.close()

if __name__ == "__main__":
    flows = fetch_entsoe_data()
    if flows:
        sync_entsoe_to_neo4j(flows)
