extends CanvasLayer

var _panel: PanelContainer = null
var _vbox: VBoxContainer = null
var _visible_tasks: bool = false

func _ready() -> void:
	layer = 600
	_build()
	visible = false


func _build() -> void:
	_panel = PanelContainer.new()
	_panel.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	_panel.offset_left = -340
	_panel.offset_right = -16
	_panel.offset_top = 72
	_panel.offset_bottom = 420
	_panel.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_panel())
	add_child(_panel)
	var outer := VBoxContainer.new()
	outer.add_theme_constant_override("separation", 12)
	_panel.add_child(outer)
	var head := PanelContainer.new()
	head.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_panel())
	head.custom_minimum_size.y = 36
	var ht := Label.new()
	ht.text = "Tasks"
	ht.add_theme_font_size_override("font_size", 16)
	ht.add_theme_color_override("font_color", Color.WHITE)
	head.add_child(ht)
	outer.add_child(head)
	_vbox = VBoxContainer.new()
	_vbox.add_theme_constant_override("separation", 8)
	outer.add_child(_vbox)


func _unhandled_input(event: InputEvent) -> void:
	if not GameManager or GameManager.game_bundle.is_empty():
		return
	if event.is_action_pressed("task_list"):
		for h in get_tree().get_nodes_in_group("game_hud"):
			if h.has_method("flash_top_bar"):
				h.flash_top_bar()
				break
		_visible_tasks = not _visible_tasks
		visible = _visible_tasks
		if _visible_tasks:
			_refresh()
		get_viewport().set_input_as_handled()


func _refresh() -> void:
	for c in _vbox.get_children():
		c.queue_free()
	var ch := GameManager.get_current_chapter()
	var ids: Array = ch.get("spotlight_npc_ids", [])
	var npcs: Array = GameManager.game_bundle.get("narrative", {}).get("npcs", [])
	for nid in ids:
		var name := str(nid)
		for n in npcs:
			if n is Dictionary and str(n.get("id", "")) == str(nid):
				name = str(n.get("name", nid))
				break
		var row := PanelContainer.new()
		row.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_panel())
		var h := HBoxContainer.new()
		row.add_child(h)
		var lbl := Label.new()
		lbl.text = "Get a clue from " + name
		lbl.add_theme_color_override("font_color", Color.WHITE)
		h.add_child(lbl)
		if GameManager.has_clue_from_npc_this_chapter(str(nid)):
			var ok := Label.new()
			ok.text = "  ✓"
			ok.add_theme_color_override("font_color", Color(0.6, 0.95, 0.65))
			h.add_child(ok)
		_vbox.add_child(row)
