# Results

Real runs for the [leaderboard](https://sundaysebasidian-byte.github.io/whatsent/). One file per agent version.

1. Run the agent under whatsent with the suggested prompt. `--clean` turns off your own MCP servers and plugins
   (`claude`, `codex`, `codebuddy`, `copilot`), so the run shows the agent and not your setup; `--result-to` saves the result here:
   `whatsent run --clean --result-to results/ -- <agent>` (CLI) or `whatsent run --app cursor --agent-version 1.2.3 --result-to results/` (IDE).
2. The file is named `<agent>-<version>[-clean].json`. Open a pull request that adds it.

`result.json` holds only what the board shows: which canaries left, destination hosts, byte counts and the
platform. It has no paths, prompts, commands or file contents. Check it before you submit anyway.

While this folder has no results, the published board shows the made-up examples from `examples/results/`,
clearly labelled as examples.
