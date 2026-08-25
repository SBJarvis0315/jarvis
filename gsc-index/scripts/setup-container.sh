#!/usr/bin/env bash
# 클라우드 세션 시작 시 1회 실행. 환경 설정의 Setup script 에 걸어두세요.
#
# 컨테이너는 매 실행마다 새로 뜨므로 아래 세 가지가 매번 필요합니다.
#   1) certutil (NSS 트러스트 스토어 조작용)
#   2) 프록시 CA 를 크로미움 NSS 스토어에 등록  ← 없으면 ERR_CERT_AUTHORITY_INVALID
#   3) playwright 파이썬 패키지 (크로미움 바이너리는 이미지에 이미 있음)
set -euo pipefail

echo "[setup] certutil 설치"
apt-get update -qq
apt-get install -y -qq libnss3-tools

echo "[setup] 프록시 CA 를 크로미움 NSS 스토어에 등록"
mkdir -p /root/.pki/nssdb
work=$(mktemp -d)
awk 'BEGIN{n=0} /BEGIN CERTIFICATE/{n++} {print > ("'"$work"'/ca" n ".pem")}' /root/.ccr/ca-bundle.crt
for f in "$work"/ca*.pem; do
  certutil -A -n "ccr-$(basename "$f")" -t "C,," -i "$f" -d sql:/root/.pki/nssdb 2>/dev/null || true
done
rm -rf "$work"
echo "[setup] 등록된 CA: $(certutil -L -d sql:/root/.pki/nssdb | grep -c ',,' || echo 0) 개"

echo "[setup] playwright 설치"
pip install --quiet playwright
echo "[setup] 완료"
