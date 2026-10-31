# Results

Real runs for the [leaderboard](https://sundaysebasidian-byte.github.io/whatsent/). One file per agent version.

1. Run the agent under whatsent with the suggested prompt. `--clean` turns off your own MCP servers and plugins
   (`claude`, `codex`, `codebuddy`, `copilot`), so the run shows the agent and not your setup; `--result-to` saves the result here:
   `whatsent run --clean --result-to results/ -- <agent>` (CLI) or `whatsent run --app cursor --agent-version 1.2.3 --result-to results/` (IDE).
2. The file is named `<agent>-<version>[-clean].json`; if one is already there it is kept and this batch is saved as `-2`, `-3`, and the board combines them. Results made with different whatsent versions are never combined; they get separate rows. Run `whatsent check results/`, then open a pull request that adds it.

`result.json` holds only what the board shows: which canaries left, destination hosts, byte counts and the
platform. It has no paths, prompts, commands or file contents. `whatsent check` rejects extra fields, values that look like
paths or canary markers, totals that do not add up and a task file that was never seen without being marked; CI runs it on every pull request.
It cannot tell a real run from a made-up one with consistent numbers, so a reviewer still reads the pull request.

While this folder has no results, the published board shows the made-up examples from `examples/results/`,
clearly labelled as examples.
