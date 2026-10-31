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
    
    # Sæt tidsinterval (seneste 24 timer)
    end = pd.Timestamp.now(tz='UTC')
    start = end - pd.Timedelta(days=1)
    
    # EIC-koder for Danmark (DK1 = Vestdanmark, DE_LU = Tyskland/Luxembourg)
    country_code_from = 'DK_1'
    country_code_to = 'DE_LU'
    
    print(f"Henter fysiske strømme fra ENTSO-E for {country_code_from} -> {country_code_to}...")
    
    try:
        df = client.query_physical_flows(country_code_from, country_code_to, start=start, end=end)
        print(f"Hentede {len(df)} datapunkter fra ENTSO-E.")
        return df
    except Exception as e:
        print(f"Fejl ved hentning af ENTSO-E data: {e}")
        return None

def sync_entsoe_to_neo4j(df):
    if df is None or df.empty:
        print("Ingen ENTSO-E data at synkronisere.")
        return

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    if not uri or not user or not password:
        print("FEJL: Neo4j miljøvariabler ikke fundet!")
        return

    print("Forbinder til Neo4j AuraDB for at synkronisere ENTSO-E markedsdata...")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        count = 0
        for timestamp, val in df.items():
            if pd.isna(val):
                continue
            
            session.run(
                """
                MERGE (i:Interconnector {id: "DK1-DE_LU"})
                SET i.last_update = $utc_time,
                    i.physical_flow_mw = $flow,
                    i.confidence_tier = 1,
                    i.source = "ENTSO-E Transparency Platform"
                """,
                utc_time=str(timestamp),
                flow=float(val)
            )
            count += 1
            
        print(f"Succes! Opdaterede {count} tidsdatapunkter for interconnector i Neo4j.")

    driver.close()

if __name__ == "__main__":
    df_flows = fetch_entsoe_data()
    if df_flows is not None:
        sync_entsoe_to_neo4j(df_flows)
