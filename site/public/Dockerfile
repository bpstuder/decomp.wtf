# decomp.wtf in Docker, for servers (docker-compose.yml in the repository does this for you).
# Build context is the REPOSITORY ROOT, so the fork's own source is baked in:
#   docker build -t decomp-wtf -f site/public/Dockerfile .
#
# The same Linux as decomp.wtf's WSL system on Windows (linux-base.sh). decomp.wtf itself installs into the
# decomp user's home on the first start: keep /home/decomp on a volume, and updates it installs itself stay.
#
#   docker run -d --name decomp-wtf -p 127.0.0.1:6464:6464 -e DECOMP_PORT=6464 \
#     -v decomp-wtf-home:/home/decomp decomp-wtf
#   docker exec decomp-wtf decomp url    (the address that opens it, signed in)
#
# Because the source is copied in and DECOMP_SOURCE points at it, the image needs neither GitHub nor
# decomp.wtf's download site to produce a working install: the image is the artefact, so an update is a
# rebuild + redeploy (not `decomp update` inside the container). Bump DECOMP_INSTALL_ID on the deployment
# to force the volume's install to be redone from the new image. Publishing the app behind a front door
# (Tailscale `serve`, a reverse proxy) also needs DECOMP_ALLOWED_HOSTS — the app refuses a Host header
# outside 127.0.0.1/localhost otherwise.
#
# The compilers inside are x86 Linux programs: on Apple Silicon this runs as linux/amd64 (Rosetta or QEMU).
FROM --platform=linux/amd64 debian:trixie-slim

COPY site/public/linux-base.sh /tmp/linux-base.sh
RUN sh /tmp/linux-base.sh docker && rm /tmp/linux-base.sh
COPY site/public/install.sh /usr/local/share/decomp-wtf/install.sh
COPY pyproject.toml README.md LICENSE /usr/local/share/decomp-wtf/src/
COPY src /usr/local/share/decomp-wtf/src/src
ENV DECOMP_SOURCE=/usr/local/share/decomp-wtf/src

USER decomp
WORKDIR /home/decomp
ENV LANG=C.UTF-8 DECOMP_RUNTIME=docker PATH=/home/decomp/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EXPOSE 6464
HEALTHCHECK --interval=30s --timeout=5s --start-period=10m CMD curl -fsS "http://127.0.0.1:${DECOMP_PORT:-6464}/health" >/dev/null || exit 1
ENTRYPOINT ["/usr/local/bin/decomp-entrypoint"]
