extends Node
## NPC voice manager: download per-line audio from backend and play it.
## Stops instantly when dialogue closes / player walks away.

signal voice_started(npc_id: String)
signal voice_finished(npc_id: String)

const HTTP_TIMEOUT_SEC := 10.0

var _player: AudioStreamPlayer = null
var _http: HTTPRequest = null
var _current_npc_id: String = ""
var _pending_finished_callback: Callable = Callable()


func _ready() -> void:
	_player = AudioStreamPlayer.new()
	_player.bus = "Master"
	_player.autoplay = false
	_player.finished.connect(_on_voice_finished)
	add_child(_player)

	_http = HTTPRequest.new()
	_http.timeout = HTTP_TIMEOUT_SEC
	_http.request_completed.connect(_on_http_done)
	add_child(_http)


func play_npc_voice(npc_id: String, audio_url: String, on_finished: Callable = Callable()) -> void:
	if audio_url.is_empty():
		if on_finished.is_valid():
			on_finished.call()
		return

	stop_npc_voice()
	_current_npc_id = npc_id
	_pending_finished_callback = on_finished

	var err := _http.request(audio_url)
	if err != OK:
		_current_npc_id = ""
		_pending_finished_callback = Callable()


func stop_npc_voice() -> void:
	if _player and _player.playing:
		_player.stop()
	if _pending_finished_callback.is_valid():
		_pending_finished_callback.call()
	_pending_finished_callback = Callable()
	if not _current_npc_id.is_empty():
		voice_finished.emit(_current_npc_id)
	_current_npc_id = ""


func _on_http_done(result: int, response_code: int, headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code >= 400:
		_on_voice_finished()
		return

	# Server provides raw PCM (16-bit little-endian mono) plus an X-Audio-Sample-Rate header.
	var sample_rate := 24000
	for h in headers:
		var s := str(h)
		if s.to_lower().begins_with("x-audio-sample-rate:"):
			var parts := s.split(":", false, 2)
			if parts.size() >= 2:
				var v := str(parts[1]).strip_edges()
				if v.is_valid_int():
					sample_rate = int(v)

	var wav := AudioStreamWAV.new()
	wav.data = body
	wav.format = AudioStreamWAV.FORMAT_16_BITS
	wav.mix_rate = sample_rate
	wav.stereo = false

	_player.stream = wav
	_player.play()
	if not _current_npc_id.is_empty():
		voice_started.emit(_current_npc_id)


func _on_voice_finished() -> void:
	if _pending_finished_callback.is_valid():
		_pending_finished_callback.call()
	_pending_finished_callback = Callable()
	if not _current_npc_id.is_empty():
		voice_finished.emit(_current_npc_id)
	_current_npc_id = ""

