import { Polyline, Marker } from 'react-leaflet';
import L from 'leaflet';
import { useMemo } from 'react';

function createRouteLabel(text, isRecommended) {
  const bg = isRecommended ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.9)';
  const borderColor = isRecommended ? 'rgba(22, 163, 74, 0.5)' : 'rgba(202, 138, 4, 0.4)';
  const textColor = isRecommended ? '#15803d' : '#a16207';

  return L.divIcon({
    className: 'route-label',
    html: `
      <div style="
        background: ${bg};
        border: 1px solid ${borderColor};
        color: ${textColor};
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 10px;
        font-weight: 700;
        font-family: Inter, sans-serif;
        white-space: nowrap;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        letter-spacing: 0.03em;
      ">${text}</div>
    `,
    iconSize: [0, 0],
    iconAnchor: [50, 10],
  });
}

const MAX_ROUTES = 2;

export default function RouteOverlay({ routes }) {
  const routeData = useMemo(() => {
    if (!routes?.routes_to_facilities) return [];
    return routes.routes_to_facilities
      .filter((r) => r.status !== 'no_safe_route' && r.route_geometry)
      .slice(0, MAX_ROUTES);
  }, [routes]);

  if (!routeData.length) return null;

  return (
    <>
      {routeData.map((route) => {
        const isRecommended = route.rank === 1;
        // OSRM unavailable: graph path is approximate, so draw it dotted
        const isApprox = route._hasRoadGeometry === false;
        const color = route.safety_score >= 80
          ? '#16a34a'
          : route.safety_score >= 60
            ? '#ca8a04'
            : '#dc2626';

        const positions = route.route_geometry.coordinates.map(
          ([lon, lat]) => [lat, lon]
        );
        const midIdx = Math.floor(positions.length / 2);
        const midPoint = positions[midIdx];

        return (
          <div key={`route-${route.facility_id}`}>
            {isRecommended && (
              <Polyline
                positions={positions}
                pathOptions={{ color, weight: 14, opacity: 0.15, lineCap: 'round', lineJoin: 'round' }}
              />
            )}

            <Polyline
              positions={positions}
              pathOptions={{
                color,
                weight: isRecommended ? 4 : 2.5,
                opacity: isRecommended ? 0.9 : 0.5,
                dashArray: isApprox ? '2 8' : isRecommended ? undefined : '10 6',
                lineCap: 'round',
                lineJoin: 'round',
              }}
            />

            {midPoint && (
              <Marker
                position={midPoint}
                icon={createRouteLabel(
                  isRecommended
                    ? `BEST ROUTE \u2022 ${route.total_time_min} min`
                    : `ALT \u2022 ${route.total_time_min} min`,
                  isRecommended
                )}
                interactive={false}
              />
            )}
          </div>
        );
      })}
    </>
  );
}
