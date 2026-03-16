extends CanvasLayer
## NPC chat modal: conversation history, input, Send. Calls game_server /api/chat.

signal closed()
signal awarded_clues(clue_ids: Array)

var _npc_id: String = ""
var _npc_name: String = ""
var _panel: PanelContainer = null
var _history: RichTextLabel = null
var _input_field: LineEdit = null
var _send_btn: Button = null
var _close_btn: Button = null
var _error_label: Label = null
var _header_label: Label = null
var _http: HTTPRequest = null
var _sending: bool = false
var _container: Control = null  ## CanvasItem with modulate (CanvasLayer has none)
var _dim: ColorRect = null
var _center: Control = null
var _scroll: ScrollContainer = null
var _loading_label: Label = null
var _tween: Tween = null
const ANIM_DURATION := 0.2

func _ready() -> void:
	layer = 1000
	_process_input(false)
	_build_ui()
	visible = false


func _build_ui() -> void:
	_container = Control.new()
	_container.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_container)
	# Fullscreen dim
	_dim = ColorRect.new()
	_dim.name = "Dim"
	_dim.set_anchors_preset(Control.PRESET_FULL_RECT)
	_dim.color = Color(0.02, 0.04, 0.08, 0.5)
	_dim.mouse_filter = Control.MOUSE_FILTER_STOP
	_dim.gui_input.connect(_on_dim_input)
	_container.add_child(_dim)

	# Panel centered on screen
	_center = Control.new()
	_center.set_anchors_preset(Control.PRESET_FULL_RECT)
	_container.add_child(_center)

	_panel = PanelContainer.new()
	_panel.custom_minimum_size = Vector2(520, 420)
	_panel.size = Vector2(520, 420)
	_panel.mouse_filter = Control.MOUSE_FILTER_STOP
	_panel.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_modal())
	_center.add_child(_panel)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 12)
	_panel.add_child(vbox)

	# Header
	var header := PanelContainer.new()
	header.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_header_strip())
	var header_h := HBoxContainer.new()
	header_h.add_theme_constant_override("separation", 12)
	_header_label = Label.new()
	_header_label.name = "NpcName"
	_header_label.text = "NPC"
	_header_label.add_theme_font_size_override("font_size", 20)
	_header_label.add_theme_color_override("font_color", Color(0.85, 0.94, 0.88))
	header_h.add_child(_header_label)
	_close_btn = Button.new()
	_close_btn.text = "✕"
	_close_btn.pressed.connect(_on_close)
	UiThemeHelper.apply_glass_button(_close_btn)
	header_h.add_child(_close_btn)
	header.add_child(header_h)
	vbox.add_child(header)

	# History
	_scroll = ScrollContainer.new()
	_scroll.custom_minimum_size.y = 200
	_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var vbar := _scroll.get_v_scroll_bar()
	if vbar:
		vbar.step = 4.0
	_history = RichTextLabel.new()
	_history.bbcode_enabled = false
	_history.fit_content = true
	_history.scroll_following = true
	_history.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_history.custom_minimum_size.x = 400
	_history.add_theme_font_size_override("normal_font_size", 16)
	_history.add_theme_color_override("default_color", Color(0.95, 0.95, 0.95))
	_history.add_theme_color_override("font_color", Color(0.95, 0.95, 0.95))
	_scroll.add_child(_history)
	vbox.add_child(_scroll)

	_error_label = Label.new()
	_error_label.add_theme_color_override("font_color", Color(0.9, 0.4, 0.4))
	_error_label.visible = false
	vbox.add_child(_error_label)

	_loading_label = Label.new()
	_loading_label.text = "..."
	_loading_label.add_theme_font_size_override("font_size", 12)
	_loading_label.add_theme_color_override("font_color", Color(0.6, 0.6, 0.6))
	_loading_label.visible = false
	vbox.add_child(_loading_label)

	# Input row
	var input_row := HBoxContainer.new()
	input_row.add_theme_constant_override("separation", 8)
	_input_field = LineEdit.new()
	_input_field.placeholder_text = "Type a message..."
	_input_field.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_input_field.custom_minimum_size.x = 360
	_input_field.add_theme_font_size_override("font_size", 16)
	_input_field.add_theme_color_override("font_color", Color(0.95, 0.95, 0.95))
	_input_field.add_theme_color_override("placeholder_color", Color(0.6, 0.6, 0.6))
	_input_field.text_submitted.connect(_on_input_submitted)
	_input_field.text_changed.connect(_on_input_text_changed)
	input_row.add_child(_input_field)
	_send_btn = Button.new()
	_send_btn.text = "Send"
	_send_btn.pressed.connect(_do_send)
	UiThemeHelper.apply_glass_button(_send_btn)
	input_row.add_child(_send_btn)
	vbox.add_child(input_row)

	_http = HTTPRequest.new()
	add_child(_http)
	_http.request_completed.connect(_on_request_completed)


