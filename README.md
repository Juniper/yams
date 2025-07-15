# YAMS (Yet Another MCP Server)

**YAMS** is a powerful Model Context Protocol (MCP) server designed for analyzing services running on Kubernetes clusters. Built with FastAPI, YAMS provides seamless integration with VS Code Copilot Chat and other MCP-compatible tools.

## What is YAMS?

YAMS is a **generic Kubernetes management tool** that can connect to any Kubernetes environment using standard kubeconfig files or secure SSH tunnels. While designed with Juniper Cloud-Native Router (JCNR) deployments in mind, YAMS works with any Kubernetes cluster.

### Key Capabilities

- **Multi-cluster Management**: Connect to multiple Kubernetes clusters simultaneously
- **Flexible Access Methods**: Direct kubeconfig access or SSH tunnel connections for remote clusters
- **Generic Kubernetes Operations**: List clusters, namespaces, pods, and execute commands in any pod
- **JCNR-Specific Tools**: Specialized commands for DPDK, Contrail Agent, and cRPD components
- **VS Code Integration**: Native support for VS Code Copilot Chat and other MCP clients

### Use Cases

- **Infrastructure Analysis**: Query and analyze Kubernetes deployments across multiple clusters
- **JCNR Operations**: Monitor and troubleshoot Juniper Cloud-Native Router deployments
- **Remote Cluster Access**: Securely access private or on-premises clusters through SSH tunnels

## Features

- HTTP-based MCP server using FastAPI
- Kubernetes integration with kubeconfig support
- SSH tunnel support for remote cluster access
- Generic Tools: `list_clusters`, `list_namespaces`, `list_pods`, `execute_command`
- Specialized JCNR Tools: `execute_dpdk_command`, `execute_agent_command`, `execute_crpd_command`, `check_core_files`, `analyze_logs`
- VS Code Copilot Chat compatible
- CORS support and health check endpoint

## Configuration

### Configure Clusters

Create a `clusters.json` file with your cluster configurations. Each cluster is defined by a unique name (key) and configuration object (value).

#### Cluster Configuration Fields:

**Required fields for each cluster:**
- **`kubeconfig_path`**: Absolute or relative path to the kubeconfig file
  - *Example*: `"/home/user/.kube/config"`, `"~/.kube/prod-config"`
  - *Purpose*: Path to the kubeconfig file that contains cluster connection details
  - *Note*: For SSH tunneled clusters, this should be the path on the remote host

**Optional fields for each cluster:**
- **`description`**: Human-readable description of the cluster
  - *Example*: `"Production JCNR cluster"`, `"Development environment"`
  - *Purpose*: Documentation and identification in logs and UI

- **`environment`**: Environment classification
  - *Example*: `"production"`, `"staging"`, `"development"`, `"test"`
  - *Purpose*: Logical grouping and environment-specific handling

- **`location`**: Physical or logical location identifier
  - *Example*: `"us-east-1"`, `"on-premises"`, `"datacenter-a"`
  - *Purpose*: Geographic or infrastructure location reference

- **`ssh`**: SSH tunnel configuration object (see SSH Configuration Options below)
  - *Purpose*: Required when cluster is not directly accessible and needs SSH tunneling

#### Configuration Structure:
```json
{
  "cluster-name": {
    "kubeconfig_path": "path/to/kubeconfig",
    "description": "Optional description",
    "environment": "optional-environment",
    "location": "optional-location", 
    "ssh": {
      // SSH configuration (optional, see SSH section below)
    }
  }
}
```

#### Direct Kubeconfig Access
```json
{
  "production": {
    "kubeconfig_path": "/home/user/.kube/prod-cluster-config",
    "description": "Production Kubernetes cluster",
    "environment": "production",
    "location": "us-east-1"
  },
  "staging": {
    "kubeconfig_path": "/home/user/.kube/staging-cluster-config", 
    "description": "Staging environment for testing",
    "environment": "staging",
    "location": "us-west-2"
  },
  "local": {
    "kubeconfig_path": "~/.kube/config",
    "description": "Local Kubernetes cluster"
  }
}
```

#### Minimal Configuration Example
```json
{
  "my-cluster": {
    "kubeconfig_path": "~/.kube/config"
  }
}
```

#### SSH Tunnel Access
```json
{
  "remote-cluster": {
    "kubeconfig_path": "/home/user/.kube/remote-cluster-config",
    "description": "Remote cluster accessed via SSH tunnel",
    "ssh": {
      "host": "jump-host.example.com",
      "port": 22,
      "username": "ubuntu",
      "key_path": "/home/user/.ssh/id_rsa",
      "k8s_host": "10.0.1.100",
      "k8s_port": 6443,
      "local_port": 6443
    }
  },
  "password-auth-cluster": {
    "kubeconfig_path": "/home/user/.kube/password-cluster-config",
    "description": "Cluster with SSH password authentication",
    "ssh": {
      "host": "bastion.company.com",
      "username": "operator",
      "password": "secure-password",
      "k8s_host": "kubernetes.internal",
      "k8s_port": 6443,
      "local_port": 6444
    }
  }
}
```

