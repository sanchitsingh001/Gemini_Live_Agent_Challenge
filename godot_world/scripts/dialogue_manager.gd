extends Node
## DialogueManager autoload: loads dialogue.json, shows bottom text box.
## Supports full narrative format (npcs, chapters, dialogue_packs) with tags, meters, option gating.
## Compatible with both legacy dialogue_builder format and new dynamic narrative format from chapters_to_dialogue.py.
## Falls back to legacy events format for backward compatibility.

const DIALOGUE_PATH := "res://generated/dialogue.json"
const NPC_INTERACT_RANGE_M := 1.75
const STATE_PATH := "user://dialogue_state.json"

var dialogue_data: Dictionary = {}
var events: Array = []
var event_by_id: Dictionary = {}
var npc_first_event: Dictionary = {}

var use_full_narrative: bool = false
var npcs: Dictionary = {}
var clues: Dictionary = {}
var chapters: Array = []
var chapter_by_id: Dictionary = {}
var chapter_index_map: Dictionary = {}
var dialogue_index: Dictionary = {}
var npc_pack_chapters: Dictionary = {}
var clue_min_chapter: Dictionary = {}
var display_name_to_npc_id: Dictionary = {}
var ending_block: Dictionary = {}
var state_tags: Dictionary = {}
var state_flags: Dictionary = {}
var npc_meters: Dictionary = {}
var collected_clue_ids: Dictionary = {}  # clue_id -> true
var current_chapter_id: String = "chapter_1"
var _full_npc_id: String = ""
var _full_node_id: String = ""
var _full_node_map: Dictionary = {}
var _full_applied_node_ids: Dictionary = {}
var _full_current_options: Array = []

var dialogue_active: bool = false
var current_event_id: String = ""
var _dialogue_start_npc_name: String = ""

# UI nodes (created in _ready)
var _layer: CanvasLayer = null
var _panel: PanelContainer = null
var _vbox: VBoxContainer = null
var _speaker_label: Label = null
var _text_label: Label = null
var _choices_container: HBoxContainer = null
var _next_btn: Button = null
var _hint_label: Label = null

# Arrow-key choice selection: when current event has choices
var _current_choice_goto_ids: Array = []  # [goto_id, ...]
var _selected_choice_index: int = 0

# Ending sequence: black screen + narrator lines, then quit
var _ending_mode: bool = false
var _ending_layer: CanvasLayer = null
var _ending_label: Label = null
var _ending_hint: Label = null
var _ending_ev: Dictionary = {}  # current ending event for _ending_advance

# Inventory / ESC menu
var _inventory_layer: CanvasLayer = null
var _inventory_panel: PanelContainer = null
var _inventory_visible: bool = false
var _inventory_tab_clues: Control = null
var _inventory_tab_inventory: Control = null
var _inventory_clues_scroll: ScrollContainer = null
var _inventory_clues_list: VBoxContainer = null
var _inventory_tags_container: VBoxContainer = null
var _inventory_chapter_label: Label = null
var _inventory_beat_label: Label = null
var _inventory_show_all_clues: bool = false
var _inventory_show_all_btn: Button = null
var _last_npc_for_meters: String = ""

# Chapter popup
var _chapter_popup_layer: CanvasLayer = null
var _chapter_popup_title: Label = null
var _chapter_popup_beat: Label = null
var _chapter_popup_timer: float = 0.0
var _chapter_popup_active: bool = false

# Clue toast
var _clue_toast_layer: CanvasLayer = null
var _clue_toast_label: Label = null
var _clue_toast_timer: float = 0.0
var _clue_toast_active: bool = false

# State persistence
var _save_pending := false
var _save_timer := 0.0
var _loaded_from_save: bool = false


func _ready() -> void:
	_load_dialogue()
	_build_ui()
	_hide_ui()
	if use_full_narrative:
		_build_inventory_ui()
		_build_chapter_popup()
		_build_clue_toast()
		if not _loaded_from_save:
			call_deferred("_show_chapter_popup", current_chapter_id)


func _process(delta: float) -> void:
	if _save_pending:
		_save_timer += delta
		if _save_timer >= 0.5:
			_save_pending = false
			_save_timer = 0.0
			_do_save_state()
	if _chapter_popup_active:
		_chapter_popup_timer -= delta
		if _chapter_popup_timer <= 0:
			_hide_chapter_popup()
	if _clue_toast_active:
		_clue_toast_timer -= delta
		if _clue_toast_timer <= 0:
			_hide_clue_toast()


func _input(event: InputEvent) -> void:
	if _ending_mode:
		if event.is_action_pressed("ui_accept") or event.is_action_pressed("ui_select"):
			_ending_advance()
			get_viewport().set_input_as_handled()
		return
	if _chapter_popup_active:
		if event is InputEventKey or (event is InputEventMouseButton and event.pressed):
			_hide_chapter_popup()
			get_viewport().set_input_as_handled()
		return
	if not dialogue_active or _current_choice_goto_ids.is_empty():
		return
	var n := _current_choice_goto_ids.size()
	if n == 0:
		return
	if event.is_action_pressed("ui_left") or event.is_action_pressed("ui_up"):
		_selected_choice_index = (_selected_choice_index - 1 + n) % n
		_update_choice_highlight()
		get_viewport().set_input_as_handled()
	elif event.is_action_pressed("ui_right") or event.is_action_pressed("ui_down"):
		_selected_choice_index = (_selected_choice_index + 1) % n
		_update_choice_highlight()
		get_viewport().set_input_as_handled()


func _load_dialogue() -> void:
	var path := DIALOGUE_PATH
	if not FileAccess.file_exists(path):
		path = _resolve_path(path)
	var f = FileAccess.open(path, FileAccess.READ)
	if f == null:
		push_error("DialogueManager: Could not open dialogue.json at " + path)
		return
	var json_text := f.get_as_text()
	f.close()
	var json := JSON.new()
	var err := json.parse(json_text)
	if err != OK:
		push_error("DialogueManager: Failed to parse dialogue.json: " + json.get_error_message())
		return
	dialogue_data = json.data
	events = dialogue_data.get("events", [])
	event_by_id.clear()
	npc_first_event.clear()
	_ending_event_cache.clear()
	use_full_narrative = false
	var world_data = dialogue_data.get("world", {})
	if world_data is Dictionary and dialogue_data.has("npcs") and world_data.has("chapters"):
		var ch_arr = world_data.get("chapters", [])
		if ch_arr is Array and ch_arr.size() > 0:
			use_full_narrative = true
			_load_full_narrative()
			return
	for i in range(events.size()):
		var ev = events[i]
		var eid := str(ev.get("id", ""))
		if eid.is_empty():
			continue
		event_by_id[eid] = ev
		var speaker := str(ev.get("speaker", ""))
		if not speaker.is_empty() and not npc_first_event.has(speaker):
			npc_first_event[speaker] = eid
	print("DialogueManager: Loaded legacy format - ", events.size(), " events, ", npc_first_event.size(), " speakers")


