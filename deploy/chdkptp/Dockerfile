# SPDX-License-Identifier: GPL-2.0-only
# chdkptp (CLI, USB + PTP/IP) and the Canon UPnP pairing helper, pinned.
#   deploy/chdkptp/fetch_svn.py https://subversion.assembla.com/svn/chdkptp 1535 trunk build/chdkptp-src
#   docker build -t mfilm-chdkptp -f deploy/chdkptp/Dockerfile build/chdkptp-src
#   USB:    docker run --rm --privileged -v /dev/bus/usb:/dev/bus/usb mfilm-chdkptp -e"connect" -e"ls A/"
#   Wi-Fi:  docker run --rm --network host mfilm-chdkptp -e"connect -h=<camera ip>" ...
#   pairing helper: docker run --rm --network host --entrypoint ptpip-canon-upnp-helper mfilm-chdkptp <server ip>
FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ca-certificates libusb-dev liblua5.3-dev libreadline-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*
# chdkptp trunk r1535, exported by fetch_svn.py (the svn client hangs on assembla)
COPY . /src
WORKDIR /src
RUN printf 'USE_LUA_VER=53\nPTPIP_SUPPORT=1\nREADLINE_SUPPORT=1\nLUA_INCLUDE_DIR=/usr/include/lua5.3\nLUA_LIB=lua5.3\n' > config.mk \
    && make -j"$(nproc)" && ls -la chdkptp

FROM debian:bookworm-slim
ARG HELPERS_COMMIT=7be8abc6d907aa23942e25f2d88976b887916761
RUN apt-get update && apt-get install -y --no-install-recommends \
      libusb-0.1-4 liblua5.3-0 libreadline8 python3 python3-pip ca-certificates curl \
    && pip3 install --break-system-packages --no-cache-dir ssdpy==0.4.1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/chdkptp /opt/chdkptp/chdkptp
COPY --from=build /src/lua /opt/chdkptp/lua
RUN curl -fsSL -o /usr/local/bin/ptpip-canon-upnp-helper \
      https://raw.githubusercontent.com/reyalpchdk/ptpip-canon-helpers/${HELPERS_COMMIT}/ptpip-canon-upnp-helper.py \
    && curl -fsSL -o /usr/local/bin/ptpip-canon-desc-helper.py \
      https://raw.githubusercontent.com/reyalpchdk/ptpip-canon-helpers/${HELPERS_COMMIT}/ptpip-canon-desc-helper.py \
    && chmod +x /usr/local/bin/ptpip-canon-upnp-helper
ENV CHDKPTP_DIR=/opt/chdkptp LUA_PATH=/opt/chdkptp/lua/?.lua;; 
WORKDIR /work
ENTRYPOINT ["/opt/chdkptp/chdkptp"]
