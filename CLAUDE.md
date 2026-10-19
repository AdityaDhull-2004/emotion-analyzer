# CLAUDE.md: working rules for emotion-analyzer

Taken from `specs.md` §15. If this file and the spec disagree, the spec wins.

## Source of truth

- `specs.md` is the source of truth. When the design or direction changes, update it first and record the reason in §20 (change log).
- `README.md` is the user guide, not the plan. The build checklist is `tasks.md`.

## After each finished task

1. Tick it in `tasks.md`.
2. Note problems in `issues.md`.
3. Note results and figures in `insights.md`.
4. Commit.

## Tests

- Tests are the acceptance criteria (§11). Every phase ends with tests that pass.
- The git pre-commit hook runs the fast tests: under 60 s, no model downloads.
- Tests that need model weights are marked `slow`.

## Python

- Use only the project virtual environment, built from `py -3.12` (`.venv\Scripts\python.exe`).
- Never use the system `python`: the one on PATH is a 3.14 interpreter from another project.

## Commands given to the user

- Put the working directory on its own line before every command.

## Kaggle

- Training code lives in the project (`src/emotion_analyzer/`); `scripts/package_kaggle.py` builds `kaggle/code/` from it.
- The Kaggle steps live in `KAGGLE.md` as complete numbered cells, each with its expected output and run time.
- Update `KAGGLE.md` whenever a cell changes.
- Kaggle code uses both T4s where it helps, checkpoints to `/kaggle/working`, resumes after interruption, stops safely before 12 h, and ends with one compact results block.
- Smoke-test locally on a tiny subset before any Kaggle run.

## Data, licences and secrets

- Never commit MELD audio, and never use it as demo samples.
- Never use a banned checkpoint (§4.4), that is, any checkpoint already trained on MELD:
  - `j-hartmann/emotion-english-distilroberta-base`
  - `j-hartmann/emotion-english-roberta-large`
  - `tae898/emoberta-base` and `tae898/emoberta-large`
  - `michellejieli/emotion_text_classifier`
  - `andreasvc/segue-meld-multitask`
  - any `emotion2vec_plus_*`
- Never print or commit secrets. Read keys from `.env`, which is git-ignored.

## Tasks that need the user

- Tasks marked **[USER]** in `tasks.md` (Kaggle runs, own recordings, the API key, the firewall rule, phone checks, §17 decisions) need the user. Stop and ask; don't do them or work around them.
