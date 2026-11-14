# Agent Rules

## Commits

- **Every change must be committed.** Never leave work sitting uncommitted: once a change is
  finished and verified, stage the files it touched and commit them with a concise message. A task
  is not done while its changes exist only in the working tree.
- Every commit must use the user's own git configuration for identity. Do not pass `--author`, do not set `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME` or `GIT_COMMITTER_EMAIL`, and do not modify or override `user.name` / `user.email` locally. Let `git commit` use whatever `git config user.name` and `git config user.email` already resolve to.
- No co-authorship. Never add `Co-Authored-By:` trailers, never add another author or multiple `Signed-off-by`-style lines for collaborators.
- No attribution footers of any kind. Do not add "Generated with ..." lines, AI/tool credit, or any other trailer to a commit message. End the commit message at its own last line.
