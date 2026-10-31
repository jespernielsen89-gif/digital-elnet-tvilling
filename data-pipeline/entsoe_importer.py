import os
import pandas as pd
from entsoe import EntsoePandasClient
from neo4j import GraphDatabase

def fetch_entsoe_data():
    api_key = os.getenv("ENTSOE_API_KEY")
    if not api_key:
        raise ValueError("FEJL: ENTSOE_API_KEY miljøvariabel mangler!")

    client = EntsoePandasClient(api_key=api_key)
    
    end = pd.Timestamp.now(tz='UTC')
    start = end - pd.Timedelta(days=2)
    
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
            # Brug den korrekte entsoe-py metode (query_physical_flow i ental)
            df = client.query_physical_flow(code_from, code_to, start=start, end=end)
            if df is not None and not df.empty:
                print(f"-> Fandt {len(df)} datapunkter for {label}.")
                all_flows[label] = df
            else:
                print(f"-> Ingen data returneret for {label}.")
        except Exception as e:
            print(f"-> Fejl ved hentning af {label}: {e}")
            
    return all_flows

def sync_entsoe_to_neo4j(all_flows):
    if not all_flows:
        print("Advarsel: Ingen ENTSO-E data hentet, men fortsætter...")
        return

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    if not uri or not user or not password:
        raise ValueError("FEJL: Neo4j miljøvariabler mangler!")

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
                
        print(f"Succes! Opdaterede i alt {total_count} datapunkter i Neo4j.")

    driver.close()

if __name__ == "__main__":
    flows = fetch_entsoe_data()
    sync_entsoe_to_neo4j(flows)
