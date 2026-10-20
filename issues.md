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

## Kaggle run

- The interactive S0 pass was skipped: the user committed the notebook directly. It worked because S0 printed GO inside the commit, but a failed CUDA check would only have shown up after the full run had used the transformers fallback. Recorded in `specs.md` §20 (v1.3).
- The outputs were unpacked into `models/emotion_outputs/` instead of being left as a zip in Downloads. P6 moved the folder to `data/kaggle/emotion_outputs/`, where per-utterance data belongs (F3).
- Kaggle's image runs Python 3.13.15 and torch 2.11.0, against 3.12.10 and torch 2.14.1 on the laptop. The text models saved there load unchanged here (transformers 5.20.2 on both sides), and fp32 CPU outputs match the Kaggle ones on 99.9% of dev clips.
- Twelve MELD train clips are under 0.1 s and were dropped in S2 (`logs/S2_dropped.txt`), on top of the known missing `dia125_utt3`.

## P6 Import and parity

- **int8 dynamic quantisation hurt the text model.** On dev it changed 14.8% of the text labels, cost 1.29 points of weighted-F1 (50.30 → 49.01) and dropped the mean top probability from 0.55 to 0.39. Its outputs also depended on batch composition (49.01 or 49.40 for the same sentences in a different order), because activations are quantised per batch. fp32 on the CPU matches Kaggle, so the text model is now deployed in fp32 (§8.3, v1.3), at about 10 ms more per clip and lower peak memory.
- `tasks.md` said to fit the temperatures and weight on "the Kaggle dev probabilities"; for an int8 text model that would have left the deployed branch uncalibrated (test ECE 16.0). Corrected to the deployed models' dev probabilities, as §8.4 states. With fp32 the two coincide.
- The P7 evaluation functions (`evaluate.py report/own`, `chatbot_compare.py`) were written while the 33-minute parity pass ran, so they share the P6 commit; P7 runs them and commits their results.
- Bash here-documents again mangled backslashes and long Python snippets twice (a broken string literal in `latency.py`, a failed `tasks.md` edit). Fixed with the Edit tool and a script file in the scratchpad.

## P7 Evaluation

- **Gemini's free tier allows 20 requests a day per model.** The first chatbot run used `gemini-3.8-flash`. After 20 clips it got `429 RESOURCE_EXHAUSTED` (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, limit 20), and the script lost all 20 answers because it only wrote `chatbot_raw.csv` at the end.
  - Fixed: each answer is now appended as it arrives.
  - A rerun resumes on the same model, and a used-up daily quota stops the run cleanly with a partial report.
  - The rerun found `gemini-3.7-flash` already out of quota too, so it used `gemini-3.5-flash` (served as `gemini-3.6-flash`).
  - It had answered 10 clips, slowly, with the client retrying while the service was busy, when the user put a new key in `.env`. That run was stopped and resumed on the same model with the new key.
  - The new key's daily quota ran out after 17 more requests, so 27 of 28 clips are answered.
  - The user chose to commit P7 with the report marked partial and send the last clip (surprise_04) after the quota resets.
- **New voices: the sound branch doesn't transfer.** On the 28 own recordings, sound is 28.6% accurate, against 60.7% for text. Because w_sound is 0.75 (fitted on MELD dev), the fused answer follows the sound branch and gets 35.7%.
  - Not changed: the weight is fitted on dev by the spec's rule, and 28 clips are too few to refit it on.
  - Reported in `own_recordings.md` and `insights.md`.
- The own recordings are 28 clips, not the 30–50 that §7.3 asks for (4 per emotion, which meets the minimum per class).
- The Kaggle text prediction files list test clips in a different order from the sound files. Rows scored on their own are unaffected. `fusion_gains` reorders by id before pairing rows, and `fusion.align` already does this for fusion.
- A Bash here-document turned `"\n"` in a Python snippet into real line breaks again (in `evaluate.keep_discussion`). Fixed with the Edit tool.

## P7 rework (spec v1.4)

- **The fusion rule changed after the held-out recordings were seen.** The own recordings prompted the refit, so they no longer measure the system blind. This is recorded in spec §20, `own_recordings.md`, `chatbot.md` and `results_table.md`, which also shows the old weight's MELD test rows. MELD test was not used to choose the weight.
- MELD's train and test CSVs (no audio) were downloaded to count speakers before §7.4 allowed it; v1.4 adds them to §7.4. `data.download_meld_meta()` fetches them.
- The laptop came off mains during the rework. A processing time measured on battery (2.19 s per own clip) was discarded, and every timing was redone on mains after the user plugged in.
- The test `test_fit_chooses_the_weight_on_the_masked_clips_only` first assumed the unmasked weight would be above 0.5. Calibration flattens a mostly-wrong branch, so it was 0.2. The test now checks that the masked weight is lower.

## P8 App

- **Analyses slow down after sustained load.** After about half an hour of back-to-back analyses (headless-browser checks and curl loops), processing time rose from 1.65 s to 2.6–2.7 s per clip.
  - Almost all of it was the Whisper encoder (1.2 s → 2.1 s).
  - The laptop was on mains in the "Best performance" power mode, with the CPU at about 80% of its rated speed.
  - It happened through curl with no browser open too, and with no leftover headless processes, so it's the machine's state (most likely heat), not the page.
  - The AC-08 measurement (median 1.65 s, protocol in §10.5) stands. A hot laptop will show slower times in the live demo. Not changed.
- Page bugs found in the browser checks, all fixed:
  - the header's class `.top` collided with the class that marks the top probability bar, so that row took the header's styles (renamed `.site-header`);
  - a blanket CSS `text-anchor: middle` overrode the SVG labels' own anchors, so the stage timings sat on the arrows;
  - `calc()` can't multiply two percentages, so the bars in the results table didn't draw;
  - passing `null` to `replaceChildren` printed "null" in the right/wrong banner.
