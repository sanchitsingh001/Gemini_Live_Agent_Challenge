extends CharacterBody3D

const SPEED = 5.0
const BOOST_SPEED = 50.0
const JUMP_VELOCITY = 4.5
const MOUSE_SENSITIVITY = 0.003

# Get the gravity from the project settings to be synced with RigidBody nodes.
var gravity: float = ProjectSettings.get_setting("physics/3d/default_gravity")

var camera: Camera3D = null

@export var player_height_m: float = 1.8
@export var eye_height_ratio: float = 0.92
@export var capsule_radius_m: float = 0.3

func _ready() -> void:
	print("PLAYER SCRIPT: _ready() called")
	add_to_group("player")
	camera = get_node_or_null("Camera3D")
	_setup_input_map()
	_apply_player_scale()
	print("PLAYER SCRIPT: actions setup complete. Camera: ", camera)
	
	# game_bundle: start with visible cursor so user can click Begin on intro; click to capture for look
	# web: always visible, click to capture. native non-game_bundle: capture immediately
	if OS.has_feature("web") or _use_game_bundle_mode():
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	else:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

var fly_mode: bool = false
var _last_frame_pos := Vector3.ZERO
var _stuck_frames := 0
# Horizontal only (XZ); keep tight so only face-to-face talk feels natural
const NPC_INTERACT_RANGE_M := 2.75
var _near_npc: Node = null  # Closest NPC in range (group "npc"), for E-to-talk
var _near_clue: Node = null  # Closest clue in range (group "clue"), for E-to-examine

func _setup_input_map() -> void:
	# Programmatically add WASD actions if they don't exist
	if not InputMap.has_action("move_forward"):
		InputMap.add_action("move_forward")
		var ev = InputEventKey.new()
		ev.keycode = KEY_W
		InputMap.action_add_event("move_forward", ev)
		
	if not InputMap.has_action("move_backward"):
		InputMap.add_action("move_backward")
		var ev = InputEventKey.new()
		ev.keycode = KEY_S
		InputMap.action_add_event("move_backward", ev)
		
	if not InputMap.has_action("move_left"):
		InputMap.add_action("move_left")
		var ev = InputEventKey.new()
		ev.keycode = KEY_A
		InputMap.action_add_event("move_left", ev)
		
	if not InputMap.has_action("move_right"):
		InputMap.add_action("move_right")
		var ev = InputEventKey.new()
		ev.keycode = KEY_D
		InputMap.action_add_event("move_right", ev)
		
	if not InputMap.has_action("jump"):
		InputMap.add_action("jump")
		var ev = InputEventKey.new()
		ev.keycode = KEY_SPACE
		InputMap.action_add_event("jump", ev)
		
	if not InputMap.has_action("sprint"):
		InputMap.add_action("sprint")
		var ev = InputEventKey.new()
		ev.keycode = KEY_SHIFT
		InputMap.action_add_event("sprint", ev)

	# Fly controls
	if not InputMap.has_action("fly_toggle"):
		InputMap.add_action("fly_toggle")
		var ev = InputEventKey.new()
		ev.keycode = KEY_F
		InputMap.action_add_event("fly_toggle", ev)

	# Fly up: V (works on Mac; never share E with interact)
	if not InputMap.has_action("fly_up"):
		InputMap.add_action("fly_up")
	InputMap.action_erase_events("fly_up")
	var ev_fly := InputEventKey.new()
	ev_fly.keycode = KEY_V
	InputMap.action_add_event("fly_up", ev_fly)

	if not InputMap.has_action("fly_down"):
		InputMap.add_action("fly_down")
		var ev = InputEventKey.new()
		ev.keycode = KEY_Q
		InputMap.action_add_event("fly_down", ev)

	if not InputMap.has_action("interact"):
		InputMap.add_action("interact")
		var ev = InputEventKey.new()
		ev.keycode = KEY_E
		InputMap.action_add_event("interact", ev)

func _apply_player_scale() -> void:
	if camera:
		camera.position.y = player_height_m * eye_height_ratio
		camera.current = true

	var cs: CollisionShape3D = $CollisionShape3D
	if not cs:
		return
		
	if cs.shape is CapsuleShape3D:
		var cap: CapsuleShape3D = cs.shape
		cap.radius = capsule_radius_m
		cap.height = max(0.1, player_height_m - 2.0 * capsule_radius_m)
		cs.position.y = player_height_m / 2.0

