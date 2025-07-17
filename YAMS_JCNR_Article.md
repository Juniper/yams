# YAMS: Managing JCNR with Model Context Protocol

## Introduction

Managing Kubernetes environments with advanced routing capabilities like JCNR can be complex, especially when dealing with multiple clusters. **YAMS (Yet Another MCP Server)** is a Model Context Protocol server designed to simplify the management and troubleshooting of Juniper Cloud-Native Router (JCNR) deployments across multiple Kubernetes clusters.

YAMS provides network engineers and DevOps teams with a unified interface for managing JCNR infrastructure, integrating with tools like VS Code Copilot Chat for improved workflow efficiency.

## What is YAMS?

YAMS is an HTTP-based Model Context Protocol (MCP) server that integrates with Kubernetes clusters, with specific tools for JCNR deployments. Built on FastAPI and compatible with VS Code Copilot Chat, YAMS simplifies complex Kubernetes operations through a consistent interface.

### Core Architecture

- **HTTP-based MCP Server**: RESTful API design with FastAPI framework
- **Multi-cluster Support**: Manage multiple Kubernetes environments simultaneously
- **SSH Tunnel Integration**: Secure access to private or on-premises clusters
- **JCNR-Specialized Tools**: Purpose-built commands for DPDK, Contrail Agent, and cRPD operations
- **VS Code Integration**: Native support for Copilot Chat and other MCP clients

## JCNR: The Foundation

Juniper Cloud-Native Router (JCNR) is Juniper's containerized routing solution that brings enterprise-grade routing capabilities to Kubernetes environments. JCNR consists of three primary components:

1. **DPDK (Data Plane Development Kit)**: High-performance packet processing
2. **Contrail Agent**: Virtual networking and policy enforcement
3. **cRPD (Containerized Routing Protocol Daemon)**: BGP and other routing protocols

Managing these components across multiple clusters typically requires manual intervention and technical expertise. YAMS helps streamline this process.

## Benefits of YAMS for JCNR Management

### 1. **Multi-Cluster Management**

JCNR management typically requires connecting to each cluster individually and running commands across different namespaces. YAMS provides a unified interface:

```bash
# Traditional approach - requires multiple steps:
kubectl config use-context cluster1
kubectl exec -n contrail vrdpdk-pod -- vif --list
kubectl config use-context cluster2
kubectl exec -n contrail vrdpdk-pod -- vif --list

# YAMS approach - single command across all clusters:
execute_dpdk_command: "vif --list"
```

### 2. **Log Analysis and Diagnostics**

YAMS includes tools for analyzing logs and detecting issues across cluster nodes:

- **Automated Log Scanning**: Searches for error patterns in system logs, DPDK logs, and Contrail logs
- **Core File Detection**: Identifies crash dumps and core files across all nodes
- **Performance Monitoring**: Analyzes large log files and disk usage patterns
- **Targeted Analysis**: Focus on specific pods or namespaces for detailed troubleshooting

### 3. **Secure Remote Access**

Many JCNR deployments are in private or on-premises environments. YAMS supports SSH tunneling for secure access:

```json
{
  "production-jcnr": {
    "kubeconfig_path": "/etc/kube/prod-config",
    "description": "Production JCNR cluster",
    "ssh": {
      "host": "jump-server.company.com",
      "username": "netops",
      "key_path": "/home/user/.ssh/prod_key",
      "k8s_host": "k8s-master.internal",
      "k8s_port": 6443
    }
  }
}
```

### 4. **VS Code Integration**

Integration with VS Code Copilot Chat allows for natural language interactions:

- **"Run comprehensive JCNR analysis on production cluster"** → `jcnr_summary`
- **"Check DPDK interface statistics across all clusters"** → `execute_dpdk_command`
- **"Find any core files in the last 24 hours"** → `check_core_files`
- **"Show me error logs from contrail agents"** → `analyze_logs`
- **"Execute system diagnostics on contrail tools pod"** → `pod_command_and_summary`
- **"Get BGP neighbor status from all cRPD instances"** → `execute_junos_cli_commands`

## Real-World Use Cases

