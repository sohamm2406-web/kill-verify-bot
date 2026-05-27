HOW TO USE REFERENCE IMAGES
============================

Drop your images into the correct sub-folder:

  reference_images/
  ├── legit/       ← genuine, unedited stats screenshots from your game
  │                  (players who were manually verified by staff)
  └── tampered/    ← screenshots you know were edited/faked
                     (optional but strongly improves fake detection)

Supported formats: .png  .jpg  .jpeg  .webp

TIPS:
- 3–10 legit images is plenty. More than 20 will slow down each analysis
  and may hit Gemini's token limits.
- Variety helps: different players, different stat ranges, different devices
  (PC screenshot vs phone photo of screen) so Gemini learns what's normal.
- For tampered/ folder: even 1–2 examples of edited screenshots dramatically
  improves fake detection. You don't need many.
- After adding/removing images, run /reloadrefs in Discord (staff only)
  and the bot picks them up immediately — no restart needed.
