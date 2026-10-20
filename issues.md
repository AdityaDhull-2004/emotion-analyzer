# Issues

Known problems and errors, newest at the bottom of each phase.

## P1 Scaffold

- `torch.ao.quantization.quantize_dynamic` (§8.3) is deprecated in torch 2.14.1 in favour of torchao, but still works (the quantised engine is `onednn` on this laptop). torch is pinned, and pytest filters the warning.
- Two repository hygiene files that §13 doesn't list: `.gitattributes`, which keeps `.githooks/pre-commit` on LF line endings because `core.autocrlf` is true and sh fails on CRLF; and `*.egg-info/` in `.gitignore`, which the editable install creates.
- Free RAM was 1.6 GB at the start of the build. Model-heavy steps run one at a time.

## P2 Data

- MELD dev `dia99_utt3` and `dia108_utt5` are 0.064 s long (1,024 samples). They are below the 0.1 s floor, so they are dropped after the join assertion (§7.1). Dev has 1,106 usable clips.
- MELD dev has four audio files with no CSV row (`dia49_utt4`, `dia49_utt5`, `dia66_utt9`, `dia66_utt10`). They are ignored, as §7.1 says.
- Moving the 1,112 extracted files took about 3 minutes, probably because Windows Defender scans each file. Expect slow local file operations on audio folders.
