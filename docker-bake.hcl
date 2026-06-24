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
  // Both images build on every Tekton run. The worker target's
  // contexts entry points its FROM at the just-built web image so
  // the two stay in lockstep — a develop-tag rebuild of the web
  // image always produces a matching worker image.
  targets = ["ellington-web", "ellington-web-worker"]
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

target "ellington-web-worker" {
  context    = "."
  dockerfile = "docker/Dockerfile.worker"
  // The worker FROMs the freshly-built web image. buildx's named
  // contexts wire that up so we don't depend on the registry having
  // the new tag at the moment the worker layer reads its base.
  contexts = {
    "${REGISTRY}/ellington-web:${TAG}" = "target:ellington-web"
  }
  args = {
    WORKER_BASE_IMAGE = "${REGISTRY}/ellington-web:${TAG}"
  }
  tags      = ["${REGISTRY}/ellington-web-worker:${TAG}"]
  platforms = ["linux/amd64"]
}