func _resolve_path(res_path: String) -> String:
	if FileAccess.file_exists(res_path):
		return res_path
	var rel = res_path.replace("res://", "")
	var base_dir := OS.get_executable_path().get_base_dir()
	var ext_path := base_dir.path_join(rel)
	if FileAccess.file_exists(ext_path):
		return ext_path
	return res_path


func _chapter_num(ch_id: String) -> int:
	var parts = str(ch_id).split("_")
	if parts.size() >= 2:
		return int(parts[parts.size() - 1]) if parts[parts.size() - 1].is_valid_int() else 999
	return 999


func _as_list(v) -> Array:
	if v == null:
		return []
	if v is Array:
		return v
	return []


func _load_full_narrative() -> void:
	npcs.clear()
	clues.clear()
	chapters.clear()
	chapter_by_id.clear()
	chapter_index_map.clear()
	dialogue_index.clear()
	npc_pack_chapters.clear()
	clue_min_chapter.clear()
	display_name_to_npc_id.clear()
	state_tags.clear()
	state_flags.clear()
	npc_meters.clear()
	collected_clue_ids.clear()
	for n in dialogue_data.get("npcs", []):
		if n is Dictionary and n.has("id"):
			var nid = str(n.get("id", ""))
			npcs[nid] = n
			display_name_to_npc_id[str(n.get("name", ""))] = nid
			var m = n.get("meters", {})
			if m is Dictionary:
				npc_meters[nid] = {
					"trust": int(m.get("trust", 0)),
					"pressure": int(m.get("pressure", 0)),
					"debt": int(m.get("debt", 0))
				}
			else:
				npc_meters[nid] = {"trust": 0, "pressure": 0, "debt": 0}
	for c in dialogue_data.get("clues", []):
		if c is Dictionary and c.has("id"):
			clues[str(c.get("id", ""))] = c
	var world_data = dialogue_data.get("world", {})
	var raw_ch = world_data.get("chapters", []) if world_data is Dictionary else []
	chapters = []
	for c in raw_ch:
		if c is Dictionary and c.has("id"):
			chapters.append(c)
	chapters.sort_custom(func(a, b): return _chapter_num(a.get("id", "")) < _chapter_num(b.get("id", "")))
	for i in range(chapters.size()):
		chapter_by_id[chapters[i].get("id", "")] = chapters[i]
		chapter_index_map[chapters[i].get("id", "")] = i
	current_chapter_id = chapters[0].get("id", "chapter_1") if chapters.size() > 0 else "chapter_1"
	ending_block = world_data.get("ending", {}) if world_data is Dictionary else {}
	if dialogue_data.has("ending") and dialogue_data.get("ending") is Dictionary:
		ending_block = dialogue_data.get("ending", {})
	for t in _as_list(dialogue_data.get("entrypoints", {}).get("starting_tags", [])):
		if t is String:
			state_tags[t] = true
	for nid in npcs.keys():
		var packs = npcs[nid].get("dialogue_packs", [])
		if packs is Array:
			dialogue_index[nid] = {}
			var ch_list: Array = []
			for p in packs:
				if p is Dictionary:
					var ch_id = str(p.get("chapter_id", ""))
					var nodes = p.get("dialogue", [])
					var node_map: Dictionary = {}
					for node in nodes:
						if node is Dictionary and node.has("id"):
							node_map[str(node.get("id", ""))] = node
					dialogue_index[nid][ch_id] = {"_nodes": node_map, "_raw_nodes": nodes}
					ch_list.append(ch_id)
			ch_list.sort_custom(func(a, b): return _chapter_num(a) < _chapter_num(b))
			npc_pack_chapters[nid] = ch_list
	for ch in chapters:
		var cid = ch.get("id", "")
		# Support both legacy clue_focus_ids and new available_clue_ids from chapters_to_dialogue.py
		var clue_ids = _as_list(ch.get("clue_focus_ids", []))
		clue_ids.append_array(_as_list(ch.get("available_clue_ids", [])))
		for clue_id in clue_ids:
			if clue_id is String and clue_id in clues and not clue_min_chapter.has(clue_id):
				clue_min_chapter[clue_id] = cid
	var default_cid = chapters[0].get("id", "chapter_1") if chapters.size() > 0 else "chapter_1"
	for clue_id in clues.keys():
		if not clue_min_chapter.has(clue_id):
			clue_min_chapter[clue_id] = default_cid
	_clamp_meters()
	_load_state()
	print("DialogueManager: Loaded full narrative - ", npcs.size(), " NPCs, ", chapters.size(), " chapters")


func _clamp_meters() -> void:
	for nid in npc_meters:
		var m = npc_meters[nid]
		m.trust = clampi(int(m.trust), 0, 3)
		m.pressure = clampi(int(m.pressure), 0, 3)
		m.debt = clampi(int(m.debt), -2, 2)


func _load_state() -> void:
	var f = FileAccess.open(STATE_PATH, FileAccess.READ)
	if f == null:
		return
	var json_text := f.get_as_text()
	f.close()
	var json := JSON.new()
	if json.parse(json_text) != OK:
		return
	var data = json.data
	if data is not Dictionary:
		return
	var st = data.get("state_tags", {})
	if st is Dictionary:
		for k in st.keys():
			if k is String and st[k] == true:
				state_tags[k] = true
	var meters_raw = data.get("npc_meters", {})
	if meters_raw is Dictionary:
		for nid in meters_raw.keys():
			if nid is not String or not npc_meters.has(nid):
				continue
			var m_raw = meters_raw[nid]
			if m_raw is not Dictionary:
				continue
			var m = npc_meters[nid]
			m.trust = clampi(int(m_raw.get("trust", m.trust)), 0, 3)
			m.pressure = clampi(int(m_raw.get("pressure", m.pressure)), 0, 3)
			m.debt = clampi(int(m_raw.get("debt", m.debt)), -2, 2)
	var ch_id = data.get("current_chapter_id", "")
	if ch_id is String and not ch_id.is_empty() and chapter_by_id.has(ch_id):
		current_chapter_id = ch_id
	_loaded_from_save = true
	var collected = data.get("collected_clue_ids", {})
	if collected is Dictionary:
		for k in collected.keys():
			if k is String and collected[k] == true:
				collected_clue_ids[k] = true


