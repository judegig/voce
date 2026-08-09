---
name: ship
description: Update README.md to reflect the code changes made this session, then commit and push them to GitHub. Use when the user says to ship, wrap up, finalize, or push a change, or asks to update the README and GitHub together.
argument-hint: [optional: short description of what to ship, if not obvious from the session]
---

# Ship: document + commit + push

Run this whenever the user asks to "ship", "wrap up", "finalize", or otherwise wants
the README updated and the code pushed to GitHub together, after code changes have
been made in the session (by Claude or the user).

## Steps

1. **Identify what actually changed.** Run `git status` and `git diff` (plus
   `git diff` against any already-committed-but-unpushed commits, e.g.
   `git log origin/master..HEAD`) to see the real code changes. Don't rely on
   conversation memory alone — verify against the actual diff before writing
   anything down.

2. **Update README.md.** For each user-facing change (new behavior, fixed bug,
   changed setting, new troubleshooting case), add or edit the relevant section
   of README.md so it accurately describes current behavior. Skip purely
   internal changes (refactors, comments, variable renames) that don't change
   what someone using the app would experience. Match the README's existing
   tone, structure, and section layout rather than bolting on a new format.

3. **Review before staging.** Run `git status` and `git diff` again after the
   README edit. Confirm nothing unintended is included — no secrets, no
   unrelated files, no scratch/debug files.

4. **Commit.** Stage exactly the files that changed (code + README) —
   never `git add -A` or `git add .`. Write a commit message describing why
   the change was made, matching this repo's existing style (check `git log`
   for tone: concise, present-tense summary line, occasional body explaining
   the reasoning). End the commit message with:
   ```
   Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
   ```

5. **Push.** Push to `origin` on the current branch. If the push is rejected
   because the branch has diverged, stop and report it — do not force-push.

6. **Report back.** Tell the user, in 1-2 sentences, what was committed and
   pushed, plus the resulting commit hash(es). Don't restate the whole diff.

## Guardrails

- If there's nothing uncommitted or unpushed, say so and stop — don't create
  an empty commit.
- If a change hasn't actually been tested/verified yet (e.g. a fix still
  awaiting confirmation it works), say that plainly rather than presenting it
  as a done, verified fix — in the report and, if relevant, the commit body.
- Never commit `.env`, `settings.json`, `.claude/settings.local.json`, or
  anything else covered by `.gitignore`. If `git status` shows one of those
  as staged, stop and warn before proceeding.
