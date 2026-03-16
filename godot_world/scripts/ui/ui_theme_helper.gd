extends Node
## Autoload singleton name UiThemeHelper — glass-first UI (frosted, light borders).


## Top bar / clue panel — wide, shallow glass
func style_panel() -> StyleBoxFlat:
	return style_glass_bar_wide()


func style_glass_bar_wide() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.72, 0.78, 0.92, 0.16)
	s.set_corner_radius_all(0)
	s.set_border_width_all(0)
	s.set_border_width(SIDE_BOTTOM, 1)
	s.border_color = Color(1, 1, 1, 0.35)
	s.shadow_size = 6
	s.shadow_color = Color(0, 0, 0, 0.12)
	s.set_content_margin_all(14)
	s.set_content_margin(SIDE_TOP, 12)
	s.set_content_margin(SIDE_BOTTOM, 12)
	return s


## Cards / list rows — glass pill
func style_pill() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.85, 0.9, 0.98, 0.12)
	s.set_corner_radius_all(12)
	s.set_border_width_all(1)
	s.border_color = Color(1, 1, 1, 0.4)
	s.set_content_margin_all(12)
	return s


func style_button() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.2, 0.24, 0.32, 0.35)
	s.set_corner_radius_all(10)
	s.set_border_width_all(1)
	s.border_color = Color(1, 1, 1, 0.45)
	s.set_content_margin_all(12)
	return s


func apply_button_theme(btn: Button) -> void:
	btn.add_theme_stylebox_override("normal", style_button())
	btn.add_theme_stylebox_override("hover", style_button())
	btn.add_theme_stylebox_override("pressed", style_button())
	btn.add_theme_color_override("font_color", Color.WHITE)
	btn.add_theme_font_size_override("font_size", 15)


## Modals / task panel — frosted glass
func style_glass_panel() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.88, 0.92, 0.98, 0.18)
	s.set_corner_radius_all(20)
	s.set_border_width_all(1)
	s.border_color = Color(1, 1, 1, 0.5)
	s.shadow_size = 14
	s.shadow_color = Color(0, 0, 0, 0.2)
	s.set_content_margin_all(20)
	return s


## Glass primary button
func style_glass_button() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.2, 0.26, 0.36, 0.4)
	s.set_corner_radius_all(12)
	s.set_border_width_all(1)
	s.border_color = Color(1, 1, 1, 0.55)
	s.set_content_margin_all(12)
	return s


func apply_glass_button(btn: Button) -> void:
	var n := style_glass_button()
	var h := style_glass_button()
	h.bg_color = Color(0.28, 0.34, 0.44, 0.52)
	btn.add_theme_stylebox_override("normal", n)
	btn.add_theme_stylebox_override("hover", h)
	btn.add_theme_stylebox_override("pressed", n)
	btn.add_theme_color_override("font_color", Color(0.98, 0.99, 1.0))
	btn.add_theme_font_size_override("font_size", 17)


## NPC dialogue — main block (bottom row, left)
func style_dialogue_bar() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.82, 0.88, 0.96, 0.2)
	s.set_corner_radius_all(16)
	s.set_border_width_all(1)
	s.border_color = Color(1, 1, 1, 0.48)
	s.shadow_size = 12
	s.shadow_color = Color(0, 0, 0, 0.18)
	s.set_content_margin_all(16)
	return s


func style_dialogue_name_strip() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.65, 0.72, 0.88, 0.22)
	s.set_corner_radius_all(10)
	s.set_border_width_all(1)
	s.border_color = Color(1, 1, 1, 0.35)
	s.set_content_margin_all(10)
	return s


func style_dialogue_choice_button() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.78, 0.84, 0.94, 0.18)
	s.set_corner_radius_all(12)
	s.set_border_width_all(1)
	s.border_color = Color(1, 1, 1, 0.42)
	s.set_content_margin_all(12)
	return s


func apply_dialogue_choice_button(btn: Button) -> void:
	var n := style_dialogue_choice_button()
	var h := style_dialogue_choice_button()
	h.bg_color = Color(0.88, 0.92, 0.98, 0.28)
	h.border_color = Color(1, 1, 1, 0.55)
	btn.add_theme_stylebox_override("normal", n)
	btn.add_theme_stylebox_override("hover", h)
	btn.add_theme_stylebox_override("pressed", n)
	btn.add_theme_stylebox_override("disabled", n)
	btn.add_theme_color_override("font_color", Color(0.96, 0.98, 1.0))
	btn.add_theme_font_size_override("font_size", 16)


## Selected player line while NPC is thinking
func style_dialogue_selected_choice() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.45, 0.62, 0.52, 0.28)
	s.set_corner_radius_all(12)
	s.set_border_width_all(1)
	s.border_color = Color(0.75, 0.95, 0.85, 0.55)
	s.set_content_margin_all(12)
	return s


## Chat modal shell + header strip
func style_glass_modal() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.82, 0.88, 0.96, 0.22)
	s.set_corner_radius_all(18)
	s.set_border_width_all(1)
	s.border_color = Color(1, 1, 1, 0.5)
	s.shadow_size = 20
	s.shadow_color = Color(0, 0, 0, 0.25)
	s.set_content_margin_all(18)
	return s


func style_glass_header_strip() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.72, 0.8, 0.92, 0.2)
	s.set_corner_radius_all(14)
	s.set_border_width_all(0)
	s.set_border_width(SIDE_BOTTOM, 1)
	s.border_color = Color(1, 1, 1, 0.4)
	s.set_content_margin_all(14)
	return s


## Toast / small callouts
func style_glass_toast() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.55, 0.72, 0.62, 0.28)
	s.set_corner_radius_all(14)
	s.set_border_width_all(1)
	s.border_color = Color(0.85, 0.98, 0.9, 0.5)
	s.set_content_margin_all(14)
	return s


## Dialogue manager / legacy full-narrative panels
func style_glass_dialogue_block() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.8, 0.86, 0.95, 0.2)
	s.set_corner_radius_all(14)
	s.set_border_width_all(1)
	s.border_color = Color(1, 1, 1, 0.45)
	s.set_content_margin_all(16)
	return s


func style_glass_inventory_side() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.78, 0.84, 0.94, 0.18)
	s.set_corner_radius_all(0)
	s.set_border_width_all(0)
	s.set_border_width(SIDE_LEFT, 1)
	s.border_color = Color(1, 1, 1, 0.4)
	s.set_content_margin_all(14)
	return s