func _process_input(enable: bool) -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS if enable else Node.PROCESS_MODE_INHERIT


func _input(event: InputEvent) -> void:
	if not visible:
		return
	# Don't consume any keys - let them reach the LineEdit for typing.
	# clue_inventory_panel and settings_menu already skip C/ESC when chat is open.


func _on_dim_input(ev: InputEvent) -> void:
	if ev is InputEventMouseButton and ev.pressed and ev.button_index == MOUSE_BUTTON_LEFT:
		_on_close()


func open_chat(npc_id: String, npc_name: String) -> void:
	_npc_id = npc_id
	_npc_name = npc_name
	_history.text = ""
	_input_field.text = ""
	_error_label.visible = false
	_sending = false
	_update_send_state()
	_update_loading()
	if _header_label:
		_header_label.text = _npc_name
	if _tween and _tween.is_valid():
		_tween.kill()
	visible = true
	# Center panel on screen using viewport size
	var vp_size := get_viewport().get_visible_rect().size
	_panel.position = Vector2(vp_size.x * 0.5 - 260, vp_size.y * 0.5 - 210)
	_panel.size = Vector2(520, 420)
	_process_input(true)
	Input.set_mouse_mode(Input.MOUSE_MODE_VISIBLE)
	_modulate_in()
	_input_field.call_deferred("grab_focus")


func _on_close() -> void:
	close_chat()

func close_chat() -> void:
	if _tween and _tween.is_valid():
		_tween.kill()
	_modulate_out()


func _modulate_in() -> void:
	_container.modulate = Color(1, 1, 1, 0)
	if _dim:
		_dim.color.a = 0
	var center_y := get_viewport().get_visible_rect().size.y * 0.5 - 210
	_panel.position.y = center_y + 20
	_panel.modulate = Color(1, 1, 1, 0.95)
	_tween = create_tween()
	_tween.set_trans(Tween.TRANS_SINE)
	_tween.set_ease(Tween.EASE_OUT)
	_tween.set_parallel(true)
	_tween.tween_property(_container, "modulate:a", 1.0, ANIM_DURATION)
	_tween.tween_property(_panel, "position:y", center_y, ANIM_DURATION)
	_tween.tween_property(_panel, "modulate:a", 1.0, ANIM_DURATION)
	if _dim:
		_tween.tween_method(_set_dim_alpha, 0.0, 0.5, ANIM_DURATION)


func _modulate_out() -> void:
	var center_y := get_viewport().get_visible_rect().size.y * 0.5 - 210
	_tween = create_tween()
	_tween.set_trans(Tween.TRANS_SINE)
	_tween.set_ease(Tween.EASE_IN)
	_tween.set_parallel(true)
	_tween.tween_property(_container, "modulate:a", 0.0, ANIM_DURATION)
	_tween.tween_property(_panel, "position:y", center_y - 20, ANIM_DURATION)
	if _dim:
		_tween.tween_method(_set_dim_alpha, 0.5, 0.0, ANIM_DURATION)
	_tween.tween_callback(_on_close_finished)


func _set_dim_alpha(a: float) -> void:
	if _dim:
		var c := _dim.color
		c.a = a
		_dim.color = c


