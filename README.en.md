# OVHcloud Infrastructure Manager with Pulumi and Nix

This project deploys and manages an infrastructure on OVHcloud using Pulumi for Infrastructure as Code (IaC) and Nix to ensure a reproducible development environment.

The project is structured into two interdependent Pulumi stacks:
1.  **`main_stack`**: This stack is responsible for creating the OVH Public Cloud project, which serves as a container for all other resources.
2.  **`data_stack`**: This stack deploys storage resources. It creates several S3 buckets as well as the necessary IAM users and policies for secure and partitioned data access.

---

## Nix Installation (Prerequisite)

This project requires Nix with the **flakes** feature enabled.

### Step 1: Install Nix

The recommended installation method is the multi-user installation, which provides better isolation and security. Open a terminal and run the following command:

```bash
sh <(curl --proto '=https' --tlsv1.2 -L https://nixos.org/nix/install) --daemon
```

Follow the instructions displayed by the script. Once the installation is complete, **close and reopen your terminal** for the changes to take effect.

### Step 2: Enable Flakes

Flakes are an experimental feature that must be enabled manually.

1.  **Create or edit the Nix configuration file.**
    -   On **macOS** or other **Linux** distributions (non-NixOS), this file is typically located at `~/.config/nix/nix.conf`.
    -   Create the directory and file if they do not exist:
        ```bash
        mkdir -p ~/.config/nix
        touch ~/.config/nix/nix.conf
        ```

2.  **Add the following line to the `nix.conf` file**:
    ```
    experimental-features = nix-command flakes
    ```

After saving the file, Nix is ready to be used with this project.

---

## Environment Setup

The project uses a `flake.nix` file to define and manage the development environment. To activate it, run the following command at the root of the project:

```bash
nix develop
```

This command will automatically:
- Install all required dependencies (`pulumi`, `python`, `nodejs`, `poetry`, etc.).
- Set up a Python virtual environment (`.venv`).
- Install the project's Python dependencies with Poetry.
- Authenticate you with the Bitwarden CLI to retrieve necessary secrets (OVH API keys, Pulumi S3 backend, etc.).
- Configure Pulumi to use the appropriate S3 backend.

**Important Note:** On the first run, the script will ask for your Bitwarden credentials if the environment variables are not set.

### Non-Interactive Configuration (CI/CD)

For non-interactive use (e.g., in a script or continuous integration), you can pre-configure the following environment variables before running `nix develop`.

-   `BW_CLIENTID`: Your Bitwarden API "client_id".
-   `BW_CLIENTSECRET`: Your Bitwarden API "client_secret".
-   `BW_PASSWORD`: Your Bitwarden master password.

By setting these variables, the initialization script will not need to prompt you for them interactively.

```bash
# .envrc
export BW_CLIENTID="your_client_id"
export BW_CLIENTSECRET="your_client_secret"
export BW_PASSWORD="your_master_password"
```

---

## Project Structure

```
.
├── flake.nix              # Nix environment configuration file
├── package.json           # Node.js dependencies (for Bitwarden CLI)
└── ovh-server/
    ├── pyproject.toml     # Python dependencies managed by Poetry
    ├── data/              # Pulumi stack for data resources (S3, users)
    │   ├── __main__.py
    │   └── Pulumi.yaml
    └── main_stack/        # Pulumi stack for the OVH Public Cloud project
        ├── __main__.py
        └── Pulumi.yaml
```
---

## Infrastructure Deployment

The deployment must be done in a specific order, as the `data` stack depends on resources created by the `main_stack`.

### Step 1: Deploy the `main_stack`

This stack creates the OVH Public Cloud project.

1.  Make sure you are in the Nix environment (`nix develop`).
2.  Navigate to the stack's directory:
    ```bash
    cd ovh-server/main_stack
    ```
3.  Deploy the stack with Pulumi:
    ```bash
    pulumi up
    ```
    Pulumi will show you a preview of the resources to be created. Confirm to start the deployment.

### Step 2: Deploy the `data` stack

This stack creates the S3 buckets and users.

1.  Navigate to the stack's directory:
    ```bash
    cd ../data
    ```
2.  Deploy the stack:
    ```bash
    pulumi up
    ```
    This command will deploy the buckets and users based on the project ID created in the previous step.

---

## Dependency Management

-   **Environment**: Managed by `flake.nix`.
-   **Python**: Managed by `Poetry` via the `ovh-server/pyproject.toml` file. Dependencies are installed automatically by the Nix `shellHook`.
-   **Node.js**: Managed by `npm` via `package.json`, mainly for the Bitwarden CLI.

---

## Pulumi

### Stack Management

Managing the configuration and outputs of Pulumi stacks is done via simple CLI commands. Make sure you are in the directory of the relevant stack (`ovh-server/main_stack` or `ovh-server/data_stack`) before running these commands.

#### Viewing Configuration

A stack's configuration contains the parameters needed for its deployment (e.g., project IDs or resource names).

-   **To see the configuration (encrypted values for secrets)**:
    ```bash
    pulumi config
    ```

-   **To see the configuration in plaintext (decrypting secrets)**:
    > **Warning**: This command displays sensitive information in plaintext. Use it with caution.
    ```bash
    pulumi config --show-secrets
    ```

#### Viewing Outputs

A stack's outputs represent the values exported by the infrastructure after its deployment. They are often used as inputs for other stacks or to connect applications.

-   **To see the outputs of the current stack**:
    ```bash
    pulumi stack output
    ```

-   **To see the outputs in JSON format (useful for scripts)**:
    ```bash
    pulumi stack output --json
    ```

### Stack Documentation

#### `main_stack`

This stack provisions the OVH Public Cloud project.

-   **Configuration**:
    -   This stack has no customizable configuration.

-   **Outputs**:
    -   `project_id`: (String) The unique identifier of the created Public Cloud project.

#### `data_stack`

This stack deploys S3 storage resources, along with the associated IAM users and policies.

-   **Configuration**:
    -   `project_id`: (String, **secret**) The identifier of the Public Cloud project in which the resources should be created. This value is typically retrieved from the `main_stack`'s output.

-   **Outputs**:
    -   `bucket_names`: (Array<String>) The list of names of the created S3 buckets.
    -   `s3_users`: (Array<Object>) A list of objects representing the created S3 users, each with:
        -   `user_name`: (String) The user's name.
        -   `access_key_id`: (String) The user's Access Key ID.
        -   `secret_access_key`: (String, **secret**) The user's Secret Access Key.
