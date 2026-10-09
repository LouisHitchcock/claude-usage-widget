# Windows portable build (Codex test branch)

The [Windows portable executable workflow](../.github/workflows/windows-exe.yml) runs on pushes to `fix/codex-windows-support-20261009` or via manual dispatch.

1. Open [Actions > Windows portable executable](https://github.com/LouisHitchcock/claude-usage-widget/actions/workflows/windows-exe.yml).
2. Open the most recent **successful** run for the Codex Windows branch.
3. Under **Artifacts**, download `ClaudeUsageWidget-Windows-x64`.
4. Extract the ZIP and run `ClaudeUsageWidget.exe`. No separate Python installation is needed.

The EXE bundles the Python GUI, **not the Codex CLI**. To display Codex limits, install the Codex CLI separately, sign in with `codex login`, and ensure `codex` is on PATH. Claude usage still requires Claude Code credentials.

The configuration path is `%USERPROFILE%\\.config\\claude-usage\\config.json`. Add `"providers": ["claude", "codex"]` to the JSON object to enable Codex rows. If the CLI is missing or logged out, the Codex rows are hidden. Codex is polled at most every 300 seconds by default.

The workflow runs pytest on Windows before packaging. This is a development artifact, not a signed installer; Windows SmartScreen may warn about unsigned, newly built executables. Only run downloads from this repository's own successful GitHub Actions runs.
