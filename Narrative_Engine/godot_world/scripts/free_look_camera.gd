extends Camera3D

@export var sensitivity := 0.25
@export var speed := 20.0
@export var sprint_multiplier := 3.0

var _mouse_captured := false

func _ready() -> void:
	# Start with mouse captured for immediate control
	_capture_mouse()

func _input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_RIGHT and event.pressed:
			_capture_mouse()
		elif event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
			# Optional: click to interact, but for now just ensure capture if needed
			if not _mouse_captured:
				_capture_mouse()
	
	if event is InputEventKey:
		if event.pressed and event.keycode == KEY_ESCAPE:
			_release_mouse()

	if _mouse_captured and event is InputEventMouseMotion:
		rotate_y(deg_to_rad(-event.relative.x * sensitivity))
		rotate_object_local(Vector3.RIGHT, deg_to_rad(-event.relative.y * sensitivity))

func _process(delta: float) -> void:
	if not _mouse_captured:
		return

	var input_dir := Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
	var direction := (transform.basis * Vector3(input_dir.x, 0, input_dir.y)).normalized()
	
	var current_speed := speed
	if Input.is_key_pressed(KEY_SHIFT):
		current_speed *= sprint_multiplier
		
	if direction:
		position += direction * current_speed * delta
		
	# Vertical movement with Q/E
	if Input.is_key_pressed(KEY_E):
		position.y += current_speed * delta
	if Input.is_key_pressed(KEY_Q):
		position.y -= current_speed * delta

func _capture_mouse() -> void:
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	_mouse_captured = true

func _release_mouse() -> void:
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	_mouse_captured = false
