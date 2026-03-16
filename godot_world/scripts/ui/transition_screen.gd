extends CanvasLayer
## Fullscreen chapter transition: image + glass center card + hook text
## Dismiss: Continue button, click anywhere, E, Space, or ui_accept.

var _root: Control = null

func _ready() -> void:
	# Above title (2500) / setup (2400) so this screen always receives clicks & focus
	layer = 2750
	visible = false
	process_mode = Node.PROCESS_MODE_INHERIT
	if GameManager:
		GameManager.pending_transition_ready.connect(_on_pending)


func _on_pending() -> void:
	_show_for_chapter(GameManager.current_chapter_id)


func show_for_chapter_id(ch_id: String) -> void:
	_show_for_chapter(ch_id)


func _show_for_chapter(ch_id: String) -> void:
	for c in get_children():
		c.queue_free()
	_root = Control.new()
	_root.set_anchors_preset(Control.PRESET_FULL_RECT)
	_root.mouse_filter = Control.MOUSE_FILTER_PASS
	add_child(_root)

	# Bottom of stack: fullscreen catcher so clicks outside the card still continue
	var click_catch := ColorRect.new()
	click_catch.set_anchors_preset(Control.PRESET_FULL_RECT)
	click_catch.color = Color(0, 0, 0, 0.001)
	click_catch.mouse_filter = Control.MOUSE_FILTER_STOP
	click_catch.gui_input.connect(_on_root_gui_input)
	_root.add_child(click_catch)

	var tex := TextureRect.new()
	tex.set_anchors_preset(Control.PRESET_FULL_RECT)
	tex.mouse_filter = Control.MOUSE_FILTER_IGNORE
	tex.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	tex.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	var fname := "chapter_transition_%s.png" % ch_id
	var bg_tex := GameManager.bundle_load_texture(fname) if GameManager else null
	if not bg_tex and GameManager:
		bg_tex = GameManager.bundle_load_texture("opening.png")
	if bg_tex:
		tex.texture = bg_tex
	_root.add_child(tex)

	var dim := ColorRect.new()
	dim.set_anchors_preset(Control.PRESET_FULL_RECT)
	dim.mouse_filter = Control.MOUSE_FILTER_IGNORE
	dim.color = Color(0.02, 0.03, 0.06, 0.28)
	_root.add_child(dim)

	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	center.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_root.add_child(center)

	var panel := PanelContainer.new()
	panel.mouse_filter = Control.MOUSE_FILTER_STOP
	panel.gui_input.connect(_on_panel_gui_input)
	panel.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_panel())
	panel.custom_minimum_size = Vector2(520, 280)
	panel.set_size(Vector2(720, 420))
	panel.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	panel.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	center.add_child(panel)

	var v := VBoxContainer.new()
	v.add_theme_constant_override("separation", 18)
	v.alignment = BoxContainer.ALIGNMENT_CENTER
	panel.add_child(v)

	var chapters: Array = GameManager.game_bundle.get("narrative", {}).get("chapters", []) if GameManager else []
	var title_txt := ch_id
	var hook := ""
	for c in chapters:
		if c is Dictionary and str(c.get("id", "")) == ch_id:
			title_txt = str(c.get("title", ch_id))
			hook = str(c.get("transition_player_hook", c.get("narration", "")))
			break

	var head := Label.new()
	head.text = title_txt
	head.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	head.add_theme_font_size_override("font_size", 26)
	head.add_theme_color_override("font_color", Color(0.98, 0.99, 1.0))
	head.mouse_filter = Control.MOUSE_FILTER_IGNORE
	v.add_child(head)

	var body := Label.new()
	body.text = hook if not hook.is_empty() else "Continue your investigation."
	body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.custom_minimum_size = Vector2(640, 0)
	body.add_theme_font_size_override("font_size", 18)
	body.add_theme_color_override("font_color", Color(0.96, 0.97, 1.0))
	body.mouse_filter = Control.MOUSE_FILTER_IGNORE
	v.add_child(body)

	var btn := Button.new()
	btn.text = "Continue"
	btn.custom_minimum_size = Vector2(260, 52)
	UiThemeHelper.apply_glass_button(btn)
	btn.pressed.connect(_close)
	btn.mouse_filter = Control.MOUSE_FILTER_STOP
	btn.focus_mode = Control.FOCUS_ALL
	v.add_child(btn)

	var hint := Label.new()
	hint.text = "E · Space · Enter · Click anywhere"
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	hint.add_theme_font_size_override("font_size", 12)
	hint.add_theme_color_override("font_color", Color(0.78, 0.84, 0.92))
	hint.mouse_filter = Control.MOUSE_FILTER_IGNORE
	v.add_child(hint)

	visible = true
	process_mode = Node.PROCESS_MODE_ALWAYS
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	_play_narration_audio(ch_id)
	call_deferred("_focus_continue", btn)


func _play_narration_audio(ch_id: String) -> void:
	if not AudioManager or not GameManager:
		return
	var chapters: Array = GameManager.game_bundle.get("narrative", {}).get("chapters", [])
	var voice := ""
	var bgm := ""
	for c in chapters:
		if c is Dictionary and str(c.get("id", "")) == ch_id:
			voice = str(c.get("transition_voice_path", ""))
			bgm = str(c.get("transition_bgm_path", ""))
			break
	if not bgm.is_empty():
		AudioManager.play_bgm(bgm, false, true, true)
	if not voice.is_empty():
		AudioManager.play_voiceover(voice)


func _focus_continue(btn: Button) -> void:
	if is_instance_valid(btn) and visible:
		btn.grab_focus()


func _on_root_gui_input(event: InputEvent) -> void:
	if not visible:
		return
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		_close()
		get_viewport().set_input_as_handled()


func _on_panel_gui_input(event: InputEvent) -> void:
	## Clicks on card background (not absorbed by Button) still continue
	if not visible:
		return
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		_close()
		get_viewport().set_input_as_handled()


func _input(event: InputEvent) -> void:
	if not visible:
		return
	if event.is_echo():
		return
	var dismiss := false
	if event.is_action_pressed("ui_accept"):
		dismiss = true
	if event is InputEventKey and event.pressed:
		var evk := event as InputEventKey
		var k: int = int(evk.keycode)
		if k == 0:
			k = int(evk.physical_keycode)
		if k == KEY_E or k == KEY_SPACE:
			dismiss = true
	if dismiss:
		_close()
		get_viewport().set_input_as_handled()


func _close() -> void:
	if not visible:
		return
	visible = false
	process_mode = Node.PROCESS_MODE_INHERIT
	if AudioManager:
		AudioManager.stop_voiceover()
		AudioManager.stop_bgm(true)
		_start_exploration_bgm()
	for c in get_children():
		c.queue_free()
	_root = null
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	# Top HUD: show 5–10s when entering chapter (Ch1 after setup + every transition)
	for h in get_tree().get_nodes_in_group("game_hud"):
		if h.has_method("flash_top_bar"):
			h.flash_top_bar()
			break


func _start_exploration_bgm() -> void:
	if not AudioManager or not GameManager:
		return
	var area_bgm: Dictionary = GameManager.game_bundle.get("audio", {}).get("area_bgm", {})
	var area_id := GameManager.player_area_id
	if area_id.is_empty():
		area_id = str(GameManager.game_bundle.get("spawn_point", {}).get("area_id", ""))
	var path := ""
	if area_bgm.has(area_id):
		path = str(area_bgm[area_id])
	else:
		for k in area_bgm:
			path = str(area_bgm[k])
			break
	if not path.is_empty():
		AudioManager.play_bgm(path, true, true)
