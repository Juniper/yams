# YAMS (Yet Another MCP Server)

**YAMS** is a powerful Model Context Protocol (MCP) server designed for analyzing services running on Kubernetes clusters. YAMS supports both **HTTP** and **stdio** transport modes, providing seamless integration with VS Code Copilot Chat and other MCP-compatible tools.

## What is YAMS?

YAMS is a **generic Kubernetes management tool** that can connect to any Kubernetes environment using standard kubeconfig files or secure SSH tunnels. While designed with Juniper Cloud-Native Router (JCNR) deployments in mind, YAMS works with any Kubernetes cluster.

### Key Capabilities

- **Dual Transport Support**: HTTP transport (default) for web clients and stdio transport for VS Code Copilot Chat and other MCP-compatible tools
- **Multi-cluster Management**: Connect to multiple Kubernetes clusters simultaneously
- **Flexible Access Methods**: Direct kubeconfig access or SSH tunnel connections for remote clusters
- **Generic Kubernetes Operations**: List clusters, namespaces, pods, and execute commands in any pod
- **JCNR-Specific Analysis**: Deep visibility with CLI commands and HTTP API integration. Correlate data from commands to give a usable summary of JCNR state.
- **VS Code Integration**: Native support for VS Code Copilot Chat and other MCP clients

### Use Cases

- **Infrastructure Analysis**: Query and analyze Kubernetes deployments across multiple clusters
- **JCNR Operations**: Monitor and troubleshoot Juniper Cloud-Native Router deployments
- **Remote Cluster Access**: Securely access private or on-premises clusters through SSH tunnels

## Features

- **Dual Transport Support**: HTTP transport (default) and stdio transport for different integration needs
- MCP server built with FastAPI for HTTP mode and native stdio support
- Kubernetes integration with kubeconfig support
- SSH tunnel support for remote cluster access
- **Generic Tools**: `list_clusters`, `list_namespaces`, `list_pods`, `execute_command`, `pod_command_and_summary`
- **JCNR-Specific Tools**: 
  - `execute_dpdk_command` - DPDK datapath commands (vrdpdk pods)
  - `execute_agent_command` - Contrail Agent commands (vrouter-nodes pods)
  - `execute_junos_cli_commands` - cRPD and cSRX routing commands (jcnr namespace)
  - `jcnr_summary` - **Comprehensive JCNR datapath analysis with CLI + HTTP API correlation**
- **Operations Tools**: `check_core_files`, `analyze_logs`
- **Advanced Features**:
  - Configurable command lists via JSON files
  - XML-to-table formatting for Sandesh HTTP API responses
  - Multi-cluster datapath correlation analysis
  - Automated JCNR component discovery
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

- **`pod_command_list`**: Path to JSON file containing commands for pod diagnostics
  - *Example*: `"pod-command-list.json"`
  - *Purpose*: Used by `pod_command_and_summary` tool for running diagnostic commands

- **`jcnr_command_list`**: Path to JSON file containing JCNR datapath commands  
  - *Example*: `"jcnr-command-list.json"`
  - *Purpose*: Used by `jcnr_summary` tool for comprehensive datapath analysis

- **`ssh`**: SSH tunnel configuration object (see SSH Configuration Options below)
  - *Purpose*: Required when cluster is not directly accessible and needs SSH tunneling

#### Configuration Structure:
```json
{
  "cluster-name": {
    "kubeconfig_path": "path/to/kubeconfig",
    "description": "Optional description",
    "pod_command_list": "path/to/pod-command-list.json",
    "jcnr_command_list": "path/to/jcnr-command-list.json",
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
    "pod_command_list": "pod-command-list.json",
    "jcnr_command_list": "jcnr-command-list.json"
  },
  "staging": {
    "kubeconfig_path": "/home/user/.kube/staging-cluster-config", 
    "description": "Staging environment for testing",
    "pod_command_list": "pod-command-list.json"
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
# Lets go to YAMS directory
cd /path/to/yams

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On macOS/Linux
# or venv\Scripts\activate  # On Windows

# Install dependencies
pip install -r requirements.txt
```

