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

## P3 Speech pipeline

- PyAV 19.0.1 dropped the `metadata_errors` argument that `faster_whisper.decode_audio` 1.2.1 passes to `av.open`, so every decode failed. PyAV is pinned to 18.1.0, the newest that works.
- Equal-length chunking of long clips split words at chunk boundaries. `chunk_audio` now cuts at the quietest nearby frame.
- If S4 picks the 30 s window (the preliminary choice), latency is 1.71 s median and 1.93 s p90 against the 2.0 s limit. Other load on the laptop could push it over.
- The decode stage includes VAD, which takes about 0.1 s of the 117 ms. §5.3's timing keys have no separate VAD entry.

## P4 Training code

- In smoke runs, the temperature fit hits its upper bound (T = 20) when the text model is near-constant. This only happens with tiny settings. On Kaggle, a T at either bound would point to a training problem and should be checked in P6.

## P5 Kaggle package

- A batch of 32 full 30 s windows on the laptop CPU uses more memory than is free (attention scores alone are about 3.4 GB). The process dies silently with exit code 127 and an empty log. The cells now use `BATCH = 16` on Kaggle (fp16 on a 15 GB T4) and 4 in the dry run. The error messages say that an empty log usually means out of memory.
- In the dry run, train and test are copies of the same dev clips, so the three splits show the same WER. That is expected; the rehearsal checks the plumbing, not the numbers.
- On the laptop CPU, S0's re-estimate is about 18 GPU-hours and the verdict reads CHECK. Only Kaggle's T4 numbers count for the go-ahead.
