extends CanvasLayer
## NPC dialogue: bottom NPC line (left) + **individual choice buttons on the right** (no scroll).

signal closed()

var _npc_id: String = ""
var _npc_name: String = ""
var _root: Control = null
var _dim: ColorRect = null
var _name_lbl: Label = null
var _body_lbl: Label = null
var _hint_lbl: Label = null
var _npc_bar: PanelContainer = null
var _choices_rail: PanelContainer = null
var _choices_vbox: VBoxContainer = null
var _http: HTTPRequest = null
var _sending: bool = false
var _error_lbl: Label = null
var _loading: Label = null
var _choice_rows: Array = []
var conversation_open: bool = false
var _dot_phase: float = 0.0
var _typing: bool = false
var _typing_text: String = ""
var _typing_visible_chars: int = 0
var _typing_speed: float = 55.0 # characters per second
var _typing_accum: float = 0.0
const _BOTTOM_MARGIN := 14
const _SIDE_MARGIN := 16
const _CHOICES_WIDTH := 320
const _CHOICE_SEP := 10
const _CHOICE_MIN_HEIGHT := 52


func _ready() -> void:
	layer = 2600
	_http = HTTPRequest.new()
	add_child(_http)
	_http.request_completed.connect(_on_http_done)
	_build()
	conversation_open = false
	visible = false
	set_process_unhandled_input(true)
	set_process_input(true)


func _key_to_choice_index(event: InputEvent) -> int:
	if not (event is InputEventKey) or not event.pressed or event.echo:
		return -1
	var evk := event as InputEventKey
	var k: int = int(evk.keycode)
	if k == 0:
		k = int(evk.physical_keycode)
	var u: int = int(evk.unicode)
	if k >= KEY_1 and k <= KEY_9:
		return k - KEY_1
	if k >= KEY_KP_1 and k <= KEY_KP_9:
		return k - KEY_KP_1
	if u >= 49 and u <= 57:
		return u - 49
	return -1


func _try_number_choice(event: InputEvent) -> bool:
	var idx: int = _key_to_choice_index(event)
	if idx < 0 or idx >= _choice_rows.size():
		return false
	var row: Dictionary = _choice_rows[idx]
	_on_choice_pressed(str(row.get("id", "")), str(row.get("label", "")))
	get_viewport().set_input_as_handled()
	return true


func _input(event: InputEvent) -> void:
	if not conversation_open:
		return
	if event.is_action_pressed("ui_cancel"):
		if not _sending:
			close_dialogue()
			get_viewport().set_input_as_handled()
		return
	if _sending:
		return
	if _try_number_choice(event):
		return


func _process(delta: float) -> void:
	if not conversation_open:
		return

	if _sending:
		_dot_phase += delta
		var frame: int = int(_dot_phase / 0.45) % 4
		var dots: String = ["   ", ".  ", ".. ", "..."][frame]
		_loading.text = dots
		_loading.visible = true
		_body_lbl.text = ""
		return

	if _typing:
		_typing_accum += delta * _typing_speed
		var target_visible := int(_typing_accum)
		if target_visible > _typing_visible_chars:
			_typing_visible_chars = min(target_visible, _typing_text.length())
			_body_lbl.text = _typing_text.substr(0, _typing_visible_chars)
		if _typing_visible_chars >= _typing_text.length():
			_typing = false
			_loading.visible = false


func _inner_choice_width() -> int:
	var style := _choices_rail.get_theme_stylebox("panel") if _choices_rail else null
	var pad := 32
	if style:
		pad = int(style.get_content_margin(SIDE_LEFT) + style.get_content_margin(SIDE_RIGHT))
	return max(120, _CHOICES_WIDTH - pad)


func _make_choice_button(number_prefix: String, line: String) -> Button:
	var b := Button.new()
	b.text = number_prefix + line
	b.focus_mode = Control.FOCUS_NONE
	b.alignment = HORIZONTAL_ALIGNMENT_LEFT
	b.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	b.clip_text = false
	var w := _inner_choice_width()
	b.custom_minimum_size = Vector2(w, _CHOICE_MIN_HEIGHT)
	UiThemeHelper.apply_dialogue_choice_button(b)
	return b


func _layout_choices_rail() -> void:
	if not _choices_rail or not _choices_vbox:
		return
	call_deferred("_do_layout_choices_rail")
	_refresh_choice_rail_size()


func _refresh_choice_rail_size() -> void:
	## After layout, autowrap updates button height — second pass so rail grows with text.
	await get_tree().process_frame
	if not is_instance_valid(_choices_rail):
		return
	_do_layout_choices_rail()


