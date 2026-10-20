# Generates the speech test fixtures in tests/fixtures/ with Windows' built-in
# text-to-speech (System.Speech), as 16 kHz mono 16-bit WAV (spec sections 13 and 15).
# Run once; the WAV files are committed so tests never call text-to-speech.
#
# Working directory: E:\AIDS\Project\emotion-analyzer
#   powershell -ExecutionPolicy Bypass -File tools\make_fixtures.ps1

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech

$outDir = Join-Path $PSScriptRoot "..\tests\fixtures"
New-Item -ItemType Directory -Force $outDir | Out-Null
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono)

function Write-Speech($name, $sentences, $pauseMs) {
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synth.Rate = 0
    $prompt = New-Object System.Speech.Synthesis.PromptBuilder
    foreach ($s in $sentences) {
        $prompt.AppendText($s)
        $prompt.AppendBreak([TimeSpan]::FromMilliseconds($pauseMs))
    }
    $path = Join-Path $outDir $name
    $synth.SetOutputToWaveFile($path, $format)
    $synth.Speak($prompt)
    $synth.Dispose()
    Write-Output ("{0}: {1} bytes" -f $name, (Get-Item $path).Length)
}

# About 5 s: one utterance, the normal-clip case.
Write-Speech "speech_short.wav" @(
    "I can't believe you did that. That was the best surprise ever."
) 100

# About 24 s with pauses: the long-recording case, split into segments by VAD.
Write-Speech "speech_long.wav" @(
    "Good morning, everyone, and thank you for coming today.",
    "I was really worried that nobody would show up.",
    "The train was late again, and I nearly missed the meeting.",
    "But now I feel much better, because you are all here.",
    "Let's get started with the first item on the list."
) 1000
