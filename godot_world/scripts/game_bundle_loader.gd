extends RefCounted
## Converts game_bundle.json format to the internal format expected by world_loader.
## Call build_runtime_from_game_bundle(bundle) to get {world_data, area_layouts}.
## world_data and area_layouts are compatible with _spawn_world, _spawn_area, _spawn_entities.
##
## game_bundle uses diagram units (world_block_diagram: ~1-3 per area). We compute a
## world_to_grid_scale so the world spans ~80 grid units (~145m) for a moderately spacious 3D world.

static func _point_to_arr(p) -> Array:
	if p is Array and p.size() >= 2:
		return [float(p[0]), float(p[1])]
	if p is Dictionary:
		return [float(p.get("x", 0)), float(p.get("y", 0))]
	return [0.0, 0.0]


## Compute scale so diagram units map to grid units. Target: world spans ~80 grid units.
static func _compute_world_to_grid_scale(areas_dict: Dictionary, connections_arr: Array) -> float:
	var x_min := 1e10
	var x_max := -1e10
	var y_min := 1e10
	var y_max := -1e10
	for a in areas_dict.values():
		if a is not Dictionary:
			continue
		var rect: Dictionary = a.get("rect", {})
		var rx := float(rect.get("x", 0.0))
		var ry := float(rect.get("y", 0.0))
		var rw := float(rect.get("w", 1.0))
		var rh := float(rect.get("h", 1.0))
		if rx < x_min: x_min = rx
		if rx + rw > x_max: x_max = rx + rw
		if ry < y_min: y_min = ry
		if ry + rh > y_max: y_max = ry + rh
	for c in connections_arr:
		if c is not Dictionary:
			continue
		for p in c.get("polyline", []):
			var pt := _point_to_arr(p)
			var px := float(pt[0])
			var py := float(pt[1])
			if px < x_min: x_min = px
			if px > x_max: x_max = px
			if py < y_min: y_min = py
			if py > y_max: y_max = py
	var span_x := maxf(x_max - x_min, 0.5)
	var span_y := maxf(y_max - y_min, 0.5)
	var world_span := maxf(span_x, span_y)
	var target_grid_units := 80.0
	return target_grid_units / world_span


