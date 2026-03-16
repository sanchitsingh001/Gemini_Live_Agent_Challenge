extends CanvasLayer
## Clue collected toast: brief top-center notification

var _panel: PanelContainer = null
var _label: Label = null
var _timer: float = 0.0
var _margin: MarginContainer = null
var _tween: Tween = null
var _hiding: bool = false
const ANIM_DURATION := 0.2

func _ready() -> void:
	layer = 800
	_build_ui()
	visible = false
	if GameManager:
		GameManager.clue_added.connect(_on_clue_added)


func _build_ui() -> void:
	_margin = MarginContainer.new()
	_margin.set_anchors_preset(Control.PRESET_TOP_WIDE)
	_margin.anchor_top = 0.0
	_margin.anchor_left = 0.0
	_margin.anchor_right = 1.0
	_margin.offset_top = 60
	_margin.offset_left = 100
	_margin.offset_right = -100
	add_child(_margin)

	_panel = PanelContainer.new()
	_panel.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_toast())
	_margin.add_child(_panel)

	_label = Label.new()
	_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_label.add_theme_font_size_override("font_size", 16)
	_label.add_theme_color_override("font_color", Color(0.91, 0.91, 0.91))
	_panel.add_child(_label)


func _on_clue_added(clue_id: String) -> void:
	if _tween and _tween.is_valid():
		_tween.kill()
	var label := clue_id
	if GameManager and not GameManager.game_bundle.is_empty():
		for c in GameManager.game_bundle.get("narrative", {}).get("clues", []):
			if c is Dictionary and str(c.get("id", "")) == clue_id:
				label = str(c.get("label", clue_id))
				break
	_label.text = "Collected: " + label
	visible = true
	_hiding = false
	_timer = 2.5
	_margin.position.y = -80
	_margin.modulate.a = 0
	_tween = create_tween()
	_tween.set_trans(Tween.TRANS_SINE)
	_tween.set_ease(Tween.EASE_OUT)
	_tween.set_parallel(true)
	_tween.tween_property(_margin, "position:y", 0, ANIM_DURATION)
	_tween.tween_property(_margin, "modulate:a", 1.0, ANIM_DURATION)


func _process(delta: float) -> void:
	if not visible or _hiding:
		return
	_timer -= delta
	if _timer <= 0:
		_hide_toast()


func _hide_toast() -> void:
	_hiding = true
	if _tween and _tween.is_valid():
		_tween.kill()
	_tween = create_tween()
	_tween.set_trans(Tween.TRANS_SINE)
	_tween.set_ease(Tween.EASE_IN)
	_tween.set_parallel(true)
	_tween.tween_property(_margin, "modulate:a", 0.0, ANIM_DURATION * 0.8)
	_tween.tween_callback(_on_hide_done)


func _on_hide_done() -> void:
	visible = false
	_hiding = false
