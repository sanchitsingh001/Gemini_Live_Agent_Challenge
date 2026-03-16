extends Node3D

enum WeatherType {
	NONE,
	RAIN,
	SNOW,
	FOG
}

@export var weather_type: WeatherType = WeatherType.NONE
@export var intensity: float = 1.0  # 0.0 to 1.0

var rain_particles: GPUParticles3D
var snow_particles: GPUParticles3D
var world_bounds: AABB = AABB()  # World bounds for rain coverage
var world_center: Vector3 = Vector3.ZERO
var world_environment: WorldEnvironment
var environment: Environment
var day_night_cycle: Node  # Reference to day/night cycle for time-based fog

func _ready() -> void:
	# Find WorldEnvironment for weather effects
	world_environment = get_node_or_null("../WorldEnvironment")
	if world_environment != null:
		environment = world_environment.environment
		if environment == null:
			push_warning("WeatherManager: Environment resource not found!")
	
	# Find day/night cycle for time-based fog
	day_night_cycle = get_node_or_null("../DayNightCycle")
	
	# Calculate world bounds from all areas
	call_deferred("_calculate_world_bounds")
	
	# Create rain particle system
	rain_particles = _create_rain_particles()
	if rain_particles != null:
		add_child(rain_particles)
	else:
		push_error("WeatherManager: Failed to create rain particles!")
	
	# Create snow particle system
	snow_particles = _create_snow_particles()
	if snow_particles != null:
		add_child(snow_particles)
	else:
		push_error("WeatherManager: Failed to create snow particles!")
	
	# Apply initial weather (only if particles were created successfully)
	if rain_particles != null and snow_particles != null:
		_update_weather()

func _calculate_world_bounds() -> void:
	# Find all area nodes to calculate world bounds
	var areas = get_tree().get_nodes_in_group("generated_areas")
	if areas.is_empty():
		# Fallback: use a large default area
		world_bounds = AABB(Vector3(-200, 0, -200), Vector3(400, 0, 400))
		world_center = Vector3(0, 0, 0)
		print("WeatherManager: Using default world bounds")
		return
	
	# Calculate bounding box from all areas
	var min_x = INF
	var max_x = -INF
	var min_z = INF
	var max_z = -INF
	
	for area in areas:
		if area is Node3D:
			var area_node = area as Node3D
			var global_pos = area_node.global_position
			# Get area size from its children (ground plane)
			for child in area_node.get_children():
				if child is MeshInstance3D:
					var mesh_inst = child as MeshInstance3D
					if mesh_inst.mesh is PlaneMesh:
						var plane = mesh_inst.mesh as PlaneMesh
						var area_size = plane.size
						var area_pos = global_pos + mesh_inst.position
						
						min_x = min(min_x, area_pos.x - area_size.x / 2.0)
						max_x = max(max_x, area_pos.x + area_size.x / 2.0)
						min_z = min(min_z, area_pos.z - area_size.y / 2.0)
						max_z = max(max_z, area_pos.z + area_size.y / 2.0)
	
	if min_x == INF:
		# Fallback if no areas found
		world_bounds = AABB(Vector3(-200, 0, -200), Vector3(400, 0, 400))
		world_center = Vector3(0, 0, 0)
	else:
		world_center = Vector3((min_x + max_x) / 2.0, 0, (min_z + max_z) / 2.0)
		var world_size = Vector3(max_x - min_x, 200, max_z - min_z)  # Height of 200 for sky
		world_bounds = AABB(world_center - world_size / 2.0, world_size)
	
	print("WeatherManager: World bounds calculated: ", world_bounds)
	print("WeatherManager: World center: ", world_center)
	
	# Update particle positions
	_update_particle_positions()