func _unhandled_input(event: InputEvent) -> void:
	# Dialogue: ESC + number keys handled on dialogue_panel; WASD still moves; range exit closes talk

	# Fallback: if frozen at intro and user presses Space/Enter/E, skip intro (in case intro UI isn't visible)
	if _use_game_bundle_mode() and GameManager and not GameManager.intro_begun:
		if event.is_action_pressed("interact") or event.is_action_pressed("ui_accept"):
			GameManager.intro_begun = true
			var intro_nodes = get_tree().get_nodes_in_group("intro_screen")
			for n in intro_nodes:
				if n.visible:
					n.visible = false
					break
			get_viewport().set_input_as_handled()
			return

	if event is InputEventKey and event.pressed and event.keycode == KEY_R:
		print("DEBUG: Force respawn/unstuck")
		position += Vector3(0, 5, 0)
		velocity = Vector3.ZERO

	# Web or game_bundle: click to capture mouse for look (allows intro Begin button to work)
	if (OS.has_feature("web") or _use_game_bundle_mode()) and Input.mouse_mode != Input.MOUSE_MODE_CAPTURED:
		if event is InputEventMouseButton and event.pressed:
			if event.button_index == MOUSE_BUTTON_LEFT or event.button_index == MOUSE_BUTTON_RIGHT:
				Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
				return
	
	if event is InputEventMouseMotion:
		if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED and camera != null:
			rotate_y(-event.relative.x * MOUSE_SENSITIVITY)
			camera.rotate_x(-event.relative.y * MOUSE_SENSITIVITY)
			camera.rotation.x = clamp(camera.rotation.x, deg_to_rad(-90), deg_to_rad(90))
	
	if event.is_action_pressed("inventory"):
		# game_bundle: C polled in _physics_process — do not eat C here
		if _use_game_bundle_mode():
			return
		if DialogueManager != null:
			DialogueManager.toggle_inventory_panel()
		get_viewport().set_input_as_handled()
		return

	if event.is_action_pressed("ui_cancel"):
		# Let SettingsMenu (and dialogue when open) see ESC first via _input; only toggle mouse if nothing else handled
		if not get_viewport().is_input_handled():
			if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
				Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
			else:
				Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
			
	if event.is_action_pressed("fly_toggle"):
		fly_mode = not fly_mode
		print("Fly mode: ", "ON" if fly_mode else "OFF")

	# Dialogue: E to start when near NPC (not while already in dialogue); E clue
	if _use_game_bundle_mode():
		if _is_chat_panel_open():
			pass
		elif _near_npc != null and event.is_action_pressed("interact"):
			var npc_id: String = str(_near_npc.get_meta("npc_id", "")) if _near_npc.has_meta("npc_id") else ""
			var display_name: String = str(_near_npc.get_meta("display_name", "")) if _near_npc.has_meta("display_name") else ""
			if npc_id.is_empty() and not display_name.is_empty():
				npc_id = display_name  # server still keys by narrative id when ids match name
			if not npc_id.is_empty():
				var npc_3d = _near_npc as Node3D
				if npc_3d != null:
					var look_target = Vector3(global_position.x, npc_3d.global_position.y, global_position.z)
					npc_3d.look_at(look_target, Vector3.UP)
					npc_3d.rotate_y(PI)
				_open_chat_panel(npc_id, display_name)
				get_viewport().set_input_as_handled()
				return
		elif _near_clue != null and event.is_action_pressed("interact"):
			var clue_id: String = str(_near_clue.get_meta("clue_id", ""))
			if not clue_id.is_empty() and GameManager:
				if GameManager.collect_clue_if_available(clue_id):
					get_viewport().set_input_as_handled()
				return
	elif DialogueManager != null:
		if DialogueManager.has_active_dialogue():
			if event.is_action_pressed("interact") or event.is_action_pressed("ui_accept"):
				DialogueManager.advance()
				get_viewport().set_input_as_handled()
				return
		elif _near_npc != null and event.is_action_pressed("interact"):
			var display_name = _near_npc.get_meta("display_name", "") if _near_npc.has_meta("display_name") else ""
			if not display_name.is_empty():
				var npc_3d = _near_npc as Node3D
				if npc_3d != null:
					var look_target = Vector3(global_position.x, npc_3d.global_position.y, global_position.z)
					npc_3d.look_at(look_target, Vector3.UP)
					npc_3d.rotate_y(PI)
				DialogueManager.start_dialogue(display_name)
				get_viewport().set_input_as_handled()
				return
		elif _near_clue != null and event.is_action_pressed("interact"):
			var clue_id: String = str(_near_clue.get_meta("clue_id", ""))
			if not clue_id.is_empty():
				DialogueManager.collect_clue(clue_id)
				get_viewport().set_input_as_handled()
				return

var frame_count = 0

func _use_game_bundle_mode() -> bool:
	return GameManager != null and not GameManager.game_bundle.is_empty()

## Edge-detect raw keys (Mac + HTML5: InputMap actions often miss on CharacterBody3D)
var _key_down_prev: Dictionary = {}

