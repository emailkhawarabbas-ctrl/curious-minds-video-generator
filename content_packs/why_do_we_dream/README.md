# Content pack: Why Do We Dream?

Curated scripts for the MVP acceptance test (`script_short.json`, `script_long.json`) plus
reviewed metadata (`metadata.json`). Scripts were written from the research gathered by
`src/research` (Wikipedia: Dream, Rapid eye movement sleep, REM sleep behavior disorder;
PubMed reviews on the neural mechanisms of dreaming, dreaming research and dreaming in
mammals). Every number in the narration appears in those sources; theories are presented
as hypotheses. The pipeline re-runs research and the automated fact-check on every build.

The pipeline uses a content pack automatically when `content_packs/<topic_slug>/` exists
(`script_source: auto`). Delete or rename the pack to let the LLM / offline generator write
the scripts instead.
