# YAMS (Yet Another MCP Server)

Juniper Cloud-Native Router (JCNR) is Juniper's software-based, 
cloud-native router solution. JCNR runs on various cloud and on-prem 
environments providing rich routing solution. JCNR runs on kubernetes
in these deployment environments.

YAMS (Yet Another MCP Server) is a Model Context Protocol (MCP)
server with Kubernetes support. This MCP server is generic
in nature and can be used for any kubernetes environment either using
kubeconfig or SSH.

Analysing JCNR deployments is one the usecases for YAMS where YAMS 
can talk to multiple kubernetes clusters running JCNR instances,
fetches information related JCNR and relate data for better
understanding of the deployments. 

There are generic tools provided in YAMS for accessing any pod in any
namespace in a given cluster.

## Features

- HTTP-based MCP server using FastAPI
- Kubernetes integration with kubeconfig support
- SSH tunnel support for remote cluster access
- Generic Tools: `list_clusters`, `list_namespaces`, `list_pods`, `execute_command`
- Specialized JCNR Tools: `execute_dpdk_command`, `execute_agent_command`, `execute_crpd_command`
- VS Code Copilot Chat compatible
- CORS support and health check endpoint

## Quick Setup

### 1. Install Dependencies

```bash
# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On macOS/Linux
# or venv\Scripts\activate  # On Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Clusters

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

### 3. Start the Server

```bash
# Start server with Kubernetes sources
python enhanced_mcp_server.py --port 40041 --clusters-config clusters.json
```

### 4. Configure VS Code

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

- `--port`: Port to run the server on (default: 8000)
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

## Production Deployment

### Security Considerations

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

### Performance Optimization

- Use a production ASGI server like Gunicorn
- Add caching for frequently accessed resources
- Implement connection pooling for database connections
- Monitor server performance and resource usage

## Requirements

See `requirements.txt` for the complete list of dependencies. Key requirements include:

- fastapi
- uvicorn
- mcp
- kubernetes (optional, for Kubernetes support)
- paramiko and sshtunnel (optional, for SSH tunnel support)
- pydantic

## Support

For issues or questions:

1. Check the console output for error messages
2. Verify all dependencies are installed correctly
3. Test with the provided examples
4. Review the MCP protocol documentation
5. Check VS Code developer console for client-side errors
6. Test SSH connections manually before configuring tunnels

## SSH Public Key Authentication Setup

When using SSH tunnel access with key-based authentication, follow these steps:

### 1. Generate SSH Key Pair

```bash
# Generate RSA key pair (replace 'mykey' with your desired key name)
ssh-keygen -t rsa -b 4096 -f ~/.ssh/mykey

# Set correct permissions
chmod 600 ~/.ssh/mykey
chmod 644 ~/.ssh/mykey.pub
```

### 2. Install Public Key on Remote Server

```bash
# Copy your public key to the remote server (replace with your details)
ssh-copy-id -i ~/.ssh/mykey.pub username@remote-host.com
```

Or manually:
```bash
# Copy public key content
cat ~/.ssh/mykey.pub

# SSH to remote server and add it
ssh username@remote-host.com
mkdir -p ~/.ssh
echo "ssh-rsa AAAAB3NzaC1yc2E... your-public-key-here" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
chmod 700 ~/.ssh
```

### 3. Test SSH Connection

```bash
# Test the key-based authentication (replace with your details)
ssh -i ~/.ssh/mykey username@remote-host.com
```

### 4. Configure in clusters.json

```json
{
  "my-cluster": {
    "kubeconfig_path": "/home/username/.kube/config",
    "ssh": {
      "host": "remote-host.com",
      "username": "username",
      "key_path": "/home/localuser/.ssh/mykey",
      "k8s_host": "localhost"
    }
  }
}
```

### 5. Key Points

- **Private Key** (e.g., `mykey`) - Used in `key_path` configuration
- **Public Key** (e.g., `mykey.pub`) - Installed on remote server
- SSH host key verification is automatically disabled for automation
- Use either `key_path` OR `password` for authentication, not both
- Ensure private key has correct permissions (600)

#### Security Notes for SSH Tunnels
- **SSL Certificate Bypass**: When using SSH tunnels, the MCP server automatically disables SSL certificate verification for the Kubernetes API server because certificates are not valid for `127.0.0.1` tunnel endpoints
- **Production Considerations**: For production environments, consider using VPN connections or properly configured SSL certificates instead of SSH tunnels
- **Credential Protection**: Never store SSH private keys or passwords in the clusters.json file if it might be shared or committed to version control
