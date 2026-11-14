# Contributing

Thank you for helping. This project is small on purpose, and a small, focused change is the easiest to review.
Taking part in this project means following the [Code of Conduct](CODE_OF_CONDUCT.md).

## Privacy first

Never paste real session records, real report output with private paths, or credentials into an issue or a pull
request. Session records hold your prompts, your file names and your commands. Reproduce the problem with a
synthetic fixture instead: invented paths (`/home/dev/project`), invented ids, invented commands. The same goes
for the tests you add: test data is synthetic.

## Set up

1. Clone the repository and use Python 3.10 or newer. The tool itself needs nothing else.
2. Run `make check`. It runs the linter and the tests.

`uv` is only needed for the pinned linter, which the `Makefile` starts with `uvx`. Without `uv`, run
`pip install ruff==0.17.2` and then `make check RUFF=ruff`.

## A good first contribution

- **A reader for another harness.** One module and one test; see [docs/harnesses.md](docs/harnesses.md) for the
  contract and for the harnesses we would like next.
- **A new rule.** One entry in the `RULES` table in `src/stickyagents/rules.py` and one test in
  `tests/test_rules.py`. Rules are listed in [docs/rules.md](docs/rules.md).
- **A credential or startup path the tables miss.** Add it to the credential tables in
  `src/stickyagents/zones.py`, or to `STARTUP_FILES` in `rules.py`, with a test.

If your idea is larger than that, open an issue first so that we can agree on the shape before you write it.

## Rules a change must keep

[AGENTS.md](AGENTS.md) lists them: standard library only, no network, no subprocess, no file content or command
text kept, no model in the loop, one module per harness, synthetic test data, and a size bound that
`tests/test_project_rules.py` checks. `make check` fails when one is broken.

## Open a pull request

One change per pull request. In the description, say:

- **What** changed.
- **Why**: the problem or the need.
- **How you checked**: `make check`, and anything else you ran.

Never weaken a test or a check to get green. If a check is wrong, say why in the pull request.

## License

The project is under the Apache-2.0 license (see [LICENSE](LICENSE)). By submitting a contribution you license it
under the same terms, as section 5 of the license says. There is no separate agreement to sign.
