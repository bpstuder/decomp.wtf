# Running decomp.wtf as a service

The root `docker-compose.yml` is the app in its simplest form. `docker/compose.yaml` is what a
server needs on top of it: a pinned image, the front door's hostname declared, the install
identified so a rebuild actually lands, and the games directory mounted read-only.

```bash
cp docker/compose.yaml docker/.env.example <app-dir>/
# edit <app-dir>/.env: DECOMP_ALLOWED_HOSTS, DECOMP_ROMS, and (if you must) DECOMP_SUBNET
docker compose -f <app-dir>/compose.yaml up -d --build
docker compose -f <app-dir>/compose.yaml exec decomp decomp url    # the signed-in address
```

The app's home is the bind mount `${DECOMP_DATA}` on the host (the deployment uses
`/opt/selfhosted/data/decomp-wtf`) — not a named volume, so `/home/decomp`'s contents (its install,
`Decomp/` with the projects, `.decomp/` with the database and the log) are an ordinary directory you
can read, grep, copy and edit. The install itself lives there too, which is what makes
`DECOMP_INSTALL_ID` meaningful: the entrypoint only reinstalls the app when that marker changes.

Back it up, with a shell you can read afterwards:

```bash
docker compose -f <app-dir>/compose.yaml stop
tar -czf "/opt/selfhosted/backups/decomp-wtf-$(date -u +%Y%m%dT%H%M%SZ).tar.gz" -C "$DECOMP_DATA" .
docker compose -f <app-dir>/compose.yaml up -d
```

A copy made while the app ran would hold a live SQLite database, hence the `stop` first; the log
(`Decomp/.decomp/logs/decomp.log`) is the one to read when an import fails, and it is in the same
directory.

## What the first start does

`site/public/linux-base.sh` builds the Debian base the app runs on, and the Dockerfile copies this
checkout's `pyproject.toml`, `README.md`, `LICENSE` and `src` into
`/usr/local/share/decomp-wtf/src` with `DECOMP_SOURCE` pointing at it. The entrypoint installs the
app **from the image** into the volume on first start (a few minutes), then `decomp setup` downloads
the free compilers and drafts toolchain. There is no dependency on GitHub or on decomp.wtf's download
site, and the app records channel `image`, so its own update button stays out of the way:

```
$ docker logs <container> | head -4
decomp.wtf: installing (the first start takes a few minutes)
▸ uv 0.13.1
▸ installing decomp.wtf from /usr/local/share/decomp-wtf/src
$ docker exec <container> decomp update --check
decomp.wtf 0.10.7 is up to date
```

## Publishing it on a tailnet (Tailscale `serve`)

Tailnet-only, so the app's token URL is enough to log in; nothing is exposed to the internet.

1. **Define the service** — the CLI cannot do this: `PUT /api/v2/tailnet/-/services/svc:<name>`
   with `{"name": "svc:<name>", "ports": ["tcp:443"], "tags": ["tag:server"], "comment": "..."}`.
   Copy the shape of a service that already exists (`GET .../services/svc:<other>`) so ports and
   tags match. The name gets a TailVIP in `addrs`.
2. **Point the host at the app**:
   `tailscale serve --service=svc:<name> --bg --https=443 http://127.0.0.1:6464`
3. **Approve this node** for the service:
   `POST /api/v2/tailnet/-/services/svc:<name>/device/<nodeId>/approved` with the body
   **`{"approved": true}`**. An empty body returns 200 and approves nothing.
   Get `<nodeId>` from `GET /api/v2/tailnet/-/devices` (match the hostname).

Then `https://<name>.<magicdns-suffix>` opens the app, and the TLS cert is issued for that name.
Without step 3 the name resolves and answers nothing; without `DECOMP_ALLOWED_HOSTS` the app answers
403 `bad host` to every request through it.

The same reasoning applies to any reverse proxy: give the app the name it will be reached by (or
rewrite `Host` in the proxy), because it deliberately refuses unknown Host headers.

## Updating after a code change

The image is the artefact; there is no release channel for this fork.

```bash
cd <checkout>                        # edit code, then:
DECOMP_INSTALL_ID=$(date -u +%Y%m%d-%H%M%SZ)
sed -i "s/^DECOMP_INSTALL_ID=.*/DECOMP_INSTALL_ID=$DECOMP_INSTALL_ID/" <app-dir>/.env
docker compose -f <app-dir>/compose.yaml up -d --build
docker compose -f <app-dir>/compose.yaml logs -f decomp   # "installing decomp.wtf from ..."
```

Not bumping `DECOMP_INSTALL_ID` is the classic trap: the image rebuilds, the container restarts, and
the volume keeps running the old install, because the entrypoint only reinstalls when the recorded
marker differs.

## ROMs and what the app may hold

The app ships no game code and provides no ROMs. Mount the games you own read-only and import them
by path. The only binary ROM in this repository is
`src/decompnet/app/static/demo/demo-quest-64.z64` — Demo Quest 64, which
`projects/demo-rom/build.py` rebuilds from CC0 sources plus zlib 1.1.4 (Zlib license); it is small,
it contains no third-party game code, and `tests/test_rom.py` proves every function in it matches the
source in `projects/`.