func _do_save_state() -> void:
	if not use_full_narrative:
		return
	var st_dict := {}
	for k in state_tags.keys():
		st_dict[k] = true
	var m_dict := {}
	for nid in npc_meters.keys():
		var m = npc_meters[nid]
		m_dict[nid] = {"trust": m.trust, "pressure": m.pressure, "debt": m.debt}
	var c_dict := {}
	for k in collected_clue_ids.keys():
		if k is String and collected_clue_ids[k] == true:
			c_dict[k] = true
	var data := {
		"state_tags": st_dict,
		"npc_meters": m_dict,
		"current_chapter_id": current_chapter_id,
		"collected_clue_ids": c_dict
	}
	var json_str := JSON.stringify(data)
	var f = FileAccess.open(STATE_PATH, FileAccess.WRITE)
	if f == null:
		push_warning("DialogueManager: Could not save state to " + STATE_PATH)
		return
	f.store_string(json_str)
	f.close()


func _schedule_save_state() -> void:
	_save_pending = true
	_save_timer = 0.0


func _requirement_ok(npc_id: String, req_any, req_all, min_trust, min_pressure) -> Array:
	var meters = npc_meters.get(npc_id, {"trust": 0, "pressure": 0, "debt": 0})
	if min_trust != null:
		var mt = int(min_trust) if (min_trust is int or (min_trust is float)) else 0
		if meters.trust < mt:
			return [false, "needs trust>=%d" % mt]
	if min_pressure != null:
		var mp = int(min_pressure) if (min_pressure is int or (min_pressure is float)) else 0
		if meters.pressure < mp:
			return [false, "needs pressure>=%d" % mp]
	var tags_any = _as_list(req_any)
	var tags_all = _as_list(req_all)
	if tags_any.size() > 0:
		var has_any = false
		for t in tags_any:
			if t is String and state_tags.has(t):
				has_any = true
				break
		if not has_any:
			return [false, "needs any of %s" % str(tags_any)]
	for t in tags_all:
		if t is String and not state_tags.has(t):
			return [false, "needs all; missing %s" % t]
	return [true, ""]


func _apply_effects(npc_id: String, obj: Dictionary) -> Array:
	var added: Array = []
	if not npc_meters.has(npc_id):
		return added
	var m = npc_meters[npc_id]
	var td = obj.get("trust_delta")
	if td != null and (td is int or (td is float and td == int(td))):
		m.trust = clampi(m.trust + int(td), 0, 3)
	var pd = obj.get("pressure_delta")
	if pd != null and (pd is int or (pd is float and pd == int(pd))):
		m.pressure = clampi(m.pressure + int(pd), 0, 3)
	var dd = obj.get("debt_delta")
	if dd != null and (dd is int or (dd is float and dd == int(dd))):
		m.debt = clampi(m.debt + int(dd), -2, 2)
	for t in _as_list(obj.get("adds_tags", [])):
		if t is String and not state_tags.has(t):
			state_tags[t] = true
			added.append(t)
	for t in _as_list(obj.get("add_tags", [])):
		if t is String and not state_tags.has(t):
			state_tags[t] = true
			added.append(t)
	for t in _as_list(obj.get("removes_tags", [])):
		if t is String and state_tags.has(t):
			state_tags.erase(t)
	_schedule_save_state()
	if _inventory_visible:
		_refresh_inventory_ui()
	return added


func _chapter_completed(ch: Dictionary) -> bool:
	var exit_tags = _as_list(ch.get("exit_tags", []))
	for t in exit_tags:
		if t is String and not state_tags.has(t):
			return false
	return true


func _chapter_unlocked(ch: Dictionary, prev_ch) -> bool:
	if prev_ch != null and not _chapter_completed(prev_ch):
		return false
	var entry_any = ch.get("entry_tags_any", null)
	var entry_list = _as_list(entry_any)
	if entry_list.size() == 0:
		return true
	for t in entry_list:
		if t is String and state_tags.has(t):
			return true
	return false


func _ending_unlocked() -> bool:
	if ending_block.is_empty():
		return false
	var req = _as_list(ending_block.get("requires_tags_all", []))
	for t in req:
		if t is String and not state_tags.has(t):
			return false
	return true


func _auto_advance_chapter() -> void:
	if chapters.size() == 0:
		return
	var prev_chapter_id := current_chapter_id
	var cur_idx = chapter_index_map.get(current_chapter_id, 0)
	var cur = chapters[cur_idx] if cur_idx < chapters.size() else null
	if cur == null:
		return
	while _chapter_completed(cur):
		if cur_idx + 1 >= chapters.size():
			break
		var nxt = chapters[cur_idx + 1]
		var prev = cur
		if not _chapter_unlocked(nxt, prev):
			break
		cur_idx += 1
		current_chapter_id = nxt.get("id", current_chapter_id)
		cur = nxt
		_schedule_save_state()
	if current_chapter_id != prev_chapter_id:
		_show_chapter_popup(current_chapter_id)
		_refresh_inventory_ui()


func _clue_available_now(clue_id: String) -> Array:
	## Returns [ok: bool, reason: String]. Clue available if current chapter >= clue_min_chapter.
	var default_cid: String = chapters[0].get("id", "chapter_1") if chapters.size() > 0 else "chapter_1"
	var min_cid: String = str(clue_min_chapter.get(clue_id, default_cid))
	var cur_idx: int = int(chapter_index_map.get(current_chapter_id, 0))
	var min_idx: int = int(chapter_index_map.get(min_cid, 0))
	if cur_idx >= min_idx:
		return [true, ""]
	return [false, "locked until %s" % min_cid]


func collect_clue(clue_id: String) -> void:
	## Called when player interacts with a clue entity. Adds reveals_tags to state, advances chapter if needed.
	if not use_full_narrative:
		return
	var c = clues.get(clue_id)
	if c == null:
		push_warning("DialogueManager: Unknown clue id: " + clue_id)
		return
	var arr := _clue_available_now(clue_id)
	if not arr[0]:
		if _hint_label:
			_hint_label.text = str(arr[1])
			_hint_label.visible = true
		return
	collected_clue_ids[clue_id] = true
	for t in _as_list(c.get("reveals_tags", [])):
		if t is String:
			state_tags[t] = true
	_auto_advance_chapter()
	_schedule_save_state()
	if _ending_unlocked():
		_trigger_full_ending()
		return
	_show_clue_toast(str(c.get("label", clue_id)))
	_refresh_inventory_ui()
	if _hint_label:
		_hint_label.text = "Collected: %s" % str(c.get("label", clue_id))
		_hint_label.visible = true


