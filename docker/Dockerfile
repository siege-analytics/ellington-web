
ARG UBUNTU_BASE_IMAGE
FROM ${UBUNTU_BASE_IMAGE}

ARG PYTHON_VENV_PATH=/opt/venv
ARG DEBIAN_FRONTEND=noninteractive

# Environmental Variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# assure TZ config
RUN apt-get update && apt-get install -y tzdata

# Install the basics, python utils, gdal, and postgres.
# apt-get update is INSIDE this RUN so a layer rebuild always picks up
# the current package index — previously the update was in a separate
# RUN (line 13) which got cached for months, then this install would
# 404 fetching versions that had been rotated out of security.ubuntu.com.
# See #91 follow-up: PR #92 added git, which invalidated this layer
# and surfaced the stale-index bug.
RUN apt-get update && apt-get install -y \
    build-essential \
    ca-certificates \
    vim \
    wget \
    curl \
    # git is required by pip when a requirement uses the
    # ``pkg @ git+https://...`` URL form. omr-leadsheet (PR #85,
    # Phase 4-PDF #81) installs that way. Without git the Tekton
    # build fails at the pip step even though GitHub Actions CI
    # passes (Actions runners have git pre-installed). See #91.
    git \
    zip \
    unzip \
    python3-pip \
    python3-pyproj \
    python3-venv \
    gdal-bin \
    postgresql \
    postgresql-contrib \
    postgis \
    netcat-traditional \
    sqlite3 \
    spatialite-bin \
    libcairo2-dev \
    libjpeg-dev \
    libgif-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Python Installer Config
COPY docker/pip.conf /etc/pip.conf

# Activate Python Virtual Environment
RUN python3 -m venv ${PYTHON_VENV_PATH}
ENV PATH="${PYTHON_VENV_PATH}/bin:$PATH"

# Install GDAL python bindings
RUN apt-get update \
    && apt-get install -y --install-recommends libgdal-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal
RUN pip install --trusted-host pypi.python.org --upgrade pip --default-timeout=1200 GDAL=="$(gdal-config --version).*" \
 && echo "succesfully built python gdal bindings"

# Install PIP requirements
ADD docker/requirements.txt /tmp/
RUN pip install --trusted-host pypi.python.org --default-timeout=1200 --upgrade pip -r /tmp/requirements.txt

# Container entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

# Bake the Django source into the image, then set WORKDIR to the project
# root (where manage.py lives) so daphne's `ellington_web.asgi:application`
# resolves against the inner project package.
COPY app/ /usr/src/app/
WORKDIR /usr/src/app/ellington_web

EXPOSE 8080

# ASGI runtime — matches the substrate's port-8080 design note in
# ellington-web-manifests/base/deployment.yaml. The entrypoint runs
# Django migrations + collectstatic and then exec's whatever CMD is set.
CMD ["daphne", "-b", "0.0.0.0", "-p", "8080", "ellington_web.asgi:application"]