func _do_layout_choices_rail() -> void:
	if not is_instance_valid(_choices_rail):
		return
	var sep := _CHOICE_SEP
	var content_h := 0
	var n := _choices_vbox.get_child_count()
	for i in n:
		var ch := _choices_vbox.get_child(i)
		if ch is Control:
			content_h += (ch as Control).get_combined_minimum_size().y
			if i < n - 1:
				content_h += sep
	var style := _choices_rail.get_theme_stylebox("panel")
	if style:
		content_h += int(style.get_content_margin(SIDE_TOP) + style.get_content_margin(SIDE_BOTTOM))
	content_h = max(content_h, _CHOICE_MIN_HEIGHT + 24)
	_choices_rail.custom_minimum_size = Vector2(_CHOICES_WIDTH, content_h)
	_choices_rail.size = Vector2(_CHOICES_WIDTH, content_h)
	_choices_rail.anchor_left = 1.0
	_choices_rail.anchor_right = 1.0
	_choices_rail.anchor_top = 1.0
	_choices_rail.anchor_bottom = 1.0
	_choices_rail.offset_left = -_CHOICES_WIDTH - _SIDE_MARGIN
	_choices_rail.offset_right = -_SIDE_MARGIN
	_choices_rail.offset_bottom = -_BOTTOM_MARGIN
	_choices_rail.offset_top = _choices_rail.offset_bottom - content_h


func _build() -> void:
	_root = Control.new()
	_root.set_anchors_preset(Control.PRESET_FULL_RECT)
	_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_root)

	_dim = ColorRect.new()
	_dim.set_anchors_preset(Control.PRESET_FULL_RECT)
	_dim.color = Color(0.04, 0.06, 0.12, 0.16)
	_dim.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_root.add_child(_dim)

	# NPC block: bottom-left, leaves gutter for choice column on the right
	_npc_bar = PanelContainer.new()
	_npc_bar.set_anchors_preset(Control.PRESET_BOTTOM_WIDE)
	_npc_bar.anchor_top = 1.0
	_npc_bar.anchor_bottom = 1.0
	_npc_bar.offset_left = _SIDE_MARGIN
	_npc_bar.offset_right = -_CHOICES_WIDTH - _SIDE_MARGIN - 12
	# Lift the NPC bar so it no longer touches the bottom edge at all.
	# Keep the same 160px height, but add a vertical gap above the bottom margin.
	var npc_bar_height := 160
	var bottom_gap := _BOTTOM_MARGIN + 40
	_npc_bar.offset_bottom = -bottom_gap
	_npc_bar.offset_top = -bottom_gap - npc_bar_height
	_npc_bar.mouse_filter = Control.MOUSE_FILTER_STOP
	_npc_bar.add_theme_stylebox_override("panel", UiThemeHelper.style_dialogue_bar())
	_root.add_child(_npc_bar)

	var bar_v := VBoxContainer.new()
	bar_v.add_theme_constant_override("separation", 10)
	_npc_bar.add_child(bar_v)

	var name_strip := PanelContainer.new()
	name_strip.add_theme_stylebox_override("panel", UiThemeHelper.style_dialogue_name_strip())
	var name_inner := HBoxContainer.new()
	_name_lbl = Label.new()
	_name_lbl.text = "NPC"
	_name_lbl.add_theme_font_size_override("font_size", 15)
	_name_lbl.add_theme_color_override("font_color", Color(0.92, 0.94, 0.98))
	name_inner.add_child(_name_lbl)
	name_strip.add_child(name_inner)
	bar_v.add_child(name_strip)

	var body_scroll := ScrollContainer.new()
	body_scroll.custom_minimum_size = Vector2(0, 64)
	body_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	bar_v.add_child(body_scroll)
	_body_lbl = Label.new()
	_body_lbl.text = "…"
	_body_lbl.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_body_lbl.add_theme_font_size_override("font_size", 17)
	_body_lbl.add_theme_color_override("font_color", Color(0.98, 0.99, 1.0))
	_body_lbl.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body_scroll.add_child(_body_lbl)

	var foot := HBoxContainer.new()
	foot.add_theme_constant_override("separation", 16)
	_hint_lbl = Label.new()
	_hint_lbl.text = "1–9 choose · Esc close · C clues"
	_hint_lbl.add_theme_font_size_override("font_size", 12)
	_hint_lbl.add_theme_color_override("font_color", Color(0.82, 0.88, 0.94))
	foot.add_child(_hint_lbl)
	_loading = Label.new()
	_loading.text = "   "
	_loading.visible = false
	_loading.add_theme_font_size_override("font_size", 14)
	_loading.add_theme_color_override("font_color", Color(0.88, 0.92, 0.96))
	foot.add_child(_loading)
	bar_v.add_child(foot)

	_error_lbl = Label.new()
	_error_lbl.add_theme_font_size_override("font_size", 12)
	_error_lbl.add_theme_color_override("font_color", Color(1, 0.55, 0.55))
	_error_lbl.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_error_lbl.visible = false
	bar_v.add_child(_error_lbl)

	# Right column: one button per option, **no ScrollContainer** — stack grows upward from bottom
	_choices_rail = PanelContainer.new()
	_choices_rail.mouse_filter = Control.MOUSE_FILTER_STOP
	_choices_rail.add_theme_stylebox_override("panel", UiThemeHelper.style_dialogue_bar())
	_root.add_child(_choices_rail)

	_choices_vbox = VBoxContainer.new()
	_choices_vbox.add_theme_constant_override("separation", _CHOICE_SEP)
	_choices_vbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_choices_rail.add_child(_choices_vbox)
	_do_layout_choices_rail()