func _update_particle_positions() -> void:
	# Position rain and snow particles at the center of the world, high in the sky
	# Rain should cover the entire world area
	if world_bounds.size != Vector3.ZERO:
		# Position at world center, very high in the sky
		global_position = Vector3(world_center.x, 200.0, world_center.z)  # 200 units high
		
		# Update emission box to cover entire world with generous margin
		var world_size = world_bounds.size
		# Use actual world size with 100% margin on all sides to ensure full coverage
		var emission_width = max(world_size.x, 500) * 2.0  # Double the size
		var emission_depth = max(world_size.z, 500) * 2.0  # Double the size
		var emission_height = 150.0  # Very tall emission box in the sky
		
		var rain_material = rain_particles.process_material as ParticleProcessMaterial
		if rain_material != null:
			# Make emission box cover entire world area
			# Note: emission_box_extents is half-extents (radius from center)
			# So for a 1000 unit wide box, we need extents of 500
			# Use MASSIVE extents to ensure full coverage - make it even bigger
			var extents_x = max(emission_width / 2.0, 2000)  # At least 4000 units wide
			var extents_z = max(emission_depth / 2.0, 2000)  # At least 4000 units deep
			var extents_y = max(emission_height / 2.0, 100)  # At least 200 units tall
			rain_material.emission_box_extents = Vector3(extents_x, extents_y, extents_z)
			# Ensure emission shape is BOX
			rain_material.emission_shape = 2  # BOX
			print("Rain emission box extents: ", rain_material.emission_box_extents)
			print("Rain emission box full size: ", extents_x * 2, " x ", extents_y * 2, " x ", extents_z * 2)
			print("Rain global position: ", global_position)
		
		var snow_material = snow_particles.process_material as ParticleProcessMaterial
		if snow_material != null:
			snow_material.emission_box_extents = Vector3(emission_width / 2.0, emission_height / 2.0, emission_depth / 2.0)
		
		# Update visibility AABB to cover entire area
		var visibility_size = Vector3(emission_width, 300, emission_depth)
		rain_particles.visibility_aabb = AABB(
			Vector3(-emission_width / 2.0, -50, -emission_depth / 2.0),
			visibility_size
		)
		snow_particles.visibility_aabb = rain_particles.visibility_aabb
	else:
		# Fallback: use large default area
		global_position = Vector3(0, 200, 0)
		var rain_material = rain_particles.process_material as ParticleProcessMaterial
		if rain_material != null:
			rain_material.emission_box_extents = Vector3(500, 75, 500)  # Large default area
		var snow_material = snow_particles.process_material as ParticleProcessMaterial
		if snow_material != null:
			snow_material.emission_box_extents = Vector3(500, 75, 500)
		
		# Large visibility AABB for fallback
		rain_particles.visibility_aabb = AABB(Vector3(-500, -50, -500), Vector3(1000, 300, 1000))
		snow_particles.visibility_aabb = rain_particles.visibility_aabb

func _create_rain_particles() -> GPUParticles3D:
	var particles = GPUParticles3D.new()
	particles.name = "RainParticles"
	
	# Create particle process material
	var material = ParticleProcessMaterial.new()
	material.direction = Vector3(0, -1, 0)
	material.initial_velocity_min = 10.0
	material.initial_velocity_max = 15.0
	material.gravity = Vector3(0, -20.0, 0)  # Stronger gravity for faster, more realistic rain
	material.scale_min = 0.2
	material.scale_max = 0.4
	
	# Emission settings
	particles.amount = 30000  # Many particles for full world coverage
	particles.lifetime = 8.0  # Long lifetime so particles can fall from sky to ground
	particles.emitting = false
	# Visibility AABB will be set in _update_particle_positions() based on world size
	particles.visibility_aabb = AABB(Vector3(-1000, -100, -1000), Vector3(2000, 500, 2000))  # Large default
	
	# Emission shape - large box above
	# In Godot 4.5, use integer value: 0=POINT, 1=SPHERE, 2=BOX, 3=POINTS, 4=DIRECTED_POINTS, 5=RING
	material.emission_shape = 2  # BOX
	# Emission box will be set based on world bounds in _update_particle_positions()
	# Set to a MASSIVE default area to ensure full coverage - this should cover the entire map
	material.emission_box_extents = Vector3(2000, 150, 2000)  # MASSIVE default (4000x300x4000 units)
	print("Created rain particles with MASSIVE default emission box: ", material.emission_box_extents)
	print("  - This creates a box 4000 units wide x 300 tall x 4000 deep")
	# Spread particles evenly across the entire emission box
	material.direction = Vector3(0, -1, 0)
	material.spread = 0.0  # No angular spread - straight down
	
	# Draw pass - thin lines for rain streaks (realistic rain appearance)
	var quad_mesh = QuadMesh.new()
	quad_mesh.size = Vector2(0.03, 4.0)  # Very thin and long for rain streaks
	particles.draw_pass_1 = quad_mesh
	
	# Material for rain drops - subtle and semi-transparent
	var rain_material = StandardMaterial3D.new()
	rain_material.albedo_color = Color(0.85, 0.88, 0.95, 0.4)  # Light blue-gray, more transparent
	rain_material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	rain_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	rain_material.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES  # Face camera but maintain direction
	rain_material.no_depth_test = false  # Proper depth testing
	particles.material_override = rain_material
	
	particles.process_material = material
	
	return particles

