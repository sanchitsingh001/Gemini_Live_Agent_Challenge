extends Node3D

signal time_changed(hours: float)

@export var time_of_day: float = 12.0  # 0-24 hours (12 = noon)
@export var cycle_enabled: bool = true
@export var cycle_speed: float = 1.0  # Multiplier for time progression (1.0 = real-time, 60.0 = 1 hour per minute)

var directional_light: DirectionalLight3D
var world_environment: WorldEnvironment
var environment: Environment
var weather_manager: Node  # Reference to weather manager to check current weather

# Time progression
const SECONDS_PER_HOUR = 3600.0
var time_accumulator: float = 0.0

func _ready() -> void:
	# Find DirectionalLight3D
	directional_light = get_node_or_null("../DirectionalLight3D")
	if directional_light == null:
		push_error("DayNightCycle: DirectionalLight3D not found!")
	
	# Find WorldEnvironment
	world_environment = get_node_or_null("../WorldEnvironment")
	if world_environment == null:
		push_error("DayNightCycle: WorldEnvironment not found!")
		return
	
	environment = world_environment.environment
	if environment == null:
		push_error("DayNightCycle: Environment resource not found!")
		return
	
	# Find weather manager
	weather_manager = get_node_or_null("../WeatherManager")
	
	# Initialize time
	_update_lighting()

func _process(delta: float) -> void:
	if not cycle_enabled:
		return
	
	# Advance time
	var time_delta_hours = (delta * cycle_speed) / SECONDS_PER_HOUR
	time_accumulator += time_delta_hours
	
	# Update time of day (wrap around 24 hours)
	time_of_day = fmod(time_of_day + time_delta_hours, 24.0)
	
	_update_lighting()
	time_changed.emit(time_of_day)

func set_time_of_day(hours: float) -> void:
	time_of_day = fmod(hours, 24.0)
	time_accumulator = 0.0
	_update_lighting()
	time_changed.emit(time_of_day)

func set_cycle_enabled(enabled: bool) -> void:
	cycle_enabled = enabled

func set_cycle_speed(speed: float) -> void:
	cycle_speed = max(0.0, speed)

func _update_lighting() -> void:
	if directional_light == null or environment == null:
		return
	
	# Calculate sun angle (0 = midnight, 6 = sunrise, 12 = noon, 18 = sunset, 24 = midnight)
	# Sun rotates around X axis (east to west)
	# At noon (12:00), sun is directly overhead (rotation.x = 0)
	# At midnight (0:00), sun is below horizon (rotation.x = 180)
	
	var normalized_time = time_of_day / 24.0  # 0.0 to 1.0
	var sun_angle = (normalized_time - 0.5) * TAU  # -PI to PI
	
	# Rotate sun around X axis
	# At noon: rotation.x = 0 (sun overhead)
	# At midnight: rotation.x = PI (sun below)
	var sun_rotation_x = -sun_angle
	
	# Also rotate around Y axis for east-west movement
	var sun_rotation_y = normalized_time * TAU - PI / 2.0
	
	# Update directional light rotation
	directional_light.rotation.x = sun_rotation_x
	directional_light.rotation.y = sun_rotation_y
	
	# Calculate sun position factor (0 = below horizon, 1 = overhead)
	var sun_height = sin(sun_angle + PI / 2.0)  # 0 to 1
	sun_height = max(0.0, sun_height)  # Clamp to 0-1
	
	# Update light color based on time of day
	if sun_height > 0.1:
		# Day time - warm sunlight (slightly brighter overall)
		var day_factor = clamp((sun_height - 0.1) / 0.9, 0.0, 1.0)
		var warm_color = Color(1.0, 0.97, 0.9)
		var cool_color = Color(0.85, 0.9, 1.0)
		directional_light.light_color = warm_color.lerp(cool_color, 1.0 - day_factor)
		# Push direct light a bit higher so mid-day feels brighter and shadows lift
		directional_light.light_energy = 1.6 * day_factor + 0.2
	else:
		# Night time - slightly brighter moonlight so silhouettes are visible
		directional_light.light_color = Color(0.75, 0.8, 1.0)
		directional_light.light_energy = 0.35
	
	# Update environment ambient light (raise floor and ceiling for a more ambient feel)
	var ambient_brightness = lerp(0.25, 0.9, sun_height)
	environment.ambient_light_energy = ambient_brightness
	environment.ambient_light_color = Color(0.8, 0.85, 1.0).lerp(Color(0.3, 0.3, 0.4), 1.0 - sun_height)
	
	# Update sky colors if using ProceduralSkyMaterial
	# Only update if weather manager is not controlling the sky (no active weather)
	var has_active_weather = false
	if weather_manager != null:
		has_active_weather = weather_manager.weather_type != weather_manager.WeatherType.NONE
	
	if not has_active_weather:
		var sky = environment.sky
		if sky != null:
			var sky_material = sky.sky_material
			if sky_material is ProceduralSkyMaterial:
				var proc_sky = sky_material as ProceduralSkyMaterial
				# Sky color based on sun height
				if sun_height > 0.1:
					# Day sky
					proc_sky.sky_top_color = Color(0.3, 0.5, 0.8).lerp(Color(0.1, 0.1, 0.2), 1.0 - sun_height)
					proc_sky.sky_horizon_color = Color(0.7, 0.8, 0.9).lerp(Color(0.2, 0.2, 0.3), 1.0 - sun_height)
				else:
					# Night sky
					proc_sky.sky_top_color = Color(0.05, 0.05, 0.1)
					proc_sky.sky_horizon_color = Color(0.1, 0.1, 0.15)
