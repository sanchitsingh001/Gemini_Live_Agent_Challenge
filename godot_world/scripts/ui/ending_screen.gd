extends CanvasLayer
## Ending: background image + centered glass card + paginated text

var _container: Control = null
var _overlay: ColorRect = null
var _glass: PanelContainer = null
var _label: Label = null
var _hint: Label = null
var _prev_btn: Button = null
var _next_btn: Button = null
var _page_label: Label = null
var _tween: Tween = null
var _pages: Array[String] = []
var _page_index: int = 0
const FADE_DURATION := 0.5
const MAX_CHARS_PER_PAGE := 600

func _ready() -> void:
	layer = 1500
	_build_ui()
	visible = false
	if GameManager:
		GameManager.ending_triggered.connect(_on_ending)


func _build_ui() -> void:
	_container = Control.new()
	_container.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_container)
	var bg := TextureRect.new()
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	bg.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	bg.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	if GameManager:
		var bg_tex := GameManager.bundle_load_texture("ending_screen.png")
		if bg_tex:
			bg.texture = bg_tex
	_container.add_child(bg)
	_overlay = ColorRect.new()
	_overlay.set_anchors_preset(Control.PRESET_FULL_RECT)
	_overlay.color = Color(0.02, 0.04, 0.08, 0.35)
	_container.add_child(_overlay)

	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	_container.add_child(center)

	_glass = PanelContainer.new()
	_glass.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_panel())
	_glass.custom_minimum_size = Vector2(560, 280)
	_glass.set_size(Vector2(700, 400))
	center.add_child(_glass)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 20)
	vbox.alignment = BoxContainer.ALIGNMENT_CENTER
	_glass.add_child(vbox)

	_label = Label.new()
	_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_label.custom_minimum_size = Vector2(640, 0)
	_label.add_theme_font_size_override("font_size", 22)
	_label.add_theme_color_override("font_color", Color(0.97, 0.98, 1.0))
	vbox.add_child(_label)

	var nav_hbox := HBoxContainer.new()
	nav_hbox.add_theme_constant_override("separation", 14)
	nav_hbox.alignment = BoxContainer.ALIGNMENT_CENTER
	vbox.add_child(nav_hbox)

	_prev_btn = Button.new()
	_prev_btn.text = "← Prev"
	_prev_btn.pressed.connect(_on_prev)
	UiThemeHelper.apply_glass_button(_prev_btn)
	nav_hbox.add_child(_prev_btn)

	_page_label = Label.new()
	_page_label.add_theme_font_size_override("font_size", 14)
	_page_label.add_theme_color_override("font_color", Color(0.9, 0.92, 0.95))
	nav_hbox.add_child(_page_label)

	_next_btn = Button.new()
	_next_btn.text = "Next →"
	_next_btn.pressed.connect(_on_next)
	UiThemeHelper.apply_glass_button(_next_btn)
	nav_hbox.add_child(_next_btn)

	_hint = Label.new()
	_hint.text = "Press E or Space to continue"
	_hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_hint.add_theme_font_size_override("font_size", 14)
	_hint.add_theme_color_override("font_color", Color(0.88, 0.9, 0.94))
	vbox.add_child(_hint)


func _split_into_pages(text: String) -> Array[String]:
	if text.strip_edges().is_empty():
		return ["The end."]
	var pages: Array[String] = []
	var raw_paragraphs := text.split("\n\n", false)
	for p in raw_paragraphs:
		var trimmed := str(p).strip_edges()
		if trimmed.is_empty():
			continue
		if trimmed.length() <= MAX_CHARS_PER_PAGE:
			pages.append(trimmed)
		else:
			var sentences := trimmed.split(". ")
			var chunk := ""
			for i in range(sentences.size()):
				var s := str(sentences[i]).strip_edges()
				if not s.ends_with("."):
					s += "."
				if chunk.length() + s.length() + 1 > MAX_CHARS_PER_PAGE and not chunk.is_empty():
					pages.append(chunk.strip_edges())
					chunk = s
				else:
					chunk = chunk + " " + s if not chunk.is_empty() else s
			if not chunk.is_empty():
				pages.append(chunk.strip_edges())
	if pages.is_empty():
		pages.append("The end.")
	pages.append("The End")
	return pages


func _update_page_display() -> void:
	_prev_btn.visible = _page_index > 0
	_next_btn.visible = _page_index < _pages.size() - 1
	_page_label.visible = _pages.size() > 1
	if _pages.size() > 1:
		_page_label.text = "Page %d of %d" % [_page_index + 1, _pages.size()]
	if _page_index >= 0 and _page_index < _pages.size():
		_label.text = _pages[_page_index]
	if _page_index == _pages.size() - 1:
		_hint.text = "Press E or Space to close"
		_label.add_theme_font_size_override("font_size", 28)
	else:
		_label.add_theme_font_size_override("font_size", 22)
		_hint.text = "Use arrows or buttons to navigate"


func _on_prev() -> void:
	if _page_index > 0:
		_page_index -= 1
		_update_page_display()


func _on_next() -> void:
	if _page_index < _pages.size() - 1:
		if AudioManager:
			AudioManager.stop_voiceover()
		_page_index += 1
		_update_page_display()


func _on_ending() -> void:
	if _tween and _tween.is_valid():
		_tween.kill()
	if AudioManager:
		AudioManager.stop_bgm(true)
	var ending = GameManager.game_bundle.get("narrative", {}).get("ending", {})
	var full_text := str(ending.get("black_screen_text", "The end."))
	_pages = _split_into_pages(full_text)
	_page_index = 0
	_update_page_display()
	visible = true
	_container.modulate.a = 0
	_tween = create_tween()
	_tween.set_trans(Tween.TRANS_SINE)
	_tween.set_ease(Tween.EASE_OUT)
	_tween.tween_property(_container, "modulate:a", 1.0, FADE_DURATION)
	_play_ending_audio(ending)


func _play_ending_audio(ending: Dictionary) -> void:
	if not AudioManager:
		return
	var voice := str(ending.get("voice_path", ""))
	var bgm := str(ending.get("bgm_path", ""))
	if not bgm.is_empty():
		AudioManager.play_bgm(bgm, false, true, true)
	if not voice.is_empty():
		AudioManager.play_voiceover(voice)


func _input(event: InputEvent) -> void:
	if not visible:
		return
	if event.is_action_pressed("ui_left"):
		_on_prev()
		get_viewport().set_input_as_handled()
		return
	if event.is_action_pressed("ui_right"):
		_on_next()
		get_viewport().set_input_as_handled()
		return
	if event.is_action_pressed("ui_accept") or event.is_action_pressed("interact"):
		if _page_index < _pages.size() - 1:
			_on_next()
		else:
			if AudioManager:
				AudioManager.stop_voiceover()
				AudioManager.stop_bgm(true)
			visible = false
		get_viewport().set_input_as_handled()
