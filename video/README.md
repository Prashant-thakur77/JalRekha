# The NadiSaathi film, built from code

Every scene, line and number in the film comes from this folder and the repository's result files. Change a line or a
shot, re-run the commands, and the film rebuilds.

| Step | Command | Makes |
|---|---|---|
| Numbers | `python3 video/facts.py` | every number the film says, read from `eval/results/headline.json` |
| Narration | `~/.pyenv/versions/3.10.13/bin/python video/synth.py` | Chatterbox takes of `narration.py` in the reference voice; the take Whisper hears best is kept |
| Screen takes | `python3 video/record.py [flows]` | screencasts of the live app and of the AWS console (read-only federated session) |
| Privacy check | `~/Videos/jalrekha/.venv-ocr/bin/python video/check_private.py` | OCR of every AWS take; fails if the account id is readable |
| Film | `python3 video/film.py [--preview]` | footage, takes, drawn scenes (`gfx.html`), the 3D architecture scene (`three.html`), the composed theme (`music.py`), effects, captions, `NadiSaathi.mp4`, a 720p copy and an `.srt` |
| Thumbnail | `video/thumbnail.html`, screenshotted at 1920×1080 | the YouTube thumbnail |

Outputs go to `~/Videos/jalrekha/`. Prashant's camera lines are `~/Downloads/1.mov` … `8.mov`; each is matched to its
script line by Whisper and captioned with what was actually said. Footage, music, voice and fonts are listed in
`LICENSES.md`.
