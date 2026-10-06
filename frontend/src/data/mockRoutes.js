/**
 * Farm: Valley Center Ranch (33.20, -117.26)
 * Single best route to the closest safe shelter.
 */
export const mockRoutes = {
  farm: { id: "valley_center_ranch", lat: 33.20, lon: -117.26 },
  routes_to_facilities: [
    {
      rank: 1,
      facility_id: "del_mar_fairgrounds",
      facility_name: "Del Mar Fairgrounds",
      facility_lat: 32.974,
      facility_lon: -117.268,
      total_time_min: 28,
      total_distance_km: 26,
      safety_score: 95,
      min_fire_distance_km: 12.4,
      trailer_friendly: true,
      status: "safe",
      route_geometry: {
        type: "LineString",
        coordinates: [
          [-117.260, 33.200],
          [-117.258, 33.194],
          [-117.255, 33.188],
          [-117.254, 33.182],
          [-117.256, 33.176],
          [-117.258, 33.170],
          [-117.261, 33.163],
          [-117.263, 33.156],
          [-117.264, 33.148],
          [-117.265, 33.140],
          [-117.266, 33.132],
          [-117.267, 33.124],
          [-117.268, 33.116],
          [-117.269, 33.108],
          [-117.270, 33.100],
          [-117.271, 33.092],
          [-117.271, 33.084],
          [-117.272, 33.076],
          [-117.272, 33.068],
          [-117.273, 33.060],
          [-117.273, 33.052],
          [-117.274, 33.044],
          [-117.274, 33.036],
          [-117.275, 33.028],
          [-117.275, 33.020],
          [-117.274, 33.012],
          [-117.273, 33.004],
          [-117.271, 32.996],
          [-117.269, 32.988],
          [-117.268, 32.982],
          [-117.268, 32.978],
          [-117.268, 32.974],
        ]
      },
      segments: [
        { road: "Mission Rd South", status: "safe", time_min: 8 },
        { road: "I-15 South", status: "safe", time_min: 12 },
        { road: "Via de la Valle", status: "safe", time_min: 5 },
        { road: "Jimmy Durante Blvd", status: "safe", time_min: 3 }
      ],
      warnings: []
    }
  ],
  timestamp: new Date().toISOString(),
};
