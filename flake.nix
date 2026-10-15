{
  description = "Orca's native headless server, without Electron";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/eaad089433ca2bb662274377d33df3d0e51ef28b";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      package = pkgs.callPackage ./package.nix { };
    in
    {
      packages.${system} = {
        default = package;
        orca-server = package;
      };

      overlays.default = final: prev: {
        orca-server = final.callPackage ./package.nix { };
      };
    };
}
