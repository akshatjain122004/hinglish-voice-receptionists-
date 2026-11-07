# Architecture notes

Design choices and discoveries worth remembering, added as phases progress.

## Phase 0

- **Sarvam TTS: `bulbul:v2` is deprecated.** The API rejects it with
  `Model 'bulbul:v2' has been deprecated. Please use 'bulbul:v3' instead.`
  `bulbul:v3` also has a different speaker list than v2 (e.g. `anushka` is not
  valid on v3; `priya`, `neha`, `pooja` etc. are). `CLAUDE.md`'s "use Bulbul v2
  while developing" guidance is outdated — use `bulbul:v3` with one of its
  supported speakers instead. Smoke-tested 2026-11-07 with speaker `priya`,
  `target_language_code="hi-IN"`; output saved to `reports/sarvam_smoke_test.wav`.
