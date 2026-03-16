extends Node
## AudioManager autoload: voiceover (TTS) and BGM with smooth fades and ducking during narration.
##
## Volume levels:
##   - Exploration BGM: area music (-10 dB)
##   - During narration: ducked (-14 dB) so BGM is audible but voiceover stays clear
##   - Voiceover: full (0 dB)

const FADE_DURATION := 0.6
const DUCK_DURATION := 0.35
## BGM volume when exploring (area music)
const BGM_EXPLORATION_DB := -10.0
## BGM volume during narration (audible under voice, doesn't overpower)
const BGM_DUCKED_DB := -14.0

var _bgm: AudioStreamPlayer = null
var _voice: AudioStreamPlayer = null
var _tween_bgm: Tween = null
var _tween_voice: Tween = null
var _current_bgm_path: String = ""
var _bgm_should_loop: bool = false


func _ready() -> void:
	_bgm = AudioStreamPlayer.new()
	_bgm.bus = "Master"
	_bgm.volume_db = BGM_EXPLORATION_DB
	_bgm.autoplay = false
	_bgm.finished.connect(_on_bgm_finished)
	add_child(_bgm)

	_voice = AudioStreamPlayer.new()
	_voice.bus = "Master"
	_voice.volume_db = 0.0
	_voice.autoplay = false
	add_child(_voice)

	_voice.finished.connect(_on_voice_finished)

	if GameManager:
		GameManager.player_area_changed.connect(_on_player_area_changed)


func _on_player_area_changed(area_id: String) -> void:
	if not GameManager:
		return
	var area_bgm: Dictionary = GameManager.game_bundle.get("audio", {}).get("area_bgm", {})
	if area_bgm.has(area_id):
		var path := str(area_bgm[area_id])
		if path != _current_bgm_path:
			crossfade_to_bgm(path, true)


func _on_bgm_finished() -> void:
	"""When BGM reaches end, restart if we're in loop mode (reliable for WAV and OGG)."""
	if _bgm_should_loop and not _current_bgm_path.is_empty() and _bgm.stream:
		_bgm.play()


func bundle_audio_path(rel: String) -> String:
	"""Resolve relative audio path (e.g. audio/voiceover_setup.wav) to absolute path."""
	if rel.is_empty():
		return ""
	if not GameManager:
		return ""
	var base: String = ""
	if GameManager:
		base = str(GameManager.game_output_path).strip_edges()
	# In Web exports, all bundle audio is packed into res://generated/audio/,
	# so ignore external GAME_OUTPUT paths and always use packed resources.
	if OS.has_feature("web"):
		base = ""
	if base.is_empty():
		base = OS.get_environment("GAME_OUTPUT")
	if base.is_empty():
		# Exported build (e.g. web): audio is packed under res://generated/
		var res_path := "res://generated/" + rel
		if ResourceLoader.exists(res_path):
			return res_path
		return ""
	var full: String = base + "/" + rel if not base.ends_with("/") else base + rel
	var candidates: PackedStringArray = []
	candidates.append(ProjectSettings.globalize_path("res://..".path_join(full)))
	var exec_base := OS.get_executable_path().get_base_dir()
	if OS.get_name() == "macOS":
		candidates.append(exec_base.path_join("../Resources").path_join(full))
	candidates.append(exec_base.path_join(full))
	for p in candidates:
		if FileAccess.file_exists(p):
			return p
	return ""


func _kill_tween(tween: Tween) -> void:
	if tween and tween.is_valid():
		tween.kill()


func _set_bgm_loop(stream: AudioStream, loop: bool) -> void:
	"""Enable or disable looping for BGM (OGG or WAV)."""
	if stream is AudioStreamOggVorbis:
		(stream as AudioStreamOggVorbis).loop = loop
	elif stream is AudioStreamWAV and loop:
		var wav: AudioStreamWAV = stream as AudioStreamWAV
		wav.loop_mode = AudioStreamWAV.LOOP_FORWARD
		wav.loop_begin = 0
		# loop_end in samples: length_sec * mix_rate; stereo = 2 channels
		var total_samples := int(wav.get_length() * float(wav.mix_rate)) * (2 if wav.stereo else 1)
		wav.loop_end = total_samples


func play_bgm(path_rel: String, loop: bool = true, fade_in: bool = true, start_ducked: bool = false) -> void:
	"""Play BGM from bundle-relative path. Optional fade-in. start_ducked = true for narrative screens (BGM stays quiet)."""
	if path_rel.is_empty():
		stop_bgm()
		return
	var abs_path := bundle_audio_path(path_rel)
	if abs_path.is_empty():
		return
	var stream := load_audio_stream(abs_path)
	if not stream:
		return
	_kill_tween(_tween_bgm)
	_bgm.stream = stream
	_bgm_should_loop = loop
	_set_bgm_loop(stream, loop)
	var target_db := BGM_EXPLORATION_DB
	if start_ducked:
		target_db = BGM_DUCKED_DB
	_bgm.volume_db = -80.0 if fade_in else target_db
	_bgm.play()
	_current_bgm_path = path_rel
	if fade_in:
		_tween_bgm = create_tween()
		_tween_bgm.set_trans(Tween.TRANS_SINE)
		_tween_bgm.set_ease(Tween.EASE_OUT)
		_tween_bgm.tween_property(_bgm, "volume_db", target_db, FADE_DURATION)