func _get_pack_for(npc_id: String, chapter_id: String) -> Dictionary:
	if not dialogue_index.has(npc_id):
		return {}
	var by_ch = dialogue_index[npc_id]
	if by_ch.has(chapter_id):
		return by_ch[chapter_id]
	var cur_n = _chapter_num(chapter_id)
	var best = {}
	var best_n = -1
	for ch_id in by_ch.keys():
		var pn = _chapter_num(ch_id)
		if pn <= cur_n and pn > best_n:
			best = by_ch[ch_id]
			best_n = pn
	return best


func get_collected_clue_ids() -> Array:
	var out: Array = []
	for k in collected_clue_ids.keys():
		if collected_clue_ids[k] == true:
			out.append(k)
	return out


func get_clues_with_status() -> Array:
	## Returns Array of {clue: dict, collected: bool, available_now: bool}
	var out: Array = []
	var cur_idx: int = int(chapter_index_map.get(current_chapter_id, 0))
	var default_cid: String = chapters[0].get("id", "chapter_1") if chapters.size() > 0 else "chapter_1"
	for clue_id in clues.keys():
		var c = clues[clue_id]
		var collected: bool = collected_clue_ids.get(clue_id, false) == true
		var min_cid: String = str(clue_min_chapter.get(clue_id, default_cid))
		var min_idx: int = int(chapter_index_map.get(min_cid, 0))
		var available_now: bool = cur_idx >= min_idx
		out.append({"clue": c, "clue_id": clue_id, "collected": collected, "available_now": available_now})
	return out


func get_state_tags_sorted() -> Array:
	var out: Array = []
	for k in state_tags.keys():
		if state_tags[k] == true and k is String:
			out.append(k)
	out.sort()
	return out


func get_current_chapter_id() -> String:
	return current_chapter_id


func get_current_chapter_title() -> String:
	var ch = chapter_by_id.get(current_chapter_id, {})
	return str(ch.get("title", current_chapter_id))


func get_current_chapter_beat_summary() -> String:
	var ch = chapter_by_id.get(current_chapter_id, {})
	return str(ch.get("beat_summary", ""))


func get_npc_meters_for_display() -> Dictionary:
	## Returns {trust, pressure, debt} for last NPC talked to.
	var nid: String = _last_npc_for_meters
	if nid.is_empty() and npc_meters.size() > 0:
		nid = npc_meters.keys()[0]
	if not npc_meters.has(nid):
		return {}
	return npc_meters[nid].duplicate()


# Cache for ending event detection to avoid repeated traversal
var _ending_event_cache: Dictionary = {}  # event_id -> bool


func _is_ending_event(event_id: String) -> bool:
	"""
	Check if an event should start the ending sequence (black screen).
	True if event_id is "end" OR if the event has tags.ending = true.
	"""
	if event_id == "end":
		return true
	
	var ev: Dictionary = event_by_id.get(event_id, {})
	var tags: Dictionary = ev.get("tags", {}) if ev.get("tags", {}) is Dictionary else {}
	return tags.get("ending", false)


func _build_ui() -> void:
	_layer = CanvasLayer.new()
	_layer.name = "DialogueLayer"
	add_child(_layer)

	_panel = PanelContainer.new()
	_panel.name = "DialoguePanel"
	_panel.set_anchors_preset(Control.PRESET_FULL_RECT)
	_panel.anchor_top = 0.75
	_panel.anchor_bottom = 1.0
	_panel.anchor_left = 0.0
	_panel.anchor_right = 1.0
	_panel.offset_left = 20
	_panel.offset_top = 20
	_panel.offset_right = -20
	_panel.offset_bottom = -20
	_panel.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_dialogue_block())
	_layer.add_child(_panel)

	_vbox = VBoxContainer.new()
	_vbox.name = "VBox"
	_vbox.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT, Control.PRESET_MODE_MINSIZE, 8)
	_vbox.add_theme_constant_override("separation", 12)
	_panel.add_child(_vbox)

	_speaker_label = Label.new()
	_speaker_label.name = "SpeakerLabel"
	_speaker_label.text = ""
	_speaker_label.add_theme_font_size_override("font_size", 22)
	_speaker_label.add_theme_color_override("font_color", Color(0.9, 0.85, 0.6))
	_vbox.add_child(_speaker_label)

	_text_label = Label.new()
	_text_label.name = "TextLabel"
	_text_label.text = ""
	_text_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_text_label.custom_minimum_size.y = 60
	_text_label.add_theme_font_size_override("font_size", 18)
	_vbox.add_child(_text_label)

	_choices_container = HBoxContainer.new()
	_choices_container.name = "ChoicesContainer"
	_choices_container.add_theme_constant_override("separation", 12)
	_vbox.add_child(_choices_container)

	_next_btn = Button.new()
	_next_btn.name = "NextButton"
	_next_btn.text = "Next (E / Space)"
	_next_btn.pressed.connect(_on_next_pressed)
	_vbox.add_child(_next_btn)

	_hint_label = Label.new()
	_hint_label.name = "HintLabel"
	_hint_label.text = "Arrow keys: select  •  E / Space: confirm"
	_hint_label.add_theme_font_size_override("font_size", 14)
	_hint_label.add_theme_color_override("font_color", Color(0.7, 0.7, 0.8))
	_vbox.add_child(_hint_label)
	_hint_label.visible = false