#### Minimal SSH Configuration Examples
```json
{
  "ssh-key-cluster": {
    "kubeconfig_path": "/home/user/.kube/ssh-cluster-config",
    "ssh": {
      "host": "jump-server.com",
      "username": "user",
      "key_path": "/home/user/.ssh/id_rsa",
      "k8s_host": "kubernetes.internal"
    }
  },
  "ssh-password-cluster": {
    "kubeconfig_path": "/home/user/.kube/ssh-cluster-config",
    "ssh": {
      "host": "bastion.company.com",
      "username": "operator",
      "password": "my-password",
      "k8s_host": "localhost"
    }
  }
}
```

## Quick Setup

Choose your preferred installation method:

### Option A: Docker (Recommended)

Docker provides an isolated, reproducible environment with all dependencies included.

```bash
# Quick start - automated setup
./docker-run.sh

# Check health
curl http://localhost:40041/health
```

**Docker automatically handles:**
- Default configuration (uses sample config if none provided)
- SSH key permissions
- Directory creation
- Service startup

### Option B: Local Python Installation

```bash
# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On macOS/Linux
# or venv\Scripts\activate  # On Windows

# Install dependencies
pip install -r requirements.txt
```

**With Local Python:**
```bash
# Start server with Kubernetes sources
python enhanced_mcp_server.py --port 40041 --clusters-config clusters.json
```

## Configure VS Code

Add to your VS Code `settings.json`:

```json
{
  "mcp": {
    "servers": {
      "yams-mcp-server": {
        "url": "http://127.0.0.1:40041/mcp/"
      }
    }
  }
}
```
## Command Line Options

- `--port`: Port to run the server on (default: 40041)
- `--clusters-config`: Path to JSON file containing cluster configurations

## API Endpoints

- `GET /`: Server information and available endpoints
- `GET /health`: Health check endpoint
- `POST /mcp`: Main MCP protocol endpoint

## MCP Protocol Support

This server implements the Model Context Protocol over HTTP and supports:

- **Tools**: Callable functions that can be invoked by the client
- **Resources**: Readable content that can be accessed by URI
- **Initialization**: Proper MCP handshake and capability negotiation

## Available Tools

### 1. **list_clusters**
   - Description: List all configured Kubernetes clusters

### 2. **list_namespaces**
   - Description: List namespaces in a Kubernetes cluster
   - Parameters: `cluster_name` (optional string) - Name of the cluster

### 3. **list_pods**
   - Description: List pods in a specific namespace and cluster
   - Parameters: `namespace` (string), `cluster_name` (optional string)

### 4. **execute_command**
   - Description: Execute a command in a specific pod
   - Parameters: `pod_name` (string), `namespace` (string), `command` (string), `container` (optional string), `cluster_name` (optional string)

### 5. **execute_dpdk_command**
   - Description: Execute a command in all DPDK pods (vrdpdk) in contrail namespace across all clusters
   - Parameters: `command` (string), `cluster_name` (optional string) - executes on all clusters if not specified
   - Example Commands: `vif --list`, `dropstats`, `vif --get 0`

### 6. **execute_agent_command**
   - Description: Execute a command in all Contrail Agent pods (vrouter-nodes) in contrail namespace across all clusters
   - Parameters: `command` (string), `cluster_name` (optional string) - executes on all clusters if not specified
   - Example Commands: `contrail-status`, `vif --list`, `nh --list`

### 7. **execute_crpd_command**
   - Description: Execute a command in all cRPD (Contrail Routing Protocol Daemon) pods in jcnr namespace across all clusters
   - Parameters: `command` (string), `cluster_name` (optional string) - executes on all clusters if not specified
   - Example Commands: `show route`, `show bgp summary`, `show interfaces terse`

### 8. **check_core_files**
   - Description: Check for core files on nodes in a Kubernetes cluster. Searches common locations for core dumps
   - Parameters: 
     - `cluster_name` (optional string) - Name of the cluster (checks all clusters if not specified)
     - `search_paths` (optional array) - Custom paths to search for core files (uses default paths if not specified)
     - `max_age_days` (optional integer) - Maximum age of core files to report in days (default: 7 days)
   - Default Search Paths: `/cores`, `/var/cores`, `/var/crash`, `/var/log/crash`, `/var/log/cores`
   - Use Cases: Debugging crashes, system monitoring, troubleshooting application failures

### 9. **analyze_logs**
   - Description: Analyze log files in `/var/log/` and `/log/` directories on cluster nodes. Searches for errors, large files, and recent activity