**With Local Python:**
```bash
# Start server with Kubernetes sources using HTTP transport (default)
python enhanced_mcp_server.py --port 40041 --clusters-config clusters/clusters.json
```

## Configure VS Code

**For HTTP transport (default):**
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

**For stdio transport (recommended for VS Code):**
```json
{
  "yams-mcp-stdio-server": {
      "type": "stdio",
      "command": "/path/to/yams/run_mcp_stdio.sh",
      "args": [
          "/path/to/yams",
          "/path/to/yams/clusters/clusters-stdio.json",
          "/path/to/yams/venv"
      ]
  }
}
```
## Command Line Options

- `--transport`: Transport mode - `http` (default) or `stdio`
- `--port`: Port to run the HTTP server on (default: 40041, ignored for stdio)
- `--clusters-config`: Path to JSON file containing cluster configurations

## API Endpoints (HTTP Transport Only)

- `GET /`: Server information and available endpoints
- `GET /health`: Health check endpoint
- `POST /mcp`: Main MCP protocol endpoint

## MCP Protocol Support

This server implements the Model Context Protocol with support for both transports:

- **HTTP Transport**: RESTful API endpoints for web clients and testing
- **stdio Transport**: Direct stdin/stdout communication
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

### 7. **execute_junos_cli_commands**
   - Description: Execute a command in all cRPD (Contrail Routing Protocol Daemon) and cSRX pods in jcnr namespace across all clusters
   - Parameters: `command` (string), `cluster_name` (optional string) - executes on all clusters if not specified
   - Example Commands: `show route`, `show bgp summary`, `show interfaces terse`, `show security policies`

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
   - Parameters:
     - `cluster_name` (optional string) - Name of the cluster (analyzes all clusters if not specified)
     - `pod_name` (optional string) - Name of a specific pod to analyze logs for
     - `namespace` (optional string) - Kubernetes namespace of the pod (required if pod_name is specified)
     - `log_paths` (optional array) - Custom paths to search for log files
     - `max_age_days` (optional integer) - Maximum age of log files to analyze in days (default: 7)
     - `max_lines` (optional integer) - Maximum number of lines to return from log analysis (default: 100)
     - `pattern` (optional string) - Custom regex pattern to search for in logs

### 10. **pod_command_and_summary**
   - Description: Run a set of commands on a given pod and summarize the outputs with execution statistics. Commands are loaded exclusively from a file referenced in the cluster configuration's 'pod_command_list' field.
   - Parameters:
     - `pod_name` (string) - Name of the pod to execute commands on
     - `namespace` (string) - Kubernetes namespace of the pod
     - `container` (optional string) - Container name (defaults to first container)
     - `cluster_name` (optional string) - Name of the cluster

### 11. **jcnr_summary** ⭐ (New JCNR Datapath Analysis Tool)
   - Description: **Comprehensive JCNR datapath analysis** combining CLI commands and HTTP API data with correlation analysis
   - Parameters: `cluster_name` (optional string) - Name of the cluster (analyzes all clusters if not specified)
   - **Key Features**:
     - **Automated Discovery**: Finds and connects to DPDK pods (vrdpdk) in contrail namespace
     - **CLI Commands**: Executes comprehensive datapath commands (nh, vif, rt, frr, mpls, flow)
     - **HTTP API Integration**: Fetches data from Sandesh HTTP API (port 8085) with XML-to-table formatting
     - **Correlation Analysis**: Analyzes relationships between next-hops, routes, MPLS labels, and flows
     - **Configurable Commands**: Uses JSON configuration files for customizable command/endpoint lists
     - **Enhanced Output**: Structured tables, summary statistics, and detailed analysis

## JCNR-Specific Features

YAMS provides specialized tools for **Juniper Cloud-Native Router (JCNR)** deployments, offering deep visibility into datapath operations and network state.

### JCNR Analysis

The `jcnr_summary` tool provides comprehensive analysis of JCNR components from datapath
utilities to vRouter Agent insights. 

#### **Configuration Management:**
JCNR commands and endpoints are configurable via JSON files:

