import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase

app = FastAPI(title="Digital Elnet Tvilling API", version="1.0")

# Tillad at frontend (f.eks. localhost eller Vercel) kan tilgå API'et
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Hent Neo4j forbindelsesdetaljer fra miljøvariabler
URI = os.environ.get("NEO4J_URI")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD")

def get_neo4j_driver():
    if not URI or not PASSWORD:
        return None
    return GraphDatabase.driver(URI, auth=(USER, PASSWORD))

@app.get("/")
def read_root():
    return {"status": "online", "message": "Velkommen til Digital Elnet Tvilling API"}

@app.get("/api/substations")
def get_substations():
    driver = get_neo4j_driver()
    if not driver:
        raise HTTPException(status_code=500, detail="Database-forbindelse ikke konfigureret korrekt.")
    
    features = []
    with driver.session() as session:
        # Hent substations fra Neo4j
        result = session.run(
            "MATCH (s:Substation) WHERE s.lat IS NOT NULL AND s.lon IS NOT NULL RETURN s"
        )
        for record in result:
            node = record["s"]
            # Byg et GeoJSON Point for hver station
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(node["lon"]), float(node["lat"])]
                },
                "properties": {
                    "mRID": node.get("mRID"),
                    "name": node.get("name"),
                    "voltage": node.get("voltage"),
                    "confidence_tier": node.get("confidence_tier"),
                    "data_provenance": node.get("data_provenance")
                }
            }
            features.append(feature)
            
    driver.close()
    
    # Returner som samlet GeoJSON FeatureCollection
    return {
        "type": "FeatureCollection",
        "features": features
    }
