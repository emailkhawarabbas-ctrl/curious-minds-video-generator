# Content pack: Why can't you tickle yourself?

Curated scripts (`script_short.json`, `script_long.json`) plus reviewed metadata
(`metadata.json`). Scripts were written from the research gathered by `src/research`
(Wikipedia: Tickling, Efference copy; PubMed review "The extraordinary enigma of ordinary
tickle behavior: Why gargalesis still puzzles neuroscience"). Every number in the narration
appears in those sources. Ideas about why tickling exists are presented as hypotheses. The
pipeline re-runs research and the automated fact-check on every build.

The pipeline uses a content pack automatically when `content_packs/<topic_slug>/` exists
(`script_source: auto`). Delete or rename the pack to let the LLM / offline generator write
the scripts instead.
