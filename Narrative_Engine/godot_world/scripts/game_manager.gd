extends Node
## GameManager autoload: game_bundle, chapter/clue state, 2D position for clue-based game.

const DEFAULT_BUNDLE_PATH := "res://generated/game_bundle.json"
const DEFAULT_RUNTIME_CONFIG_PATH := "res://generated/runtime_config.json"

var game_bundle: Dictionary = {}
var current_chapter_id: String = "chapter_1"
var tile_size_m: float = 1.8
var collected_clue_ids: Dictionary = {}
var player_position_2d: Vector2 = Vector2.ZERO
var player_area_id: String = ""
var show_ending: bool = false
var game_server_url: String = "http://127.0.0.1:8000"
var game_output_path: String = ""

var npc_conversations: Dictionary = {}
var near_interactable: Dictionary = {}
var intro_begun: bool = true
## Title → setup → spawn
var title_passed: bool = false
var setup_passed: bool = false

## Deferred until NPC dialogue closes
var pending_chapter_advance: bool = false
var pending_ending: bool = false

## npc_id -> true once player opened dialogue this chapter
var npc_spoken_chapter: Dictionary = {}
## chapter_id:npc_id -> true once that NPC awarded ≥1 clue via dialogue/chat this chapter (tasks ✓)
var npc_awarded_clue_chapter: Dictionary = {}
## While NPC dialogue open: Node3D in group npc (range check + end talk if player walks away)
var dialogue_npc: Node = null

signal clue_added(clue_id: String)
signal chapter_advanced(chapter_id: String)
signal ending_triggered()
signal pending_transition_ready()
signal player_area_changed(area_id: String)


func _ready() -> void:
	_load_runtime_config()
	var url := OS.get_environment("GAME_SERVER_URL")
	if not url.is_empty():
		game_server_url = url
	var out := OS.get_environment("GAME_OUTPUT")
	if not out.is_empty():
		game_output_path = out
	_load_bundle()


func init_from_bundle(bundle: Dictionary, p_tile_size_m: float = 1.8) -> void:
	if bundle.is_empty():
		return
	game_bundle = bundle
	var sp = game_bundle.get("spawn_point", {})
	player_position_2d = Vector2(float(sp.get("x", 0)), float(sp.get("y", 0)))
	player_area_id = str(sp.get("area_id", ""))
	current_chapter_id = "chapter_1"
	collected_clue_ids.clear()
	npc_conversations.clear()
	npc_spoken_chapter.clear()
	npc_awarded_clue_chapter.clear()
	dialogue_npc = null
	near_interactable = {}
	intro_begun = false
	title_passed = false
	setup_passed = false
	show_ending = false
	pending_chapter_advance = false
	pending_ending = false
	tile_size_m = p_tile_size_m
	print("GameManager: Initialized from WorldLoader bundle")


func _load_bundle() -> void:
	var path := DEFAULT_BUNDLE_PATH
	var env_output := OS.get_environment("GAME_OUTPUT")
	if not env_output.is_empty():
		var ext_path := path.get_base_dir().path_join("..").path_join(env_output).path_join("game_bundle.json")
		if FileAccess.file_exists(ProjectSettings.globalize_path(ext_path)):
			path = ProjectSettings.globalize_path(ext_path)
		else:
			var base := OS.get_executable_path().get_base_dir()
			if OS.get_name() == "macOS":
				base = base.path_join("../Resources")
			var alt := base.path_join(env_output).path_join("game_bundle.json")
			if FileAccess.file_exists(alt):
				path = alt
	if not FileAccess.file_exists(path) and not ResourceLoader.exists(path):
		var rel := path.replace("res://", "")
		var base2 := OS.get_executable_path().get_base_dir()
		if OS.get_name() == "macOS":
			path = base2.path_join("../Resources/" + rel)
		else:
			path = base2.path_join(rel)
	var txt := ""
	if FileAccess.file_exists(path):
		var f := FileAccess.open(path, FileAccess.READ)
		if f:
			txt = f.get_as_text()
			f.close()
	if txt.is_empty():
		return
	var parsed = JSON.parse_string(txt)
	if parsed is Dictionary:
		game_bundle = parsed
		var sp = game_bundle.get("spawn_point", {})
		player_position_2d = Vector2(float(sp.get("x", 0)), float(sp.get("y", 0)))
		player_area_id = str(sp.get("area_id", ""))
		current_chapter_id = "chapter_1"
		collected_clue_ids.clear()
		npc_conversations.clear()
		show_ending = false
		pending_chapter_advance = false
		pending_ending = false
		dialogue_npc = null
		print("GameManager: Loaded game_bundle from ", path)


