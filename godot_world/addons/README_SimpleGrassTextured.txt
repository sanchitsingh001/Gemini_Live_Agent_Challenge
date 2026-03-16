SimpleGrassTextured addon (Option A)
------------------------------------
For addon grass + wind to work:

1. Addon path: res://addons/simplegrasstextured/ must exist.
   - Either: symlink simplegrasstextured -> ../SimpleGrassTextured-4125f7302a7a291b547343d267c8407af7dd7ba6/addons/simplegrasstextured
   - Or: copy the contents of that folder here as simplegrasstextured/

2. Autoload: Project Settings → AutoLoad
   Name: SimpleGrass
   Path: res://addons/simplegrasstextured/singleton.tscn

3. Plugin: Project Settings → Plugins → enable "SimpleGrassTextured" if listed.

4. World loader: use_simple_grass_textured = true, use_grass_meshes = false (defaults).

If the addon is only in the hash-named folder, the code will still try to load grass.gd from there, but the SimpleGrass singleton (wind) requires res://addons/simplegrasstextured/ so its resources load.