func _create_snow_particles() -> GPUParticles3D:
	var particles = GPUParticles3D.new()
	particles.name = "SnowParticles"
	
	# Create particle process material
	var material = ParticleProcessMaterial.new()
	material.direction = Vector3(0, -1, 0)
	material.initial_velocity_min = 0.5
	material.initial_velocity_max = 2.0
	material.gravity = Vector3(0, -1.0, 0)  # Lighter gravity for snow
	
	# Add wind drift
	material.angular_velocity_min = -10.0
	material.angular_velocity_max = 10.0
	
	material.scale_min = 0.05
	material.scale_max = 0.1
	
	# Emission settings
	particles.amount = 5000  # More particles for full world coverage
	particles.lifetime = 15.0  # Long lifetime for slow-falling snow
	particles.emitting = false
	
	# Emission shape - large box above
	# In Godot 4.5, use integer value: 0=POINT, 1=SPHERE, 2=BOX, 3=POINTS, 4=DIRECTED_POINTS, 5=RING
	material.emission_shape = 2  # BOX
	# Emission box will be set based on world bounds in _update_particle_positions()
	material.emission_box_extents = Vector3(200, 50, 200)  # Default large area, will be updated
	
	# Draw pass - quad for snowflakes
	var quad_mesh = QuadMesh.new()
	quad_mesh.size = Vector2(0.2, 0.2)
	particles.draw_pass_1 = quad_mesh
	
	# Material for snowflakes
	var snow_material = StandardMaterial3D.new()
	snow_material.albedo_color = Color(1.0, 1.0, 1.0, 0.9)
	snow_material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	snow_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	particles.material_override = snow_material
	
	particles.process_material = material
	
	return particles

func set_weather(type: int, weather_intensity: float = 1.0) -> void:
	# Convert int to WeatherType enum
	weather_type = type as WeatherType
	intensity = clamp(weather_intensity, 0.0, 1.0)
	_update_weather()

