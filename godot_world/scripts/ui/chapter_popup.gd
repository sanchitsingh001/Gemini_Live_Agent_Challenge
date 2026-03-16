extends CanvasLayer
## Chapter advance overlay: title, beat summary, dismiss on key

var _overlay: ColorRect = null
var _panel: PanelContainer = null
var _title: Label = null
var _beat: Label = null
var _hint: Label = null
var _timer: float = 0.0
var _tween: Tween = null
const ANIM_DURATION := 0.25

func _ready() -> void:
	layer = 2740
	_build_ui()
	visible = false
	if GameManager:
		GameManager.chapter_advanced.connect(_on_chapter_advanced)


func _build_ui() -> void:
	_overlay = ColorRect.new()
	_overlay.set_anchors_preset(Control.PRESET_FULL_RECT)
	_overlay.color = Color(0.02, 0.04, 0.1, 0.45)
	_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(_overlay)

	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(center)

	_panel = PanelContainer.new()
	_panel.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_modal())
	center.add_child(_panel)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 16)
	_panel.add_child(vbox)

	_title = Label.new()
	_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_title.add_theme_font_size_override("font_size", 26)
	_title.add_theme_color_override("font_color", Color(0.88, 0.96, 0.9))
	vbox.add_child(_title)

	_beat = Label.new()
	_beat.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_beat.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_beat.custom_minimum_size.x = 440
	_beat.add_theme_font_size_override("font_size", 16)
	_beat.add_theme_color_override("font_color", Color(0.91, 0.91, 0.91))
	vbox.add_child(_beat)

	_hint = Label.new()
	_hint.text = "E · Space · Enter · Click to continue"
	_hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_hint.add_theme_font_size_override("font_size", 13)
	_hint.add_theme_color_override("font_color", Color(0.54, 0.56, 0.59))
	vbox.add_child(_hint)


func _on_chapter_advanced(chapter_id: String) -> void:
	_show(chapter_id)


func show_first_chapter() -> void:
	if GameManager and not GameManager.game_bundle.is_empty():
		_show(GameManager.current_chapter_id)


func _show(chapter_id: String) -> void:
	if _tween and _tween.is_valid():
		_tween.kill()
	var ch := {}
	if GameManager:
		for c in GameManager.game_bundle.get("narrative", {}).get("chapters", []):
			if c is Dictionary and str(c.get("id", "")) == chapter_id:
				ch = c
				break
	var title := "Chapter: " + str(ch.get("title", chapter_id))
	var beat := str(ch.get("beat_summary", ""))
	_title.text = title
	_beat.text = beat
	visible = true
	process_mode = Node.PROCESS_MODE_ALWAYS
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	_timer = 5.0
	_overlay.modulate = Color(1, 1, 1, 0)
	_panel.pivot_offset = _panel.size / 2
	_panel.scale = Vector2(0.9, 0.9)
	_panel.modulate = Color(1, 1, 1, 0)
	_tween = create_tween()
	_tween.set_trans(Tween.TRANS_SINE)
	_tween.set_ease(Tween.EASE_OUT)
	_tween.set_parallel(true)
	_tween.tween_property(_overlay, "modulate", Color(1, 1, 1, 1), ANIM_DURATION)
	_tween.tween_property(_panel, "scale", Vector2(1, 1), ANIM_DURATION)
	_tween.tween_property(_panel, "modulate", Color(1, 1, 1, 1), ANIM_DURATION)


func _process(delta: float) -> void:
	if not visible:
		return
	_timer -= delta
	if _timer <= 0:
		_dismiss()


func _dismiss() -> void:
	_timer = -1
	if _tween and _tween.is_valid():
		_tween.kill()
	_tween = create_tween()
	_tween.set_trans(Tween.TRANS_SINE)
	_tween.set_ease(Tween.EASE_IN)
	_tween.set_parallel(true)
	_tween.tween_property(_overlay, "modulate", Color(1, 1, 1, 0), ANIM_DURATION * 0.8)
	_tween.tween_property(_panel, "scale", Vector2(0.95, 0.95), ANIM_DURATION * 0.8)
	_tween.tween_callback(func():
		visible = false
		process_mode = Node.PROCESS_MODE_INHERIT
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	)


func _input(event: InputEvent) -> void:
	if not visible:
		return
	if event.is_echo():
		return
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		_dismiss()
		get_viewport().set_input_as_handled()
		return
	if event.is_action_pressed("ui_accept"):
		_dismiss()
		get_viewport().set_input_as_handled()
		return
	if event is InputEventKey and event.pressed:
		var evk := event as InputEventKey
		var k: int = int(evk.keycode)
		if k == 0:
			k = int(evk.physical_keycode)
		if k == KEY_E or k == KEY_SPACE:
			_dismiss()
			get_viewport().set_input_as_handled()