func _unhandled_input(event: InputEvent) -> void:
	if not conversation_open or _sending:
		return
	if event.is_action_pressed("ui_cancel"):
		close_dialogue()
		get_viewport().set_input_as_handled()
		return
	if _try_number_choice(event):
		pass


func open_dialogue(npc_id: String, npc_name: String, npc_node: Node = null) -> void:
	_npc_id = npc_id
	_npc_name = npc_name
	_name_lbl.text = npc_name
	_body_lbl.text = ""
	_dot_phase = 0.0
	_loading.text = "   "
	_loading.visible = true
	_typing = false
	_typing_text = ""
	_typing_visible_chars = 0
	_typing_accum = 0.0
	_body_lbl.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_error_lbl.visible = false
	_clear_choices()
	_choice_rows.clear()
	conversation_open = true
	layer = 5000
	visible = true
	_root.visible = true
	_npc_bar.visible = true
	_choices_rail.visible = true
	process_mode = Node.PROCESS_MODE_ALWAYS
	set_process(true)
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	if GameManager:
		GameManager.record_npc_dialogue_open(npc_id)
		GameManager.dialogue_npc = npc_node
	_request_turn("open", "", "")


func _clear_choices() -> void:
	for c in _choices_vbox.get_children():
		c.queue_free()
	_choice_rows.clear()


func _show_selected_only(choice_label: String) -> void:
	_clear_choices()
	var b := Button.new()
	b.text = choice_label
	b.disabled = true
	b.focus_mode = Control.FOCUS_NONE
	b.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	b.alignment = HORIZONTAL_ALIGNMENT_LEFT
	b.custom_minimum_size = Vector2(_inner_choice_width(), _CHOICE_MIN_HEIGHT)
	b.add_theme_stylebox_override("normal", UiThemeHelper.style_dialogue_selected_choice())
	b.add_theme_stylebox_override("hover", UiThemeHelper.style_dialogue_selected_choice())
	b.add_theme_stylebox_override("pressed", UiThemeHelper.style_dialogue_selected_choice())
	b.add_theme_stylebox_override("disabled", UiThemeHelper.style_dialogue_selected_choice())
	b.add_theme_color_override("font_color", Color(0.95, 0.99, 0.96))
	b.add_theme_font_size_override("font_size", 15)
	_choices_vbox.add_child(b)
	_choice_rows.clear()
	_layout_choices_rail()


func _request_turn(kind: String, choice_id: String, choice_label: String) -> void:
	if _sending:
		return
	_sending = true
	set_process(true)
	_dot_phase = 0.0
	_loading.visible = true
	_loading.add_theme_font_size_override("font_size", 18)
	_body_lbl.text = ""
	_error_lbl.visible = false
	var conv: Array = GameManager.get_conversation(_npc_id) if GameManager else []
	var collected: Array = []
	for k in GameManager.collected_clue_ids.keys():
		if GameManager.collected_clue_ids[k]:
			collected.append(k)
	var ch: Dictionary = GameManager.get_current_chapter() if GameManager else {}
	var cur_chapter: String = str(ch.get("id", "chapter_1")) if ch else "chapter_1"
	var base := GameManager.game_server_url if GameManager else "http://127.0.0.1:8000"
	var body := {
		"npc_id": _npc_id,
		"current_chapter": cur_chapter,
		"collected_clues": collected,
		"conversation_history": conv,
		"turn_kind": kind,
		"choice_id": choice_id,
		"choice_label": choice_label
	}
	if GameManager and not GameManager.game_output_path.is_empty():
		body["output"] = GameManager.game_output_path
	var err := _http.request(base + "/api/dialogue_turn", ["Content-Type: application/json"], HTTPClient.METHOD_POST, JSON.stringify(body))
	if err != OK:
		_sending = false
		_loading.visible = false
		_body_lbl.text = "Could not send request to %s (err %s). Is the game server running (port 8000)?" % [base, str(err)]
		set_process(false)
		_place_fallback_bye()