- Headless Chrome won't make a window narrower than about 500 px, and a 390 px iframe stalled the page's report request. Phone width was checked with DevTools device emulation instead.
- A Bash here-document mangled `"\n"` in a Python edit script again (the chatbot JSON edit). Fixed by writing the script with the Write tool.

## P9 Deployment

- **The campus Wi-Fi (`iiscwlan`) is a Public network to Windows**, and campus networks often isolate devices from each other. The firewall rule and the switch to Private are the user's administrator steps. If the phone still can't connect, the README's hotspot fallback or the tunnel applies.
- **`python.exe` already has inbound Allow rules on the Public profile** (for the base Python 3.12 that the venv's launcher runs, and for Miniconda), left from earlier Windows prompts. So any Python server on this laptop accepts connections on public networks. Not changed: it predates the project, and only the user can review it.
- **Checks from the laptop can't prove the firewall lets a phone in.** Windows doesn't filter a machine's traffic to its own LAN address, so the smoke checks through `https://10.217.15.89:8443` test the server, the binding and the certificate, not the firewall. Only the phone test does that.
- **The first `offline_check.ps1` would have passed with the network on.** It tested the internet with ping, which the campus network blocks. Now it makes HTTPS requests to huggingface.co and 1.1.1.1, and a dry run with Wi-Fi on reports "NOT VALID".
  - The same dry run caught a second bug: Windows PowerShell 5.1 doesn't unroll a parsed JSON array, so the script fell back to the speech fixture instead of a demo clip.
- **A near-tie can flip between server restarts.** Within one running server, the same clip gives the same probabilities every time (5 repeats). But `disgust_01` is a near-tie (anger 0.218, surprise 0.217), and its fused answer was surprise in one server process and anger in another. The Results page claimed "the same clip always gets the same answer"; it now says a clip sent again to the running server gets the same answer.
- Windows PowerShell 5.1 turns a native program's stderr into errors when output is redirected, which would stop the scripts under `$ErrorActionPreference = "Stop"`. The scripts use `Continue` and check exit codes. `$profile` is a built-in variable and was renamed in `serve.ps1`.
- A Bash here-document mangled `"\n"` in the access-log code again (a syntax error the tests caught). Fixed with the Edit tool.
- Processing times during the P9 checks were 2.6–2.9 s per clip, against the 1.65 s benchmark. This is the same slow-CPU state recorded in P8, with about 1.3 GB of memory free during the checks.
- **The phone's tunnel test isn't in the log.** The user reported the tunnel link working on mobile data, but none of the phone's requests reached the tunnel.
  - `logs/server.log` has no request from the phone with `cf_ip`.
  - cloudflared's own metrics counted 33 proxied requests with no errors. That is exactly the 33 `cf_ip` lines from the P9 checks (curl and headless Chrome).
  - The phone's second session (22:26–22:27: a demo click, then Run all demos) came straight over the Wi-Fi, in the page that was already open, with no page load. A likely cause: Android stays on Wi-Fi when mobile data is switched on, so that open tab was still the LAN page.
  - To redo: switch the phone's Wi-Fi off and open a new tunnel address. The quick tunnel's address changes on every run.
- The campus Wi-Fi turned out not to isolate devices: once the user set it to Private, the phone reached the laptop directly. The hotspot fallback wasn't needed.

## P9, spec v1.6: no demo clips

- **The user's demo clips were public while the tunnel ran** (22:05–22:30). Anyone with the tunnel address could have played the 7 recordings in `app/static/samples/`. The user removed the demo clips from the page (v1.6).
  - Nobody else fetched them. The access log saw only four client addresses: the phone, the laptop's LAN address, localhost, and the campus address of my own tunnel checks.
  - All 24 clip downloads were the P9 checks or the phone's demo run.
  - cloudflared's own counter (33 requests) matches the 33 tunnel lines, all from the checks.
- The clips were never committed (`app/static/samples/` was git-ignored, and the repository has no remote), so they aren't in the git history either.
- `data/own/demo_ok.txt` is no longer read. If it stays, `evaluate own` lists it among the skipped files.
- `results/own_recordings.md`, `results/chatbot.md` and `results/chatbot_raw.csv` list each own recording by file name (emotion and number) with its true label and the predictions. They hold no audio, transcripts or speaker details, and the web page doesn't use them (it reads the `.json` aggregates). Raised with the user, not changed.
- Two slips while making the change, both caught before the tests:
  - a shell escape turned `\f` into a form feed in a README path;
  - PowerShell read `"$got:"` as a scoped variable, now `${got}`.
- **The second round of phone tests and the offline check (reported at 22:50) aren't in the evidence.** They are not recorded as done.
  - Since the 22:45 restart, every line in `logs/server.log` is a P9 check (curl and headless Chrome), and the tunnel counter is still 16, exactly those checks.
  - The phone's last request was at 22:27, in the earlier Wi-Fi session.
  - `results/offline_check.txt` doesn't exist. Windows' Wi-Fi log has no disconnect since 13:06. The server held port 8443 the whole time, so `offline_check.ps1` would have stopped at once with "Port 8443 is in use".

## P10 Transcript

- **One turn's message had no empty line after it.** In turn 14 the export put "Ran 2 shell commands" straight after the user's message, so "the message ends at the first empty line" swallowed that line into it. The session-log check caught it (13 of 17 turns matched). The converter now ends a message at the first line that isn't padded to the terminal width, and the test covers that case.
- The export shortens long tool output itself ("… +N lines (ctrl+o to expand)"), so `transcript.html` shows what the export holds. The full output is only in the session's `.jsonl` log, outside the repository.
