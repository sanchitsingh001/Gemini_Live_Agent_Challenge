extends CanvasLayer
## Glass compass: center = look; markers for task NPCs (no clue yet).

const COMPASS_WIDTH := 440
const COMPASS_HEIGHT := 30
## Top bar ~58px; compass sits just under it when bar is on.
const COMPASS_TOP_WITH_BAR := 66
const COMPASS_TOP_NO_BAR := 10
const COMPASS_BOTTOM_PAD := 8
const VISIBLE_HALF_RAD := deg_to_rad(52.0)
const NPC_COLORS: Array[Color] = [
	Color(1.0, 0.45, 0.42),
	Color(0.4, 0.88, 0.95),
	Color(0.55, 0.95, 0.5),
	Color(1.0, 0.82, 0.35),
	Color(0.92, 0.55, 0.98),
]

# Glass + readable ink (aligned with UiThemeHelper glass bar)
const GLASS_BG := Color(0.72, 0.78, 0.92, 0.14)
const GLASS_HI := Color(1.0, 1.0, 1.0, 0.12)
const GLASS_BORDER := Color(1.0, 1.0, 1.0, 0.4)
const GLASS_SHADOW := Color(0.02, 0.04, 0.08, 0.22)
const INK := Color(0.06, 0.08, 0.12, 0.88)
const TICK := Color(0.95, 0.97, 1.0, 0.55)

var _root: Control = null
var _strip: Control = null


func _ready() -> void:
	layer = 105
	_root = Control.new()
	_root.set_anchors_preset(Control.PRESET_CENTER_TOP)
	_root.anchor_left = 0.5
	_root.anchor_right = 0.5
	_root.anchor_top = 0.0
	_root.anchor_bottom = 0.0
	_root.offset_left = -COMPASS_WIDTH * 0.5
	_root.offset_right = COMPASS_WIDTH * 0.5
	_root.offset_top = COMPASS_TOP_NO_BAR
	_root.offset_bottom = COMPASS_TOP_NO_BAR + COMPASS_HEIGHT + COMPASS_BOTTOM_PAD
	add_child(_root)
	_strip = _CompassStrip.new()
	_strip.custom_minimum_size = Vector2(COMPASS_WIDTH, COMPASS_HEIGHT)
	_strip.set_anchors_preset(Control.PRESET_CENTER)
	_strip.anchor_left = 0.5
	_strip.anchor_right = 0.5
	_strip.anchor_top = 0.5
	_strip.anchor_bottom = 0.5
	_strip.offset_left = -COMPASS_WIDTH * 0.5
	_strip.offset_right = COMPASS_WIDTH * 0.5
	_strip.offset_top = -COMPASS_HEIGHT * 0.5
	_strip.offset_bottom = COMPASS_HEIGHT * 0.5
	_root.add_child(_strip)


func _process(_delta: float) -> void:
	if not _strip or _root == null:
		return
	var show := _should_show()
	_root.visible = show
	if show:
		var top := COMPASS_TOP_NO_BAR
		for h in get_tree().get_nodes_in_group("game_hud"):
			if h.has_method("is_top_bar_visible") and h.is_top_bar_visible():
				top = COMPASS_TOP_WITH_BAR
				break
		if _root.offset_top != top:
			_root.offset_top = top
			_root.offset_bottom = top + COMPASS_HEIGHT + COMPASS_BOTTOM_PAD
		_strip.queue_redraw()


func _should_show() -> bool:
	if not GameManager or GameManager.game_bundle.is_empty():
		return false
	if not GameManager.title_passed or not GameManager.setup_passed:
		return false
	if GameManager.show_ending:
		return false
	return true


