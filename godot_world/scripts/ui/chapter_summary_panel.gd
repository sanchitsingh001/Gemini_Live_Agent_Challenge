extends CanvasLayer
## Bottom panel: "Story so far", what to do, exit requirements

var _panel: PanelContainer = null
var _content: RichTextLabel = null

func _ready() -> void:
	layer = 150
	_build_ui()


func _build_ui() -> void:
	_panel = PanelContainer.new()
	_panel.set_anchors_preset(Control.PRESET_BOTTOM_WIDE)
	_panel.anchor_top = 0.85
	_panel.anchor_left = 0.0
	_panel.anchor_right = 1.0
	_panel.anchor_bottom = 1.0
	_panel.offset_top = -12
	_panel.offset_left = 16
	_panel.offset_right = -16
	_panel.offset_bottom = -12
	var style := UiThemeHelper.style_glass_panel()
	style.set_corner_radius_all(0)
	style.set_border_width_all(0)
	style.set_border_width(SIDE_TOP, 1)
	_panel.add_theme_stylebox_override("panel", style)
	add_child(_panel)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 8)
	_panel.add_child(vbox)

	var header := Label.new()
	header.text = "STORY SO FAR"
	header.add_theme_font_size_override("font_size", 11)
	header.add_theme_color_override("font_color", Color(0.55, 0.68, 0.42))
	vbox.add_child(header)

	_content = RichTextLabel.new()
	_content.bbcode_enabled = false
	_content.add_theme_font_size_override("normal_font_size", 13)
	_content.add_theme_color_override("default_color", Color(0.91, 0.91, 0.91))
	_content.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_content.custom_minimum_size.y = 60
	_content.fit_content = true
	vbox.add_child(_content)


func _process(_delta: float) -> void:
	if GameManager and not GameManager.game_bundle.is_empty():
		_refresh()


func _refresh() -> void:
	if not _content:
		return
	var meta = GameManager.game_bundle.get("narrative", {}).get("meta", {})
	var ch := GameManager.get_current_chapter()
	var clues = GameManager.game_bundle.get("narrative", {}).get("clues", [])
	var npcs = GameManager.game_bundle.get("narrative", {}).get("npcs", [])
	var parts: PackedStringArray = []
	var role := str(meta.get("player_role", ""))
	if not role.is_empty():
		var r := role
		if r.length() > 0:
			r = r.substr(0, 1).to_upper() + r.substr(1)
		parts.append("You are " + r + ".")
	var collected := GameManager.get_collected_clues()
	if collected.size() > 0:
		var labels: PackedStringArray = []
		for c in collected:
			labels.append(str(c.get("label", c.get("id", ""))))
		parts.append("So far you've uncovered " + ", ".join(labels) + ".")
	if ch:
		var narr := str(ch.get("narration", ""))
		if not narr.is_empty():
			parts.append(narr)
		var spotlight: Array = ch.get("spotlight_npc_ids", [])
		if spotlight.size() > 0:
			var names: PackedStringArray = []
			for nid in spotlight:
				for n in npcs:
					if n is Dictionary and str(n.get("id", "")) == nid:
						names.append(str(n.get("name", nid)))
						break
			if names.size() > 0:
				parts.append("Explore the area and talk to " + ", ".join(names) + " to uncover clues.")
		var exit_ids: Array = ch.get("exit_require_all_clues", [])
		if exit_ids.size() > 0:
			var exit_labels: PackedStringArray = []
			for cid in exit_ids:
				for c in clues:
					if c is Dictionary and str(c.get("id", "")) == cid:
						exit_labels.append(str(c.get("label", cid)))
						break
			if exit_labels.size() > 0:
				parts.append("To finish this chapter, uncover: " + ", ".join(exit_labels) + ".")
	_content.text = " ".join(parts) if parts.size() > 0 else ""
