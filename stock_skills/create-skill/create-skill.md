# stock_skills/create-skill/

A bundled [[stock_skills]] skill. Slug `create-skill`; frontmatter name **write-a-skill**.

Part of the [[Easel]] knowledge graph.

## Contents
- `SKILL.md` — the skill body. Triggered when the user wants to create/write/build a new
  skill. Walks the model through: gather requirements → draft (`SKILL.md` + reference files +
  optional scripts) → review with the user → save the packaged folder to the skills storage
  location. Includes the skill folder structure, a `SKILL.md` template, description-writing
  rules (the description is the only thing the agent sees when choosing a skill), and a review
  checklist.

No `references/` folder.

## See also
- [[stock_skills]] — how skills are discovered and shipped.
- [[tools]] — `skills.read_skill` loads this body for the model.
- Sibling skill: [[grill-me]].
