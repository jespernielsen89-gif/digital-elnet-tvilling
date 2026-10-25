import React, { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import './App.css';

export default function App() {
  const mapContainer = useRef(null);
  const map = useRef(null);

  useEffect(() => {
    if (map.current) return; // Initialiser kun én gang

    // Opret MapLibre kort med CartoDB Dark baggrund
    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
      center: [10.2, 56.1], // Centreret over Danmark
      zoom: 6.5
    });

    map.current.on('load', () => {
      // Indlæs GeoJSON-filen genereret af vores GitHub Actions pipeline
      map.current.addSource('elnet-data', {
        type: 'geojson',
        data: './substations.geojson'
      });

      // 1. Lag for højspændingsledninger (LineString)
      map.current.addLayer({
        id: 'elnet-lines',
        type: 'line',
        source: 'elnet-data',
        filter: ['==', '$type', 'LineString'],
        paint: {
          'line-color': [
            'case',
            ['>=', ['get', 'voltage_int'], 400000], '#ff3b30', // 400 kV (Rød)
            ['>=', ['get', 'voltage_int'], 132000], '#ffcc00', // 132/150 kV (Gul)
            '#00d2ff' // Udefineret / Andet (Lyseblå)
          ],
          'line-width': [
            'case',
            ['>=', ['get', 'voltage_int'], 400000], 3,
            2
          ]
        }
      });

      // 2. Lag for transformerstationer (Point)
      map.current.addLayer({
        id: 'elnet-substations',
        type: 'circle',
        source: 'elnet-data',
        filter: ['==', '$type', 'Point'],
        paint: {
          'circle-radius': 5,
          'circle-color': '#ffffff',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#00d2ff'
        }
      });

      // Klik-hændelse til popups med stamdata
      map.current.on('click', ['elnet-substations', 'elnet-lines'], (e) => {
        const props = e.features[0].properties;
        const coords = e.lngLat;

        const htmlContent = `
          <div style="color: #333; font-size: 13px; line-height: 1.4;">
            <strong style="font-size: 14px;">${props.name || 'Ukendt'}</strong><br/>
            <strong>Type:</strong> ${props.type === 'substation' ? 'Transformerstation' : 'Højspændingsledning'}<br/>
            <strong>Spænding:</strong> ${props.voltage || 'Ukendt'}<br/>
            <strong>Operatør:</strong> ${props.operator || 'Ukendt'}<br/>
            <span style="color: #666; font-size: 11px;">mRID: ${props.mRID}</span>
          </div>
        `;

        new maplibregl.Popup()
          .setLngLat(coords)
          .setHTML(htmlContent)
          .addTo(map.current);
      });

      // Musemarkør-tilpasning ved hold over elementer
      map.current.on('mouseenter', ['elnet-substations', 'elnet-lines'], () => {
        map.current.getCanvas().style.cursor = 'pointer';
      });
      map.current.on('mouseleave', ['elnet-substations', 'elnet-lines'], () => {
        map.current.getCanvas().style.cursor = '';
      });
    });

    return () => {
      if (map.current) {
        map.current.remove();
        map.current = null;
      }
    };
  }, []);

  return (
    <div style={{ position: 'relative', width: '100vw', height: '100vh' }}>
      <div ref={mapContainer} style={{ width: '100%', height: '100%' }} />
      <div style={{
        position: 'absolute',
        top: '20px',
        left: '20px',
        background: 'rgba(20, 20, 20, 0.85)',
        color: '#fff',
        padding: '15px',
        borderRadius: '8px',
        boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
        zIndex: 10,
        backdropFilter: 'blur(5px)',
        border: '1px solid rgba(255,255,255,0.1)'
      }}>
        <h3 style={{ margin: '0 0 8px 0', fontSize: '16px' }}>⚡ Dansk Elnet Tvilling</h3>
        <p style={{ margin: '0 0 10px 0', fontSize: '12px', color: '#aaa' }}>Transmissions- & Regionalnet (OSM Data)</p>
        <div style={{ fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ width: '12px', height: '3px', background: '#ff3b30', display: 'inline-block' }}></span> 400 kV Tracé
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ width: '12px', height: '3px', background: '#ffcc00', display: 'inline-block' }}></span> 132/150 kV Tracé
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ width: '8px', height: '8px', background: '#fff', borderRadius: '50%', border: '2px solid #00d2ff', display: 'inline-block' }}></span> Station
          </div>
        </div>
      </div>
    </div>
  );
}
