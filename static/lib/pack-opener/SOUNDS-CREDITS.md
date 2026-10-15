# Sounds

The ceremony's cues. `manifest.json` maps a cue to its file;
`pnpm build:sounds` bakes them into `src/core/sound/samples.js` as data URIs, so
the scene has nothing to fetch. MP3 (LAME VBR `-q:a 2`, 44.1 kHz, channels as
they were): every browser decodes it.

The files carry their own licences below; the package's MIT licence covers the
code, not them.

## Kenney — CC0, https://kenney.nl

Casino Audio and Sci-Fi Sounds, public domain, no attribution required.

- `pack-open-1.mp3`, `card-place-2.mp3`
- `engine-low-1.mp3` — a low hum, looped under the charge

## Freesound — CC0, https://freesound.org

Public domain, no attribution required. Each is at
`https://freesound.org/s/<sound>/`. The score's lead times are tuned to where
these peak; a host laying its own file over a cue (`sound.samples`) keeps the
beat by matching that.

- `magic.mp3` — "Boom" (236956), trimmed to 2 s: the slice's landing, a sub
  boom under the card.
- `reveal-sweep.mp3` — "GLEAM-GLOW-SFX-CHIME" (351408), as it is, trimmed to
  4.5 s. The slice's sweep; the score starts it 2 s before the card lands.
- `impact.mp3` — "Riser Hit sfx 054" (712713), led by silence and trimmed to
  3.1 s: hits 0.94 s in, so the score starts it that much early. The slice's.
- `burst-sweep.mp3` — "Chimes" (389789), as it is, trimmed to 4.5 s. The
  burst's sweep, cued like the slice's.
- `burst-impact.mp3` — "Riser Hit sfx 041" (649066), led by silence and
  trimmed to 3.1 s: hits 0.94 s in. The burst's impact.
- `burst-magic.mp3` — "Ramon's Sexy Sub Drop 6000" (346316), trimmed to 2 s:
  the burst's landing, a sub drop under the card.
- `blast.mp3` — "POWERFUL RUMBLY HELLISH IMPACT" (826216), led by silence
  and trimmed to 4 s: the impact 0.57 s in, on the burst's flash frame.
- `ring-step.mp3` — "Points_Tick2" (721514), as it is: a click as the ring
  turns past a copy.
- `ring-whoosh.mp3` — "robowhoosh electrobass 4" (807444), as it is: under
  each fact, the banner, the chosen pack rising.
- `pack-select.mp3` — "Sound Design Elements Impact SFX PS 011" (751356),
  trimmed to 3.6 s: the tap that chooses a copy, its hit 0.4 s in.
- `chime.mp3` — "Vibrato Celesta C" (573617): on the flip.

## Rendered — our own

Synthesised with Web Audio (`OfflineAudioContext`, 44.1 kHz stereo, fixed
seeds) and rendered once in Chrome; react-native-audio-api renders the same
graph thinner, so they ship as files rather than being synthesised on load.

- `swish.mp3` — the air the turning card cuts
- `whoosh-deep.mp3` — the lid coming off
- `sub-hit.mp3` — the weight under it
- `boom.mp3` — the burst's blast