func _update_weather() -> void:
	# Check if particles are valid before using them
	if rain_particles == null or snow_particles == null:
		push_error("WeatherManager: Particles not initialized!")
		return
	
	# Disable all particles first
	rain_particles.emitting = false
	snow_particles.emitting = false
	
	# IMPORTANT: Update particle positions and emission box BEFORE enabling particles
	# This ensures the emission box is set correctly before particles start spawning
	if world_bounds.size != Vector3.ZERO:
		_update_particle_positions()
	else:
		# Use fallback large area if world bounds not calculated yet
		global_position = Vector3(0, 200, 0)
		var rain_material = rain_particles.process_material as ParticleProcessMaterial
		if rain_material != null:
			rain_material.emission_box_extents = Vector3(1000, 100, 1000)  # Very large default (2000x200x2000)
			rain_material.emission_shape = 2  # BOX
			print("Using fallback rain emission box: ", rain_material.emission_box_extents)
		var snow_material = snow_particles.process_material as ParticleProcessMaterial
		if snow_material != null:
			snow_material.emission_box_extents = Vector3(1000, 100, 1000)
			snow_material.emission_shape = 2  # BOX
	
	# Adjust emission based on intensity
	var base_rain_amount = 50000  # Increased for better coverage
	var base_snow_amount = 10000
	
	match weather_type:
		WeatherType.RAIN:
			# CRITICAL: Set emission box FIRST, then amount, then restart
			var rain_material = rain_particles.process_material as ParticleProcessMaterial
			if rain_material != null:
				# Force a VERY large emission box to ensure full coverage
				if world_bounds.size != Vector3.ZERO:
					_update_particle_positions()
				else:
					# Use massive default box
					rain_material.emission_box_extents = Vector3(2000, 150, 2000)  # 4000x300x4000 units!
					rain_material.emission_shape = 2  # BOX
					global_position = Vector3(0, 200, 0)
					print("Using MASSIVE fallback emission box: ", rain_material.emission_box_extents)
				
				# Verify emission box is set correctly
				print("FINAL Rain emission box extents: ", rain_material.emission_box_extents)
				print("FINAL Rain emission shape: ", rain_material.emission_shape)
				print("FINAL Rain global position: ", global_position)
			
			# Set amount AFTER emission box
			rain_particles.amount = int(base_rain_amount * intensity)
			
			# Stop, clear, and restart particles
			rain_particles.emitting = false
			rain_particles.restart()  # Clear all existing particles
			# Small delay to ensure restart completes
			call_deferred("_enable_rain_emission")
			snow_particles.emitting = false
			_apply_rainy_environment()
			print("Weather: Rain enabled with intensity: ", intensity)
			print("  - Rain particles amount: ", rain_particles.amount)
		WeatherType.SNOW:
			snow_particles.amount = int(base_snow_amount * intensity)
			if world_bounds.size != Vector3.ZERO:
				_update_particle_positions()
			snow_particles.restart()
			snow_particles.emitting = true
			rain_particles.emitting = false
			_apply_snowy_environment()
			print("Weather: Snow enabled with intensity: ", intensity)
		WeatherType.FOG:
			rain_particles.emitting = false
			snow_particles.emitting = false
			_apply_foggy_environment(intensity)
			print("Weather: Fog enabled with intensity: ", intensity)
		WeatherType.NONE:
			rain_particles.emitting = false
			snow_particles.emitting = false
			_apply_clear_environment()
			print("Weather: Disabled")

func _apply_rainy_environment() -> void:
	if environment == null:
		return
	
	# Darken the sky and add fog for cloudy/rainy weather
	var sky = environment.sky
	if sky != null:
		var sky_material = sky.sky_material
		if sky_material is ProceduralSkyMaterial:
			var proc_sky = sky_material as ProceduralSkyMaterial
			# Dark, cloudy sky colors
			proc_sky.sky_top_color = Color(0.3, 0.35, 0.4)  # Dark gray-blue
			proc_sky.sky_horizon_color = Color(0.4, 0.45, 0.5)  # Slightly lighter gray
			proc_sky.ground_bottom_color = Color(0.2, 0.25, 0.3)
			proc_sky.ground_horizon_color = Color(0.3, 0.35, 0.4)
	
	# Reduce ambient light for cloudy weather
	environment.ambient_light_color = Color(0.4, 0.45, 0.5)  # Cool, dim light
	environment.ambient_light_energy = 0.3
	
	# Add fog for atmosphere
	environment.fog_enabled = true
	environment.fog_light_color = Color(0.5, 0.55, 0.6)
	environment.fog_sun_scatter = 0.3
	environment.fog_density = 0.01
	environment.fog_aerial_perspective = 0.5

func _apply_snowy_environment() -> void:
	if environment == null:
		return
	
	# Bright, overcast sky for snow
	var sky = environment.sky
	if sky != null:
		var sky_material = sky.sky_material
		if sky_material is ProceduralSkyMaterial:
			var proc_sky = sky_material as ProceduralSkyMaterial
			# Bright, overcast sky
			proc_sky.sky_top_color = Color(0.6, 0.65, 0.7)  # Light gray
			proc_sky.sky_horizon_color = Color(0.7, 0.75, 0.8)  # Very light gray
			proc_sky.ground_bottom_color = Color(0.8, 0.85, 0.9)
			proc_sky.ground_horizon_color = Color(0.7, 0.75, 0.8)
	
	# Bright ambient light for snow
	environment.ambient_light_color = Color(0.7, 0.75, 0.8)
	environment.ambient_light_energy = 0.5
	
	# Light fog for snow
	environment.fog_enabled = true
	environment.fog_light_color = Color(0.9, 0.9, 0.95)
	environment.fog_sun_scatter = 0.5
	environment.fog_density = 0.005
	environment.fog_aerial_perspective = 0.3

