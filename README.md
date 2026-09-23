# skill-picker

You have thirty agent skills and remember four of them. This ranks your own
skills against what you just asked for, so your agent can offer the right one
and you decide whether to use it.

It prints JSON and takes no action. Nothing runs in the background, and no
skill is ever invoked for you.

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

## Give it an API key

Ranking runs on [TypeSafe](https://console.typesafe.ai/keys)'s Jev model. The
router reads a key from one of three sources and never stores one. The first
*configured* source wins: if a helper command is set and fails, that is an
error rather than a fallthrough to the key file, so a stale key can't be used
behind your back.

| Source | Use it when |
| --- | --- |
| `TYPESAFE_API_KEY` | CI, containers, a one-off run |
| `TYPESAFE_API_KEY_COMMAND` | your key lives in a secret manager |
| `~/.config/typesafe/api-key` | you just want it to work |

The simplest setup:

```bash
mkdir -p ~/.config/typesafe
printf '%s' 'YOUR_KEY' > ~/.config/typesafe/api-key
chmod 600 ~/.config/typesafe/api-key
```

That location follows `XDG_CONFIG_HOME` when you set it.

With a secret manager, point the router at any command that prints the key:

```bash
export TYPESAFE_API_KEY_COMMAND='op read "op://Private/TypeSafe/credential"'
export TYPESAFE_API_KEY_COMMAND='pass show typesafe/api-key'
export TYPESAFE_API_KEY_COMMAND='security find-generic-password -s typesafe -w'
```

That command runs without a shell, so metacharacters in it stay literal. Its
standard error is left connected to your terminal, so an unlock prompt is
visible rather than silently blocking, and neither its output nor its
arguments ever appear in an error message.

Without a key the router reports `status: unavailable` and your agent carries
on as before. Every skill stays invocable by name; routing only helps you find
one.

## Point it at your skills

It reads any directory of `<name>/SKILL.md` files with YAML frontmatter, the
layout Claude Code and `.agents` already use. `~/.agents/skills` is tried
first, then `~/.claude/skills`.

```bash
skill-picker --skills-dir ~/my-skills
export SKILL_PICKER_SKILLS_DIR=~/my-skills
```

A skill is routable when its frontmatter has a `description`. Set
`user-invocable: false` to keep one out of the ranking. The description is what
the model matches against, so write it for the situation the skill is for, not
the steps it performs.

Deterministic commands can compete in the same ranking through a JSON file:

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

1. **Gate and shortlist.** Three questions decide whether the request wants a
   procedure at all, and one ranks the full catalog by description. Below the
   gate floor it returns nothing and never makes the second call, so "thanks!"
   costs half of what a real task costs.
2. **Rerank the top three** against each skill's opening instructions, with a
   per-skill question asking whether it actually fits. Anything below the fit
   floor is dropped, so a weak third suggestion disappears instead of padding
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

This measures the router once it is called. It cannot tell you whether your
agent remembered to call it.

## What leaves your machine

The request text, and the name, description, and opening instructions of your
skills. Not your conversation history, not your files, not your repository.

For `--actions` entries the command line itself is sent, because that is what
the model ranks them by, so keep credentials out of those command strings.

Because the request is sent verbatim, tell your agent to skip routing for
messages containing credentials, and treat the request as untrusted data: the
router's prompts already instruct the model not to follow instructions found
inside it.

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t tests
```

The tests are offline. Only `skill-picker-eval` and a real `skill-picker` run
call the API.
