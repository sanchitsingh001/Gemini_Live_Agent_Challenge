extends Control

signal weather_changed(type: int, intensity: float)
signal time_changed(hours: float)
signal cycle_enabled_changed(enabled: bool)
signal cycle_speed_changed(speed: float)

@onready var weather_option: OptionButton = $Panel/VBoxContainer/WeatherContainer/WeatherOption
@onready var intensity_slider: HSlider = $Panel/VBoxContainer/WeatherContainer/IntensitySlider
@onready var intensity_label: Label = $Panel/VBoxContainer/WeatherContainer/IntensityLabel
@onready var time_slider: HSlider = $Panel/VBoxContainer/TimeContainer/TimeSlider
@onready var time_label: Label = $Panel/VBoxContainer/TimeContainer/TimeLabel
@onready var cycle_enabled_check: CheckBox = $Panel/VBoxContainer/TimeContainer/CycleEnabledCheck
@onready var cycle_speed_slider: HSlider = $Panel/VBoxContainer/TimeContainer/CycleSpeedSlider
@onready var cycle_speed_label: Label = $Panel/VBoxContainer/TimeContainer/CycleSpeedLabel
@onready var close_button: Button = $Panel/VBoxContainer/CloseButton

const SETTINGS_PATH = "user://settings.cfg"
const SETTINGS_SECTION = "settings"

var weather_manager: Node
var day_night_cycle: Node

func _ready() -> void:
	# Find weather manager and day/night cycle
	# SettingsMenu is at: CanvasLayer/SettingsMenu
	# WeatherManager is at: World/WeatherManager
	# So we need to go up to CanvasLayer, then to World, then to WeatherManager
	weather_manager = get_node_or_null("../../WeatherManager")
	if weather_manager == null:
		# Try alternative path
		weather_manager = get_tree().get_first_node_in_group("weather_manager")
		if weather_manager == null:
			push_warning("SettingsMenu: Could not find WeatherManager")
	
	day_night_cycle = get_node_or_null("../../DayNightCycle")
	if day_night_cycle == null:
		# Try alternative path
		day_night_cycle = get_tree().get_first_node_in_group("day_night_cycle")
		if day_night_cycle == null:
			push_warning("SettingsMenu: Could not find DayNightCycle")
	
	# Setup weather options
	weather_option.add_item("None", 0)
	weather_option.add_item("Rain", 1)
	weather_option.add_item("Snow", 2)
	weather_option.add_item("Fog", 3)
	
	# Setup intensity slider (0-100%)
	intensity_slider.min_value = 0.0
	intensity_slider.max_value = 100.0
	intensity_slider.value = 50.0
	
	# Setup time slider (0-24 hours)
	time_slider.min_value = 0.0
	time_slider.max_value = 24.0
	time_slider.step = 0.1
	time_slider.value = 12.0
	
	# Setup cycle speed slider (0-120x speed)
	cycle_speed_slider.min_value = 0.0
	cycle_speed_slider.max_value = 120.0
	cycle_speed_slider.step = 1.0
	cycle_speed_slider.value = 60.0
	
	# Connect signals
	weather_option.item_selected.connect(_on_weather_selected)
	intensity_slider.value_changed.connect(_on_intensity_changed)
	time_slider.value_changed.connect(_on_time_changed)
	cycle_enabled_check.toggled.connect(_on_cycle_enabled_toggled)
	cycle_speed_slider.value_changed.connect(_on_cycle_speed_changed)
	close_button.pressed.connect(_on_close_button_pressed)
	
	# Load saved settings
	load_settings()
	
	add_to_group("settings_menu")
	visible = false
	process_mode = Node.PROCESS_MODE_ALWAYS  # Always process input, even when paused
	set_process_input(true)
	set_process_unhandled_input(true)  # fallback if another node ate _input

func _settings_esc_ok() -> bool:
	for n in get_tree().get_nodes_in_group("chat_panel"):
		if n.has_method("is_npc_chat_open") and n.is_npc_chat_open():
			return false
	return true

func _input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_cancel") and _settings_esc_ok():
		toggle_menu()
		get_viewport().set_input_as_handled()