func _place_fallback_bye() -> void:
	_clear_choices()
	_choice_rows.append({"id": "bye", "label": "Goodbye."})
	var b := _make_choice_button("1  ", "Goodbye.")
	b.pressed.connect(_on_choice_pressed.bind("bye", "Goodbye."))
	_choices_vbox.add_child(b)
	_layout_choices_rail()


func _on_http_done(_result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	_sending = false
	_loading.visible = false
	set_process(true)
	var txt := body.get_string_from_utf8()
	var parsed = JSON.parse_string(txt)
	if _result != HTTPRequest.RESULT_SUCCESS:
		_body_lbl.text = "Server unreachable (result %s). Run: ./run_game.sh --godot from Narrative_Engine." % str(_result)
		_place_fallback_bye()
		return
	if parsed is Dictionary and code < 400:
		var line := str(parsed.get("npc_line", ""))
		var choices: Array = parsed.get("choices", [])
		var awarded: Array = parsed.get("awarded_clues", [])
		var ended: bool = bool(parsed.get("conversation_ended", false))
		var audio_url := str(parsed.get("npc_audio_url", ""))
		if GameManager:
			GameManager.append_message(_npc_id, "assistant", line)
			for cid in awarded:
				GameManager.add_clue(str(cid))
			if awarded.size() > 0:
				GameManager.record_npc_clue_award(_npc_id)
		_typing_text = line if not line.is_empty() else "…"
		_typing_visible_chars = 0
		_typing_accum = 0.0
		_typing = true
		_body_lbl.text = ""
		_clear_choices()
		var num := 1
		for c in choices:
			if c is Dictionary:
				var id := str(c.get("id", ""))
				var lab := str(c.get("label", "…"))
				_choice_rows.append({"id": id, "label": lab})
				var b := _make_choice_button("%d  " % num, lab)
				b.pressed.connect(_on_choice_pressed.bind(id, lab))
				_choices_vbox.add_child(b)
				num += 1
		_layout_choices_rail()
		if ended:
			call_deferred("_close_and_apply")
		# NPC TTS (optional)
		if not audio_url.is_empty():
			var nvm := get_node_or_null("/root/NpcVoiceManager")
			if nvm:
				nvm.play_npc_voice(_npc_id, audio_url)
	else:
		var detail := str(parsed.get("detail", txt.substr(0, 200))) if parsed is Dictionary else txt.substr(0, 300)
		_body_lbl.text = "Dialogue error (HTTP %s): %s" % [str(code), detail]
		_place_fallback_bye()


func _on_choice_pressed(choice_id: String, choice_label: String) -> void:
	if _sending:
		return
	if choice_id.to_lower() == "bye":
		if GameManager:
			GameManager.append_message(_npc_id, "user", choice_label)
		_show_selected_only(choice_label)
		_request_turn("bye", "bye", choice_label)
		return
	if GameManager:
		GameManager.append_message(_npc_id, "user", choice_label)
	_show_selected_only(choice_label)
	_request_turn("choice", choice_id, choice_label)


func _close_and_apply() -> void:
	# Stop NPC voice immediately when dialogue closes.
	var nvm := get_node_or_null("/root/NpcVoiceManager")
	if nvm:
		nvm.stop_npc_voice()
	conversation_open = false
	set_process(false)
	layer = 2600
	visible = false
	process_mode = Node.PROCESS_MODE_INHERIT
	if GameManager:
		GameManager.dialogue_npc = null
		GameManager.apply_pending_transitions_if_any()
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	closed.emit()


func close_dialogue() -> void:
	if conversation_open or visible:
		if GameManager:
			GameManager.dialogue_npc = null
		_close_and_apply()


func open_chat(npc_id: String, npc_name: String, npc_node: Node = null) -> void:
	open_dialogue(npc_id, npc_name, npc_node)


func close_chat() -> void:
	close_dialogue()


func is_npc_chat_open() -> bool:
	return conversation_open
