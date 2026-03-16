extends CanvasLayer
## Top HUD bar: chapter + boxed Clue / Task prompts (C / T)
## Hidden by default; flashes 5–10s when player presses C, T, or Esc.

const FLASH_DURATION_MIN := 5.0
const FLASH_DURATION_MAX := 10.0

var _panel: PanelContainer = null
var _chapter_label: Label = null
var _clue_count_label: Label = null
var _flash_time_left: float = 0.0


func _hud_pill_style() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.18, 0.22, 0.3, 0.55)
	s.set_corner_radius_all(10)
	s.set_border_width_all(1)
	s.border_color = Color(1, 1, 1, 0.38)
	s.set_content_margin_all(10)
	s.set_content_margin(SIDE_LEFT, 14)
	s.set_content_margin(SIDE_RIGHT, 14)
	return s


func _ready() -> void:
	add_to_group("game_hud")
	layer = 100
	_build_ui()
	_refresh()
	_panel.visible = false


func _build_ui() -> void:
	_panel = PanelContainer.new()
	_panel.set_anchors_preset(Control.PRESET_TOP_WIDE)
	_panel.anchor_top = 0.0
	_panel.anchor_left = 0.0
	_panel.anchor_right = 1.0
	_panel.offset_bottom = 58
	_panel.add_theme_stylebox_override("panel", UiThemeHelper.style_panel())
	add_child(_panel)

	var hbox := HBoxContainer.new()
	hbox.add_theme_constant_override("separation", 16)
	hbox.set_anchors_preset(Control.PRESET_FULL_RECT)
	_panel.add_child(hbox)

	_chapter_label = Label.new()
	_chapter_label.add_theme_font_size_override("font_size", 16)
	_chapter_label.add_theme_color_override("font_color", Color(0.96, 0.98, 1.0))
	hbox.add_child(_chapter_label)

	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	hbox.add_child(spacer)

	# —— Clues button box (C) ——
	var clue_box := PanelContainer.new()
	clue_box.add_theme_stylebox_override("panel", _hud_pill_style())
	var clue_row := HBoxContainer.new()
	clue_row.add_theme_constant_override("separation", 10)
	clue_box.add_child(clue_row)
	var clue_key := Label.new()
	clue_key.text = "C"
	clue_key.add_theme_font_size_override("font_size", 14)
	clue_key.add_theme_color_override("font_color", Color(0.65, 0.78, 0.95))
	clue_row.add_child(clue_key)
	var clue_title := Label.new()
	clue_title.text = "Clues"
	clue_title.add_theme_font_size_override("font_size", 15)
	clue_title.add_theme_color_override("font_color", Color(0.92, 0.95, 1.0))
	clue_row.add_child(clue_title)
	_clue_count_label = Label.new()
	_clue_count_label.add_theme_font_size_override("font_size", 15)
	_clue_count_label.add_theme_color_override("font_color", Color(0.75, 0.88, 0.98))
	clue_row.add_child(_clue_count_label)
	hbox.add_child(clue_box)

	# —— Tasks button box (T) ——
	var task_box := PanelContainer.new()
	task_box.add_theme_stylebox_override("panel", _hud_pill_style())
	var task_row := HBoxContainer.new()
	task_row.add_theme_constant_override("separation", 10)
	task_box.add_child(task_row)
	var task_key := Label.new()
	task_key.text = "T"
	task_key.add_theme_font_size_override("font_size", 14)
	task_key.add_theme_color_override("font_color", Color(0.65, 0.78, 0.95))
	task_row.add_child(task_key)
	var task_title := Label.new()
	task_title.text = "Tasks"
	task_title.add_theme_font_size_override("font_size", 15)
	task_title.add_theme_color_override("font_color", Color(0.92, 0.95, 1.0))
	task_row.add_child(task_title)
	hbox.add_child(task_box)


## Compass / layout: true while the top strip is shown.
func is_top_bar_visible() -> bool:
	return _panel != null and _panel.visible


## Show top bar; each trigger resets the hide timer (5–10s).
func flash_top_bar(duration_sec: float = -1.0) -> void:
	var d := duration_sec
	if d < 0.0:
		d = randf_range(FLASH_DURATION_MIN, FLASH_DURATION_MAX)
	_flash_time_left = d
	if _panel:
		_panel.visible = true


func _process(delta: float) -> void:
	if GameManager and game_bundle_loaded():
		_refresh()
	if _flash_time_left > 0.0:
		_flash_time_left -= delta
		if _flash_time_left <= 0.0 and _panel:
			_panel.visible = false


func game_bundle_loaded() -> bool:
	return GameManager != null and not GameManager.game_bundle.is_empty()


func _refresh() -> void:
	if not _chapter_label or not _clue_count_label:
		return
	if GameManager and not GameManager.game_bundle.is_empty():
		var ch := GameManager.get_current_chapter()
		var title := str(ch.get("title", "Chapter 1")) if ch else "Chapter 1"
		_chapter_label.text = "Chapter: " + title
		var count := 0
		for k in GameManager.collected_clue_ids:
			if GameManager.collected_clue_ids[k]:
				count += 1
		_clue_count_label.text = str(count)
	else:
		_chapter_label.text = "Chapter: -"
		_clue_count_label.text = "0"