func _unhandled_input(event: InputEvent) -> void:
	if get_viewport().is_input_handled():
		return
	if event.is_action_pressed("ui_cancel") and _settings_esc_ok():
		toggle_menu()
		get_viewport().set_input_as_handled()

func toggle_menu() -> void:
	visible = not visible
	if visible:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
		get_tree().paused = true
		# Make sure menu can receive input when paused
		process_mode = Node.PROCESS_MODE_ALWAYS
	else:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		get_tree().paused = false

func _on_weather_selected(index: int) -> void:
	var intensity = intensity_slider.value / 100.0
	_apply_weather(index, intensity)
	save_settings()

func _on_intensity_changed(value: float) -> void:
	intensity_label.text = "Intensity: %d%%" % int(value)
	var weather_type = weather_option.get_selected_id()
	_apply_weather(weather_type, value / 100.0)
	save_settings()

func _on_time_changed(value: float) -> void:
	var hours = int(value)
	var minutes = int((value - hours) * 60)
	time_label.text = "Time: %02d:%02d" % [hours, minutes]
	_apply_time(value)
	save_settings()

func _on_cycle_enabled_toggled(enabled: bool) -> void:
	_apply_cycle_enabled(enabled)
	save_settings()

func _on_cycle_speed_changed(value: float) -> void:
	cycle_speed_label.text = "Speed: %.1fx" % value
	_apply_cycle_speed(value)
	save_settings()

func _on_close_button_pressed() -> void:
	toggle_menu()

func load_settings() -> void:
	var config = ConfigFile.new()
	var err = config.load(SETTINGS_PATH)
	
	if err != OK:
		# No saved settings, use defaults
		return
	
	# Load weather settings
	var weather_type = config.get_value(SETTINGS_SECTION, "weather_type", 0)
	var intensity = config.get_value(SETTINGS_SECTION, "weather_intensity", 0.5)
	weather_option.selected = weather_type
	intensity_slider.value = intensity * 100.0
	_on_intensity_changed(intensity_slider.value)
	_on_weather_selected(weather_type)
	
	# Load time settings
	var time_of_day = config.get_value(SETTINGS_SECTION, "time_of_day", 12.0)
	var cycle_enabled = config.get_value(SETTINGS_SECTION, "cycle_enabled", true)
	var cycle_speed = config.get_value(SETTINGS_SECTION, "cycle_speed", 60.0)
	
	time_slider.value = time_of_day
	cycle_enabled_check.button_pressed = cycle_enabled
	cycle_speed_slider.value = cycle_speed
	
	_on_time_changed(time_of_day)
	_on_cycle_enabled_toggled(cycle_enabled)
	_on_cycle_speed_changed(cycle_speed)

func save_settings() -> void:
	var config = ConfigFile.new()
	
	# Save weather settings
	config.set_value(SETTINGS_SECTION, "weather_type", weather_option.get_selected_id())
	config.set_value(SETTINGS_SECTION, "weather_intensity", intensity_slider.value / 100.0)
	
	# Save time settings
	config.set_value(SETTINGS_SECTION, "time_of_day", time_slider.value)
	config.set_value(SETTINGS_SECTION, "cycle_enabled", cycle_enabled_check.button_pressed)
	config.set_value(SETTINGS_SECTION, "cycle_speed", cycle_speed_slider.value)
	
	config.save(SETTINGS_PATH)

func _apply_weather(type: int, intensity: float) -> void:
	if weather_manager != null:
		weather_manager.set_weather(type, intensity)
	weather_changed.emit(type, intensity)

func _apply_time(hours: float) -> void:
	if day_night_cycle != null:
		day_night_cycle.set_time_of_day(hours)
	time_changed.emit(hours)

func _apply_cycle_enabled(enabled: bool) -> void:
	if day_night_cycle != null:
		day_night_cycle.set_cycle_enabled(enabled)
	cycle_enabled_changed.emit(enabled)

func _apply_cycle_speed(speed: float) -> void:
	if day_night_cycle != null:
		day_night_cycle.set_cycle_speed(speed)
	cycle_speed_changed.emit(speed)
