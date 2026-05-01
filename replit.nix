{pkgs}: {
  deps = [
    pkgs.zip
    pkgs.unzip
    pkgs.zlib
    pkgs.openssl
    pkgs.libffi
    pkgs.pkg-config
    pkgs.libtool
    pkgs.automake
    pkgs.autoconf
    pkgs.jdk17
    pkgs.ffmpeg
  ];
}
