extends RefCounted
## HTTP client for game_server POST /api/chat

static func send_chat(
	base_url: String,
	npc_id: String,
	message: String,
	conversation_history: Array,
	current_chapter: String,
	collected_clues: Array,
	output: String
) -> HTTPRequest:
	var url := base_url.path_join("/api/chat").replace("//", "/")
	if not url.begins_with("http"):
		url = base_url + "/api/chat"
	var body := {
		"npc_id": npc_id,
		"message": message,
		"conversation_history": conversation_history,
		"current_chapter": current_chapter,
		"collected_clues": collected_clues
	}
	if not output.is_empty():
		body["output"] = output
	var json_str := JSON.stringify(body)
	var req := HTTPRequest.new()
	req.use_threads = true
	var err := req.request(url, ["Content-Type: application/json"], HTTPClient.METHOD_POST, json_str)
	if err != OK:
		push_error("ChatAPI: request failed: %d" % err)
		return null
	return req
