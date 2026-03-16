extends RefCounted
class_name NoiseTextureGenerator

# Utility class to generate noise textures for shaders
# This can be called once at startup to create a noise texture if none exists

static func generate_noise_texture(size: int = 256) -> ImageTexture:
	"""
	Generates a simple noise texture using FastNoiseLite.
	This is a fallback if no noise texture file is provided.
	"""
	var img = Image.create(size, size, false, Image.FORMAT_RGB8)
	
	# Create noise generator
	var noise = FastNoiseLite.new()
	noise.seed = randi()
	noise.frequency = 0.1
	noise.noise_type = FastNoiseLite.TYPE_PERLIN
	
	# Generate noise values
	for x in range(size):
		for y in range(size):
			var value = noise.get_noise_2d(x, y)
			# Normalize from -1..1 to 0..1
			value = (value + 1.0) / 2.0
			img.set_pixel(x, y, Color(value, value, value))
	
	# Create texture
	var texture = ImageTexture.new()
	texture.set_image(img)
	return texture
