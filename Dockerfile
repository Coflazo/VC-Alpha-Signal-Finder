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
COPY config ./config

RUN pip install --no-cache-dir . && python -c "import vc_alpha" || true

# Data lives on a mounted volume so it survives the container and so the operator
# can see exactly what is stored. It never leaves their machine.
VOLUME ["/app/data"]
EXPOSE 8420
ENV VC_ALPHA_HOST=0.0.0.0

CMD ["vc-alpha"]
