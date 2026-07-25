#!/usr/bin/env bash

set -euo pipefail

version="8.21.0"
archive_sha256="aa1b66a70eace83dc624508745646c08ae561de512ab403adffb93ac87fc72e6"
prefix="${PYNETFT_CURL_PREFIX:-/opt/pynetft-curl}"
build_root="$(mktemp -d)"
archive="${PYNETFT_CURL_ARCHIVE_CACHE:-${build_root}/curl-${version}.tar.xz}"
source_root="${build_root}/source"

cleanup() {
  rm -rf "${build_root}"
}
trap cleanup EXIT

mkdir -p "$(dirname "${archive}")"
if [[ ! -f "${archive}" ]]; then
  curl -fsSL "https://curl.se/download/curl-${version}.tar.xz" -o "${archive}"
fi
printf '%s  %s\n' "${archive_sha256}" "${archive}" | sha256sum --check
mkdir -p "${source_root}"
tar -xJf "${archive}" --strip-components=1 -C "${source_root}"

cd "${source_root}"
./configure \
  --prefix="${prefix}" \
  --disable-shared \
  --enable-static \
  --disable-dependency-tracking \
  --with-pic \
  --enable-http \
  --disable-dict \
  --disable-file \
  --disable-ftp \
  --disable-gopher \
  --disable-imap \
  --disable-ipfs \
  --disable-ldap \
  --disable-ldaps \
  --disable-mqtt \
  --disable-pop3 \
  --disable-rtsp \
  --disable-smb \
  --disable-smtp \
  --disable-telnet \
  --disable-tftp \
  --disable-websockets \
  --disable-manual \
  --disable-docs \
  --without-ssl \
  --without-libpsl \
  --without-zlib \
  --without-brotli \
  --without-zstd \
  --without-libidn2 \
  --without-nghttp2 \
  --without-ngtcp2 \
  --without-nghttp3 \
  --without-quiche \
  --without-libuv \
  --without-libgsasl \
  --without-libssh2 \
  --without-libssh \
  --without-gssapi
make -j2
make install

test "$("${prefix}/bin/curl-config" --version)" = "libcurl ${version}"
test "$("${prefix}/bin/curl-config" --protocols)" = "HTTP"
test -f "${prefix}/lib/libcurl.a"
test ! -e "${prefix}/lib/libcurl.so"
