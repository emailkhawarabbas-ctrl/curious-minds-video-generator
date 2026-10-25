"""Single source of truth for the storyboard vocabulary.

Storyboards (hand-written, rule-generated or LLM-generated) may only reference names
listed here; the Pydantic validators in ``src/content/models.py`` enforce it. The LLM
never produces code — only these names plus data — so nothing generated is executed.
"""
from __future__ import annotations

LAYOUTS = {
    "hook_title": "Big animated title/question + mascot reaction + main icon (episode opener).",
    "character_explains": "Mascot on one side explaining; main object large on the other side with label/arrow.",
    "object_focus": "One object fills the stage; labels with leader lines point at its parts; mascot in a corner.",
    "diagram_flow": "2-4 icons connected left-to-right (or top-to-bottom) by animated pathways: a process / cause-effect.",
    "list_reveal": "2-4 items (icon + short text) revealed one by one as they are mentioned.",
    "comparison": "Two sides compared (A vs B), each with icon + label.",
    "thought_bubble": "Mascot thinking/dreaming with a big thought cloud containing 1-3 icons.",
    "fact_card": "A big animated number (statistic/duration) with a short label; mascot reacts.",
    "story_scene": "Illustrated mini-scene (e.g. a sleeping person) with ambient particles; mascot narrates.",
    "network": "Central icon connected to 3-5 satellite icons with pulsing signals (brain activity, systems).",
    "chart": "Animated chart (line / step 'hypnogram' / bars) with the mascot pointing.",
    "question": "A big question with question-mark doodles; mascot curious/thinking.",
    "timeline": "3-5 milestones along a line revealed in order (stages, history, a night of sleep).",
    "wave_monitor": "A monitor showing animated waves (brain waves / heartbeat / sound) with a state label.",
    "outro": "Brand sign-off: logo, tagline, call to action, mascot waving, confetti.",
    "demonstration": "Animated scientific diagram (see DEMOS) fills the stage and plays in stages synced to the "
                     "narration; Milo points at the active part. Use for every process / mechanism explanation.",
    "full_illustration": "One large environmental illustration (e.g. a sunset, the body's circulation) explored by "
                         "the camera with labelled callouts; Milo peeks in from a corner.",
    "character_closeup": "Milo big and expressive, talking straight to the viewer with one prop beside him "
                         "(relatable moments, reactions, direct questions). Use sparingly.",
    "spotlight": "Lively style: one big visual fills the frame, the host is large and changes position/pose, "
                 "a headline sticker and secondary visuals keep the frame changing (script mode).",
    "whiteboard": "Whiteboard explainer: a visible hand draws the visual stroke by stroke and writes the keywords; "
                  "the host reacts, thinks, counts, holds things up or draws labels itself (script mode).",
}

# Layouts / backgrounds only the lively style uses (kept out of LLM storyboard prompts)
LIVELY_ONLY = ("spotlight", "whiteboard", "doodle_paper")

# Animated explanatory diagrams for the "demonstration" layout (implemented in src/animation/demos.py)
from src.animation.demos import DEMO_KINDS as DEMOS  # noqa: E402

# Story roles a script beat can carry (retention structure; see src/content/story_engine.py)
STORY_ROLES = ("hook", "curiosity_gap", "relatable", "question", "explanation", "discovery", "surprise", "insight",
               "example", "transition", "recap", "ending")

BACKGROUNDS = {
    "paper": "Cream paper with faint doodle grid (default explainer).",
    "bedroom_night": "Cosy bedroom at night with window, moon and stars.",
    "night_sky": "Night sky with stars, moon and hills.",
    "dreamscape": "Purple-pink dream world with clouds, swirls and floating stars.",
    "lab": "Bright science lab with shelves and flasks.",
    "chalkboard": "Classroom chalkboard.",
    "brain_space": "Deep purple space with faint neural network lines.",
    "sunny_outdoors": "Blue sky, sun, clouds and green hills.",
    "space": "Outer space with planets and stars.",
    "city": "Daytime city skyline.",
    "burst_teal": "Rotating sunburst rays in brand teal.",
    "burst_orange": "Rotating sunburst rays in brand orange.",
    "burst_purple": "Rotating sunburst rays in brand purple.",
    # Human Body identity
    "bloodstream": "Inside a blood vessel: warm red lumen with drifting blood cells (circulation, heart, blood).",
    "body_lab": "Bright medical clinic with anatomy poster and a live ECG wall monitor.",
    "anatomy_blueprint": "Deep-blue medical blueprint grid with faint organ outlines and a scan line.",
    "cell_world": "Microscope view: soft field of translucent cells (cells, immunity, DNA).",
    # Science identity
    "sky_day": "Wide blue sky from zenith to pale horizon with sun glow and drifting clouds (sky, light, weather).",
    "science_grid": "Explorer's graph-paper notebook with faint orbit, wave and atom sketches.",
    "atmosphere_view": "Earth's limb from high above: space, glowing atmosphere band, planet below.",
    "sunset_sky": "Low sun with purple-pink-orange sky and silhouetted hills (sunsets, light, evening).",
    "underwater": "Under a lake or sea surface: light shafts, rising bubbles, sandy floor (water, ice, oceans, fish).",
    # Psychology identity
    "mind_maze": "Abstract mind: violet field with rotating thought rings and looping spirals.",
    "thought_room": "Quiet room late at night: desk, lamp glow, window, ticking wall clock (overthinking, worry).",
    "emotion_waves": "Soft layered colour waves for feelings, insight and calm endings.",
    # Lively style
    "doodle_paper": "Off-white paper with grain, fibres and a soft vignette; the grain boils (lively style).",
}