func _load_runtime_config() -> void:
	var path := DEFAULT_RUNTIME_CONFIG_PATH
	if not FileAccess.file_exists(path) and not ResourceLoader.exists(path):
		var rel := path.replace("res://", "")
		var base := OS.get_executable_path().get_base_dir()
		if OS.get_name() == "macOS":
			path = base.path_join("../Resources/" + rel)
		else:
			path = base.path_join(rel)
	var txt := ""
	if FileAccess.file_exists(path):
		var f := FileAccess.open(path, FileAccess.READ)
		if f:
			txt = f.get_as_text()
			f.close()
	if txt.is_empty():
		return
	var parsed = JSON.parse_string(txt)
	if not (parsed is Dictionary):
		return
	var chat_base := str(parsed.get("chat_api_base", "")).strip_edges()
	if not chat_base.is_empty():
		game_server_url = chat_base
	var out_id := str(parsed.get("world_output_id", "")).strip_edges()
	if not out_id.is_empty():
		game_output_path = out_id


func get_current_chapter() -> Dictionary:
	var chapters: Array = game_bundle.get("narrative", {}).get("chapters", [])
	for c in chapters:
		if c is Dictionary and str(c.get("id", "")) == current_chapter_id:
			return c
	return {}


func add_clue(clue_id: String) -> void:
	if collected_clue_ids.get(clue_id, false):
		return
	collected_clue_ids[clue_id] = true
	clue_added.emit(clue_id)
	_check_pending_after_clue()


func _check_pending_after_clue() -> void:
	var ending = game_bundle.get("narrative", {}).get("ending", {})
	var trigger: Dictionary = ending.get("trigger", {})
	var end_clues: Array = trigger.get("requires_all_clues", [])
	if end_clues.size() > 0:
		var all := true
		for cid in end_clues:
			if not collected_clue_ids.get(str(cid), false):
				all = false
				break
		if all:
			pending_ending = true
			return
	if can_advance_chapter():
		pending_chapter_advance = true


func advance_chapter() -> void:
	var chapters: Array = game_bundle.get("narrative", {}).get("chapters", [])
	var idx := -1
	for i in range(chapters.size()):
		if chapters[i] is Dictionary and str(chapters[i].get("id", "")) == current_chapter_id:
			idx = i
			break
	if idx >= 0 and idx < chapters.size() - 1:
		var next_ch: Dictionary = chapters[idx + 1]
		current_chapter_id = str(next_ch.get("id", "chapter_1"))
		chapter_advanced.emit(current_chapter_id)


func can_advance_chapter() -> bool:
	var ch := get_current_chapter()
	var exit_ids: Array = ch.get("exit_require_all_clues", [])
	if exit_ids.is_empty():
		return false
	for cid in exit_ids:
		if not collected_clue_ids.get(str(cid), false):
			return false
	return true


## Call when closing NPC dialogue — applies chapter advance or ending
func apply_pending_transitions_if_any() -> void:
	if pending_ending:
		pending_ending = false
		pending_chapter_advance = false
		show_ending = true
		ending_triggered.emit()
		return
	if pending_chapter_advance:
		pending_chapter_advance = false
		advance_chapter()
		pending_transition_ready.emit()


## Legacy: immediate advance (clue pickup in world)
func try_advance_and_check_ending() -> void:
	var ending = game_bundle.get("narrative", {}).get("ending", {})
	var trigger: Dictionary = ending.get("trigger", {})
	var end_clues: Array = trigger.get("requires_all_clues", [])
	if end_clues.size() > 0:
		var all := true
		for cid in end_clues:
			if not collected_clue_ids.get(str(cid), false):
				all = false
				break
		if all:
			show_ending = true
			ending_triggered.emit()
			return
	if can_advance_chapter():
		advance_chapter()


func record_npc_dialogue_open(npc_id: String) -> void:
	var key := current_chapter_id + ":" + npc_id
	npc_spoken_chapter[key] = true


func has_spoken_to_npc_this_chapter(npc_id: String) -> bool:
	return npc_spoken_chapter.get(current_chapter_id + ":" + npc_id, false)


func record_npc_clue_award(npc_id: String) -> void:
	var key := current_chapter_id + ":" + npc_id
	npc_awarded_clue_chapter[key] = true


## Task list ✓: only after this NPC gave you a clue in dialogue this chapter
func has_clue_from_npc_this_chapter(npc_id: String) -> bool:
	return npc_awarded_clue_chapter.get(current_chapter_id + ":" + npc_id, false)


