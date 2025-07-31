{
  description = "Dev environment flake for Pulumi project with vault and AWS profile setup";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in {
        devShell = pkgs.mkShell {
          buildInputs = with pkgs; [
            awscli2           # AWS CLI for profile management
            nodejs_24
            pulumi           # Pulumi CLI
            python313        # Python runtime
            python313Packages.virtualenv # Python virtualenv
            python313Packages.pipx # Pipx for Python dependency management
            direnv           # Direnv for auto-loading env
            jq               # JSON parser for CLI
            curl             # HTTP client
          ];

          shellHook = ''
            # Find project root by locating flake.nix in current or parent dirs
            dir=$PWD
            while [ "$dir" != "/" ] && [ ! -f "$dir/flake.nix" ]; do
              dir=$(dirname "$dir")
            done
            if [ -f "$dir/flake.nix" ]; then
              PROJECT_ROOT="$dir"
            else
              PROJECT_ROOT=$PWD
            fi
            echo "Setting up dev environment in $PROJECT_ROOT"
            cd "$PROJECT_ROOT"

            echo "🔧 Installing bitwarden-cli"
            npm install @bitwarden/cli
            npx bw --version
            npx bw logout
            npx bw config server https://vaultwarden.incubateur.net

            if [ -z "$BW_CLIENTID" ]; then
                read -p "Entrez la valeur de BW_CLIENTID pour accéder aux secrets Bitwarden : " BW_CLIENTID
                export BW_CLIENTID
            fi

            if [ -z "$BW_CLIENTSECRET" ]; then
                read -p "Entrez la valeur de BW_CLIENTSECRET pour accéder aux secrets Bitwarden : " BW_CLIENTSECRET
                export BW_CLIENTSECRET
            fi

            npx bw login --apikey

            if [ -z "$BW_PASSWORD" ]; then
                export BW_SESSION=$(npx bw unlock --raw)
            else
                echo "Using BW_PASSWORD from environment variable"
                export BW_SESSION=$(npx bw unlock --passwordenv BW_PASSWORD --raw)
            fi

            echo "🔑 Bitwarden session established"
            echo "🔑 Bitwarden loading pulumi backend secrets"

            for field in $(npx bw get item "Identifiant pulumi OVH" | jq -c '.fields[]'); do
                name=$(echo "$field" | jq -r '.name')
                value=$(echo "$field" | jq -r '.value')
                export "$name"="$value"
                echo "$name Loaded from Bitwarden"
            done

            # Python virtual environment setup
            python --version
            if [ ! -d .venv ]; then
              echo "Creating Python virtualenv..."
              python3 -m virtualenv .venv
            fi
            source .venv/bin/activate
            pip install --upgrade pip

            pipx install poetry==1.8.4 --force
            pipx inject poetry poetry-plugin-export --force

            (cd ovh-server && poetry lock && poetry install)

            pulumi login "$S3_BACKEND_URL"

            # Notification
            echo "✅ Dev environment ready"
            #echo "  - Pulumi passphrase loaded"
            #echo "  - Python env: $(python --version) in .venv"
          '';
        };
      }
    );
}