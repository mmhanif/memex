# Entity identity & rename semantics

Type: grilling
Status: open
Blocked by: 06

## Question

What is an Entity's stable identity: its filename slug, a frontmatter `id`, or both? When the user renames a Project or Person (title or file), what happens to references in other files: rewrite them all, keep the immutable id so nothing breaks, or tolerate broken links and surface them? How are identifier collisions and invalid characters handled, including on Windows?
