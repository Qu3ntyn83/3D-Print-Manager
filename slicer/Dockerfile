# Slicer-Dienst für den 3D Print Manager: Bambu Studio (Kommandozeile) hinter einer kleinen HTTP-Schnittstelle.
# Berechnet Druckzeit und Filamentbedarf für 3MF-Projekte, die ohne Slice-Daten gespeichert wurden.
FROM ubuntu:24.04
ARG BAMBU_URL=https://github.com/bambulab/BambuStudio/releases/download/v02.09.01.70/BambuStudio_ubu24-v02.09.01.70-20261103183404.AppImage
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl python3 \
      libgl1 libegl1 libglu1-mesa libgtk-3-0t64 libwebkit2gtk-4.1-0 \
      libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 libwayland-server0 \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL -o /tmp/bs.AppImage "$BAMBU_URL" && chmod +x /tmp/bs.AppImage \
    && cd /opt && /tmp/bs.AppImage --appimage-extract >/dev/null && mv squashfs-root bambu && rm /tmp/bs.AppImage \
    && echo "$BAMBU_URL" | sed -E 's#.*/download/v?([^/]+)/.*#\1#' > /opt/bambu/VERSION \
    && chmod -R a+rX /opt/bambu
COPY server.py /opt/server.py
RUN useradd -m -u 1000 slicer 2>/dev/null || usermod -l slicer -d /home/slicer -m ubuntu
USER 1000
ENV HOME=/tmp
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["python3", "/opt/server.py"]