func _apply_foggy_environment(fog_intensity: float) -> void:
	if environment == null:
		return
	
	# Get current time of day from day/night cycle
	var time_of_day = 12.0  # Default to noon
	if day_night_cycle != null:
		time_of_day = day_night_cycle.time_of_day
	
	# Calculate if it's day or night (6 AM to 6 PM = day)
	var is_day = time_of_day >= 6.0 and time_of_day < 18.0
	var normalized_time = time_of_day / 24.0
	var sun_height = sin((normalized_time - 0.5) * TAU + PI / 2.0)
	sun_height = max(0.0, sun_height)  # 0 to 1
	
	# Enable fog
	environment.fog_enabled = true
	
	# Fog density based on intensity (0.01 to 0.05)
	environment.fog_density = lerp(0.01, 0.05, fog_intensity)
	
	# Fog color changes based on day/night
	if is_day:
		# Day fog: lighter, grayish-white
		var day_fog_color = Color(0.7, 0.75, 0.8)  # Light gray
		environment.fog_light_color = day_fog_color.lerp(Color(0.5, 0.55, 0.6), 1.0 - sun_height)
		environment.fog_sun_scatter = lerp(0.3, 0.7, sun_height)  # More scatter during bright day
	else:
		# Night fog: darker, bluish-gray
		var night_fog_color = Color(0.15, 0.18, 0.22)  # Dark blue-gray
		environment.fog_light_color = night_fog_color
		environment.fog_sun_scatter = 0.1  # Less scatter at night
	
	# Aerial perspective for depth
	environment.fog_aerial_perspective = lerp(0.3, 0.7, fog_intensity)
	
	# Fog height (0 = ground level fog, higher = fog in sky)
	environment.fog_height = 0.0  # Ground-level fog
	environment.fog_height_density = 0.5  # How quickly fog fades with height
	
	# Update sky to be more overcast
	var sky = environment.sky
	if sky != null:
		var sky_material = sky.sky_material
		if sky_material is ProceduralSkyMaterial:
			var proc_sky = sky_material as ProceduralSkyMaterial
			if is_day:
				# Overcast day sky
				proc_sky.sky_top_color = Color(0.4, 0.45, 0.5).lerp(Color(0.2, 0.25, 0.3), 1.0 - sun_height)
				proc_sky.sky_horizon_color = Color(0.5, 0.55, 0.6).lerp(Color(0.3, 0.35, 0.4), 1.0 - sun_height)
			else:
				# Dark foggy night sky
				proc_sky.sky_top_color = Color(0.08, 0.1, 0.12)
				proc_sky.sky_horizon_color = Color(0.12, 0.15, 0.18)
	
	# Reduce ambient light for foggy conditions
	if is_day:
		environment.ambient_light_color = Color(0.5, 0.55, 0.6).lerp(Color(0.3, 0.35, 0.4), 1.0 - sun_height)
		environment.ambient_light_energy = lerp(0.2, 0.4, sun_height)
	else:
		environment.ambient_light_color = Color(0.2, 0.25, 0.3)
		environment.ambient_light_energy = 0.15

func _enable_rain_emission() -> void:
	# Enable rain emission after restart completes
	if rain_particles != null:
		rain_particles.emitting = true

func _process(_delta: float) -> void:
	# Update fog color based on time of day if fog is active
	# This ensures fog adapts to day/night cycle in real-time
	if weather_type == WeatherType.FOG and environment != null:
		_apply_foggy_environment(intensity)

func _apply_clear_environment() -> void:
	if environment == null:
		return
	
	# Reset to clear sky (day/night cycle will handle this)
	# Just disable fog
	environment.fog_enabled = false