func stop_bgm(fade_out: bool = true) -> void:
	"""Stop BGM with optional fade-out."""
	_kill_tween(_tween_bgm)
	_bgm_should_loop = false
	if not fade_out:
		_bgm.stop()
		_current_bgm_path = ""
		return
	_tween_bgm = create_tween()
	_tween_bgm.set_trans(Tween.TRANS_SINE)
	_tween_bgm.set_ease(Tween.EASE_IN)
	_tween_bgm.tween_property(_bgm, "volume_db", -80.0, FADE_DURATION * 0.8)
	_tween_bgm.tween_callback(_bgm.stop)
	_tween_bgm.tween_callback(func(): _current_bgm_path = "")


func duck_bgm_for_narration() -> void:
	"""Duck BGM so voiceover is clearly audible."""
	_kill_tween(_tween_bgm)
	_tween_bgm = create_tween()
	_tween_bgm.set_trans(Tween.TRANS_SINE)
	_tween_bgm.set_ease(Tween.EASE_OUT)
	_tween_bgm.tween_property(_bgm, "volume_db", BGM_DUCKED_DB, DUCK_DURATION)


func restore_bgm_after_narration() -> void:
	"""Restore BGM to exploration level after narration ends."""
	_kill_tween(_tween_bgm)
	_tween_bgm = create_tween()
	_tween_bgm.set_trans(Tween.TRANS_SINE)
	_tween_bgm.set_ease(Tween.EASE_OUT)
	_tween_bgm.tween_property(_bgm, "volume_db", BGM_EXPLORATION_DB, FADE_DURATION * 0.8)


func play_voiceover(path_rel: String, on_finished: Callable = Callable()) -> void:
	"""Play voiceover from bundle-relative path. Duck BGM first; restore when done."""
	if path_rel.is_empty():
		restore_bgm_after_narration()
		on_finished.call()
		return
	var abs_path := bundle_audio_path(path_rel)
	if abs_path.is_empty():
		restore_bgm_after_narration()
		on_finished.call()
		return
	var stream := load_audio_stream(abs_path)
	if not stream:
		restore_bgm_after_narration()
		on_finished.call()
		return
	_kill_tween(_tween_voice)
	duck_bgm_for_narration()
	_voice.stream = stream
	if stream is AudioStreamOggVorbis:
		(stream as AudioStreamOggVorbis).loop = false
	_voice.volume_db = 0.0
	if on_finished.is_valid():
		_voice.finished.connect(on_finished, CONNECT_ONE_SHOT)
	_voice.play()


func _on_voice_finished() -> void:
	restore_bgm_after_narration()


func stop_voiceover() -> void:
	"""Stop narrator voiceover immediately (e.g. when user skips cutscene). Restores BGM."""
	_voice.stop()
	restore_bgm_after_narration()


func play_narration_with_bgm(voice_rel: String, bgm_rel: String, on_voice_finished: Callable = Callable()) -> void:
	"""Play BGM (ducked) + voiceover. BGM restores when voiceover ends."""
	play_bgm(bgm_rel, true, true)
	duck_bgm_for_narration()
	play_voiceover(voice_rel, on_voice_finished)


func crossfade_to_bgm(path_rel: String, loop: bool = true) -> void:
	"""Crossfade to new BGM (e.g. when changing area/chapter)."""
	if path_rel == _current_bgm_path:
		return
	if path_rel.is_empty():
		stop_bgm(true)
		return
	var abs_path := bundle_audio_path(path_rel)
	if abs_path.is_empty():
		return
	var stream := load_audio_stream(abs_path)
	if not stream:
		return
	_kill_tween(_tween_bgm)
	_tween_bgm = create_tween()
	_tween_bgm.set_trans(Tween.TRANS_SINE)
	_tween_bgm.set_ease(Tween.EASE_IN_OUT)
	_tween_bgm.tween_property(_bgm, "volume_db", -80.0, FADE_DURATION * 0.5)
	_tween_bgm.tween_callback(func():
		_bgm.stop()
		_bgm.stream = stream
		_bgm_should_loop = loop
		_set_bgm_loop(stream, loop)
		_bgm.volume_db = -80.0
		_current_bgm_path = path_rel
		_bgm.play()
	)
	_tween_bgm.tween_property(_bgm, "volume_db", BGM_EXPLORATION_DB, FADE_DURATION)


func load_audio_stream(path: String) -> AudioStream:
	"""Load WAV/OGG from filesystem or packed res:// (web export)."""
	if path.is_empty():
		return null
	# In Godot 4.3 web exports, audio is always packed as resources (res://generated/...),
	# so we rely on ResourceLoader/load() instead of deprecated static load_from_file().
	return load(path) as AudioStream


func get_current_bgm_path() -> String:
	return _current_bgm_path
