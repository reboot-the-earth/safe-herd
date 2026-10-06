const API_BASE = 'http://localhost:5001/api';

async function fetchJSON(url, options = {}) {
  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return { data: await res.json(), ok: true };
  } catch (err) {
    console.warn(`[API] ${url} failed:`, err.message);
    return { data: null, ok: false, error: err.message };
  }
}

/**
 * Normalize fire data from either data/fire_data.json (dict-keyed perimeters)
 * or Person 1's get_fire_data() (array-based perimeters) into the UI format.
 */
function normalizeFireData(raw) {
  const perimeters = raw.projected_perimeters;
  let normalizedPerimeters;

  if (Array.isArray(perimeters)) {
    normalizedPerimeters = perimeters;
  } else if (perimeters && typeof perimeters === 'object') {
    normalizedPerimeters = Object.entries(perimeters).map(([key, geometry]) => ({
      hours: parseInt(key),
      geometry,
    })).sort((a, b) => a.hours - b.hours);
  } else {
    normalizedPerimeters = [];
  }

  const farms = (raw.farms_at_risk || []).map((f) => ({
    farm_id: f.farm_id,
    name: f.name || f.farm_id,
    lat: f.lat,
    lon: f.lon,
    estimated_time_to_fire_hours: f.estimated_time_to_fire_hours ?? f.hours_to_fire ?? null,
    risk_level: f.risk_level || 'moderate',
    alert_message: f.alert_message ||
      `Fire projected to reach your area in ~${f.hours_to_fire || f.estimated_time_to_fire_hours || '?'} hours.`,
  }));

  return {
    timestamp: raw.timestamp || raw.detected_at || new Date().toISOString(),
    fire_id: raw.fire_id || 'unknown',
    active_hotspots: raw.active_hotspots || [],
    current_perimeter: raw.current_perimeter,
    projected_perimeters: normalizedPerimeters,
    wind: raw.wind || {},
    weather: raw.weather || {},
    farms_at_risk: farms,
    danger_zone: raw.danger_zone || null,
  };
}

/**
 * Normalize facilities from either data/facilities.json (facility_id + capacity/occupancy)
 * or Person 3's database (id + accepts + capacity) into the UI format.
 */
function normalizeFacilities(raw) {
  const list = raw.facilities || raw;
  if (!Array.isArray(list)) return [];

  return list.map((f) => {
    const id = f.id || f.facility_id;

    let capacityTotal, capacityAvailable, accepts;

    if (f.accepts) {
      accepts = f.accepts;
      capacityTotal = Object.values(f.capacity || {}).reduce((a, b) => a + b, 0);
      const buffered = Math.floor(capacityTotal * 0.8);
      capacityAvailable = buffered;
    } else if (f.capacity && f.current_occupancy) {
      const capVals = Object.values(f.capacity);
      const occVals = Object.values(f.current_occupancy);
      capacityTotal = capVals.reduce((a, b) => a + b, 0);
      const totalOccupancy = occVals.reduce((a, b) => a + b, 0);
      capacityAvailable = capacityTotal - totalOccupancy;
      accepts = Object.keys(f.capacity).filter((k) => f.capacity[k] > 0);
    } else {
      capacityTotal = 0;
      capacityAvailable = 0;
      accepts = [];
    }

    return {
      id,
      name: f.name,
      lat: f.lat,
      lon: f.lon,
      accepts,
      capacity_total: capacityTotal,
      capacity_available: capacityAvailable,
      capacity_detail: f.capacity || {},
      infrastructure: f.infrastructure || f.amenities || [],
      access_road: f.access_road || (f.access_roads || []).join(' / '),
      trailer_access: f.trailer_access !== false,
      contact: f.contact || '',
      notes: f.notes || '',
      has_own_feed: f.has_own_feed || false,
      volunteer_run: f.volunteer_run || false,
      verified: f.verified !== false,
      county: f.county || 'San Diego',
    };
  });
}

/**
 * Fetch a real road-following route from OSRM (Open Source Routing Machine).
 * Returns a GeoJSON LineString geometry or null on failure.
 */
async function fetchOSRMGeometry(startLon, startLat, endLon, endLat) {
  try {
    const url = `https://router.project-osrm.org/route/v1/driving/${startLon},${startLat};${endLon},${endLat}?overview=full&geometries=geojson`;
    const res = await fetch(url);
    if (!res.ok) return null;
    const data = await res.json();
    if (data.code !== 'Ok' || !data.routes?.length) return null;
    return data.routes[0].geometry;
  } catch {
    return null;
  }
}

