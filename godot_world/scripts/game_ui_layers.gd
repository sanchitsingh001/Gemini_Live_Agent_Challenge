extends Node

@export var use_game_bundle: bool = false

var _hud: CanvasLayer = null
var _clue_panel: CanvasLayer = null
var _chapter_summary: CanvasLayer = null
var _chapter_popup: CanvasLayer = null
var _title: CanvasLayer = null
var _setup: CanvasLayer = null
var _transition: CanvasLayer = null
var _clue_toast: CanvasLayer = null
var _ending: CanvasLayer = null
var _dialogue: CanvasLayer = null
var _task_panel: CanvasLayer = null
var _interaction_hint: CanvasLayer = null

func _ready() -> void:
	call_deferred("_deferred_spawn_ui")


func _deferred_spawn_ui() -> void:
	var wl = get_parent()
	if wl and wl.get("use_game_bundle"):
		use_game_bundle = wl.use_game_bundle
	if not use_game_bundle or not GameManager or GameManager.game_bundle.is_empty():
		return
	_spawn_ui()


func _spawn_ui() -> void:
	var hud_script = load("res://scripts/ui/game_hud.gd")
	if hud_script:
		_hud = CanvasLayer.new()
		_hud.set_script(hud_script)
		add_child(_hud)
	var compass_script = load("res://scripts/ui/compass_hud.gd")
	if compass_script:
		var compass := CanvasLayer.new()
		compass.set_script(compass_script)
		add_child(compass)
	var clue_script = load("res://scripts/ui/clue_inventory_panel.gd")
	if clue_script:
		_clue_panel = CanvasLayer.new()
		_clue_panel.set_script(clue_script)
		add_child(_clue_panel)
	var sum_script = load("res://scripts/ui/chapter_summary_panel.gd")
	if sum_script:
		_chapter_summary = CanvasLayer.new()
		_chapter_summary.set_script(sum_script)
		_chapter_summary.visible = false
		add_child(_chapter_summary)
	var pop_script = load("res://scripts/ui/chapter_popup.gd")
	if pop_script:
		_chapter_popup = CanvasLayer.new()
		_chapter_popup.set_script(pop_script)
		_chapter_popup.visible = false
		add_child(_chapter_popup)

	var title_script = load("res://scripts/ui/title_screen.gd")
	if title_script:
		_title = CanvasLayer.new()
		_title.set_script(title_script)
		_title.play_pressed.connect(_on_title_play)
		add_child(_title)
	var setup_script = load("res://scripts/ui/setup_screen.gd")
	if setup_script:
		_setup = CanvasLayer.new()
		_setup.set_script(setup_script)
		_setup.continued.connect(_on_setup_done)
		add_child(_setup)
	var trans_script = load("res://scripts/ui/transition_screen.gd")
	if trans_script:
		_transition = CanvasLayer.new()
		_transition.set_script(trans_script)
		add_child(_transition)

	var toast_script = load("res://scripts/ui/clue_toast.gd")
	if toast_script:
		_clue_toast = CanvasLayer.new()
		_clue_toast.set_script(toast_script)
		add_child(_clue_toast)
	var end_script = load("res://scripts/ui/ending_screen.gd")
	if end_script:
		_ending = CanvasLayer.new()
		_ending.set_script(end_script)
		add_child(_ending)
	var dlg_script = load("res://scripts/ui/dialogue_panel.gd")
	if dlg_script:
		_dialogue = CanvasLayer.new()
		_dialogue.set_script(dlg_script)
		_dialogue.add_to_group("chat_panel")
		add_child(_dialogue)
	var task_script = load("res://scripts/ui/task_panel.gd")
	if task_script:
		_task_panel = CanvasLayer.new()
		_task_panel.set_script(task_script)
		add_child(_task_panel)
	var hint_script = load("res://scripts/ui/interaction_hint.gd")
	if hint_script:
		_interaction_hint = CanvasLayer.new()
		_interaction_hint.set_script(hint_script)
		add_child(_interaction_hint)


func _on_title_play() -> void:
	if _setup and _setup.has_method("show_setup"):
		_setup.show_setup()


func _on_setup_done() -> void:
	if _transition and _transition.has_method("show_for_chapter_id"):
		_transition.show_for_chapter_id(GameManager.current_chapter_id)
