#!/usr/bin/env bash
# Dump every font-rendering-relevant switch and state variable.
# Designed to run as a Bazel sh_test on both gVisor and RBE.
set -uo pipefail

echo "========== ENVIRONMENT =========="
echo "HOSTNAME=$(hostname 2>/dev/null || echo unknown)"
echo "KERNEL=$(uname -r)"
echo "KERNEL_FULL=$(uname -a)"
echo "GLIBC=$(/lib/x86_64-linux-gnu/libc.so.6 2>&1 | head -1 || echo unknown)"
echo ""

echo "========== CPU =========="
grep "model name" /proc/cpuinfo | head -1 || echo "model name: unknown"
grep "cpu family" /proc/cpuinfo | head -1 || echo "cpu family: unknown"
grep "model	" /proc/cpuinfo | head -1 || echo "model: unknown"
grep "stepping" /proc/cpuinfo | head -1 || echo "stepping: unknown"
echo "flags=$(grep "^flags" /proc/cpuinfo | head -1 | sed 's/.*: //' | tr ' ' '\n' | grep -E '^(sse|avx|fma|f16c)' | sort | tr '\n' ' ')"
echo ""

echo "========== FPU / MXCSR =========="
TMPDIR="${TEST_TMPDIR:-/tmp}"
cat >"$TMPDIR/dump_mxcsr.c" <<'CEOF'
#include <stdio.h>
#include <stdint.h>
#include <fenv.h>
int main() {
    uint32_t mxcsr;
    __asm__ __volatile__("stmxcsr %0" : "=m"(mxcsr));
    printf("MXCSR=0x%04x\n", mxcsr);
    printf("  FZ (flush-to-zero)       = %d\n", (mxcsr >> 15) & 1);
    printf("  RC (rounding control)    = %d", (mxcsr >> 13) & 3);
    switch ((mxcsr >> 13) & 3) {
        case 0: printf(" (round-to-nearest)\n"); break;
        case 1: printf(" (round-down)\n"); break;
        case 2: printf(" (round-up)\n"); break;
        case 3: printf(" (round-toward-zero)\n"); break;
    }
    printf("  PM (precision mask)      = %d\n", (mxcsr >> 12) & 1);
    printf("  UM (underflow mask)      = %d\n", (mxcsr >> 11) & 1);
    printf("  OM (overflow mask)       = %d\n", (mxcsr >> 10) & 1);
    printf("  ZM (divide-by-zero mask) = %d\n", (mxcsr >> 9) & 1);
    printf("  DM (denormal mask)       = %d\n", (mxcsr >> 8) & 1);
    printf("  IM (invalid-op mask)     = %d\n", (mxcsr >> 7) & 1);
    printf("  DAZ (denormals-are-zero) = %d\n", (mxcsr >> 6) & 1);
    unsigned short fpu_cw;
    __asm__ __volatile__("fnstcw %0" : "=m"(fpu_cw));
    printf("x87_FPU_CW=0x%04x\n", fpu_cw);
    printf("  PC (precision)  = %d", (fpu_cw >> 8) & 3);
    switch ((fpu_cw >> 8) & 3) {
        case 0: printf(" (single 24-bit)\n"); break;
        case 1: printf(" (reserved)\n"); break;
        case 2: printf(" (double 53-bit)\n"); break;
        case 3: printf(" (extended 64-bit)\n"); break;
    }
    printf("  RC (rounding)   = %d", (fpu_cw >> 10) & 3);
    switch ((fpu_cw >> 10) & 3) {
        case 0: printf(" (round-to-nearest)\n"); break;
        case 1: printf(" (round-down)\n"); break;
        case 2: printf(" (round-up)\n"); break;
        case 3: printf(" (round-toward-zero)\n"); break;
    }
    printf("fegetround()=%d", fegetround());
    switch(fegetround()) {
        case FE_TONEAREST:  printf(" (FE_TONEAREST)\n"); break;
        case FE_DOWNWARD:   printf(" (FE_DOWNWARD)\n"); break;
        case FE_UPWARD:     printf(" (FE_UPWARD)\n"); break;
        case FE_TOWARDZERO: printf(" (FE_TOWARDZERO)\n"); break;
        default: printf(" (unknown)\n"); break;
    }
    return 0;
}
CEOF
if command -v gcc >/dev/null 2>&1; then
  gcc -o "$TMPDIR/dump_mxcsr" "$TMPDIR/dump_mxcsr.c" -lm 2>/dev/null && "$TMPDIR/dump_mxcsr" || echo "MXCSR: compile succeeded but run failed"