func _build_inventory_ui() -> void:
	if not use_full_narrative:
		return
	_inventory_layer = CanvasLayer.new()
	_inventory_layer.name = "InventoryLayer"
	_inventory_layer.layer = 500
	add_child(_inventory_layer)

	_inventory_panel = PanelContainer.new()
	_inventory_panel.name = "InventoryPanel"
	_inventory_panel.set_anchors_preset(Control.PRESET_FULL_RECT)
	_inventory_panel.anchor_left = 0.4
	_inventory_panel.anchor_right = 1.0
	_inventory_panel.anchor_top = 0.0
	_inventory_panel.anchor_bottom = 1.0
	_inventory_panel.offset_left = 0
	_inventory_panel.offset_right = 0
	_inventory_panel.offset_top = 0
	_inventory_panel.offset_bottom = 0
	_inventory_panel.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_inventory_side())
	_inventory_layer.add_child(_inventory_panel)

	var inv_vbox := VBoxContainer.new()
	inv_vbox.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT, Control.PRESET_MODE_MINSIZE, 12)
	inv_vbox.add_theme_constant_override("separation", 12)
	_inventory_panel.add_child(inv_vbox)

	# Chapter beat header
	var chapter_box := VBoxContainer.new()
	chapter_box.add_theme_constant_override("separation", 4)
	_inventory_chapter_label = Label.new()
	_inventory_chapter_label.name = "ChapterLabel"
	_inventory_chapter_label.add_theme_font_size_override("font_size", 20)
	_inventory_chapter_label.add_theme_color_override("font_color", Color(0.9, 0.85, 0.5))
	_inventory_chapter_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	chapter_box.add_child(_inventory_chapter_label)
	_inventory_beat_label = Label.new()
	_inventory_beat_label.name = "BeatLabel"
	_inventory_beat_label.add_theme_font_size_override("font_size", 14)
	_inventory_beat_label.add_theme_color_override("font_color", Color(0.75, 0.75, 0.85))
	_inventory_beat_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	chapter_box.add_child(_inventory_beat_label)
	inv_vbox.add_child(chapter_box)

	# Tab buttons
	var tab_bar := HBoxContainer.new()
	tab_bar.add_theme_constant_override("separation", 8)
	var btn_clues := Button.new()
	btn_clues.text = "Clues"
	btn_clues.pressed.connect(_on_inventory_tab_clues)
	tab_bar.add_child(btn_clues)
	var btn_inv := Button.new()
	btn_inv.text = "Inventory"
	btn_inv.pressed.connect(_on_inventory_tab_inventory)
	tab_bar.add_child(btn_inv)
	inv_vbox.add_child(tab_bar)

	# Tab content container
	var tab_content := VBoxContainer.new()
	tab_content.size_flags_vertical = Control.SIZE_EXPAND_FILL

	# Clues tab content
	_inventory_tab_clues = VBoxContainer.new()
	_inventory_clues_scroll = ScrollContainer.new()
	_inventory_clues_scroll.custom_minimum_size.y = 200
	_inventory_clues_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_inventory_clues_list = VBoxContainer.new()
	_inventory_clues_list.add_theme_constant_override("separation", 8)
	_inventory_clues_scroll.add_child(_inventory_clues_list)
	_inventory_tab_clues.add_child(_inventory_clues_scroll)
	_inventory_show_all_btn = Button.new()
	_inventory_show_all_btn.text = "Show all clues"
	_inventory_show_all_btn.toggle_mode = true
	_inventory_show_all_btn.toggled.connect(func(on: bool): _inventory_show_all_clues = on; _refresh_inventory_ui())
	_inventory_tab_clues.add_child(_inventory_show_all_btn)
	tab_content.add_child(_inventory_tab_clues)

	# Inventory tab content
	_inventory_tab_inventory = VBoxContainer.new()
	var tags_label := Label.new()
	tags_label.text = "Tags you've learned:"
	tags_label.add_theme_font_size_override("font_size", 16)
	_inventory_tags_container = VBoxContainer.new()
	_inventory_tags_container.add_theme_constant_override("separation", 4)
	_inventory_tab_inventory.add_child(tags_label)
	_inventory_tab_inventory.add_child(_inventory_tags_container)
	var meters_label := Label.new()
	meters_label.text = "NPC meters (last talked):"
	meters_label.add_theme_font_size_override("font_size", 14)
	_inventory_tab_inventory.add_child(meters_label)
	var meters_val := Label.new()
	meters_val.name = "MetersValue"
	meters_val.text = "Trust: 0  Pressure: 0  Debt: 0"
	_inventory_tab_inventory.add_child(meters_val)
	var show_ending_btn := Button.new()
	show_ending_btn.name = "ShowEndingBtn"
	show_ending_btn.text = "Show Ending"
	show_ending_btn.pressed.connect(_on_show_ending_pressed)
	_inventory_tab_inventory.add_child(show_ending_btn)
	var reset_btn := Button.new()
	reset_btn.text = "Reset Progress"
	reset_btn.pressed.connect(_on_reset_progress_pressed)
	_inventory_tab_inventory.add_child(reset_btn)
	tab_content.add_child(_inventory_tab_inventory)

	# By default show Clues tab, hide Inventory tab
	_inventory_tab_inventory.visible = false
	inv_vbox.add_child(tab_content)

	_refresh_inventory_ui()
	_inventory_layer.visible = false


func _on_inventory_tab_clues() -> void:
	_inventory_tab_clues.visible = true
	_inventory_tab_inventory.visible = false


func _on_inventory_tab_inventory() -> void:
	_inventory_tab_clues.visible = false
	_inventory_tab_inventory.visible = true
	_refresh_inventory_ui()


func _on_show_ending_pressed() -> void:
	if _ending_unlocked():
		_trigger_full_ending()
	else:
		if _hint_label:
			_hint_label.text = "Ending not unlocked yet."
			_hint_label.visible = true


func _on_reset_progress_pressed() -> void:
	state_tags.clear()
	collected_clue_ids.clear()
	_clamp_meters()
	for nid in npc_meters:
		var m = npc_meters[nid]
		m.trust = 0
		m.pressure = 0
		m.debt = 0
	current_chapter_id = chapters[0].get("id", "chapter_1") if chapters.size() > 0 else "chapter_1"
	_loaded_from_save = false
	_do_save_state()
	_refresh_inventory_ui()
	if _inventory_layer:
		_inventory_layer.visible = false
		_inventory_visible = false
	get_tree().reload_current_scene()


func _refresh_inventory_ui() -> void:
	if _inventory_show_all_btn:
		_inventory_show_all_btn.button_pressed = _inventory_show_all_clues
	if _inventory_chapter_label:
		var ch_num: int = _chapter_num(current_chapter_id)
		_inventory_chapter_label.text = "Chapter %d: %s" % [ch_num, get_current_chapter_title()]
	if _inventory_beat_label:
		_inventory_beat_label.text = "What to do: " + get_current_chapter_beat_summary()
	if _inventory_clues_list:
		for c in _inventory_clues_list.get_children():
			c.queue_free()
		var items = get_clues_with_status()
		var cur_ch = chapter_by_id.get(current_chapter_id, {})
		# Support both legacy clue_focus_ids and new available_clue_ids from chapters_to_dialogue.py
		var focus_ids: Array = _as_list(cur_ch.get("clue_focus_ids", []))
		focus_ids.append_array(_as_list(cur_ch.get("available_clue_ids", [])))
		for item in items:
			var clue_id: String = item.clue_id
			var c: Dictionary = item.clue
			var collected: bool = item.collected
			var available: bool = item.available_now
			if not _inventory_show_all_clues and focus_ids.size() > 0:
				if clue_id not in focus_ids:
					continue
			var card := PanelContainer.new()
			card.add_theme_stylebox_override("panel", UiThemeHelper.style_pill())
			var card_v := VBoxContainer.new()
			card_v.add_theme_constant_override("separation", 2)
			var status_str: String = "Collected" if collected else ("Available" if available else "Locked")
			var title := Label.new()
			title.text = str(c.get("label", clue_id)) + " [" + status_str + "]"
			title.add_theme_font_size_override("font_size", 14)
			card_v.add_child(title)
			var desc := Label.new()
			desc.text = str(c.get("description", ""))
			desc.add_theme_font_size_override("font_size", 12)
			desc.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
			desc.add_theme_color_override("font_color", Color(0.8, 0.8, 0.85))
			card_v.add_child(desc)
			card.add_child(card_v)
			_inventory_clues_list.add_child(card)
	if _inventory_tags_container:
		for c in _inventory_tags_container.get_children():
			c.queue_free()
		for tag in get_state_tags_sorted():
			var l := Label.new()
			l.text = str(tag)
			l.add_theme_font_size_override("font_size", 12)
			_inventory_tags_container.add_child(l)
	var meters_val = _inventory_tab_inventory.get_node_or_null("MetersValue")
	if meters_val is Label:
		var m = get_npc_meters_for_display()
		meters_val.text = "Trust: %d  Pressure: %d  Debt: %d" % [m.get("trust", 0), m.get("pressure", 0), m.get("debt", 0)]
	var show_btn = _inventory_tab_inventory.get_node_or_null("ShowEndingBtn")
	if show_btn is Button:
		show_btn.disabled = not _ending_unlocked()


