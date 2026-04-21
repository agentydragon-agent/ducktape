# Foxconn FoxFlss — FCC unlock and RF calibration tool for DW5932e/DW5934e modems.
#
# Closed-source binary from the foxconn-pc/fii_linux GitHub repo. Provides:
#   - FoxFlss (bare): FCC unlock, allows the software radio to turn on.
#   - FoxFlss -f Check_RF_SSKU: RF calibration, writes RF tuner settings, DPR
#     tables, and NR carrier aggregation configs to modem non-volatile storage.
#   - DW5932e_RF.dat, DW5934e_RF.dat: platform-specific RF calibration data files.
#
# FoxFlss hardcodes /opt/foxconn/data/ for the .dat files; see foxconn-wwan.nix
# for the systemd-tmpfiles symlinks that put them there.
{ pkgs, lib }:

pkgs.stdenv.mkDerivation {
  pname = "foxflss";
  version = "1.0.15";

  src = pkgs.fetchFromGitHub {
    owner = "foxconn-pc";
    repo = "fii_linux";
    rev = "c4a3f92f1a1d11dd08b92f5adb5bc1800a115f28";
    hash = "sha256-z/hIWJOyHSM3xN99cKSIXJwfu6+/q3NbV6SSNO4md7g=";
  };

  nativeBuildInputs = [ pkgs.autoPatchelfHook ];
  buildInputs = [ pkgs.glibc ];

  dontBuild = true;

  installPhase = ''
    runHook preInstall
    install -Dm755 Application/FoxFlss/bin/FoxFlss $out/bin/FoxFlss
    install -Dm644 Application/FoxFlss/data/DW5932e_RF.dat $out/share/foxflss/DW5932e_RF.dat
    install -Dm644 Application/FoxFlss/data/DW5934e_RF.dat $out/share/foxflss/DW5934e_RF.dat
    runHook postInstall
  '';

  meta = {
    description = "Foxconn FCC unlock and RF calibration tool for DW5932e/DW5934e WWAN modems";
    homepage = "https://github.com/foxconn-pc/fii_linux";
    license = lib.licenses.unfree;
    platforms = [ "x86_64-linux" ];
    mainProgram = "FoxFlss";
  };
}
