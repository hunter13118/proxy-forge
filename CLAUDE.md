# CLAUDE.md — proxy-forge
Personal MTG proxy maker (deck list -> generated art -> printable cards). Spec: `SPEC.md`; how it works: `README.md`.

- Run: `start-proxy-forge.ps1` (needs the studio up on 7860: all model work goes to its `/v1/ai` API, see `../ebook-av-service/docs/AI-API.md`). Tests: `.venv\Scripts\python.exe -m pytest`.
- Official art (Archive / Vault, `printings.py`, `resolver.py`, `vault.py`, `scans.py`) is local + Scryfall, no GPU: see README "Official art". Network jobs run on the `net` worker.
- Models are the studio's, never called directly (`proxy_forge/studio.py` is the only client): need something new from them? Add it to the studio's `/v1/ai`. `D:\studio-kit` (installed editable) still supplies the Clerk sign-in check.
- Never install on C:. Data on `G:\proxy-forge-data`. pip fails while the broken `Programs\Ollama` folder is on PATH: filter it out first (see `start-proxy-forge.ps1`).
- Reference photos are personal data: never commit them and never send them off the machine (the studio, which runs the vision model and the trainer, is on this machine and deletes the photos after training).
- Never push or add remotes unless told. Personal use only: Anima's licence is non-commercial.
- Say what was and was not verified (a card actually drawn? the page actually opened?).