func toggle_inventory_panel() -> void:
	if not use_full_narrative or _inventory_layer == null:
		return
	_inventory_visible = not _inventory_visible
	_inventory_layer.visible = _inventory_visible
	if _inventory_visible:
		_refresh_inventory_ui()


func is_inventory_visible() -> bool:
	return _inventory_visible


func _build_chapter_popup() -> void:
	if not use_full_narrative:
		return
	_chapter_popup_layer = CanvasLayer.new()
	_chapter_popup_layer.name = "ChapterPopupLayer"
	_chapter_popup_layer.layer = 900
	add_child(_chapter_popup_layer)
	var overlay := ColorRect.new()
	overlay.name = "ChapterOverlay"
	overlay.set_anchors_preset(Control.PRESET_FULL_RECT)
	overlay.color = Color(0, 0, 0, 0.75)
	overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	_chapter_popup_layer.add_child(overlay)
	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	_chapter_popup_layer.add_child(center)
	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 16)
	_chapter_popup_title = Label.new()
	_chapter_popup_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_chapter_popup_title.add_theme_font_size_override("font_size", 32)
	_chapter_popup_title.add_theme_color_override("font_color", Color.WHITE)
	vbox.add_child(_chapter_popup_title)
	_chapter_popup_beat = Label.new()
	_chapter_popup_beat.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_chapter_popup_beat.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_chapter_popup_beat.custom_minimum_size.x = 500
	_chapter_popup_beat.add_theme_font_size_override("font_size", 18)
	_chapter_popup_beat.add_theme_color_override("font_color", Color(0.9, 0.9, 0.9))
	vbox.add_child(_chapter_popup_beat)
	var hint := Label.new()
	hint.text = "Click or press any key to continue"
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	hint.add_theme_font_size_override("font_size", 14)
	hint.add_theme_color_override("font_color", Color(0.6, 0.6, 0.6))
	vbox.add_child(hint)
	center.add_child(vbox)
	_chapter_popup_layer.visible = false


func _show_chapter_popup(chapter_id: String) -> void:
	if not use_full_narrative or _chapter_popup_layer == null:
		return
	var ch = chapter_by_id.get(chapter_id, {})
	var ch_num: int = _chapter_num(chapter_id)
	var title: String = "Chapter %d: %s" % [ch_num, str(ch.get("title", chapter_id))]
	var beat: String = str(ch.get("beat_summary", ""))
	if _chapter_popup_title:
		_chapter_popup_title.text = title
	if _chapter_popup_beat:
		_chapter_popup_beat.text = beat
	_chapter_popup_layer.visible = true
	_chapter_popup_active = true
	_chapter_popup_timer = 5.0


func _hide_chapter_popup() -> void:
	_chapter_popup_active = false
	if _chapter_popup_layer:
		_chapter_popup_layer.visible = false


func _build_clue_toast() -> void:
	if not use_full_narrative:
		return
	_clue_toast_layer = CanvasLayer.new()
	_clue_toast_layer.name = "ClueToastLayer"
	_clue_toast_layer.layer = 800
	add_child(_clue_toast_layer)
	var margin := MarginContainer.new()
	margin.set_anchors_preset(Control.PRESET_TOP_WIDE)
	margin.anchor_top = 0.0
	margin.anchor_left = 0.0
	margin.anchor_right = 1.0
	margin.offset_top = 60
	margin.offset_left = 100
	margin.offset_right = -100
	_clue_toast_layer.add_child(margin)
	var panel := PanelContainer.new()
	panel.add_theme_stylebox_override("panel", UiThemeHelper.style_glass_toast())
	margin.add_child(panel)
	_clue_toast_label = Label.new()
	_clue_toast_label.name = "ClueToastLabel"
	_clue_toast_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_clue_toast_label.add_theme_font_size_override("font_size", 18)
	_clue_toast_label.add_theme_color_override("font_color", Color.WHITE)
	panel.add_child(_clue_toast_label)
	_clue_toast_layer.visible = false


func _show_clue_toast(clue_label: String) -> void:
	if not use_full_narrative or _clue_toast_layer == null or _clue_toast_label == null:
		return
	_clue_toast_label.text = "Collected: " + str(clue_label)
	_clue_toast_layer.visible = true
	_clue_toast_active = true
	_clue_toast_timer = 2.5


func _hide_clue_toast() -> void:
	_clue_toast_active = false
	if _clue_toast_layer:
		_clue_toast_layer.visible = false


func _hide_ui() -> void:
	if _layer:
		_layer.visible = false
	_hide_ending_ui()
	dialogue_active = false
	_last_npc_for_meters = _full_npc_id if not _full_npc_id.is_empty() else _last_npc_for_meters
	_ending_mode = false
	current_event_id = ""
	_dialogue_start_npc_name = ""
	_current_choice_goto_ids.clear()
	_selected_choice_index = 0
	_full_npc_id = ""
	_full_node_id = ""
	_full_node_map.clear()
	_full_applied_node_ids.clear()
	_full_current_options.clear()
	_ending_ev = {}


func _show_ui() -> void:
	if _layer:
		_layer.visible = true
	dialogue_active = true


