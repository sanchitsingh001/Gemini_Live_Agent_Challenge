Optional: grass_blade.png
------------------------
For best-looking grass, add a PNG here named grass_blade.png:
- White (or light) blade shape on transparent background
- Alpha is used with alpha scissor (threshold 0.5) for crisp edges
- Suggested size: e.g. 64x256 or 128x512 (tall narrow blade)
- Single blade or small tuft; the material tints it with grass green

If this file is missing, grass still renders as solid green crossed quads with CULL_DISABLED (both sides visible).