## Spotlight NPCs still missing a task ✓ (no clue from them this chapter) — compass targets
func get_pending_task_npc_ids() -> Array:
	var ch := get_current_chapter()
	var ids: Array = ch.get("spotlight_npc_ids", [])
	var out: Array = []
	for nid in ids:
		if not has_clue_from_npc_this_chapter(str(nid)):
			out.append(str(nid))
	return out


func get_collected_clues() -> Array:
	var out: Array = []
	var clues: Array = game_bundle.get("narrative", {}).get("clues", [])
	for c in clues:
		if c is Dictionary and collected_clue_ids.get(str(c.get("id", "")), false):
			out.append(c)
	return out


func get_spawn_point() -> Dictionary:
	return game_bundle.get("spawn_point", {})


func get_npc_at_anchor(anchor_id: String) -> Dictionary:
	var npcs: Array = game_bundle.get("narrative", {}).get("npcs", [])
	for n in npcs:
		if n is Dictionary and str(n.get("anchor_id", "")) == anchor_id:
			return n
	return {}


func get_clue_at_anchor(anchor_id: String) -> Dictionary:
	var clues: Array = game_bundle.get("narrative", {}).get("clues", [])
	for c in clues:
		if c is Dictionary and str(c.get("anchor_id", "")) == anchor_id:
			return c
	return {}


func collect_clue_if_available(clue_id: String) -> bool:
	var ch := get_current_chapter()
	var available: Array = ch.get("available_clue_ids", [])
	if not clue_id in available:
		return false
	if collected_clue_ids.get(clue_id, false):
		return false
	add_clue(clue_id)
	try_advance_and_check_ending()
	return true


func get_conversation(npc_id: String) -> Array:
	return npc_conversations.get(npc_id, [])


func append_message(npc_id: String, role: String, content: String) -> void:
	if not npc_conversations.has(npc_id):
		npc_conversations[npc_id] = []
	npc_conversations[npc_id].append({"role": role, "content": content})


func update_player_position_2d(x: float, y: float) -> void:
	player_position_2d = Vector2(x, y)
	_update_area_from_position(x, y)


func _update_area_from_position(px: float, py: float) -> void:
	var areas: Array = []
	var ar = game_bundle.get("areas", {})
	if ar is Dictionary:
		for aid in ar:
			areas.append({"id": aid, "data": ar[aid]})
	elif ar is Array:
		for a in ar:
			if a is Dictionary:
				areas.append({"id": str(a.get("id", "")), "data": a})
	for item in areas:
		var aid := str(item.id)
		var d = item.data
		if not (d is Dictionary):
			continue
		var r = d.get("rect", {})
		if not (r is Dictionary):
			continue
		var rx := float(r.get("x", 0))
		var ry := float(r.get("y", 0))
		var rw := float(r.get("w", 0))
		var rh := float(r.get("h", 0))
		if rw <= 0 or rh <= 0:
			continue
		if px >= rx and px <= rx + rw and py >= ry and py <= ry + rh:
			if player_area_id != aid:
				player_area_id = aid
				player_area_changed.emit(aid)
			return


func bundle_image_path(filename: String) -> String:
	if filename.is_empty():
		return ""
	var base := game_output_path.strip_edges()
	# In Web exports, all bundle images are packed into res://generated/,
	# so ignore external GAME_OUTPUT paths and always use packed resources.
	if OS.has_feature("web"):
		base = ""
	if base.is_empty():
		base = OS.get_environment("GAME_OUTPUT")
	if base.is_empty():
		# Exported build (e.g. web): images are packed under res://generated/
		var res_path := "res://generated/" + filename
		if ResourceLoader.exists(res_path):
			return res_path
		return ""
	var rel := base + "/" + filename if not base.ends_with("/") else base + filename
	var candidates: PackedStringArray = []
	candidates.append(ProjectSettings.globalize_path("res://..".path_join(rel)))
	var exec_base := OS.get_executable_path().get_base_dir()
	if OS.get_name() == "macOS":
		candidates.append(exec_base.path_join("../Resources").path_join(rel))
	candidates.append(exec_base.path_join(rel))
	for p in candidates:
		if FileAccess.file_exists(p):
			return p
	return ""


func bundle_load_texture(filename: String) -> Texture2D:
	"""Load bundle image as Texture2D. Use this for UI (works with packed res:// in web export)."""
	var path := bundle_image_path(filename)
	if path.is_empty():
		return null
	if path.begins_with("res://"):
		return load(path) as Texture2D
	var img := Image.load_from_file(path)
	return ImageTexture.create_from_image(img) if img else null
