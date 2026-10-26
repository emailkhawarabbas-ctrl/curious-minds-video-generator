"""The "lively" visual style: stronger camera, beat scheduler, boil, paper look, quick transitions.

Modules:
  style        config/style.yaml loader (colours, fonts, timings)
  camera       continuous zoom/pan + punch-ins + shake
  boil         hand-drawn line boil for SVG assets
  beats        guarantees a new visual event every ~1.6 s
  transitions  0.2-0.3 s whip / zoom-through / ink-swipe transitions
  composer     the spotlight layout and the lively scene composition
  captions     word-by-word captions with the spoken word highlighted
"""
