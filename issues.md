# Issues

Known problems and errors, newest at the bottom of each phase.

## P1 Scaffold

- `torch.ao.quantization.quantize_dynamic` (§8.3) is deprecated in torch 2.14.1 in favour of torchao, but still works (the quantised engine is `onednn` on this laptop). torch is pinned, and pytest filters the warning.
- Two repository hygiene files that §13 doesn't list: `.gitattributes`, which keeps `.githooks/pre-commit` on LF line endings because `core.autocrlf` is true and sh fails on CRLF; and `*.egg-info/` in `.gitignore`, which the editable install creates.
- Free RAM was 1.6 GB at the start of the build. Model-heavy steps run one at a time.