### Use Case 1: Comprehensive JCNR Health Analysis

A network operations team needs to perform deep analysis of JCNR across 15 production clusters:

```bash
# Single YAMS command provides complete datapath analysis
jcnr_summary: cluster_name="all"
```

**Result**: Unified report combining:
- DPDK datapath statistics (next-hops, interfaces, routes, flows)
- HTTP API data with formatted tables (VRFs, routes, interface stats)
- Junos CLI outputs (BGP status, routing tables, system information)
- Command execution summary with success rates and timing

### Use Case 2: Multi-Cluster Health Check

A network operations team needs to verify JCNR health across production clusters:

```bash
# YAMS commands check all clusters with enhanced targeting
execute_dpdk_command: "nh --list"
execute_agent_command: "vif --list" 
execute_junos_cli_commands: "show bgp summary"
pod_command_and_summary: namespace="contrail", pod_name="contrail-tools"
```

**Result**: Health report across all clusters with detailed execution statistics.

### Use Case 3: Performance Troubleshooting

A customer reports intermittent packet drops in their JCNR environment:

```bash
# YAMS provides comprehensive analysis with enhanced tools
jcnr_summary: cluster_name="customer-prod"
analyze_logs: cluster_name="customer-prod", pattern="drop|error|fail", max_lines=200
execute_dpdk_command: "flow -l"
execute_agent_command: "vif --get 0"
```

**Result**: Complete datapath analysis including:
- Interface statistics with packet/byte counters and drop analysis
- Flow table analysis showing active flows and drop patterns  
- HTTP API data revealing routing and VRF state
- Targeted log analysis with configurable patterns and limits

### Use Case 4: Incident Response

A critical JCNR pod crashes in production:

```bash
# YAMS enables rapid incident response with enhanced diagnostics
check_core_files: cluster_name="prod-cluster", max_age_days=1
analyze_logs: pod_name="contrail-vrouter-dpdk-xyz", namespace="contrail", max_lines=500
jcnr_summary: cluster_name="prod-cluster"
pod_command_and_summary: pod_name="contrail-tools", namespace="contrail"
```

**Result**: 
- Core files located with age filtering for recent crashes
- Detailed log analysis with customizable line limits
- Complete JCNR state analysis showing datapath and control plane status
- System diagnostics with execution statistics and success rates

## Installation and Setup

### Docker Deployment (Recommended)

```bash
# Clone YAMS repository
git clone <yams-repository> yams-github
cd yams-github

# Quick start with Docker
./docker-run.sh

# Verify installation
curl http://localhost:40041/health
```

### VS Code Integration

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

### Cluster Configuration

Create `clusters/clusters.json` with your JCNR cluster details:

```json
{
  "jcnr-prod": {
    "kubeconfig_path": "/etc/kube/prod-config",
    "description": "Production JCNR cluster",
    "pod_command_list": "/app/clusters/pod-command-list.json",
    "jcnr_command_list": "/app/clusters/jcnr-command-list.json"
  },
  "jcnr-dev": {
    "kubeconfig_path": "/etc/kube/dev-config",
    "description": "Development JCNR cluster", 
    "ssh": {
      "host": "dev-jump.company.com",
      "username": "devops",
      "key_path": "/home/user/.ssh/dev_key",
      "k8s_host": "localhost"
    },
    "pod_command_list": "/app/clusters/pod-command-list.json"
  }
}
```

### Command Configuration

Configure command sets in JSON files for flexible execution:

**JCNR Commands** (`jcnr-command-list.json`):
```json
{
  "dpdk_commands": ["nh --list", "vif --list", "rt --dump 0", "flow -l"],
  "junos_cli_commands": ["show version", "show interfaces terse", "show route"],
  "http_endpoints": {
    "nh_list": "Snh_NhListReq",
    "vrf_list": "Snh_VrfListReq", 
    "inet4_routes": "Snh_Inet4UcRouteReq"
  }
}
```

**Pod Commands** (`pod-command-list.json`):
```json
{
  "commands": ["uptime", "free -m", "df -h", "ps aux"]
}
```

