# If you see errors when running the game

## SimpleGrass / addon texture errors

Errors like:
- `Failed loading resource: res://addons/simplegrasstextured/...`
- `Node not found: "/root/SimpleGrass"`
- `Invalid access to property '_height_view' on a base object of type 'null instance'`

**Do this:**

1. **Project → Project Settings → Autoload**  
   Remove **SimpleGrass** if it is listed (it points to a scene that fails to load).

2. **Project → Project Settings → Plugins**  
   Disable **SimpleGrassTextured** (or leave "Enabled" list empty so no addons run).

3. **Use procedural grass only**  
   On the **World** node (or in the script):  
   - **Use Grass Meshes** = ON (procedural crossed-quad grass)  
   - **Use Simple Grass Textured** = OFF (addon grass)

4. **Optional – fix texture cache**  
   Close Godot, delete the folder `godot_world/.godot/imported`, then reopen the project so Godot re-imports. Only do this if you need the addon later.

With the above, the game should run without addon-related errors and grass will come from the procedural system only.
