extends CanvasLayer
## opening.png + centered glass card: title + Play

signal play_pressed()

var _tex: TextureRect = null

func _ready() -> void:
	layer = 2500
	var root := Control.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(root)

	_tex = TextureRect.new()
	_tex.set_anchors_preset(Control.PRESET_FULL_RECT)
	_tex.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_tex.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	root.add_child(_tex)

	var dim := ColorRect.new()
	dim.set_anchors_preset(Control.PRESET_FULL_RECT)
	dim.color = Color(0.02, 0.03, 0.06, 0.22)
	root.add_child(dim)

	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_child(center)

	var glass := PanelContainer.new()
	glass.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_panel())
	glass.custom_minimum_size = Vector2(480, 200)
	center.add_child(glass)

	var v := VBoxContainer.new()
	v.add_theme_constant_override("separation", 22)
	v.alignment = BoxContainer.ALIGNMENT_CENTER
	glass.add_child(v)

	var title := Label.new()
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 30)
	title.add_theme_color_override("font_color", Color(0.98, 0.99, 1.0))
	v.add_child(title)

	var play := Button.new()
	play.text = "Play"
	play.custom_minimum_size = Vector2(220, 54)
	UiThemeHelper.apply_glass_button(play)
	play.pressed.connect(_on_play)
	v.add_child(play)

	visible = true
	# Ensure title label has height so it's visible
	title.custom_minimum_size = Vector2(0, 36)
	if GameManager:
		var narrative: Dictionary = GameManager.game_bundle.get("narrative", {})
		var meta: Dictionary = narrative.get("meta", {})
		var ending: Dictionary = narrative.get("ending", {})
		var one := str(meta.get("one_sentence_premise", ""))
		# Prefer story title: ending.title, then meta.title, then premise
		var game_title: String = str(ending.get("title", "")).strip_edges()
		if game_title.is_empty():
			game_title = str(meta.get("title", "")).strip_edges()
		if game_title.is_empty():
			game_title = one if one.length() <= 60 else one.substr(0, 60)
		if game_title.is_empty():
			game_title = "Story"
		title.text = game_title
	_load_bg()


func _load_bg() -> void:
	if not GameManager:
		return
	var tex := GameManager.bundle_load_texture("opening.png")
	if tex:
		_tex.texture = tex


func _on_play() -> void:
	if GameManager:
		GameManager.title_passed = true
	visible = false
	play_pressed.emit()
