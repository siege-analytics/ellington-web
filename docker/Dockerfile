
ARG UBUNTU_BASE_IMAGE
FROM ${UBUNTU_BASE_IMAGE}

ARG PYTHON_VENV_PATH=/opt/venv
ARG DEBIAN_FRONTEND=noninteractive

# Environmental Variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# assure TZ config
RUN apt-get update && apt-get install -y tzdata

# Install the basics, python utils, gdal, and postgres
RUN apt-get install -y \
    build-essential \
    ca-certificates \
    vim \
    wget \
    curl \
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
COPY pip.conf /etc/pip.conf

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
ADD requirements.txt /tmp/
RUN pip install --trusted-host pypi.python.org --default-timeout=1200 --upgrade pip -r /tmp/requirements.txt

# Container entrypoint
COPY ./entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

# set work directory
WORKDIR /usr/src/app
