extends Node

signal auth_changed
signal auth_error(msg: String)
signal account_deleted
signal leaderboard_loaded(track_id: String, entries: Array)

var _plugin = null
var signed_in: = false
var uid: = ""
var display_name: = ""
var email: = ""


func _ready() -> void :
	if OS.has_feature("android") and Engine.has_singleton("MiniRallyAuth"):
		_plugin = Engine.get_singleton("MiniRallyAuth")
		_plugin.signed_in.connect(_on_signed_in)
		_plugin.sign_in_failed.connect(_on_sign_in_failed)
		_plugin.signed_out.connect(_on_signed_out)
		_plugin.account_deleted.connect(_on_account_deleted)
		_plugin.delete_failed.connect(_on_delete_failed)
		_plugin.leaderboard_loaded.connect(_on_leaderboard_loaded)
		_refresh_current_user()
		print("[Auth] MiniRallyAuth singleton connected, signed_in=", signed_in)
	else:
		print("[Auth] MiniRallyAuth unavailable on this platform (guest mode)")


func available() -> bool:
	return _plugin != null


func _refresh_current_user() -> void :
	if _plugin == null: return
	var raw: String = str(_plugin.get_current_user())
	var parsed = JSON.parse_string(raw)
	if parsed is Dictionary and bool(parsed.get("signed_in", false)):
		signed_in = true
		uid = str(parsed.get("uid", ""))
		display_name = str(parsed.get("name", "Racer"))
		email = str(parsed.get("email", ""))
	else:
		signed_in = false
		uid = ""
		display_name = ""
		email = ""


func sign_in() -> void :
	if _plugin == null:
		auth_error.emit("Google Sign-In is only available on Android.")
		return
	_plugin.sign_in_google()


func sign_in_email(p_email: String, p_password: String) -> void :
	if _plugin == null:
		auth_error.emit("Email Sign-In is only available on Android.")
		return
	_plugin.sign_in_email(p_email, p_password)


func sign_out() -> void :
	if _plugin == null: return
	_plugin.sign_out()


func delete_account() -> void :
	if _plugin == null:
		account_deleted.emit()
		return
	_plugin.delete_account()


func submit_score(track_id: String, time_sec: float, car_id: String = "yellow") -> void :
	if _plugin == null or not signed_in or track_id == "" or time_sec <= 0.0:
		return
	var time_ms: int = int(round(time_sec * 1000.0))
	if time_ms <= 0: return
	_plugin.submit_score(track_id, time_ms, car_id)


func sync_all_best_times() -> void :
	if _plugin == null or not signed_in: return
	var bests = Game.data.get("best", {})
	if not (bests is Dictionary): return
	var car_id: String = str(Game.data.get("car", "yellow"))
	for tid in bests.keys():
		var t: float = float(bests[tid])
		if t > 0.0:
			submit_score(str(tid), t, car_id)


func fetch_leaderboard(track_id: String, limit: int = 20) -> void :
	if _plugin == null:
		leaderboard_loaded.emit(track_id, [])
		return
	_plugin.fetch_leaderboard(track_id, limit)


func _on_signed_in(p_uid: String, p_name: String, p_email: String) -> void :
	signed_in = true
	uid = p_uid
	display_name = p_name if p_name != "" else "Racer"
	email = p_email
	sync_all_best_times()
	auth_changed.emit()


func _on_sign_in_failed(err: String) -> void :
	print("[Auth] sign_in_failed: ", err)
	auth_error.emit(err)


func _on_signed_out() -> void :
	signed_in = false
	uid = ""
	display_name = ""
	email = ""
	auth_changed.emit()


func _on_account_deleted() -> void :
	signed_in = false
	uid = ""
	display_name = ""
	email = ""
	account_deleted.emit()
	auth_changed.emit()


func _on_delete_failed(err: String) -> void :
	print("[Auth] delete_failed: ", err)
	auth_error.emit(err)


func _on_leaderboard_loaded(track_id: String, entries_json: String) -> void :
	var parsed = JSON.parse_string(entries_json)
	var arr: Array = parsed if parsed is Array else []
	leaderboard_loaded.emit(track_id, arr)