class _CompassStrip extends Control:
	func _ready() -> void:
		clip_contents = true

	func _notification(what: int) -> void:
		if what == NOTIFICATION_RESIZED:
			queue_redraw()

	func _glass_backdrop(r: Rect2) -> void:
		var sb := StyleBoxFlat.new()
		sb.bg_color = GLASS_BG
		sb.set_corner_radius_all(16)
		sb.set_border_width_all(1)
		sb.border_color = GLASS_BORDER
		sb.shadow_size = 8
		sb.shadow_color = GLASS_SHADOW
		sb.draw(get_canvas_item(), r)
		# Frost highlight (top third)
		var hi := Rect2(r.position.x + 6, r.position.y + 3, r.size.x - 12, r.size.y * 0.35)
		draw_rect(hi, GLASS_HI, true)

	func _draw_string_chunky(font: Font, pos: Vector2, text: String, fill: Color) -> void:
		var sz := 11
		for dx in [-1, 0, 1]:
			for dy in [-1, 0, 1]:
				if dx == 0 and dy == 0:
					continue
				draw_string(font, pos + Vector2(dx, dy), text, HORIZONTAL_ALIGNMENT_LEFT, -1, sz, INK)
		draw_string(font, pos, text, HORIZONTAL_ALIGNMENT_LEFT, -1, sz, fill)

	func _draw() -> void:
		var w := size.x
		var h := size.y
		if w < 60 or h < 12:
			return

		_glass_backdrop(Rect2(Vector2.ZERO, size))

		var player := _get_player()
		if player == null:
			var cx := w * 0.5
			draw_line(Vector2(cx, 6), Vector2(cx, h - 6), GLASS_BORDER, 1.5)
			return

		var cam: Camera3D = player.get_node_or_null("Camera3D") as Camera3D
		if cam == null:
			return
		var forward_xz := Vector2(-cam.global_transform.basis.z.x, -cam.global_transform.basis.z.z)
		if forward_xz.length_squared() < 1e-6:
			return
		forward_xz = forward_xz.normalized()
		var yaw := atan2(forward_xz.x, forward_xz.y)

		var cx := w * 0.5
		var scale_x := (w * 0.44) / VISIBLE_HALF_RAD
		var font := ThemeDB.fallback_font
		var base_y := h - 5.0

		# Fewer, chunkier ticks (every 30°)
		for deg in range(-45, 46, 30):
			var rad := -deg_to_rad(float(deg))
			var x := cx + rad * scale_x
			if x < 6 or x > w - 6:
				continue
			var tick_w := 3.0
			var tick_h := 7.0 if deg == 0 else 5.0
			draw_rect(Rect2(x - tick_w * 0.5, base_y - tick_h, tick_w, tick_h), TICK if deg != 0 else Color(1, 1, 1, 0.75))

		# Center caret
		var caret := PackedVector2Array([
			Vector2(cx, 2),
			Vector2(cx - 5, 12),
			Vector2(cx + 5, 12),
		])
		draw_colored_polygon(caret, INK)
		var inner := PackedVector2Array([
			Vector2(cx, 4),
			Vector2(cx - 3, 10),
			Vector2(cx + 3, 10),
		])
		draw_colored_polygon(inner, Color(0.95, 0.92, 1.0, 0.95))

		var cardinals := [
			["N", PI, Color(0.35, 0.55, 0.95)],
			["E", PI * 0.5, Color(0.45, 0.75, 0.4)],
			["S", 0.0, Color(0.9, 0.4, 0.38)],
			["W", -PI * 0.5, Color(0.75, 0.45, 0.85)],
		]
		for item in cardinals:
			var rel := _wrap_angle(yaw - float(item[1]))
			if absf(rel) > VISIBLE_HALF_RAD * 1.02:
				continue
			var lx := cx + rel * scale_x
			_draw_string_chunky(font, Vector2(lx - 4, 14), str(item[0]), item[2])

		var pending: Array = GameManager.get_pending_task_npc_ids()
		var color_i := 0
		for nid in pending:
			var npc_node := _find_npc_node(str(nid))
			if npc_node == null:
				continue
			var to_xz := Vector2(npc_node.global_position.x - player.global_position.x, npc_node.global_position.z - player.global_position.z)
			if to_xz.length_squared() < 0.04:
				continue
			to_xz = to_xz.normalized()
			var rel_npc := _wrap_angle(yaw - atan2(to_xz.x, to_xz.y))
			var mx := cx + rel_npc * scale_x
			mx = clampf(mx, 14.0, w - 14.0)
			var col: Color = NPC_COLORS[color_i % NPC_COLORS.size()]
			color_i += 1
			draw_arc(Vector2(mx, 11), 6.0, 0.0, TAU, 16, INK, 2.5, true)
			draw_circle(Vector2(mx, 11), 5.0, col)
			draw_circle(Vector2(mx, 8), 1.8, Color(1, 1, 1, 0.55))

	func _get_player() -> Node3D:
		var tree := get_tree()
		if tree == null:
			return null
		return tree.get_first_node_in_group("player") as Node3D

	func _find_npc_node(npc_id: String) -> Node3D:
		var tree := get_tree()
		if tree == null:
			return null
		for n in tree.get_nodes_in_group("npc"):
			if n.get_meta("npc_id", "") == npc_id:
				return n as Node3D
		return null

	func _wrap_angle(a: float) -> float:
		while a > PI:
			a -= TAU
		while a < -PI:
			a += TAU
		return a
