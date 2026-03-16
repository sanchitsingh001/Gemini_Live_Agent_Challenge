extends CanvasLayer
## Centered-bottom hint: "Press E to talk to [Name]" or "Press E to examine" when near NPC/clue.
## Fades in/out with Tween when entering/leaving range.

var _container: Control = null  ## CanvasItem with modulate for fade (CanvasLayer has no modulate)
var _label: Label = null
var _panel: PanelContainer = null
var _tween: Tween = null
var _last_want_visible: bool = false
const FADE_DURATION := 0.15

const _text_color := Color(0.96, 0.98, 1.0)

func _ready() -> void:
	layer = 250
	_build_ui()
	visible = false
	_container.modulate.a = 0.0


func _build_ui() -> void:
	_container = Control.new()
	_container.set_anchors_preset(Control.PRESET_FULL_RECT)
	_container.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_container)

	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	center.anchor_top = 0.75
	center.anchor_bottom = 1.0
	center.mouse_filter = Control.MOUSE_FILTER_IGNORE  # Let clicks pass through for mouse capture
	_container.add_child(center)

	_panel = PanelContainer.new()
	_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE  # Don't block clicks (player needs them for capture)
	_panel.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_modal())
	center.add_child(_panel)

	_label = Label.new()
	_label.text = "Press E to interact"
	_label.add_theme_font_size_override("font_size", 15)
	_label.add_theme_color_override("font_color", _text_color)
	_panel.add_child(_label)


func _process(_delta: float) -> void:
	if not GameManager or GameManager.game_bundle.is_empty():
		return
	var near := GameManager.near_interactable
	var want_visible := not near.is_empty()
	var hint_text := ""
	if near.get("type", "") == "npc":
		# Already in conversation — don't show "Press E to talk" on top of dialogue UI
		if GameManager.dialogue_npc != null:
			want_visible = false
		elif DialogueManager and DialogueManager.has_active_dialogue():
			want_visible = false
		else:
			var name := str(near.get("name", "Someone"))
			hint_text = "Press E to talk to " + name
	elif near.get("type", "") == "clue":
		hint_text = "Press E to examine"
	if want_visible:
		_label.text = hint_text
	if want_visible != _last_want_visible:
		_last_want_visible = want_visible
		_animate_visibility(want_visible)


func _animate_visibility(show_hint: bool) -> void:
	if _tween and _tween.is_valid():
		_tween.kill()
	_tween = create_tween()
	_tween.set_trans(Tween.TRANS_SINE)
	_tween.set_ease(Tween.EASE_OUT)
	var target_alpha := 1.0 if show_hint else 0.0
	var target_visible := show_hint
	if show_hint:
		visible = true
	_tween.tween_property(_container, "modulate:a", target_alpha, FADE_DURATION)
	if not show_hint:
		_tween.tween_callback(func(): visible = false)
