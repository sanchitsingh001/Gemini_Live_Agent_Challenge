extends CanvasLayer
## Right panel: collected clues. Toggle with C key.

var _panel: PanelContainer = null
var _scroll: ScrollContainer = null
var _list: VBoxContainer = null
var _empty_label: Label = null
var _tween: Tween = null
const ANIM_DURATION := 0.2
const PANEL_WIDTH_OFFSET := 400

func _ready() -> void:
	layer = 5100
	_build_ui()
	visible = false
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_to_group("clue_inventory")
	# Do NOT handle C in _input: Player._physics_process polls inventory/C for Mac/HTML5.
	# Handling here + poll = same-frame double toggle (open then close → "C broken").
	set_process_input(false)


## Called from Player physics poll (Mac-safe); same as C key
func toggle_clues() -> void:
	_toggle()


func _build_ui() -> void:
	_panel = PanelContainer.new()
	_panel.set_anchors_preset(Control.PRESET_RIGHT_WIDE)
	_panel.anchor_left = 0.75
	_panel.anchor_right = 1.0
	_panel.anchor_top = 0.0
	_panel.anchor_bottom = 1.0
	_panel.offset_left = -12
	_panel.offset_top = 80
	_panel.offset_bottom = -12
	_panel.offset_right = 12
	_panel.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_panel())
	add_child(_panel)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 12)
	_panel.add_child(vbox)

	var header := Label.new()
	header.text = "Clues"
	header.add_theme_font_size_override("font_size", 18)
	header.add_theme_color_override("font_color", Color.WHITE)
	vbox.add_child(header)

	_scroll = ScrollContainer.new()
	_scroll.custom_minimum_size.y = 200
	_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_list = VBoxContainer.new()
	_list.add_theme_constant_override("separation", 12)
	_scroll.add_child(_list)
	vbox.add_child(_scroll)

	_empty_label = Label.new()
	_empty_label.text = "No clues yet. Explore and talk to NPCs."
	_empty_label.add_theme_font_size_override("font_size", 12)
	_empty_label.add_theme_color_override("font_color", Color(0.54, 0.56, 0.59))
	_list.add_child(_empty_label)


func _toggle() -> void:
	if _tween and _tween.is_valid():
		_tween.kill()
	var want_show := not visible
	if want_show:
		visible = true
		_panel.offset_left = PANEL_WIDTH_OFFSET
		_tween = create_tween()
		_tween.set_trans(Tween.TRANS_SINE)
		_tween.set_ease(Tween.EASE_OUT)
		_tween.tween_property(_panel, "offset_left", -12, ANIM_DURATION)
	else:
		_tween = create_tween()
		_tween.set_trans(Tween.TRANS_SINE)
		_tween.set_ease(Tween.EASE_IN)
		_tween.tween_property(_panel, "offset_left", PANEL_WIDTH_OFFSET, ANIM_DURATION)
		_tween.tween_callback(func(): visible = false)


func _process(_delta: float) -> void:
	if GameManager and not GameManager.game_bundle.is_empty():
		_refresh()


func _refresh() -> void:
	if not _list:
		return
	for c in _list.get_children():
		if c != _empty_label:
			c.queue_free()
	var collected := GameManager.get_collected_clues()
	_empty_label.visible = collected.is_empty()
	for clue in collected:
		var card := PanelContainer.new()
		card.add_theme_stylebox_override("panel", UiThemeHelper.style_pill())
		var card_v := VBoxContainer.new()
		card_v.add_theme_constant_override("separation", 4)
		var title := Label.new()
		title.text = str(clue.get("label", clue.get("id", "?")))
		title.add_theme_font_size_override("font_size", 14)
		title.add_theme_color_override("font_color", Color(0.92, 0.92, 0.92))
		card_v.add_child(title)
		var desc := Label.new()
		desc.text = str(clue.get("description", ""))
		desc.add_theme_font_size_override("font_size", 12)
		desc.add_theme_color_override("font_color", Color(0.54, 0.56, 0.59))
		desc.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		desc.custom_minimum_size.x = 180
		card_v.add_child(desc)
		card.add_child(card_v)
		_list.add_child(card)
