# OpenTTD 13.4 T09 parser fixture

`seed-17-simpleai-road.sav` is a genuine OpenTTD 13.4 save generated once for
T09 final-save parser tests. It is not T17 production acceptance evidence.

- OpenTTD: 13.4 (savegame version 302)
- Base graphics: OpenGFX 7.1
- AI: SimpleAI 14, road-only, with the pinned SimpleAI dependencies
- Seed: 17
- Game date: 1950-01-02 (OpenTTD game day 712224)
- Company ID 0: present
- Size: 99,264 bytes
- SHA-256: `062f7cb99d3fb4fb8ee722191c537331fd0f4e8e6f663b88ac3ab3b9d7ad7fad`

The runner used the acknowledged explicit `save final` command. The fixture
contains only the raw `.sav`; tests parse this static file and never regenerate it.