static func build_runtime_from_game_bundle(bundle: Dictionary) -> Dictionary:
	"""
	Convert game_bundle.json to world_loader internal format.
	bundle: {areas, connections, entities, spawn_point, narrative}
	Returns: {world_data: {areas, gates, connections}, area_layouts: {area_id: {entities, road_tiles_world}}}
	"""
	var areas_dict: Dictionary = bundle.get("areas", {})
	var connections_arr: Array = bundle.get("connections", [])
	var entities_arr: Array = bundle.get("entities", [])

	var scale := _compute_world_to_grid_scale(areas_dict, connections_arr)

	var out_world_areas: Array = []
	var out_world_gates: Array = []
	var out_connections: Array = []
	var out_area_layouts: Dictionary = {}

	# Build area rect lookup (apply scale to convert diagram units -> grid units)
	var area_rects: Dictionary = {}
	for aid in areas_dict.keys():
		var a: Dictionary = areas_dict[aid]
		var rect: Dictionary = a.get("rect", {})
		var rx := float(rect.get("x", 0.0)) * scale
		var ry := float(rect.get("y", 0.0)) * scale
		var rw := float(rect.get("w", 40.0)) * scale
		var rh := float(rect.get("h", 30.0)) * scale
		area_rects[aid] = {"x": rx, "y": ry, "w": rw, "h": rh}
		out_world_areas.append({
			"area_id": str(aid),
			"x": rx,
			"y": ry,
			"w": rw,
			"h": rh
		})
		# Gates from area.gates
		var gates: Array = a.get("gates", [])
		var gate_i := 0
		for g in gates:
			if g is Dictionary:
				gate_i += 1
			var gx := float(g.get("x", 0.0)) * scale
			var gy := float(g.get("y", 0.0)) * scale
			out_world_gates.append({
				"area_id": str(aid),
				"gate_id": "gate_%d" % gate_i,
				"edge": "S",
				"world_x": gx,
				"world_y": gy
			})
		# Initialize area_layouts and populate road_tiles_world from bundle when present
		var road_tiles: Array = []
		var roads_world_raw: Array = a.get("roads_world", [])
		if roads_world_raw.size() > 0:
			var rx_orig := float(rect.get("x", 0.0))
			var ry_orig := float(rect.get("y", 0.0))
			for pt in roads_world_raw:
				var arr := _point_to_arr(pt)
				var px := float(arr[0]) * scale
				var py := float(arr[1]) * scale
				var local_x := px - rx_orig * scale
				var local_y := py - ry_orig * scale
				road_tiles.append([local_x, local_y])
		out_area_layouts[str(aid)] = {
			"entities": [],
			"road_tiles_world": road_tiles,
			"tilemap_min_x": 0.0,
			"tilemap_min_y": 0.0
		}

	# Connections: convert polyline points to [[x,y],[x,y]] format (scaled)
	for c in connections_arr:
		if c is not Dictionary:
			continue
		var poly: Array = c.get("polyline", [])
		if poly.size() < 2:
			continue
		var pts: Array = []
		for p in poly:
			var arr := _point_to_arr(p)
			pts.append([float(arr[0]) * scale, float(arr[1]) * scale])
		out_connections.append({"polyline": pts})

	# Sample road tiles along connection polylines for internal roads
	for c in connections_arr:
		if c is not Dictionary:
			continue
		var poly: Array = c.get("polyline", [])
		if poly.size() < 2:
			continue
		# Find which area each point belongs to (nearest area rect)
		for i in range(poly.size()):
			var pt: Array = _point_to_arr(poly[i])
			var px: float = float(pt[0]) * scale
			var py: float = float(pt[1]) * scale
			for aid in area_rects.keys():
				var r: Dictionary = area_rects[aid]
				if px >= r.x and px < r.x + r.w and py >= r.y and py < r.y + r.h:
					var local_x: float = px - float(r.x)
					var local_y: float = py - float(r.y)
					var layout: Dictionary = out_area_layouts[str(aid)]
					var tiles: Array = layout["road_tiles_world"]
					var found := false
					for t in tiles:
						if t is Array and t.size() >= 2:
							if abs(float(t[0]) - local_x) < 0.1 and abs(float(t[1]) - local_y) < 0.1:
								found = true
								break
					if not found:
						tiles.append([local_x, local_y])
					break

	# Entities: group by area_id, convert to local coords
	for e in entities_arr:
		if e is not Dictionary:
			continue
		var area_id: String = str(e.get("area_id", ""))
		if area_id.is_empty() or not out_area_layouts.has(area_id):
			continue
		var rect: Dictionary = area_rects.get(area_id, {"x": 0, "y": 0})
		var ex: float = float(e.get("x", 0.0)) * scale
		var ey: float = float(e.get("y", 0.0)) * scale
		var ew: float = float(e.get("w", 0.2)) * scale
		var eh: float = float(e.get("h", 0.2)) * scale
		var local_x: float = ex - float(rect.get("x", 0))
		var local_y: float = ey - float(rect.get("y", 0))
		var layout: Dictionary = out_area_layouts[area_id]
		var entities: Array = layout["entities"]
		entities.append({
			"id": str(e.get("id", "")),
			"group": str(e.get("group", "")),
			"x": local_x,
			"y": local_y,
			"w": ew,
			"h": eh,
			"rotation_deg": 180.0,
			"needs_frontage": bool(e.get("needs_frontage", false))
		})

	return {
		"world_data": {
			"areas": out_world_areas,
			"gates": out_world_gates,
			"connections": out_connections
		},
		"area_layouts": out_area_layouts,
		"world_to_grid_scale": scale
	}
