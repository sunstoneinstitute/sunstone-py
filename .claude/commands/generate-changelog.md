---
allowed-tools: "Bash(git log:*), Bash(git tag), Bash(tail), Bash(head)"
argument-hint: "{after-commit}"
description: >-
  Generate a Markdown-formatted changelog for commits after
  the specified commit.
model: haiku
---
Convert the following git commit messages into "Keep a Changelog" format entries.
Categorize under: Added, Changed, Fixed, Removed, Security (only include categories that apply).
Be concise. Skip merge commits, version bump commits, and release commits.
Output ONLY the markdown entries with ### headers for categories, nothing else.

Commit log: !`git log --no-merges "${1:-HEAD~1}..HEAD"`
