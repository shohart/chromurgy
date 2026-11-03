# Deployment (single Linux host)

```sh
sudo useradd --system --home /var/lib/mfilm --create-home mfilm
sudo mkdir -p /opt/mfilm /etc/mfilm && sudo chown "$USER" /opt/mfilm
git clone <this repo> /opt/mfilm && cd /opt/mfilm
cmake -S . -B build && cmake --build build -j
cd src/server && uv venv .venv && uv pip install -e . --python .venv/bin/python && cd ../..
sudo cp config.example.toml /etc/mfilm/config.toml        # edit export_dir / index_command
sudo -u mfilm MFILM_CONFIG=/etc/mfilm/config.toml src/server/.venv/bin/mfilmctl init
sudo cp deploy/systemd/mfilm-worker.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now mfilm-worker
```

Importing a card (the worker picks the queued frames up):

```sh
MFILM_CONFIG=/etc/mfilm/config.toml mfilmctl import-card /media/$USER/CANON_DC --dry-run
MFILM_CONFIG=/etc/mfilm/config.toml mfilmctl import-card /media/$USER/CANON_DC
mfilmctl list-rolls
```

Network sync (docs/09), once a camera can speak HTTP:

```sh
mfilmctl device-pair --name sx510hs          # prints the token once; revoke with device-revoke
sudo cp deploy/systemd/mfilm-receiver.service /etc/systemd/system/ && sudo systemctl enable --now mfilm-receiver
# a fake camera against it (reference client for the CHDK sync code):
python -m mfilm_server.simulator --server http://127.0.0.1:8765 --token TOKEN --card /path/to/card --pull
```

## PhotoPrism checklist

- `export_dir` must be the directory PhotoPrism mounts as originals, seen from
  the host the worker runs on. Check with
  `docker inspect photoprism --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'`
  and confirm the published folder shows up in `docker exec photoprism ls /photoprism/originals/M-Film`.
  A CIFS/Samba mount of "the same" path can be rooted somewhere else on the server.
- The `mfilm` user needs write access to `<export_dir>/M-Film` only (create it and
  chown it once); nothing else in the library is touched.
- Mount order: if originals live on a separately mounted disk, a container that
  starts before the mount binds the empty mount point and PhotoPrism sees an
  empty library. Make Docker (or the container unit) wait for it, e.g. a
  drop-in with `RequiresMountsFor=/mnt/theVault`, and set the same on
  `mfilm-worker.service`.
- Indexing: PhotoPrism does not watch originals (`PHOTOPRISM_AUTO_INDEX` is for
  WebDAV uploads only). Set `PHOTOPRISM_INDEX_SCHEDULE` or `index_command`.