func _on_close_finished() -> void:
	visible = false
	_process_input(false)
	Input.set_mouse_mode(Input.MOUSE_MODE_CAPTURED)
	closed.emit()


func _on_input_submitted(_txt: String) -> void:
	_do_send()


func _do_send() -> void:
	var msg := _input_field.text.strip_edges()
	if msg.is_empty() or _sending:
		return
	_input_field.text = ""
	_sending = true
	_update_send_state()

	if GameManager:
		GameManager.append_message(_npc_id, "user", msg)
	_append_to_history("You", msg, true)

	var conv: Array = GameManager.get_conversation(_npc_id) if GameManager else []
	var collected: Array = []
	for k in GameManager.collected_clue_ids.keys():
		if GameManager.collected_clue_ids[k]:
			collected.append(k)
	var ch: Dictionary = GameManager.get_current_chapter() if GameManager else {}
	var cur_chapter: String = str(ch.get("id", "chapter_1")) if ch else "chapter_1"

	var base := GameManager.game_server_url if GameManager else "http://127.0.0.1:8000"
	var url := base + "/api/chat"
	var body: Dictionary = {
		"npc_id": _npc_id,
		"message": msg,
		"conversation_history": conv,
		"current_chapter": cur_chapter,
		"collected_clues": collected
	}
	if GameManager and not GameManager.game_output_path.is_empty():
		body["output"] = GameManager.game_output_path
	var json_str := JSON.stringify(body)
	var err := _http.request(url, ["Content-Type: application/json"], HTTPClient.METHOD_POST, json_str)
	if err != OK:
		_sending = false
		_update_send_state()
		_error_label.text = "Request failed"
		_error_label.visible = true
		return


func _on_request_completed(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_sending = false
	_update_send_state()
	if result != HTTPRequest.RESULT_SUCCESS:
		_error_label.text = "Network error"
		_error_label.visible = true
		return
	var txt := body.get_string_from_utf8()
	var parsed = JSON.parse_string(txt)
	if parsed is Dictionary:
		var status_code := int(code)
		var reply := ""
		var error_msg := ""

		if status_code >= 400:
			# HTTP error from server; prefer a human-readable detail field.
			error_msg = str(parsed.get("detail", parsed.get("error", "Chat server error; NPC can't reply right now.")))
		else:
			reply = str(parsed.get("reply", "")).strip_edges()
			if reply.is_empty():
				# Successful HTTP status but no reply field – treat as an application-level error.
				error_msg = str(parsed.get("detail", parsed.get("error", "Chat server error; NPC can't reply right now.")))

		if not error_msg.is_empty():
			_error_label.text = error_msg
			_error_label.visible = true
			print("Chat error response (%d): %s" % [status_code, txt])
			return

		var awarded: Array = parsed.get("awarded_clues", [])
		if GameManager:
			GameManager.append_message(_npc_id, "assistant", reply)
			for cid in awarded:
				GameManager.add_clue(str(cid))
			if awarded.size() > 0:
				GameManager.record_npc_clue_award(_npc_id)
			GameManager.try_advance_and_check_ending()
		_append_to_history(_npc_name, reply, false)
		if awarded.size() > 0:
			awarded_clues.emit(awarded)
	else:
		_error_label.text = "Invalid response"
		_error_label.visible = true


func _append_to_history(speaker: String, text: String, is_user: bool) -> void:
	var safe := text.replace("[", " ").replace("]", " ")
	var line := speaker + ": " + safe + "\n"
	_history.text += line
	_scroll_to_bottom()


func _scroll_to_bottom() -> void:
	call_deferred("_do_scroll_to_bottom")


func _do_scroll_to_bottom() -> void:
	if _scroll:
		var vbar = _scroll.get_v_scroll_bar()
		if vbar:
			_scroll.scroll_vertical = int(vbar.max_value)


func _on_input_text_changed(_new_text: String) -> void:
	_update_send_state()

func _update_send_state() -> void:
	_send_btn.disabled = _sending or _input_field.text.strip_edges().is_empty()
	_update_loading()


func _update_loading() -> void:
	if _loading_label:
		_loading_label.visible = _sending