func _bundle_key_just(physical_key: int) -> bool:
	var down := Input.is_key_pressed(physical_key)
	var was: bool = bool(_key_down_prev.get(physical_key, false))
	_key_down_prev[physical_key] = down
	return down and not was


func _flash_top_hud() -> void:
	for h in get_tree().get_nodes_in_group("game_hud"):
		if h.has_method("flash_top_bar"):
			h.flash_top_bar()
			break


func _poll_game_bundle_keys() -> void:
	if not _use_game_bundle_mode() or get_tree().paused:
		return
	# C handled at start of _physics_process (single toggle; clue panel does not use _input for C)
	# ESC — close chat first, else settings
	if _bundle_key_just(KEY_ESCAPE) or Input.is_action_just_pressed("ui_cancel"):
		_flash_top_hud()
		if _is_chat_panel_open():
			_close_chat_panel()
		else:
			for sm in get_tree().get_nodes_in_group("settings_menu"):
				if sm.has_method("toggle_menu"):
					sm.toggle_menu()
					break
		return
	# E — NPC / clue (action + raw E)
	if Input.is_action_just_pressed("interact") or _bundle_key_just(KEY_E):
		if _is_chat_panel_open():
			_close_chat_panel()
			return
		if _near_npc != null:
			var npc_id: String = str(_near_npc.get_meta("npc_id", "")) if _near_npc.has_meta("npc_id") else ""
			var display_name: String = str(_near_npc.get_meta("display_name", "")) if _near_npc.has_meta("display_name") else ""
			if npc_id.is_empty() and not display_name.is_empty():
				npc_id = display_name
			if not npc_id.is_empty():
				var npc_3d = _near_npc as Node3D
				if npc_3d != null:
					var look_target = Vector3(global_position.x, npc_3d.global_position.y, global_position.z)
					npc_3d.look_at(look_target, Vector3.UP)
					npc_3d.rotate_y(PI)
				_open_chat_panel(npc_id, display_name)
		elif _near_clue != null:
			var clue_id: String = str(_near_clue.get_meta("clue_id", ""))
			if not clue_id.is_empty() and GameManager:
				GameManager.collect_clue_if_available(clue_id)

func _get_chat_panel():
	var nodes = get_tree().get_nodes_in_group("chat_panel")
	return nodes[0] if nodes.size() > 0 else null

func _is_chat_panel_open() -> bool:
	var cp = _get_chat_panel()
	if cp == null:
		return false
	if cp.has_method("is_npc_chat_open"):
		return cp.is_npc_chat_open()
	# Never use CanvasLayer.visible — logs showed it stayed true and blocked E/C forever
	return false

func _open_chat_panel(npc_id: String, npc_name: String) -> void:
	var cp = _get_chat_panel()
	if cp and cp.has_method("open_chat"):
		cp.open_chat(npc_id, npc_name, _near_npc)

func _close_chat_panel() -> void:
	var cp = _get_chat_panel()
	if cp and cp.has_method("close_chat"):
		cp.close_chat()

