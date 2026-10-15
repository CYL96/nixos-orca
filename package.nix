{ lib
, stdenvNoCC
, fetchurl
, binutils
, autoPatchelfHook
, makeWrapper
, nodejs_24
, glibc
, gcc-unwrapped
, git
, bashInteractive
, coreutils
, cacert
}:

let
  source = builtins.fromJSON (builtins.readFile ./source.json);
  inherit (source) version hash;
  filename = "orca-ide_${version}_amd64.deb";
  caDefaults = ''
    if [ -z "''${SSL_CERT_FILE:-}" ]; then
      if [ -r /etc/ssl/certs/ca-certificates.crt ]; then
        export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
      else
        export SSL_CERT_FILE=${cacert}/etc/ssl/certs/ca-bundle.crt
      fi
    fi
    export NIX_SSL_CERT_FILE="''${NIX_SSL_CERT_FILE:-$SSL_CERT_FILE}"
    export NODE_EXTRA_CA_CERTS="''${NODE_EXTRA_CA_CERTS:-$SSL_CERT_FILE}"
  '';
in
assert lib.assertMsg (stdenvNoCC.hostPlatform.system == "x86_64-linux")
  "orca-server only provides the x86_64-linux native target";
assert lib.assertMsg (lib.versions.major nodejs_24.version == "24")
  "orca-server's prebuilt addons require Node.js 24";
stdenvNoCC.mkDerivation {
  pname = "orca-server";
  inherit version;

  # Keep the release asset's basename: this also reuses the existing fixed-output
  # fetchurl object rather than giving identical bytes a new store name.
  src = fetchurl {
    url = "https://github.com/stablyai/orca/releases/download/v${version}/${filename}";
    name = filename;
    inherit hash;
  };

  nativeBuildInputs = [ binutils autoPatchelfHook makeWrapper ];
  buildInputs = [ glibc gcc-unwrapped.lib ];

  # Extract only shared native-server files and the selected prebuilt target.
  # In particular, never extract Electron, other architectures, or the bundled
  # runtime markers which would ask Orca to select/download its own Node.
  unpackPhase = ''
    runHook preUnpack
    mkdir payload
    ar p "$src" data.tar.xz | tar -xJf - -C payload \
      --wildcards --no-wildcards-match-slash \
      './opt/Orca/resources/orcad-template/*.js' \
      './opt/Orca/resources/orcad-template/out' \
      './opt/Orca/resources/orcad-template/node_modules' \
      './opt/Orca/resources/orcad-template/ripgrep' \
      './opt/Orca/resources/orcad-template/native-chat-visuals' \
      './opt/Orca/resources/orcad-template/targets/linux-x64-glibc/node_modules' \
      './opt/Orca/resources/orcad-template/targets/linux-x64-glibc/ripgrep' \
      './opt/Orca/resources/node_modules/node-pty/LICENSE' \
      './opt/Orca/resources/node_modules/@parcel/watcher/LICENSE'
    runHook postUnpack
  '';

  dontConfigure = true;
  dontBuild = true;
  # Keep upstream JS and native payload intact apart from ELF linkage fixups.
  dontStrip = true;

  installPhase = ''
    runHook preInstall
    template=payload/opt/Orca/resources/orcad-template
    native="$out/lib/orca-native"
    mkdir -p "$native" "$out/bin" "$out/share/licenses/orca-server"
    cp -R "$template/"*.js "$template/out" "$template/node_modules" \
      "$template/ripgrep" "$template/native-chat-visuals" "$native/"
    chmod -R u+w "$native"
    cp -R "$template/targets/linux-x64-glibc/node_modules/." "$native/node_modules/"
    cp -R "$template/targets/linux-x64-glibc/ripgrep/." "$native/ripgrep/"

    install -m644 ${./LICENSE} "$out/share/licenses/orca-server/LICENSE.packaging"
    install -m644 ${./LICENSE.upstream} "$out/share/licenses/orca-server/LICENSE.orca"
    install -m644 payload/opt/Orca/resources/node_modules/node-pty/LICENSE \
      "$out/share/licenses/orca-server/LICENSE.node-pty"
    install -m644 payload/opt/Orca/resources/node_modules/@parcel/watcher/LICENSE \
      "$out/share/licenses/orca-server/LICENSE.parcel-watcher"

    for command in orca-server orca-server-cli; do
      entry="$native/orcad-server.js"
      if [ "$command" = orca-server-cli ]; then
        entry="$native/out/cli/index.js"
      fi
      makeWrapper ${nodejs_24}/bin/node "$out/bin/$command" \
        --add-flags "$entry" \
        --set ORCA_VERSION ${lib.escapeShellArg version} \
        --set ORCA_APP_VERSION ${lib.escapeShellArg version} \
        --set-default SHELL ${bashInteractive}/bin/bash \
        --prefix PATH : ${lib.makeBinPath [ git bashInteractive coreutils ]} \
        --run ${lib.escapeShellArg caDefaults}
    done
    runHook postInstall
  '';

  passthru = {
    sourceInfo = source;
    upstreamLicense = ./LICENSE.upstream;
  };

  meta = {
    description = "Orca native headless server and CLI, without Electron";
    homepage = "https://github.com/stablyai/orca";
    changelog = "https://github.com/stablyai/orca/releases/tag/v${version}";
    license = lib.licenses.mit;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
    platforms = [ "x86_64-linux" ];
    mainProgram = "orca-server";
  };
}
