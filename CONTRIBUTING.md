# Contributing

Thanks for looking. This tool has one job. It ranks a user's own skills
against one request and prints the ranking. I merge changes that keep it that
small; I push back on ones that grow it.

## Set up

Python 3.11 or newer. No dependencies, and nothing to install before you can
run the tests.

```bash
git clone https://github.com/MuskanPaliwal/skill-picker
cd skill-picker
PYTHONPATH=src python3 -m unittest discover -s tests -t tests
```

The suite is offline, so it needs no API key and costs nothing. CI runs
exactly that command on 3.11 and 3.13.

To try the real thing you need a key from
[console.typesafe.ai/keys](https://console.typesafe.ai/keys):

```bash
export TYPESAFE_API_KEY=your-key
echo "a customer says checkout hangs sometimes" \
  | PYTHONPATH=src python3 -m skill_picker.cli --skills-dir examples/skills
```

## Where things live

| File | Responsibility |
| --- | --- |
| `src/skill_picker/catalog.py` | reading `SKILL.md` files and action JSON |
| `src/skill_picker/router.py` | the gate, the shortlist, the rerank |
| `src/skill_picker/typesafe.py` | the Jev call and API key resolution |
| `src/skill_picker/cli.py` | the `skill-picker` command |
| `src/skill_picker/evaluate.py` | the `skill-picker-eval` harness |

## What a good change looks like

**Keep it dependency-free.** Anyone should be able to install this without
thinking about their environment. If something needs a library, it probably
belongs in a caller rather than here.

**Write the failing test first** when you change behavior, and quote the
failure in the pull request. A test written after the code tends to describe
what the code does rather than what a user needs.

**Do not add configuration for its own sake.** Every flag is a thing users
have to read about. The defaults should be right for most people.

**Changing how ranking works** means touching prompts or floors in
`router.py`. Unit tests cannot judge those. Run the evaluation before and
after on the same catalog, and paste both reports into the pull request:

```bash
skill-picker-eval --skills-dir examples/skills --cases examples/routing-cases.jsonl
```

A change that raises top-1 accuracy while raising the false-positive rate is a
trade, not an improvement; say which you chose and why.

**Adding an example skill** means adding at least one labeled case for it in
`examples/routing-cases.jsonl`. A skill with no case is a skill nobody has
checked is reachable.

## Secrets

Never paste an API key into an issue, a pull request, or a test fixture. The
tool keeps keys, helper output, and helper arguments out of its error
messages. If you find a path where one escapes, report it through GitHub's
private security advisories rather than a public issue.

## Pull requests

Say what changed, why it needed to change, and how you know it works. Small
and specific beats broad and clever. When you send a pull request you license
your contribution under the MIT terms in `LICENSE`.
