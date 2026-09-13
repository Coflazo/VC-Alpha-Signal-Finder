# For firms whose IT policy prefers a container to a Python install.
# Everything still runs on their machine; nothing is hosted.
FROM python:3.12-slim

# build-essential is present so the C++ extension compiles. Without it the package
# still installs and runs, just on the pure-Python fallback.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY vc_alpha ./vc_alpha
COPY src ./src
COPY scripts ./scripts
COPY examples ./examples

RUN pip install --no-cache-dir .

# Build the C++ extension. build-essential is installed above for exactly this, and
# the image previously carried the compiler without ever using it — so every image
# paid for a toolchain and still ran the pure-Python fallback. Non-fatal: the
# fallback is transparent and a build failure should not cost the whole image.
RUN python scripts/build_ext.py || echo "extension not built; using pure Python"
RUN python -c "from vc_alpha.fastpath import HAVE_FAST; print('fast extension:', HAVE_FAST)"

# Everything this installation owns — database, theses, keys — lives under one
# mounted directory, so it survives the container and the operator can see, back up
# and delete exactly what is stored. It never leaves their machine.
ENV VC_ALPHA_HOME=/app/data
VOLUME ["/app/data"]
EXPOSE 8420
ENV VC_ALPHA_HOST=0.0.0.0

CMD ["vc-alpha"]