TRANSITIONS = ("cut", "circle_wipe", "doodle_swipe", "slide", "star_zoom", "dots", "dip_cream", "blinds",
               # lively style: quick (0.2-0.3 s) transitions, see src/lively/transitions.py
               "whip_left", "whip_right", "whip_up", "zoom_through", "ink_swipe")
LIVELY_TRANSITIONS = ("whip_left", "whip_right", "whip_up", "zoom_through", "ink_swipe")

# Lively style vocabulary (script mode / --style lively)
STYLES = ("classic", "lively")
LIVELY_ANIMATIONS = {
    "draw_on": "Outlines trace in as if hand-drawn, then the fills fade in.",
    "pop_in": "Scales 0 -> 1.1 -> 1.0 with a springy ease.",
    "bounce": "Drops in and bounces to rest.",
    "slide_in": "Slides in from the side with an overshoot.",
    "spin_in": "Spins and grows into place.",
    "fade_in": "Soft fade (use sparingly).",
}
LIVELY_CAMERAS = {
    "zoom_in": "Slow continuous push in towards the visual.",
    "zoom_out": "Starts close and slowly pulls back.",
    "pan_left": "Slow pan, content moves left.",
    "pan_right": "Slow pan, content moves right.",
    "pan_up": "Slow tilt, content moves up.",
    "pan_down": "Slow tilt, content moves down.",
    "drift": "Gentle floating hand-held move.",
    "static": "No continuous move (punch-ins and shake still apply).",
}

CAMERA_MOVES = ("static", "zoom_in", "zoom_out", "pan_left", "pan_right", "drift", "punch_in", "shake",
                "focus", "follow", "reveal")

CHARACTER_POSITIONS = ("left", "right", "center", "corner_left", "corner_right", "closeup")

OBJECT_ROLES = ("main", "secondary", "item", "prop")

ENTRANCES_OBJ = ("pop", "elastic", "bounce", "draw", "fade", "slide_up", "spin", "none")
IDLES_OBJ = ("float", "pulse", "wiggle", "spin", "none")

DOODLE_KINDS = ("sparkles", "stars", "burst", "confetti", "zzz", "bubbles", "twinkle_field", "float_up",
                "circle_main", "underline_title", "arrow_to_main", "morph")

TEXT_STYLES = ("title", "label", "bubble", "fact", "cta", "note")

CHART_KINDS = ("line", "step", "bar")

MUSIC_MOODS = ("curious", "dreamy", "upbeat", "calm")

# Text length limits (characters) enforced by validation
MAX_TITLE_CHARS = 48
MAX_LABEL_CHARS = 30
MAX_ITEM_CHARS = 42
MAX_BUBBLE_CHARS = 90
MAX_SCENE_WORDS = {"short": 45, "long": 75}

SFX = {
    "pop": "Short bubbly pop (element appears)",
    "whoosh": "Air whoosh (transition / fast movement)",
    "ding": "Bright bell ding (fact / correct)",
    "sparkle": "Glittery shimmer (magic / idea)",
    "boing": "Cartoon spring (surprise / bounce)",
    "click": "Soft UI click (labels / list items)",
    "chime": "Warm 3-note chime (reveal / outro)",
    "tick": "Clock tick",
    "bubble": "Soft bubble blips (dreamy)",
    "magic": "Rising magical sweep (dream / imagination)",
    "snore": "Gentle cartoon snore",
    "heartbeat": "Two soft heartbeats",
    "success": "Happy rising arpeggio",
    "scribble": "Marker drawing on a whiteboard",
}
