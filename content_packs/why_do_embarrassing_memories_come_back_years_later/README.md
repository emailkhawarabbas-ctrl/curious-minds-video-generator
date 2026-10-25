# Content pack: Why do embarrassing memories come back years later?

Curated scripts (`script_short.json`, `script_long.json`) plus reviewed metadata
(`metadata.json`). Scripts were written from the research gathered by `src/research`
(Wikipedia: Involuntary memory, Emotion and memory, Autobiographical memory, Effects of
stress on memory). Every number in the narration appears in those sources. Applications of
the findings to embarrassment specifically are hedged. The pipeline re-runs research and the
automated fact-check on every build.

The pipeline uses a content pack automatically when `content_packs/<topic_slug>/` exists
(`script_source: auto`). Delete or rename the pack to let the LLM / offline generator write
the scripts instead.