func _start_dialogue_full(display_name: String) -> void:
	var npc_id = display_name_to_npc_id.get(display_name, "")
	if npc_id.is_empty():
		for nid in npcs:
			if npcs[nid].get("name", "") == display_name:
				npc_id = nid
				break
	if npc_id.is_empty():
		push_error("DialogueManager: No NPC for display_name: " + display_name)
		return
	var pack = _get_pack_for(npc_id, current_chapter_id)
	if pack.is_empty():
		push_error("DialogueManager: No dialogue pack for %s in %s" % [npc_id, current_chapter_id])
		return
	var nodes = pack.get("_raw_nodes", [])
	if nodes.size() == 0:
		push_error("DialogueManager: Empty dialogue pack for " + npc_id)
		return
	var node_map = pack.get("_nodes", {})
	var first_id = str(nodes[0].get("id", ""))
	if first_id.is_empty() and node_map.size() > 0:
		first_id = node_map.keys()[0]
	_full_npc_id = npc_id
	_last_npc_for_meters = npc_id
	_full_node_id = first_id
	_full_node_map = node_map
	_full_applied_node_ids.clear()
	_full_current_options.clear()
	_dialogue_start_npc_name = str(npcs[npc_id].get("name", npc_id))
	_show_ui()
	_display_full_node()


func _display_current() -> void:
	if use_full_narrative and not _full_npc_id.is_empty():
		_display_full_node()
		return
	_display_legacy()


func _display_full_node() -> void:
	if _full_npc_id.is_empty() or _full_node_id.is_empty():
		end_dialogue()
		return
	var node = _full_node_map.get(_full_node_id, {})
	if node.is_empty():
		end_dialogue()
		return
	var ok = _requirement_ok(_full_npc_id, node.get("required_tags_any"), node.get("required_tags_all"), node.get("min_trust"), node.get("min_pressure"))
	if not ok[0]:
		_text_label.text = "(This part of the conversation is blocked: %s)" % str(ok[1])
		_speaker_label.text = str(npcs.get(_full_npc_id, {}).get("name", "NPC"))
		_next_btn.visible = true
		_next_btn.text = "Close (E / Space)"
		for c in _choices_container.get_children():
			c.queue_free()
		_current_choice_goto_ids.clear()
		_next_btn.pressed.disconnect(_on_next_pressed)
		_next_btn.pressed.connect(_on_close_full_blocked)
		return
	if not _full_applied_node_ids.has(_full_node_id):
		var added = _apply_effects(_full_npc_id, node)
		_full_applied_node_ids[_full_node_id] = true
		_auto_advance_chapter()
		if _ending_unlocked():
			_trigger_full_ending()
			return
	var text = str(node.get("npc_text", ""))
	_speaker_label.text = str(npcs.get(_full_npc_id, {}).get("name", "NPC"))
	_text_label.text = text
	for c in _choices_container.get_children():
		c.queue_free()
	_current_choice_goto_ids.clear()
	_full_current_options.clear()
	var options = _as_list(node.get("options", []))
	var available: Array = []
	for opt in options:
		if opt is Dictionary:
			var ro = _requirement_ok(_full_npc_id, opt.get("required_tags_any"), opt.get("required_tags_all"), opt.get("min_trust"), opt.get("min_pressure"))
			if ro[0]:
				var nxt = str(opt.get("next", ""))
				available.append({"opt": opt, "next": nxt})
	if available.size() > 0:
		_next_btn.visible = false
		_hint_label.visible = true
		_selected_choice_index = 0
		for item in available:
			var opt = item.opt
			var nxt = item.next
			_full_current_options.append(nxt)
			var btn = Button.new()
			btn.text = str(opt.get("text", ""))
			btn.pressed.connect(_on_choice_full.bind(nxt))
			_choices_container.add_child(btn)
		_current_choice_goto_ids = _full_current_options.duplicate()
		_update_choice_highlight()
	else:
		_next_btn.visible = true
		_hint_label.visible = false
		var single_opt = options[0] if options.size() > 0 else {}
		var nxt = str(single_opt.get("next", "")) if single_opt is Dictionary else ""
		if nxt.is_empty() or nxt.to_upper() == "END":
			_next_btn.text = "Close (E / Space)"
			_full_current_options.clear()
			_current_choice_goto_ids.clear()
		else:
			_next_btn.text = "Next (E / Space)"
			_full_current_options = [nxt]
			_current_choice_goto_ids = [nxt]


func _on_close_full_blocked() -> void:
	_next_btn.pressed.disconnect(_on_close_full_blocked)
	_next_btn.pressed.connect(_on_next_pressed)
	end_dialogue()


func _on_close_full() -> void:
	_next_btn.pressed.disconnect(_on_close_full)
	_next_btn.pressed.connect(_on_next_pressed)
	end_dialogue()


func _on_choice_full(next_id: String) -> void:
	var node = _full_node_map.get(_full_node_id, {})
	var options = _as_list(node.get("options", []))
	var chosen = {}
	for opt in options:
		if opt is Dictionary and str(opt.get("next", "")) == next_id:
			chosen = opt
			break
	if not chosen.is_empty():
		_apply_effects(_full_npc_id, chosen)
		_auto_advance_chapter()
	if _ending_unlocked():
		_trigger_full_ending()
		return
	if next_id.is_empty() or next_id.to_upper() == "END":
		end_dialogue()
		return
	_full_node_id = next_id
	_display_full_node()


func _trigger_full_ending() -> void:
	_full_npc_id = ""
	_full_node_id = ""
	_full_node_map.clear()
	_full_applied_node_ids.clear()
	_full_current_options.clear()
	_ending_ev = {"text": str(ending_block.get("text", "The End.")), "goto": ""}
	_show_ending_sequence(_ending_ev)


