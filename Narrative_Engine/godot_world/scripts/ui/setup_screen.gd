extends CanvasLayer
## Entry / narrator setup: centered glass card + Continue

signal continued()

func _ready() -> void:
	layer = 2400
	var root := Control.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(root)

	var tex := TextureRect.new()
	tex.set_anchors_preset(Control.PRESET_FULL_RECT)
	tex.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	tex.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	root.add_child(tex)
	var bg_tex := GameManager.bundle_load_texture("setup_screen.png") if GameManager else null
	if bg_tex:
		tex.texture = bg_tex
	else:
		tex.modulate = Color(0.12, 0.13, 0.16)

	var dim := ColorRect.new()
	dim.set_anchors_preset(Control.PRESET_FULL_RECT)
	dim.color = Color(0.02, 0.03, 0.06, 0.26)
	root.add_child(dim)

	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_child(center)

	var glass := PanelContainer.new()
	glass.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_panel())
	glass.custom_minimum_size = Vector2(560, 320)
	glass.set_size(Vector2(680, 380))
	center.add_child(glass)

	var v := VBoxContainer.new()
	v.add_theme_constant_override("separation", 20)
	v.alignment = BoxContainer.ALIGNMENT_CENTER
	glass.add_child(v)

	var body := Label.new()
	body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.custom_minimum_size = Vector2(620, 0)
	body.add_theme_font_size_override("font_size", 17)
	body.add_theme_color_override("font_color", Color(0.96, 0.97, 1.0))
	if GameManager:
		var meta: Dictionary = GameManager.game_bundle.get("narrative", {}).get("meta", {})
		body.text = str(meta.get("narrator_setup", meta.get("intro_premise", "Your story begins.")))
	v.add_child(body)

	var cont := Button.new()
	cont.text = "Continue"
	cont.custom_minimum_size = Vector2(220, 50)
	UiThemeHelper.apply_glass_button(cont)
	cont.pressed.connect(_on_cont)
	v.add_child(cont)

	visible = false


func show_setup() -> void:
	visible = true
	_play_narration_audio()


func _play_narration_audio() -> void:
	if not AudioManager or not GameManager:
		return
	var meta: Dictionary = GameManager.game_bundle.get("narrative", {}).get("meta", {})
	var voice := str(meta.get("setup_voice_path", ""))
	var bgm := str(meta.get("setup_bgm_path", ""))
	if not bgm.is_empty():
		AudioManager.play_bgm(bgm, false, true, true)
	if not voice.is_empty():
		AudioManager.play_voiceover(voice)


func _on_cont() -> void:
	if AudioManager:
		AudioManager.stop_voiceover()
		AudioManager.stop_bgm(true)
	if GameManager:
		GameManager.setup_passed = true
		GameManager.intro_begun = true
	visible = false
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	continued.emit()