else
  echo "MXCSR: gcc not available"
fi
echo ""

echo "========== FONTCONFIG ENV =========="
if [ -n "${FONTCONFIG_FILE:-}" ] && [ "${FONTCONFIG_FILE:0:1}" != "/" ]; then
  export FONTCONFIG_FILE="$PWD/$FONTCONFIG_FILE"
fi
echo "FONTCONFIG_FILE=${FONTCONFIG_FILE:-<unset>}"
echo "FONTCONFIG_FILE_EXISTS=$([ -f "${FONTCONFIG_FILE:-/nonexistent}" ] && echo yes || echo no)"
echo "FONTCONFIG_PATH=${FONTCONFIG_PATH:-<unset>}"
echo "FONTCONFIG_SYSROOT=${FONTCONFIG_SYSROOT:-<unset>}"
echo "FC_DEBUG=${FC_DEBUG:-<unset>}"
echo ""

echo "========== FREETYPE ENV =========="
echo "FREETYPE_PROPERTIES=${FREETYPE_PROPERTIES:-<unset>}"
echo ""

echo "========== FONTCONFIG QUERY: Inter 12px =========="
if command -v fc-match >/dev/null 2>&1; then
  fc-match -v "Inter:size=12:weight=regular" 2>&1 | grep -E "^\t(family|style|file|hinting|autohint|hintstyle|antialias|rgba|lcdfilter|embeddedbitmap|scalable|fontformat|weight|slant|width|size|pixelsize|dpi):" | sort
else
  echo "fc-match: not available"
fi
echo ""

echo "========== SYSTEM FONT DIRS =========="
ls -d /usr/share/fonts/*/ 2>/dev/null | sort || echo "no /usr/share/fonts/ subdirs"
echo "Total fonts: $(fc-list 2>/dev/null | wc -l || echo unknown)"
echo ""

echo "========== /etc/fonts/ CONFIG =========="
echo "--- /etc/fonts/fonts.conf md5 ---"
md5sum /etc/fonts/fonts.conf 2>/dev/null || echo "no /etc/fonts/fonts.conf"
echo "--- /etc/fonts/conf.d/ entries ---"
ls /etc/fonts/conf.d/ 2>/dev/null | sort | head -40 || echo "no conf.d"
echo ""

echo "========== SHARED LIBRARIES (font-relevant) =========="
for lib in libc.so.6 libm.so.6 libexpat.so.1 libfreetype.so.6 libfontconfig.so.1; do
  for dir in /lib/x86_64-linux-gnu /usr/lib/x86_64-linux-gnu; do
    path="$dir/$lib"
    if [ -f "$path" ]; then
      echo "$lib: size=$(stat -c%s "$path") md5=$(md5sum "$path" | cut -d' ' -f1)"
      break
    fi
  done
  if [ ! -f "/lib/x86_64-linux-gnu/$lib" ] && [ ! -f "/usr/lib/x86_64-linux-gnu/$lib" ]; then
    echo "$lib: NOT FOUND"
  fi
done
echo ""

echo "========== CHROME BINARY =========="
CHROME=""
PPATH="${PUPPETEER_EXECUTABLE_PATH:-}"
if [ -n "$PPATH" ] && [ "${PPATH:0:1}" != "/" ]; then
  PPATH="$PWD/$PPATH"
fi
if [ -n "$PPATH" ]; then
  SHELL_PATH="$PPATH/chrome-linux/headless_shell"
  if [ -f "$SHELL_PATH" ]; then
    CHROME="$SHELL_PATH"
  elif [ -f "$PPATH" ]; then
    CHROME="$PPATH"
  fi
fi
if [ -n "$CHROME" ] && [ -f "$CHROME" ]; then
  echo "size=$(stat -c%s "$CHROME")"
  echo "md5=$(md5sum "$CHROME" | cut -d' ' -f1)"
  echo ""
  echo "--- Chrome version ---"
  timeout 5 "$CHROME" --version 2>&1 || echo "(no --version output)"
else
  echo "Chrome binary not found (PUPPETEER_EXECUTABLE_PATH=${PUPPETEER_EXECUTABLE_PATH:-<unset>})"
fi
echo ""

echo "========== LOCALE =========="
locale 2>/dev/null || echo "locale: unavailable"
echo ""

echo "========== /proc/self/maps (vdso + heap) =========="
grep -E "vdso|heap" /proc/self/maps 2>/dev/null || echo "no vdso/heap mapping"
echo ""

echo "========== DONE =========="
exit 0
