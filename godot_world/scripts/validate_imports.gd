extends SceneTree

# Validation script to verify all GLB files are properly imported
# Run headlessly: godot4 --headless --path godot_world --script res://scripts/validate_imports.gd
# This tests ResourceLoader.load() for each model path, which is what Web runtime will do

const ENTITY_MODELS_PATH := "res://generated/entity_models.json"

func _initialize() -> void:
	print("==========================================")
	print("Validating GLB Imports")
	print("==========================================")
	print("")
	
	# Load entity models mapping
	var entity_models_file = FileAccess.open(ENTITY_MODELS_PATH, FileAccess.READ)
	if entity_models_file == null:
		print("ERROR: Failed to open entity_models.json at: " + ENTITY_MODELS_PATH)
		quit(1)
		return
	
	var json_text = entity_models_file.get_as_text()
	entity_models_file.close()
	
	var json = JSON.new()
	var parse_result = json.parse(json_text)
	if parse_result != OK:
		print("ERROR: Failed to parse entity_models.json: " + json.get_error_message())
		quit(1)
		return
	
	var entity_models = json.data
	if typeof(entity_models) != TYPE_DICTIONARY:
		print("ERROR: entity_models.json does not contain a dictionary")
		quit(1)
		return
	
	# Collect unique model paths
	var model_paths := {}
	for entity_id in entity_models.keys():
		var path = entity_models[entity_id]
		if typeof(path) == TYPE_STRING and path != "":
			model_paths[path] = true
	
	print("Found %d unique model paths to validate" % model_paths.size())
	print("")
	
	# Validate each path
	var failed_paths := []
	var validated_count := 0
	
	for path in model_paths.keys():
		print("Validating: %s" % path)
		
		# Try to load using ResourceLoader (this is what Web runtime will do)
		var resource = ResourceLoader.load(path)
		
		if resource == null:
			print("  ERROR: ResourceLoader.load() returned null")
			failed_paths.append(path)
			continue
		
		if not resource is PackedScene:
			print("  ERROR: Loaded resource is not a PackedScene (type: %s)" % resource.get_class())
			failed_paths.append(path)
			continue
		
		# Try to instantiate to ensure it's valid
		var scene = resource as PackedScene
		var instance = scene.instantiate()
		if instance == null:
			print("  ERROR: Failed to instantiate PackedScene")
			failed_paths.append(path)
			continue
		
		instance.queue_free()
		print("  ✓ Valid (PackedScene)")
		validated_count += 1
	
	print("")
	print("==========================================")
	print("Validation Results")
	print("==========================================")
	print("Validated: %d" % validated_count)
	print("Failed: %d" % failed_paths.size())
	
	if failed_paths.size() > 0:
		print("")
		print("Failed paths:")
		for path in failed_paths:
			print("  - %s" % path)
		print("")
		print("ERROR: Some GLB files are not properly imported!")
		print("Run: godot --headless --path godot_world --import")
		quit(1)
	else:
		print("")
		print("✓ All GLB files are properly imported!")
		quit(0)
