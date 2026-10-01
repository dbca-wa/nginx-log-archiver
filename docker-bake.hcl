# docker-bake.hcl — reproducible, multi-arch build config.
# Build (local single-platform): docker buildx bake
# Build + push (multi-arch):      docker buildx bake --push
# Override at runtime:            TAG=v2 REGISTRY=ghcr.io/me docker buildx bake

variable "TAG" {
  default = "latest"
}

variable "REGISTRY" {
  default = "ghcr.io/dbca-wa"
}

variable "PLATFORMS" {
  default = "linux/amd64,linux/arm64"
}

group "default" {
  targets = ["app"]
}

target "app" {
  context    = "."
  dockerfile = "Dockerfile"
  tags       = ["${REGISTRY}/nginx-log-archiver:${TAG}"]
  platforms  = split(",", PLATFORMS)
  cache-from = ["type=gha"]
  cache-to   = ["type=gha,mode=max"]
  # Provenance + SBOM are attached on push (CI). Harmless for local non-push builds.
  attest     = ["type=provenance,mode=max", "type=sbom"]
}
