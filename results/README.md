# Results

Real runs for the [leaderboard](https://sundaysebasidian-byte.github.io/whatsent/). One file per agent version.

1. Run the agent under whatsent with the suggested prompt:
   `whatsent run --agent-version 1.2.3 -- <agent>` (CLI) or `whatsent run --app cursor --agent-version 1.2.3` (IDE).
2. Copy the run's `result.json` here as `<agent>-<version>.json` and open a pull request.

`result.json` holds only what the board shows: which canaries left, destination hosts, byte counts and the
platform. It has no paths, prompts, commands or file contents. Check it before you submit anyway.

While this folder has no results, the published board shows the made-up examples from `examples/results/`,
clearly labelled as examples.