## Advanced Features

### 1. **Comprehensive JCNR Analysis**

- **`jcnr_summary`**: Complete datapath analysis combining DPDK commands, HTTP API data, and Junos CLI outputs
  - Executes configurable command sets from external JSON files
  - Fetches Sandesh HTTP API data with XML-to-table conversion
  - Provides unified view of next-hops, interfaces, routes, flows, and BGP status
  - Supports both DPDK datapath and cRPD control plane analysis

### 2. **Specialized JCNR Commands**

- **`execute_dpdk_command`**: Target all DPDK pods (vrouter-nodes-vrdpdk) across clusters
- **`execute_agent_command`**: Execute commands in Contrail Agent pods (vrouter-nodes)
- **`execute_junos_cli_commands`**: Interact with cRPD and cSRX routing protocol daemons
  - Automatically prepends 'cli -c' for proper Junos CLI execution
  - Supports comprehensive routing and interface analysis

### 3. **Enhanced Pod Management**

- **`pod_command_and_summary`**: Execute predefined command sets on any pod with execution statistics
  - Commands loaded from configurable JSON files
  - Provides execution summary with success rates and timing
  - Supports custom command lists per cluster

### 4. **Diagnostic Tools**

- **`check_core_files`**: Automated core dump detection with age filtering
- **`analyze_logs`**: Intelligent log analysis with customizable error pattern recognition
- **`execute_command`**: Generic pod command execution with container targeting

### 5. **Flexible Configuration Management**

- **External command configuration**: Commands loaded from JSON files for easy customization
- **Per-cluster command sets**: Different command lists for different clusters
- **Configurable analysis parameters**: Customizable log analysis patterns, age filters, and output limits

### 6. **Multi-Cluster Support**

- **Direct kubeconfig access** for local clusters
- **SSH tunnel support** for remote/private clusters
- **Mixed cluster management** in single configuration

### 7. **Enhanced HTTP API Integration**

- **Sandesh API support**: Direct integration with JCNR HTTP APIs
- **XML-to-table conversion**: Automatic formatting of complex XML responses using URI pattern matching
- **Real-time data access**: Live datapath statistics and configuration data

## Security Considerations

YAMS includes security features for enterprise environments:

- **SSH key-based authentication** with tunnel management
- **SSL certificate handling** for tunneled connections
- **Temporary file cleanup** to prevent credential exposure
- **Kubernetes RBAC integration** for access control

## Benefits

Organizations using YAMS for JCNR management can see improvements in:

- **Reduced troubleshooting time** through centralized access and comprehensive analysis
- **Enhanced operational insights** with unified DPDK, Agent, and cRPD data
- **Fewer manual operations** across multiple clusters with configurable command sets
- **Faster incident response** with unified tooling and real-time HTTP API access
- **Improved debugging capabilities** with integrated log analysis and core file detection
- **Reduced operational errors** through consistent interfaces and automated command execution
- **Better visibility** into JCNR datapath and control plane status with formatted reports

## Conclusion

YAMS provides a unified approach to JCNR management across multiple Kubernetes clusters. By using Model Context Protocol and integrating with modern development tools, YAMS helps network teams:

- **Perform comprehensive analysis** with integrated DPDK, HTTP API, and Junos CLI data
- **Manage operations** across multiple clusters from a single interface
- **Reduce troubleshooting complexity** with automated diagnostic tools and configurable command sets
- **Improve operational consistency** through standardized commands and flexible configuration
- **Access real-time datapath information** via HTTP API integration with formatted output
- **Work more efficiently** with natural language interfaces and execution statistics

For organizations running JCNR deployments, YAMS offers a practical solution for simplifying multi-cluster management and improving operational workflows.

## Getting Started

To get started with YAMS:

1. **Download YAMS** from the repository
2. **Configure your clusters** using the JSON configuration format
3. **Set up VS Code integration** for enhanced workflows
4. **Begin managing** your JCNR infrastructure through the unified interface

YAMS provides a practical approach to JCNR management where multi-cluster operations meet unified tooling.

---

*For technical support and documentation, visit the YAMS project repository.*