```json
{
  "datapath_commands": [
    "nh --list",
    "vif --list", 
    "rt --dump 0",
    "frr --dump",
    "mpls --dump",
    "flow -l"
  ],
  "http_endpoints": {
    "nh_list": "Snh_NhListReq?type=&nh_index=&policy_enabled=",
    "vrf_list": "Snh_VrfListReq?name=",
    "inet4_routes": "Snh_Inet4UcRouteReq?x=0",
    "interface_list": "Snh_ItfReq?name=",
    "flow_list": "Snh_FetchFlowRecord?x=0"
  },
  "http_port": 8085,
  "analysis_config": {
    "max_display_lines": 50,
    "max_table_rows": 20,
    "max_http_display_chars": 5000,
    "enable_detailed_analysis": true,
    "truncate_large_outputs": true
  }
}
```

### JCNR Component Access

#### **DPDK Pods (vrdpdk)**
- **Purpose**: User-space datapath processing
- **Commands**: `vif --list`, `nh --list`, `rt --dump`, `dropstats`
- **Location**: `contrail` namespace
- **Tool**: `execute_dpdk_command`

#### **Contrail Agent Pods (vrouter-nodes)**
- **Purpose**: Control plane agent for datapath programming
- **Commands**: `contrail-status`, `vif --list`, `nh --list`
- **Location**: `contrail` namespace  
- **Tool**: `execute_agent_command`

#### **cRPD Pods (Contrail Routing Protocol Daemon)**
- **Purpose**: BGP/MPLS control plane routing
- **Commands**: `show route`, `show bgp summary`, `show interfaces`
- **Location**: `jcnr` namespace
- **Tool**: `execute_junos_cli_commands`
- **Note**: Commands are automatically formatted for Junos CLI (`cli -c 'command'`)

### JCNR Use Cases

