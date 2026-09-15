# Deploying the studio

## The one constraint that decides everything

The renderer **shells out to ffmpeg** and takes **12–30 s of CPU per clip**:

| Clip | Time (1 normal core) |
|---|---|
| 2 s, SD 512×512 | ~12 s |
| 2 s, HD 1280×720 | ~29 s |

That rules out serverless function hosts — **Netlify / Vercel functions cap at
~10 s and ship no ffmpeg**. It is also why the studio keeps its jobs in memory
and writes MP4s to disk.

So: **the engine needs a long-running container.** Render, Fly.io, Railway,
a VPS — anything that runs a Dockerfile and gives you real CPU.

> The split is clean, though. `plan → compile → diagnose → digest` takes
> **0.05–0.2 s** and needs only numpy. If you ever want a Netlify/Vercel
> presence, that half runs fine there as a function; only the pixel render and
> the audio mux need the container.

---

## Render (recommended)

The repo ships a `render.yaml` blueprint, so Render configures itself.

1. Push this branch to GitHub.
2. Render dashboard → **New +** → **Blueprint** → pick the repo.
3. Render reads `render.yaml`, builds the `Dockerfile`, and deploys.
4. First build takes a few minutes (apt + ffmpeg + pip).

Health check is already wired to `/api/health`.

### Plans, honestly

| Plan | CPU / RAM | What it feels like |
|---|---|---|
| **Free** | 0.1 CPU / 512 MB | Cold start ~1 min after 15 min idle. A 2 s SD clip takes **minutes**, not seconds. Fine for "does it work", painful to actually use. |
| **Starter** (~$7/mo) | 0.5 CPU / 512 MB | Always on. A 2 s SD clip lands in roughly 20–30 s. Usable. |
| **Standard** (~$25/mo) | 1 CPU / 2 GB | Comparable to a laptop. HD becomes practical. |

The free tier's 0.1 CPU is roughly **10× slower than the machine this was
developed on** — that is the whole reason the deployed build defaults to SD.

---

## Configuration

All of it is environment variables; nothing is hardcoded to a host.

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8770` | Injected by the platform. When set, the server binds `0.0.0.0`. |
| `STUDIO_HOST` | derived | Override the bind address explicitly. |
| `STUDIO_DEFAULT_SD` | off locally, **`1` in Docker** | Render 512×512 (≈4× cheaper than HD). |
| `STUDIO_MAX_FRAMES` | unlimited locally, **`240` in Docker** | Refuse clips longer than this. Guards against OOM on small instances. |
| `STUDIO_OUT_DIR` | `out/studio` | Where clips are written. Use `/tmp/...` on an ephemeral filesystem. |

The UI reads these from `/api/health` and adapts: it switches itself to SD and
shows the clip-length limit in the header.

---

## Notes and limits

- **Clips are ephemeral.** On a platform without a persistent disk, rendered
  MP4s live in `/tmp` and disappear on restart or redeploy. Add a Render Disk
  and point `STUDIO_OUT_DIR` at its mount path if you want them to survive.
- **One render at a time.** A lock serialises renders; extra requests queue.
  Two concurrent renders will OOM a 512 MB instance.
- **Jobs are in memory.** A restart loses the job list (the clips are already
  written, but the UI can no longer look them up).
- **No auth.** Anyone with the URL can spend your CPU. Put it behind Render's
  password protection or an access proxy before sharing it widely.
- **Audio is synthesised, not sampled** — no asset licensing to worry about.

---

## Run it locally

```bash
# the project interpreter (the managed one has no numpy)
"C:/Users/SATHYA TRADERS/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe" \
  tools/studio_server.py --open
```

Then http://127.0.0.1:8770

To mimic the container locally:

```bash
PORT=8791 STUDIO_DEFAULT_SD=1 STUDIO_MAX_FRAMES=144 \
  "<py>" tools/studio_server.py
```
