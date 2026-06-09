// Consumed by the cluster's `sites-build-bake` Tekton Task
// (`docker buildx bake --file docker-bake.hcl --push`).
//
// REGISTRY + TAG are set by the Task script before invoking bake.
// Defaults below let `docker buildx bake` work for local one-off builds.

variable "REGISTRY" {
  default = "localhost:32000"
}

variable "TAG" {
  default = "latest"
}

variable "UBUNTU_BASE_IMAGE" {
  default = "ubuntu:24.04"
}

group "default" {
  targets = ["ellington-web"]
}

target "ellington-web" {
  context    = "."
  dockerfile = "docker/Dockerfile"
  args = {
    UBUNTU_BASE_IMAGE = UBUNTU_BASE_IMAGE
  }
  tags      = ["${REGISTRY}/ellington-web:${TAG}"]
  platforms = ["linux/amd64"]
}
