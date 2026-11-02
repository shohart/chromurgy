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

The receiver API (`mfilm-receiver`, docs/09) is not implemented yet: SD import is the transport.