## Kubernetes Integration

The server supports multiple Kubernetes clusters configured via a JSON file. Clusters can be accessed directly via kubeconfig files or through SSH tunnels for remote access.

### SSH Tunnel Support

For clusters that are not directly accessible, YAMS supports SSH tunneling through bastion hosts or jump servers. This is particularly useful for:

- Accessing private clusters through bastion hosts
- Connecting to on-premises clusters from cloud environments
- Secure access through jump servers in corporate networks

### SSH Configuration Options

When configuring SSH tunnel access, include an `ssh` object within your cluster configuration. Here's a detailed breakdown of all available fields:

#### Required Fields:

- **`host`**: SSH server hostname or IP address
  - *Example*: `"jump-host.example.com"` or `"10.87.3.248"`
  - *Purpose*: The SSH server you'll connect to (bastion host, jump server, or direct host)

- **`username`**: SSH username for authentication
  - *Example*: `"ubuntu"`, `"admin"`, `"your-username"`
  - *Purpose*: User account on the SSH server

- **`k8s_host`**: Kubernetes API server hostname as seen from the SSH server
  - *Example*: `"localhost"`, `"10.0.1.100"`, `"k8s-master.internal"`
  - *Purpose*: Where the Kubernetes API server is accessible from the SSH server
  - *Common values*:
    - `"localhost"` - K8s API runs on the same host as SSH server
    - `"10.x.x.x"` - Internal IP address of K8s master node
    - `"kubernetes.internal"` - Internal DNS name for K8s API

#### Authentication (Choose One):

- **`key_path`**: Path to SSH private key file (for public key authentication)
  - *Example*: `"/home/user/.ssh/id_rsa"`, `"/Users/user/.ssh/company_key"`
  - *Purpose*: Private key file for passwordless SSH authentication
  - *Note*: Must be the private key, not the `.pub` file

- **`password`**: SSH password (for password authentication)
  - *Example*: `"my-secure-password"`
  - *Purpose*: Password for SSH login
  - *Security*: Consider using key-based auth for better security

#### Optional Fields:

- **`port`**: SSH server port number
  - *Default*: `22`
  - *Example*: `2222`, `22`
  - *Purpose*: Non-standard SSH port if different from 22

- **`k8s_port`**: Kubernetes API server port
  - *Default*: `6443`
  - *Example*: `6443`, `8443`, `443`
  - *Purpose*: Port where Kubernetes API server listens

- **`local_port`**: Local port for the SSH tunnel
  - *Default*: `6443`
  - *Example*: `6443`, `16443`, `8443`
  - *Purpose*: Local port to bind the tunnel (avoid conflicts with other tunnels)

#### Field Relationships and Common Patterns:

**Pattern 1: K8s API on SSH Host**
```json
"ssh": {
  "host": "k8s-master.company.com",
  "username": "admin",
  "key_path": "/home/user/.ssh/id_rsa",
  "k8s_host": "localhost",
  "k8s_port": 6443,
  "local_port": 6443
}
```

**Pattern 2: K8s API on Different Internal Host**
```json
"ssh": {
  "host": "bastion.company.com",
  "username": "jump-user",
  "password": "secure-password",
  "k8s_host": "k8s-internal.company.com",
  "k8s_port": 6443,
  "local_port": 16443
}
```

**Pattern 3: Multiple Clusters (Different Local Ports)**
```json
{
  "cluster-1": {
    "ssh": {
      "host": "bastion1.com",
      "local_port": 16443
    }
  },
  "cluster-2": {
    "ssh": {
      "host": "bastion2.com", 
      "local_port": 16444
    }
  }
}
```

**Note**: SSH host key verification is automatically disabled to prevent interactive prompts. This is equivalent to using `ssh -o StrictHostKeyChecking=no`. While this improves automation, ensure you trust the network path to your SSH hosts.

### Example Clusters Configuration (`clusters.json`)

#### Mixed Configuration with Direct and SSH Access

```json
{
  "production": {
    "kubeconfig_path": "/home/user/.kube/prod-cluster-config",
    "description": "Production Kubernetes cluster (direct access)",
    "environment": "production",
    "location": "us-east-1"
  },
  "staging": {
    "kubeconfig_path": "/home/user/.kube/staging-cluster-config", 
    "description": "Staging environment (direct access)",
    "environment": "staging",
    "location": "us-west-2"
  },
  "remote-prod": {
    "kubeconfig_path": "/home/user/.kube/remote-prod-config",
    "description": "Remote production cluster via SSH tunnel",
    "environment": "production",
    "location": "on-premises",
    "ssh": {
      "host": "bastion.company.com",
      "username": "kubectl-user",
      "key_path": "/home/user/.ssh/company_rsa",
      "k8s_host": "k8s-master.internal",
      "k8s_port": 6443,
      "local_port": 6443
    }
  },
  "dev-cluster": {
    "kubeconfig_path": "/home/user/.kube/dev-config",
    "description": "Development cluster via SSH (password auth)",
    "environment": "development",
    "ssh": {
      "host": "dev-jump.lab.local",
      "username": "developer",
      "password": "dev-password",
      "k8s_host": "localhost",
      "k8s_port": 6443,
      "local_port": 6444
    }
  }
}
```