/**
 * Normalize route output and replace straight-line geometries with real
 * road-following paths from OSRM. If OSRM is unavailable, keeps the backend
 * graph geometry and sets `_hasRoadGeometry: false` so it renders as approximate.
 */
async function normalizeRoutes(raw, origin = null) {
  if (!raw || !raw.routes_to_facilities) return null;

  const close = (a, b) =>
    Array.isArray(a) && Array.isArray(b) &&
    Math.abs(a[0] - b[0]) < 1e-4 && Math.abs(a[1] - b[1]) < 1e-4;

  const patched = await Promise.all(
    raw.routes_to_facilities.map(async (r) => {
      const coords = r.route_geometry?.coordinates;
      if (!Array.isArray(coords) || coords.length < 2) return r;

      const startPt = origin ? [origin.lon, origin.lat] : coords[0];

      // Use the facility's actual coordinates (from backend) so the route
      // ends exactly at the facility marker, not at a graph-snapped node.
      const endPt = (r.facility_lon != null && r.facility_lat != null)
        ? [r.facility_lon, r.facility_lat]
        : coords[coords.length - 1];

      const osrmGeom = await fetchOSRMGeometry(startPt[0], startPt[1], endPt[0], endPt[1]);
      if (osrmGeom?.coordinates?.length) {
        const osrmCoords = [...osrmGeom.coordinates];

        if (!close(osrmCoords[0], startPt)) osrmCoords.unshift(startPt);
        if (!close(osrmCoords[osrmCoords.length - 1], endPt)) osrmCoords.push(endPt);

        return { ...r, _hasRoadGeometry: true, route_geometry: { ...osrmGeom, coordinates: osrmCoords } };
      }

      // OSRM failed — keep the backend graph path, pinned to the farm and
      // facility markers, and mark it so the renderer can draw it as approximate
      const fallback = [...coords];
      if (!close(fallback[0], startPt)) fallback.unshift(startPt);
      if (!close(fallback[fallback.length - 1], endPt)) fallback.push(endPt);
      return { ...r, _hasRoadGeometry: false, route_geometry: { ...r.route_geometry, coordinates: fallback } };
    })
  );

  return { ...raw, routes_to_facilities: patched };
}

/**
 * Normalize Person 4's farmer_input.get_evacuation_plan() output into UI shape.
 *
 * Python returns checklist items as plain strings; the Checklist React component
 * expects {id, text, checked}. Trip cards already match the schema closely; we
 * just attach status + compute total_trips / total_evacuation_hours including
 * an optional drive_time_per_trip_min.
 */
