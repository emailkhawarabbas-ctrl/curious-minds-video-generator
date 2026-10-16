Write a $format_label script for the topic: "$topic"
Niche / content pillar: $niche (visual identity: $theme)

Target length: about $target_words spoken words in total ($duration_label).
$structure

Allowed layouts (name: purpose):
$layouts

Animated demonstrations for the "demonstration" layout (kind: what it shows, with its stages).
Give "stage_cues": single narration words that start stages 2, 3, ... and up to 4 short "labels":
$demos

Allowed assets (id: tags) — prefer the ones that literally depict the narration:
$assets

Allowed backgrounds (leave null to let the $theme identity choose): $backgrounds
Allowed character actions: $actions
Allowed expressions: $expressions
Allowed sound effects: $sfx

RESEARCH FACTS (id | status | text):
$facts

Return JSON matching the schema. Beat ids must be unique (b1, b2, ...). Each beat's narration
is 1-3 sentences ($beat_words words max). The first beat is the hook; the last beat is a
natural sign-off with a light call to action.
