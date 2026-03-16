shader_type spatial;
render_mode cull_disabled;

uniform vec3 color : source_color;
uniform vec3 color2 : source_color;
uniform sampler2D noise;
uniform float noiseScale = 20.0;

varying vec3 worldPos;

void vertex() {
	worldPos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	vec3 noiseLevel = texture(noise, worldPos.xz / noiseScale).rgb;
	// Blend UV gradient and noise for variation; avoid multiplying colors (causes black)
	float blend = (1.0 - UV.y) * 0.5 + noiseLevel.r * 0.5;
	ALBEDO = mix(color, color2, blend);
	if (!FRONT_FACING) {
		NORMAL = -NORMAL;
	}
}