function normalizeFarmerPlan(raw, { driveTimePerTripMin = 38 } = {}) {
  if (!raw || raw.error) return null;

  const slug = (s) =>
    String(s || '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_|_$/g, '')
      .slice(0, 32) || 'item';

  const trips = (raw.priority_plan || []).map((t, i) => ({
    order: t.order ?? i + 1,
    trip: t.trip ?? i + 1,
    animals: t.animals || `${t.count || ''} ${t.species || ''}`.trim(),
    count: t.count || 0,
    species: t.species || 'cattle',
    reason: t.reason || '',
    load_time_est_min: t.load_time_est_min ?? t.load_time_min ?? 0,
    handling: t.handling || t.special_handling || '',
    sedation_needed: t.sedation_needed || false,
    can_transport: t.can_transport !== false,
    status: 'pending',
  }));

  const checklist = {};
  Object.entries(raw.checklist || {}).forEach(([section, items]) => {
    const list = Array.isArray(items) ? items : [];
    checklist[section] = list.map((item, i) => {
      if (typeof item === 'string') {
        return { id: `${section}_${slug(item)}_${i}`, text: item, checked: false };
      }
      return {
        id: item.id || `${section}_${i}`,
        text: item.text || String(item),
        checked: item.checked || false,
      };
    });
  });

  const loadingMin = raw.time_estimate?.loading_time_total_min || 0;
  const totalTrips = trips.filter((t) => t.can_transport).length;
  const totalEvacMin = loadingMin + totalTrips * driveTimePerTripMin;

  return {
    farm: raw.farm || null,
    animals: raw.animals || [],
    transport: raw.transport || null,
    priority_plan: trips,
    time_estimate: {
      loading_time_total_min: loadingMin,
      drive_time_per_trip_min: driveTimePerTripMin,
      total_trips: totalTrips,
      total_evacuation_hours: Math.round((totalEvacMin / 60) * 10) / 10,
      time_available_min: raw.time_estimate?.time_available_min ?? null,
      note: raw.time_estimate?.note || '',
    },
    triage_warning: raw.triage_warning || null,
    warnings: raw.warnings || [],
    checklist,
  };
}

/**
 * Normalize evacuation plan from Person 3's get_evacuation_match() into UI format.
 */
function normalizeEvacPlan(raw) {
  if (!raw) return null;

  const trips = (raw.evacuation_trips || []).map((t, i) => ({
    order: i + 1,
    trip: t.trip || i + 1,
    animals: t.animals || `${t.count || ''} ${t.species || ''}`,
    count: t.count || 0,
    species: t.species || 'cattle',
    reason: t.reason || '',
    load_time_est_min: t.load_time_min || t.round_trip_minutes || 30,
    handling: t.handling || t.special_handling || '',
    status: 'pending',
  }));

  const summary = raw.trip_summary || {};

  return {
    priority_plan: trips,
    time_estimate: {
      loading_time_total_min: summary.total_loading_min || 0,
      drive_time_per_trip_min: summary.avg_round_trip_min || 38,
      total_trips: trips.length,
      total_evacuation_hours: raw.total_evacuation_hours || summary.total_hours || 0,
    },
    triage_warning: (raw.warnings || []).find((w) =>
      w.includes('CRITICAL') || w.includes('exceeds') || w.includes('not enough')
    ) || null,
    matched_facilities: raw.matched_facilities || [],
    warnings: raw.warnings || [],
  };
}


export async function fetchFireData(live = false) {
  const { data, ok } = await fetchJSON(`${API_BASE}/fire?live=${live}`);
  if (ok && data) return normalizeFireData(data);
  return null;
}

export async function fetchFacilities() {
  const { data, ok } = await fetchJSON(`${API_BASE}/facilities`);
  if (ok && data) return normalizeFacilities(data);
  return null;
}

export async function fetchRoutes(farmLat, farmLon) {
  const { data, ok } = await fetchJSON(`${API_BASE}/routes`, {
    method: 'POST',
    body: JSON.stringify({ farm_lat: farmLat, farm_lon: farmLon }),
  });
  if (ok && data) return await normalizeRoutes(data, { lat: farmLat, lon: farmLon });
  return null;
}

export async function fetchEvacuationPlan({
  farmId,
  animals,
  trailerCapacity,
  routeTimeMinutes = 38,
  fireArrivalHours = null,
}) {
  const { data, ok } = await fetchJSON(`${API_BASE}/plan`, {
    method: 'POST',
    body: JSON.stringify({
      farm_id: farmId,
      animals,
      trailer_capacity: trailerCapacity,
      route_time_minutes: routeTimeMinutes,
      fire_arrival_hours: fireArrivalHours,
    }),
  });
  if (ok && data) return normalizeEvacPlan(data);
  return null;
}

/**
 * Generate Person 4's farmer evacuation plan + checklist.
 *
 * @param {object} args
 * @param {{id:string,name:string,lat:number,lon:number,smoke_within_5_miles?:boolean}} args.farm
 * @param {Array<{species:string,count:number,special_needs?:string[]}>} args.animals
 * @param {{trailers:number,type:string,capacity?:object}} args.transport
 * @param {number} args.timeAvailableHours
 * @param {number} [args.driveTimePerTripMin=38] used to compute total evacuation time
 */
export async function fetchFarmerPlan({
  farm,
  animals,
  transport,
  timeAvailableHours,
  driveTimePerTripMin = 38,
}) {
  const { data, ok } = await fetchJSON(`${API_BASE}/farmer-plan`, {
    method: 'POST',
    body: JSON.stringify({
      farm,
      animals,
      transport,
      time_available_hours: timeAvailableHours,
    }),
  });
  if (ok && data) return normalizeFarmerPlan(data, { driveTimePerTripMin });
  return null;
}

export async function fetchFarmerProfiles() {
  const { data, ok } = await fetchJSON(`${API_BASE}/farmer-profiles`);
  if (ok && Array.isArray(data?.profiles)) return data.profiles;
  return null;
}

export async function checkHealth() {
  const { data, ok } = await fetchJSON(`${API_BASE}/health`);
  return ok && data?.status === 'ok';
}
