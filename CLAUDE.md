# CLAUDE.md: working rules for emotion-analyzer

Taken from `specs.md` §15 (v1.2). If this file and the spec disagree, the spec wins.

## Source of truth

- `specs.md` is the source of truth. When the design or direction changes, update it first and record the reason in §20 (change log).
- `README.md` is the user guide, not the plan. The build checklist is `tasks.md`.

## Flow

- Work through `tasks.md` in order, phase by phase.
- At the end of each phase:
  1. Make sure its tests pass.
  2. Tick its tasks.
  3. Record problems in `issues.md` and results in `insights.md`.
  4. Commit as `Pn: …`.
  5. Give a short summary.

  Then carry straight on to the next phase.
- **USER** tasks block the build. Stop and ask; don't do them or work around them.
- **USER-ANYTIME** tasks don't block. Remind the user of them in each phase summary until they're done. Stop only if the phase that needs one arrives and it still isn't done.
- Also stop if something would contradict `specs.md`, or if a result fails an acceptance criterion in a way that changes the plan.

## After each finished task

1. Tick it in `tasks.md`.
2. Note problems in `issues.md`.
3. Note results and figures in `insights.md`.

## Tests

- Tests are the acceptance criteria (§11). Every phase ends with tests that pass.
- The git pre-commit hook (`.githooks/pre-commit`, enabled with `git config core.hooksPath .githooks`) runs the fast tests: under 60 s, no model downloads.
- Tests that need model weights are marked `slow`.
- Speech test clips are fixtures generated once with Windows' built-in text-to-speech (`tools/make_fixtures.ps1`) and committed in `tests/fixtures/`. Tests never call text-to-speech at run time and never use MELD audio.

## Python

- Use only the project virtual environment, built from `py -3.12` (`.venv\Scripts\python.exe`).
- Never use the system `python`: the one on PATH is a 3.14 interpreter from another project.

## Commands given to the user

- Put the working directory on its own line before every command.

## Timing

- Before timing anything, check that the laptop is on mains power. Ask only if it is on battery.

## Kaggle

- Training code lives in the project (`src/emotion_analyzer/`). `scripts/package_kaggle.py` builds `kaggle/code/` from it.
- The Kaggle steps live in `KAGGLE.md` as complete numbered cells, each with its expected output and run time. Update `KAGGLE.md` whenever a cell changes.
- The run has two passes: S0 interactively, then Save & Run All (Commit) in the background.
- Kaggle code:
  - uses both T4s where it helps;
  - runs the GPU stages as subprocesses with the corrected `LD_LIBRARY_PATH`;
  - keeps features in `/tmp` and only small results in `/kaggle/working`;
  - resumes from `state/` markers found in `/kaggle/working` or any `/kaggle/input/*/`;
  - stops safely before 12 h;
  - ends with one compact results block.
- Smoke-test locally on a tiny subset before any Kaggle run.

## Data, licences and secrets

- Never commit MELD audio. The app serves no audio files (§5.3).
- Per-utterance transcripts and predictions stay in the git-ignored `data/kaggle/`. `results/` holds aggregates only.
- Never use a banned checkpoint (§4.4), that is, any checkpoint already trained on MELD:
  - `j-hartmann/emotion-english-distilroberta-base`
  - `j-hartmann/emotion-english-roberta-large`
  - `tae898/emoberta-base` and `tae898/emoberta-large`
  - `michellejieli/emotion_text_classifier`
  - `andreasvc/segue-meld-multitask`
  - any `emotion2vec_plus_*`
- Never print or commit secrets. Read keys from `.env`, which is git-ignored.
