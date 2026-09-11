# amiga helpers

Hatcher-UAE-ScreenMode picks an available UAE mode before IPrefs starts.
It writes ENV: only, leaving the saved VideoCore prefs alone.

Rebuild from the repo root (Docker, Apple Silicon):

```sh
docker run --rm --network none -v "$PWD:/work" -w /work/amiga \
  amigadev/crosstools@sha256:369734d6aa2aa3650487b2b2b529fdadd2a6ecf0618947677165c676bbc996de make
```

With a local m68k-amigaos toolchain, run 'make -C amiga'. The compiled
binary is bundled; building Hatcher itself doesn't need a cross-compiler.
