extends CanvasLayer
## Intro screen: player role, premise, Begin button

var _container: Control = null  ## CanvasItem with modulate for fade
var _overlay: ColorRect = null
var _vbox: VBoxContainer = null
var _genre_label: Label = null
var _role_label: Label = null
var _premise_label: Label = null
var _begin_btn: Button = null
var _tween: Tween = null
const FADE_DURATION := 0.4

signal begun()

func _ready() -> void:
	layer = 2000
	_build_ui()
	visible = true
	# CanvasLayer has no modulate; use child Control
	_container.modulate.a = 0
	_tween = create_tween()
	_tween.set_trans(Tween.TRANS_SINE)
	_tween.set_ease(Tween.EASE_OUT)
	_tween.tween_property(_container, "modulate:a", 1.0, FADE_DURATION)


func _build_ui() -> void:
	_container = Control.new()
	_container.set_anchors_preset(Control.PRESET_FULL_RECT)
	_container.mouse_filter = Control.MOUSE_FILTER_STOP  # Must receive input so Begin button works
	add_child(_container)

	_overlay = ColorRect.new()
	_overlay.set_anchors_preset(Control.PRESET_FULL_RECT)
	_overlay.color = Color.BLACK
	_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	_container.add_child(_overlay)

	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	_container.add_child(center)

	_vbox = VBoxContainer.new()
	_vbox.add_theme_constant_override("separation", 24)
	_vbox.custom_minimum_size.x = 500
	center.add_child(_vbox)

	_genre_label = Label.new()
	_genre_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_genre_label.add_theme_font_size_override("font_size", 11)
	_genre_label.add_theme_color_override("font_color", Color(0.54, 0.56, 0.59))
	_vbox.add_child(_genre_label)

	var who_label := Label.new()
	who_label.text = "WHO YOU ARE"
	who_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	who_label.add_theme_font_size_override("font_size", 12)
	who_label.add_theme_color_override("font_color", Color(0.55, 0.68, 0.42))
	_vbox.add_child(who_label)

	_role_label = Label.new()
	_role_label.text = "You are the protagonist."
	_role_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_role_label.add_theme_font_size_override("font_size", 22)
	_role_label.add_theme_color_override("font_color", Color(0.91, 0.91, 0.91))
	_vbox.add_child(_role_label)

	var story_label := Label.new()
	story_label.text = "YOUR STORY"
	story_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	story_label.add_theme_font_size_override("font_size", 12)
	story_label.add_theme_color_override("font_color", Color(0.55, 0.68, 0.42))
	_vbox.add_child(story_label)

	_premise_label = Label.new()
	_premise_label.text = "Your story begins here."
	_premise_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_premise_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_premise_label.add_theme_font_size_override("font_size", 16)
	_premise_label.add_theme_color_override("font_color", Color(0.91, 0.91, 0.91))
	_vbox.add_child(_premise_label)

	_begin_btn = Button.new()
	_begin_btn.text = "Begin"
	_begin_btn.pressed.connect(_on_begin)
	_begin_btn.custom_minimum_size = Vector2(140, 48)
	_vbox.add_child(_begin_btn)


func _process(_delta: float) -> void:
	if GameManager and not GameManager.game_bundle.is_empty() and visible:
		_refresh()


func _refresh() -> void:
	var meta = GameManager.game_bundle.get("narrative", {}).get("meta", {})
	var role := str(meta.get("player_role", "the protagonist"))
	if role.length() > 0:
		role = role.substr(0, 1).to_upper() + role.substr(1)
	_role_label.text = "You are " + role + "."
	var premise: String = str(meta.get("intro_premise", ""))
	if premise.is_empty():
		premise = str(meta.get("one_sentence_premise", "Your story begins here."))
	_premise_label.text = premise
	var genre := str(meta.get("genre", ""))
	var tone := str(meta.get("tone", ""))
	if _genre_label:
		var parts: PackedStringArray = []
		if not genre.is_empty():
			parts.append(genre)
		if not tone.is_empty():
			parts.append(tone)
		_genre_label.text = " · ".join(parts)
		_genre_label.visible = parts.size() > 0


func _on_begin() -> void:
	if GameManager:
		GameManager.intro_begun = true
	# Capture mouse for look-around so it works immediately (no extra click needed)
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	visible = false
	begun.emit()
