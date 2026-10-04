#!/usr/bin/env bash
# Build the FFmpeg binary bundled with cudAI (macOS).
#
# License: LGPL-2.1-or-later. No --enable-gpl, no --enable-nonfree, no libx264;
# H.264 is encoded with Apple's VideoToolbox. Only the components cudAI uses are
# enabled. When distributing the app, ship FFmpeg's LGPL license text and make
# this script plus the exact FFmpeg source tarball available.
#
# Usage: scripts/build_ffmpeg_lgpl.sh [arch]
#   arch: universal (x86_64 + arm64, for release), x86_64, arm64; default: host
# Output: api/ffmpeg for universal/host builds, api/ffmpeg-<arch> otherwise
set -euo pipefail

if [ "${1:-}" = "universal" ]; then
  HERE="$(cd "$(dirname "$0")" && pwd)"
  "$HERE/build_ffmpeg_lgpl.sh" x86_64
  "$HERE/build_ffmpeg_lgpl.sh" arm64
  API="$HERE/../api"
  lipo -create "$API/ffmpeg-x86_64" "$API/ffmpeg-arm64" -output "$API/ffmpeg"
  rm "$API/ffmpeg-x86_64" "$API/ffmpeg-arm64"
  echo "Built universal $API/ffmpeg: $(lipo -archs "$API/ffmpeg")"
  exit 0
fi

FFMPEG_VERSION="7.1.2"
ARCH="${1:-$(uname -m)}"
MIN_MACOS="12.0"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${TMPDIR:-/tmp}/cudai-ffmpeg-build"
SRC="$WORK/ffmpeg-$FFMPEG_VERSION"
OUT="$ROOT/api/ffmpeg"
[ $# -gt 0 ] && OUT="$ROOT/api/ffmpeg-$ARCH"

mkdir -p "$WORK"
if [ ! -d "$SRC" ]; then
  curl -fsSL "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" -o "$WORK/ffmpeg.tar.xz"
  tar -xf "$WORK/ffmpeg.tar.xz" -C "$WORK"
fi

cd "$SRC"
make distclean >/dev/null 2>&1 || true

ASM_FLAG=""
command -v nasm >/dev/null || ASM_FLAG="--disable-x86asm"

./configure \
  --arch="$ARCH" \
  --enable-cross-compile \
  --target-os=darwin \
  --cc="clang -arch $ARCH" \
  --extra-cflags="-mmacosx-version-min=$MIN_MACOS" \
  --extra-ldflags="-mmacosx-version-min=$MIN_MACOS" \
  --disable-gpl --disable-nonfree --disable-version3 \
  --disable-everything \
  --disable-autodetect \
  --enable-avfoundation --enable-videotoolbox \
  --enable-coreimage --enable-appkit \
  --disable-doc --disable-ffplay --disable-ffprobe --disable-network \
  --disable-debug --enable-static --disable-shared \
  --enable-indev=avfoundation,lavfi \
  --enable-encoder=h264_videotoolbox \
  --enable-decoder=h264,rawvideo,wrapped_avframe \
  --enable-demuxer=mov,concat \
  --enable-muxer=mp4,mov,null \
  --enable-protocol=file,pipe \
  --enable-parser=h264 \
  --enable-bsf=h264_mp4toannexb,extract_extradata,null \
  --enable-filter=color,testsrc,scale,format,null,fps,setpts,crop \
  $ASM_FLAG

# Refuse to ship a build that is not LGPL (checked from the build config so
# it also works for cross-compiled architectures).
for flag in CONFIG_GPL CONFIG_NONFREE CONFIG_VERSION3; do
  if ! grep -q "#define $flag 0" config.h; then
    echo "ERROR: $flag is enabled; this build would not be LGPL-2.1" >&2
    exit 1
  fi
done

make -j"$(sysctl -n hw.ncpu)"
cp ffmpeg "$OUT"
strip "$OUT"
echo "Built $OUT ($FFMPEG_VERSION, $ARCH, LGPL-2.1-or-later)"
