/**
 * D5.9 -- source text as a test reads it.
 *
 * Test-only. Several suites read production sources and the stylesheet as text
 * (Vite's `?raw`, or `node:fs`) and assert structure against multiline
 * literals. Neither loader touches line endings, and this repository's working
 * tree is legitimately mixed: `core.autocrlf=true` checks older files out with
 * CRLF, and a `git checkout`, `git stash` or whole-file rewrite can flip a file
 * either way without changing its committed blob -- invisibly to `git diff`.
 * An assertion that encodes `\n` then fails (or, when it is a `not.toContain`,
 * passes without checking anything) depending on how the file happens to sit
 * on disk.
 *
 * So every test that reads source text passes it through this one function at
 * the point it is loaded, and every structural assertion after that is written
 * once, in LF. Production files are never rewritten for the sake of a test.
 * `testSourceText.test.ts` is the oracle, and it also holds every test that
 * reads source text to routing it through here.
 */
export function withLfLineEndings(text: string): string {
  return text.replace(/\r\n?/g, '\n');
}
