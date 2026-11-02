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
