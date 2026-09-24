# skill-picker

You have thirty agent skills and remember four of them. This ranks your own
skills against what you just asked for, so your agent can offer the right one
and you decide whether to use it.

It prints JSON and does nothing else. No daemon, no background process, and it
never invokes a skill for you.

## Ranking runs on Jev

[Jev](https://typesafe.ai/) is TypeSafe's System One model. It writes
no prose. You send it state and typed questions, and it answers with
probabilities. Ask which of your thirty skills fits a request and you get a
number per skill instead of a paragraph to parse.

That is what makes this practical. Choosing a skill takes judgment, so it
needs a model. But a number you can compare against a threshold beats a
sentence you have to interpret, and it stays cheap enough to run on every
request. Two calls, 1.9 seconds on average.

You need a TypeSafe API key for that. Without one the tool still runs, reports
`status: unavailable`, and your agent carries on as before.

```console
$ echo "A customer says checkout sometimes hangs, but nobody has reproduced it." \
    | skill-picker --skills-dir examples/skills
{
  "gate_probability": 0.5333333333333333,
  "status": "ok",
  "suggestions": [
    {
      "description": "Create the smallest reliable reproduction for a reported bug. Use when a failure is unclear, intermittent, user-reported, or not yet proven locally.",
      "fit_probability": 0.94,
      "invocation": "/reproduce-bug",
      "kind": "skill",
      "name": "reproduce-bug",
      "relative_probability": 1.0
    },
    {
      "description": "Research how an unfamiliar system works and write a code-grounded explanation of its structure and data flow.",
      "fit_probability": 0.38,
      "invocation": "/explain-architecture",
      "kind": "skill",
      "name": "explain-architecture",
      "relative_probability": 0.0
    }
  ]
}
```

Your agent turns that into a question:

```
This looks like one of your skills:
  /reproduce-bug        smallest reliable reproduction for a reported bug
  /explain-architecture how an unfamiliar system works, with citations
Which do you want?
```

## Install

Python 3.11 or newer, no dependencies.

```bash
uv tool install git+https://github.com/MuskanPaliwal/skill-picker
```

Or from a clone, with pip 24.2 or newer:

```bash
pip install .
```

## Give it your key

Create one at [console.typesafe.ai/keys](https://console.typesafe.ai/keys),
then set it when you run the tool:

```bash
export TYPESAFE_API_KEY=your-key
echo "the export crashes intermittently, find the cause" | skill-picker
```

That is the whole setup. Put the `export` line in your shell profile, or
wherever your agent picks up its environment, and forget about it. The tool
reads the key when it makes the call and writes it nowhere.

<details>
<summary>If you would rather not keep it in your environment</summary>

A file, which the tool reads when `TYPESAFE_API_KEY` is unset:

```bash
mkdir -p ~/.config/typesafe
printf '%s' 'your-key' > ~/.config/typesafe/api-key
chmod 600 ~/.config/typesafe/api-key
```

Or any command that prints the key, for a secret manager:

```bash
export TYPESAFE_API_KEY_COMMAND='op read "op://Private/TypeSafe/credential"'
export TYPESAFE_API_KEY_COMMAND='pass show typesafe/api-key'
export TYPESAFE_API_KEY_COMMAND='security find-generic-password -s typesafe -w'
```

The first source you configure wins, in the order above. A helper command that
fails stops the run rather than quietly falling through to the file, so you
never route with a stale key by accident.

The helper runs without a shell, so metacharacters in it stay literal. Its
prompts reach your terminal, so an unlock request does not look like a hang.
Its output and arguments never appear in an error message, because either can
carry the key.

The file location follows `XDG_CONFIG_HOME` when you set it.

</details>

## Point it at your skills

It reads any directory of `<name>/SKILL.md` files with YAML frontmatter, the
layout Claude Code and `.agents` already use. It looks in `~/.agents/skills`
first, then `~/.claude/skills`.

```bash
skill-picker --skills-dir ~/my-skills
export SKILL_PICKER_SKILLS_DIR=~/my-skills
```

A skill is routable when its frontmatter has a `description`. Set
`user-invocable: false` to keep one out of the ranking. The description is what
the model matches against, so write it for the situation the skill is for, not
the steps it performs.

Plain commands can compete in the same ranking. List them in a JSON file:

```json
[
  {
    "name": "preflight",
    "description": "Collect branch readiness evidence before opening a pull request.",
    "command": "preflight-branch"
  }
]
```

```bash
skill-picker --actions ~/my-actions.json
export SKILL_PICKER_ACTIONS=~/my-actions.json
```

These appear as `$ command` rather than `/skill`, so an agent can tell your
judgment workflows apart from your scripts.

## Wire it into your agent

Add this to `AGENTS.md`, `CLAUDE.md`, or your agent's instruction file:

```markdown
Before starting a nontrivial new task, pass only the current user request to
`skill-picker` on stdin. Use a quoted heredoc so request text is never
evaluated as shell syntax. If suggestions come back, show the ranked list with
a one-line reason each, ask which to use, and wait. If none come back, or the
status is `unavailable`, continue normally. Skip routing for simple questions,
follow-ups, and requests that already name a skill. Skip it when the request
contains credentials.
```

## How it ranks

Two calls, not one.

1. **Gate and shortlist.** Three questions ask whether the request wants a
   procedure at all. A fourth ranks your whole catalog by description. Below
   the gate floor it returns nothing and skips the second call, so "thanks!"
   costs half what a real task costs.
2. **Rerank the top three** against each skill's opening instructions, with a
   per-skill question asking whether it actually fits. Anything below the fit
   floor drops out, so a weak third suggestion disappears instead of padding
   the list.

A request that already names a skill or command returns `status: skipped`
without calling the API at all.

Tune with `--gate-floor` (default 0.20) and `--fit-floor` (default 0.30).
Raising them trades recall for precision.

## Measure it on your own catalog

Guessing whether routing works is how you end up with suggestions nobody
trusts. Label some requests and measure:

```jsonl
{"id":"unreproduced-report","request":"A customer says checkout sometimes hangs, but nobody has seen it locally.","expected":"suggestions","acceptable_skills":["reproduce-bug"]}
{"id":"plain-thanks","request":"Thanks, that explanation helped.","expected":"abstain"}
{"id":"already-chosen","request":"Use /review-diff on the current branch.","expected":"skip"}
```

```bash
skill-picker-eval --skills-dir examples/skills --cases examples/routing-cases.jsonl
```

You get top-1 accuracy, top-3 recall, mean reciprocal rank, false-positive and
false-negative rates, explicit-invocation bypass, token usage, and
mean/p50/p95 latency. `--json-output` writes the full per-case report.

One limit worth knowing. This measures the ranking after something calls it.
Whether your agent remembers to call it is a separate problem, and no
benchmark here will tell you.

## What leaves your machine

The request text, and the name, description, and opening instructions of your
skills. Not your conversation history, not your files, not your repository.

For `--actions` entries it also sends the command line, since that is what the
model ranks them by. Keep credentials out of those command strings.

The request goes over the wire word for word, so tell your agent to skip
routing when a message contains credentials. The prompts already treat the
request as data and tell the model to ignore any instructions hiding in it.

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t tests
```

The tests are offline and need no API key. Only `skill-picker-eval` and a real
`skill-picker` run call Jev. See [CONTRIBUTING.md](CONTRIBUTING.md) before
opening a pull request.

## License

MIT. See [LICENSE](LICENSE). Send a pull request and you license it the same
way.