func _display_legacy() -> void:
	if current_event_id.is_empty() or not event_by_id.has(current_event_id):
		end_dialogue()
		return
	var ev: Dictionary = event_by_id[current_event_id]
	
	# Check if this is an ending event FIRST (before speaker validation)
	# This ensures ending events are shown on black screen, not in normal dialogue UI
	if _is_ending_event(current_event_id):
		_show_ending_sequence(ev)
		return
	
	# Terminal ending: black screen + narrator line(s), then quit
	var tags: Dictionary = ev.get("tags", {}) if ev.get("tags", {}) is Dictionary else {}
	if current_event_id == "end" or tags.get("ending", false):
		_show_ending_sequence(ev)
		return
	var speaker := str(ev.get("speaker", ""))
	# End conversation when we would show another NPC (scope dialogue to the one we started with)
	if speaker != "NARRATOR" and speaker != _dialogue_start_npc_name:
		# Safety net: if this event leads to "end", transition to ending sequence instead of ending
		if str(ev.get("goto", "")) == "end":
			current_event_id = "end"
			var end_ev: Dictionary = event_by_id.get("end", {})
			_show_ending_sequence(end_ev)
			return
		end_dialogue()
		return
	var text := str(ev.get("text", ""))
	_speaker_label.text = speaker
	_text_label.text = text

	# Clear choice buttons
	for c in _choices_container.get_children():
		c.queue_free()

	var choices: Array = ev.get("choices", [])
	_current_choice_goto_ids.clear()
	_selected_choice_index = 0
	if choices is Array and choices.size() > 0:
		_next_btn.visible = false
		_hint_label.visible = true
		for ch in choices:
			var choice: Dictionary = ch if ch is Dictionary else {}
			var btn := Button.new()
			btn.text = str(choice.get("text", ""))
			var goto_id := str(choice.get("goto", ""))
			_current_choice_goto_ids.append(goto_id)
			btn.pressed.connect(_on_choice_pressed.bind(goto_id))
			_choices_container.add_child(btn)
		_update_choice_highlight()
	else:
		_next_btn.visible = true
		_hint_label.visible = false
		var goto_id := str(ev.get("goto", ""))
		if goto_id.is_empty():
			_next_btn.text = "Close (E / Space)"
		else:
			_next_btn.text = "Next (E / Space)"


func _update_choice_highlight() -> void:
	var children = _choices_container.get_children()
	for i in range(children.size()):
		var btn = children[i] as Button
		if btn:
			btn.modulate = Color(1.25, 1.2, 0.85) if i == _selected_choice_index else Color(1, 1, 1)
			if i == _selected_choice_index:
				btn.grab_focus()

func _on_next_pressed() -> void:
	advance()


func _on_choice_pressed(goto_id: String) -> void:
	if goto_id.is_empty():
		end_dialogue()
		return
	current_event_id = goto_id
	_display_current()


func has_active_dialogue() -> bool:
	return dialogue_active or _ending_mode


func start_dialogue(npc_display_name: String) -> void:
	if use_full_narrative:
		_start_dialogue_full(npc_display_name)
		return
	var first_id = npc_first_event.get(npc_display_name, "")
	if first_id.is_empty():
		push_error("DialogueManager: No dialogue for speaker: " + npc_display_name)
		return
	_dialogue_start_npc_name = npc_display_name
	current_event_id = first_id
	_show_ui()
	_display_legacy()


func advance() -> void:
	if _ending_mode:
		_ending_advance()
		return
	if not dialogue_active:
		return
	if use_full_narrative and not _full_npc_id.is_empty():
		if _current_choice_goto_ids.size() > 0:
			var idx = _selected_choice_index if _selected_choice_index < _current_choice_goto_ids.size() else 0
			var goto_id: String = str(_current_choice_goto_ids[idx])
			_on_choice_full(goto_id)
		else:
			end_dialogue()
		return
	if current_event_id.is_empty():
		return
	if _current_choice_goto_ids.size() > 0:
		var goto_id: String = str(_current_choice_goto_ids[_selected_choice_index])
		_on_choice_pressed(goto_id)
		return
	var ev: Dictionary = event_by_id.get(current_event_id, {})
	var goto_id: String = str(ev.get("goto", ""))
	if goto_id.is_empty():
		end_dialogue()
		return
	current_event_id = goto_id
	_display_legacy()


func end_dialogue() -> void:
	_hide_ui()


func _show_ending_sequence(ev: Dictionary) -> void:
	if _layer:
		_layer.visible = false
	_ending_mode = true
	_ending_ev = ev
	if _ending_layer == null:
		_ending_layer = CanvasLayer.new()
		_ending_layer.name = "EndingLayer"
		_ending_layer.layer = 1000
		add_child(_ending_layer)
		var black := ColorRect.new()
		black.name = "EndingBlack"
		black.set_anchors_preset(Control.PRESET_FULL_RECT)
		black.set_anchor(SIDE_LEFT, 0.0)
		black.set_anchor(SIDE_TOP, 0.0)
		black.set_anchor(SIDE_RIGHT, 1.0)
		black.set_anchor(SIDE_BOTTOM, 1.0)
		black.offset_left = 0
		black.offset_top = 0
		black.offset_right = 0
		black.offset_bottom = 0
		black.color = Color.BLACK
		black.mouse_filter = Control.MOUSE_FILTER_IGNORE
		_ending_layer.add_child(black)
		var center := CenterContainer.new()
		center.name = "EndingCenter"
		center.set_anchors_preset(Control.PRESET_FULL_RECT)
		center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT, Control.PRESET_MODE_MINSIZE, 40)
		_ending_layer.add_child(center)
		var vbox := VBoxContainer.new()
		vbox.add_theme_constant_override("separation", 24)
		center.add_child(vbox)
		_ending_label = Label.new()
		_ending_label.name = "EndingLabel"
		_ending_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		_ending_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		_ending_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		_ending_label.custom_minimum_size.x = 600
		_ending_label.add_theme_font_size_override("font_size", 28)
		_ending_label.add_theme_color_override("font_color", Color.WHITE)
		vbox.add_child(_ending_label)
		_ending_hint = Label.new()
		_ending_hint.name = "EndingHint"
		_ending_hint.text = "Press E or Space to continue"
		_ending_hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		_ending_hint.add_theme_font_size_override("font_size", 16)
		_ending_hint.add_theme_color_override("font_color", Color(0.6, 0.6, 0.6))
		vbox.add_child(_ending_hint)
	_ending_layer.visible = true
	_ending_label.text = str(ev.get("text", ""))


func _hide_ending_ui() -> void:
	if _ending_layer:
		_ending_layer.visible = false


func _ending_advance() -> void:
	if not _ending_mode:
		return
	var ev: Dictionary = _ending_ev if not _ending_ev.is_empty() else event_by_id.get(current_event_id, {})
	var goto_id: String = str(ev.get("goto", ""))
	if goto_id.is_empty():
		_quit_or_the_end()
		return
	current_event_id = goto_id
	ev = event_by_id.get(current_event_id, {})
	if ev.is_empty():
		_quit_or_the_end()
		return
	_ending_label.text = str(ev.get("text", ""))


func _quit_or_the_end() -> void:
	_ending_mode = false
	_hide_ending_ui()
	if _ending_layer != null and _ending_label != null:
		_ending_layer.visible = true
		_ending_label.text = "The End"
		if _ending_hint:
			_ending_hint.text = ""
	if OS.has_feature("web"):
		pass
	else:
		# Show "The End" on black for ~1.5 s, then quit
		var t := get_tree().create_timer(1.5)
		t.timeout.connect(_on_ending_quit_timeout)


func _on_ending_quit_timeout() -> void:
	get_tree().quit()