func _physics_process(delta: float) -> void:
	# C / clues: poll before intro return so one toggle per frame (clue panel no longer uses _input for C)
	if _use_game_bundle_mode() and GameManager and not get_tree().paused:
		if _bundle_key_just(KEY_C) or Input.is_action_just_pressed("inventory"):
			_flash_top_hud()
			for inv in get_tree().get_nodes_in_group("clue_inventory"):
				if inv.has_method("toggle_clues"):
					inv.toggle_clues()
					break
	# Freeze player until intro "Begin" is clicked (game_bundle mode)
	if _use_game_bundle_mode() and GameManager and not GameManager.intro_begun:
		if _bundle_key_just(KEY_E) or _bundle_key_just(KEY_SPACE) or Input.is_action_just_pressed("ui_accept"):
			GameManager.intro_begun = true
			Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
			var intro_nodes = get_tree().get_nodes_in_group("intro_screen")
			for n in intro_nodes:
				if n.visible:
					n.visible = false
					break
		var any_move := Input.get_vector("move_left", "move_right", "move_forward", "move_backward")
		if any_move.length_squared() > 0.01:
			GameManager.intro_begun = true
			Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
			var intro_nodes2 = get_tree().get_nodes_in_group("intro_screen")
			for n in intro_nodes2:
				if n.visible:
					n.visible = false
					break
		if not GameManager.intro_begun:
			velocity = Vector3.ZERO
			move_and_slide()
			return

	# Update closest NPC in range for E-to-talk
	var npcs = get_tree().get_nodes_in_group("npc")
	var best_dist := NPC_INTERACT_RANGE_M
	_near_npc = null
	for n in npcs:
		if n is Node3D:
			var np := (n as Node3D).global_position
			var d := Vector2(global_position.x - np.x, global_position.z - np.z).length()
			if d < best_dist:
				best_dist = d
				_near_npc = n
	# Update closest clue in range for E-to-examine
	best_dist = NPC_INTERACT_RANGE_M
	_near_clue = null
	var clues = get_tree().get_nodes_in_group("clue")
	for c in clues:
		if c is Node3D:
			var cp3 := (c as Node3D).global_position
			var d := Vector2(global_position.x - cp3.x, global_position.z - cp3.z).length()
			if d < best_dist:
				best_dist = d
				_near_clue = c

	# Update GameManager for interaction hint UI
	if GameManager and _use_game_bundle_mode():
		if _near_npc != null:
			var display_name := str(_near_npc.get_meta("display_name", "")) if _near_npc.has_meta("display_name") else "Someone"
			if display_name.is_empty():
				display_name = "Someone"
			GameManager.near_interactable = {"type": "npc", "name": display_name}
		elif _near_clue != null:
			GameManager.near_interactable = {"type": "clue"}
		else:
			GameManager.near_interactable = {}

	# Mac + exported builds: _unhandled_input often never hits the player — poll keys here
	if GameManager.intro_begun:
		_poll_game_bundle_keys()

	frame_count += 1
	if frame_count % 60 == 0:
		var input = Input.get_vector("move_left", "move_right", "move_forward", "move_backward")
		print("PLAYER LOOP: Input: %v | Vel: %v | Pos: %v | Mode: %s | OnFloor: %s" % [input, velocity, position, "FLY" if fly_mode else "WALK", is_on_floor()])

	var current_speed = SPEED
	if Input.is_action_pressed("sprint"):
		current_speed = BOOST_SPEED

	var input_dir := Input.get_vector("move_left", "move_right", "move_forward", "move_backward")

	if fly_mode:
		# Flying Movement (No Gravity, 6DOF) - TRUE NOCLIP
		var direction = Vector3.ZERO
		
		# Move relative to Camera look direction
		if camera == null:
			return
		
		var cam_basis = camera.global_transform.basis
		direction += -cam_basis.z * -input_dir.y # Forward/Back
		direction += cam_basis.x * input_dir.x # Left/Right
		
		if Input.is_action_pressed("fly_up"):
			direction.y += 1.0
		if Input.is_action_pressed("fly_down"):
			direction.y -= 1.0
		
		if direction.length() > 0:
			direction = direction.normalized()
			velocity = direction * current_speed
		else:
			velocity = velocity.move_toward(Vector3.ZERO, current_speed)
		
		# Noclip Movement (Bypass Physics) - NO move_and_slide!
		position += velocity * delta
			
	else:
		# Walking Movement (Standard FPS with Physics)
		if not is_on_floor():
			velocity.y -= gravity * delta

		if Input.is_action_pressed("jump") and is_on_floor():
			velocity.y = JUMP_VELOCITY

		var direction := (transform.basis * Vector3(input_dir.x, 0, input_dir.y)).normalized()
		
		if direction:
			velocity.x = direction.x * current_speed
			velocity.z = direction.z * current_speed
		else:
			velocity.x = move_toward(velocity.x, 0, current_speed)
			velocity.z = move_toward(velocity.z, 0, current_speed)

		# Physics movement - ONLY in walk mode
		move_and_slide()

	# Walked out of NPC talk range → end dialogue (no server bye; clues already saved per turn)
	if _use_game_bundle_mode() and _is_chat_panel_open() and GameManager:
		var dn: Node = GameManager.dialogue_npc
		if dn == null or not is_instance_valid(dn):
			_close_chat_panel()
		elif dn is Node3D:
			var dnp := (dn as Node3D).global_position
			var d_xz := Vector2(global_position.x - dnp.x, global_position.z - dnp.z).length()
			if d_xz > NPC_INTERACT_RANGE_M + 0.5:
				_close_chat_panel()

	# Sync 2D position for GameManager (game_bundle mode)
	if _use_game_bundle_mode() and GameManager:
		var ts: float = GameManager.tile_size_m
		if ts <= 0:
			ts = 1.8
		GameManager.update_player_position_2d(global_position.x / ts, global_position.z / ts)
	
		# Stuck Debugging and Auto-Unstuck (Only in Walk Mode)
		if get_slide_collision_count() > 0:
			if frame_count % 60 == 0:
				var collider = get_slide_collision(0).get_collider()
				print("PLAYER COLLISION: Hitting ", collider.name if collider else "null")
				
			# If trying to move but position isn't changing significantly
			if velocity.length() > 1.0 and (position - _last_frame_pos).length() < 0.01:
				_stuck_frames += 1
				if _stuck_frames > 60: # Stuck for 1 second
					print("DEBUG: Auto-unstuck triggered! Teleporting up.")
					position.y += 10.0
					_stuck_frames = 0
			else:
				_stuck_frames = 0
				
		_last_frame_pos = position
