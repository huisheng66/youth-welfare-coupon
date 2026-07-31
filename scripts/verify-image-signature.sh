#!/usr/bin/env bash
# 校验 GHCR 镜像的 cosign 签名（部署端使用，OWASP Docker Rule #13 / CIS §4.5）
#
# 用法：
#   bash scripts/verify-image-signature.sh <repo> <image> <digest|tag>
#   bash scripts/verify-image-signature.sh youth-welfare/youth api latest
#   bash scripts/verify-image-signature.sh youth-welfare/youth api sha256:abc123...
#
# 前置：
#   - 安装 cosign：https://docs.sigstore.dev/cosign/installation/
#   - 网络可访问 ghcr.io 与 sigstore 透明日志（Rekor）
#
# 校验通过返回 0，失败返回非零。CI 可作为部署前门禁：
#   bash scripts/verify-image-signature.sh $REPO api $DIGEST || exit 1
set -euo pipefail

REPO="${1:?usage: $0 <repo> <image> <digest|tag>}"
IMAGE="${2:?usage: $0 <repo> <image> <digest|tag>}"
REF="${3:?usage: $0 <repo> <image> <digest|tag>}"

# 校验值：与 .github/workflows/security.yml 中 sign job 的 identity 完全一致
IDENTITY="https://github.com/${REPO}/.github/workflows/security.yml@refs/heads/main"
ISSUER="https://token.actions.githubusercontent.com"
IMAGE_URI="ghcr.io/${REPO,,}-${IMAGE}"

# 如果 ref 不是 sha256: 前缀，自动解析 tag 的 digest
if [[ "$REF" != sha256:* ]]; then
  echo "==> resolving digest for tag: ${IMAGE_URI}:${REF}"
  DIGEST=$(docker buildx imagetools inspect "${IMAGE_URI}:${REF}" --format '{{.Manifest.Digest}}' 2>/dev/null \
           || skopeo inspect "docker://${IMAGE_URI}:${REF}" --format '{{.Digest}}' 2>/dev/null \
           || crane digest "${IMAGE_URI}:${REF}" 2>/dev/null)
  if [ -z "${DIGEST:-}" ]; then
    echo "ERROR: cannot resolve digest for ${IMAGE_URI}:${REF}" >&2
    echo "       install one of: docker buildx / skopeo / crane" >&2
    exit 2
  fi
  REF="${DIGEST}"
fi

FULL_REF="${IMAGE_URI}@${REF}"

if ! command -v cosign >/dev/null 2>&1; then
  echo "ERROR: cosign not installed. Install: https://docs.sigstore.dev/cosign/installation/" >&2
  exit 2
fi

echo "==> cosign verify (keyless)"
echo "    image:    ${FULL_REF}"
echo "    identity: ${IDENTITY}"
echo "    issuer:   ${ISSUER}"
echo

# keyless 校验：用 Fulcio CA 证书 + Rekor 透明日志，无需管理公钥
COSIGN_EXPERIMENTAL=1 cosign verify \
  --certificate-identity "${IDENTITY}" \
  --certificate-oidc-issuer "${ISSUER}" \
  "${FULL_REF}"

echo
echo "==> signature verified"