### Configuration Files

- `clusters-sample.json` - Comprehensive example with multiple environments

## VS Code Integration

### Using VS Code Tasks

Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on macOS) and type "Tasks: Run Task" to access predefined tasks:

- **Install Dependencies**: Installs all required Python packages
- **Start MCP Server**: Starts the server with default configuration
- **Test Server Health**: Tests if the server is responding
- **Setup Virtual Environment**: Creates a Python virtual environment

## Security Considerations

#### General Security
- Add authentication if deploying publicly
- Use HTTPS in production environments
- Validate all input parameters thoroughly
- Implement rate limiting for public endpoints
- Secure kubeconfig files and SSH credentials

#### SSH Tunnel Security
- **SSL Verification**: For SSH tunneled clusters, SSL certificate verification is automatically disabled (`insecure-skip-tls-verify: true`) because the Kubernetes API server certificate is not valid for `127.0.0.1` tunnel endpoints
- **SSH Host Key Verification**: SSH host key checking is disabled for automation, but this reduces security. Consider adding host key validation for production use
- **Key Management**: Store SSH private keys securely with proper permissions (600). Never commit private keys to version control
- **Network Security**: SSH tunnels should only be used in trusted network environments. Consider VPN alternatives for enhanced security

#### Kubeconfig Security
- **File Permissions**: Ensure kubeconfig files have restricted permissions (600 or 640)
- **Temporary Files**: The server creates temporary kubeconfig files for SSH tunneled clusters. These are automatically cleaned up on shutdown
- **Credential Storage**: Avoid storing sensitive credentials in cluster configuration files. Use environment variables or secure credential stores when possible

## Requirements

See `requirements.txt` for the complete list of dependencies. Key requirements include:

- fastapi
- uvicorn
- mcp
- kubernetes (optional, for Kubernetes support)
- paramiko and sshtunnel (optional, for SSH tunnel support)
- pydantic

#### Security Notes for SSH Tunnels
- **SSL Certificate Bypass**: When using SSH tunnels, the MCP server automatically disables SSL certificate verification for the Kubernetes API server because certificates are not valid for `127.0.0.1` tunnel endpoints
- **Production Considerations**: For production environments, consider using VPN connections or properly configured SSL certificates instead of SSH tunnels
- **Credential Protection**: Never store SSH private keys or passwords in the clusters.json file if it might be shared or committed to version control

## Docker Deployment

YAMS includes Docker support for easy deployment and consistent environments.

### Quick Start with Docker

```bash
# Automated setup
./docker-run.sh
```

### Directory Setup

The Docker script automatically creates these directories for volume mounting:

```bash
./clusters/      # Runtime cluster configurations (contains clusters.json)
./sshkeys/       # SSH private keys for tunnel access  
./kubeconfigs/   # Kubernetes config files
```

### File Placement Guide

#### 1. **Cluster Configuration** (`./clusters/`)
```bash
# clusters.json should already be in the clusters/ directory
# Edit ./clusters/clusters.json with your actual cluster settings
```

#### 2. **SSH Keys** (`./sshkeys/`)
```bash
# Copy SSH private keys (for clusters using SSH tunnels)
cp ~/.ssh/id_rsa ./sshkeys/
cp ~/.ssh/company_key ./sshkeys/

# IMPORTANT: Set proper permissions BEFORE running Docker
# SSH keys must have 600 permissions for security
chmod 600 ./sshkeys/*
```

**Note**: SSH keys are mounted read-only in the container for security. Ensure permissions are set correctly on the host system before mounting.

#### 3. **Kubeconfig Files** (`./kubeconfigs/`)
```bash
# Copy kubeconfig files referenced in clusters.json
cp ~/.kube/config ./kubeconfigs/
cp ~/.kube/prod-cluster ./kubeconfigs/
cp ~/.kube/staging-cluster ./kubeconfigs/

# Set proper permissions  
chmod 600 ./kubeconfigs/*
```

### Volume Mount Details

| Host Directory | Container Path | Purpose | Access Mode |
|---------------|----------------|---------|-------------|
| `./clusters/` | `/app/clusters/` | Active cluster configurations | Read-Write |
| `./sshkeys/` | `/app/.ssh/` | SSH private keys for tunneling | Read-Only |
| `./kubeconfigs/` | `/app/kubeconfigs/` | Kubernetes configuration files | Read-Only |