- **Performance Analysis**: Monitor interface statistics, flow processing, packet drops
- **Routing Verification**: Validate route installation across IPv4/IPv6 tables
- **Datapath Debugging**: Correlate next-hops, routes, and flows for troubleshooting
- **Multi-cluster Monitoring**: Compare configurations across JCNR deployments
- **Operational Health**: Check core files, analyze logs, verify component status

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
    "pod_command_list": "pod-command-list.json",
    "jcnr_command_list": "jcnr-command-list.json"
  },
  "staging": {
    "kubeconfig_path": "/home/user/.kube/staging-cluster-config", 
    "description": "Staging environment (direct access)",
    "pod_command_list": "pod-command-list.json"
  },
  "remote-prod": {
    "kubeconfig_path": "/home/user/.kube/remote-prod-config",
    "description": "Remote production cluster via SSH tunnel",
    "pod_command_list": "pod-command-list.json",
    "jcnr_command_list": "jcnr-command-list.json",
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
    "pod_command_list": "pod-command-list.json",
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

## Pod Command Configuration

The `pod_command_list` configuration enables intelligent, pod-specific diagnostic command execution through the `pod_command_and_summary` tool.

### Configuration File Structure

Create a JSON file with pod-specific command configurations:

```json
{
  "description": "Enhanced pod-specific diagnostic commands with pattern matching support",
  "pod_configurations": [
    {
      "pod_name": "nginx-*",
      "namespace": "default",
      "description": "Nginx web server diagnostic commands (pattern match)",
      "commands": [
        "hostname",
        "uptime",
        "ps aux | grep nginx",
        "nginx -t",
        "nginx -V",
        "curl -I http://localhost",
        "df -h",
        "free -m",
        "netstat -tulpn | grep :80",
        "ls -la /var/log/nginx/",
        "tail -20 /var/log/nginx/access.log",
        "tail -20 /var/log/nginx/error.log"
      ]
    },
    {
      "pod_name": "redis-*",
      "namespace": "default",
      "description": "Redis cache server diagnostic commands",
      "commands": [
        "hostname",
        "uptime",
        "ps aux | grep redis",
        "redis-cli ping",
        "redis-cli info memory",
        "redis-cli info stats",
        "redis-cli config get '*'",
        "df -h",
        "free -m",
        "netstat -tulpn | grep :6379"
      ]
    },
    {
      "pod_name": "*",
      "namespace": "*",
      "description": "Generic pod diagnostic commands (fallback)",
      "commands": [
        "hostname",
        "uptime",
        "ps aux | head -20",
        "df -h",
        "free -m",
        "env | grep -E 'PATH|HOME|USER|KUBERNETES'",
        "ip addr show",
        "netstat -tulpn | head -10"
      ]
    }
  ],
  "execution_options": {
    "timeout_seconds": 30,
    "max_output_size": 1048576,
    "retry_count": 1,
    "parallel_execution": false,
    "continue_on_error": true
  }
}
```

### Pod Name Matching System

The system uses intelligent pattern matching to select appropriate command sets:

#### 1. **Exact Match**
```json
{
  "pod_name": "nginx-deployment-abc123",
  "namespace": "default",
  "commands": ["specific", "commands", "for", "this", "exact", "pod"]
}
```

#### 2. **Wildcard Pattern Match**
```json
{
  "pod_name": "nginx-*",
  "namespace": "default",
  "commands": ["commands", "for", "any", "nginx", "pod"]
}
```

#### 3. **Universal Fallback**
```json
{
  "pod_name": "*",
  "namespace": "*",
  "commands": ["generic", "commands", "for", "any", "pod"]
}
```

### Command Selection Priority

When executing `pod_command_and_summary`, the system follows this selection logic:

1. **Exact Match**: Look for exact pod name and namespace match
2. **Pattern Match**: Find wildcard patterns that match the pod name  
3. **Fallback**: Use the first configuration if no matches found
4. **Universal**: Use `*` pattern as final fallback

**Example**: For pod `nginx-deployment-abc123` in namespace `default`:
1. Try exact match: `nginx-deployment-abc123` 
2. Try pattern match: `nginx-*`
3. Fallback to first config or `*` pattern

### Execution Options

Configure command execution behavior globally:

```json
"execution_options": {
  "timeout_seconds": 30,           // Command execution timeout
  "max_output_size": 1048576,      // Max output size in bytes (1MB)
  "retry_count": 1,                // Number of retry attempts on failure
  "parallel_execution": false,     // Execute commands in parallel (not implemented)
  "continue_on_error": true        // Continue if one command fails
}
```

### Usage Examples

#### Execute pod-specific commands
```bash
# The system automatically selects appropriate commands based on pod name
curl -X POST http://127.0.0.1:40041/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "pod_command_and_summary",
      "arguments": {
        "pod_name": "nginx-deployment-abc123",
        "namespace": "default",
        "cluster_name": "production"
      }
    }
  }'
```

### Command Output Summary

The tool provides detailed execution statistics:

```
Command Execution Summary
=========================
Pod: nginx-deployment-abc123
Namespace: default
Container: nginx
Cluster: production
Command Source: cluster_config: /path/to/pod-command-list.json

Execution Options:
  Timeout: 30s
  Max Output Size: 1048576 bytes
  Retry Count: 1
  Continue on Error: true

✓ Command 1: nginx -t (success, 5 lines, 245 bytes)
   Execution Time: 0.12s
   First line: nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
   Last line: nginx: configuration file /etc/nginx/nginx.conf test is successful

✓ Command 2: ps aux | grep nginx (success, 8 lines, 456 bytes)
   Execution Time: 0.08s
   First line: root      1234  0.0  0.1 123456  7890 ?        Ss   10:30   0:00 nginx: master
   Last line: www-data   1251  0.0  0.0  12345   890 pts/0    S+   10:31   0:00 grep nginx

Commands executed: 12
Successful: 11
Failed: 1
Success rate: 91.7%
```

### Integration with Clusters

Reference your pod command list in the cluster configuration:

```json
{
  "production": {
    "kubeconfig_path": "/path/to/kubeconfig",
    "pod_command_list": "clusters/pod-command-list.json",
    "description": "Production cluster with enhanced pod diagnostics"
  }
}
```

This intelligent command selection system ensures that each pod type receives appropriate diagnostic commands, making troubleshooting more efficient and targeted.

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

