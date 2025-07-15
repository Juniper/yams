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

- **"Check DPDK interface statistics across all clusters"**
- **"Find any core files in the last 24 hours"**
- **"Show me error logs from contrail agents"**
- **"Generate a core dump of the DPDK process for debugging"**

## Real-World Use Cases

### Use Case 1: Multi-Cluster Health Check

A network operations team needs to verify JCNR health across 15 production clusters:

```bash
# Single YAMS command checks all clusters
execute_dpdk_command: "contrail-status"
execute_agent_command: "vif --list"
execute_crpd_command: "show bgp summary"
```

**Result**: Health report across all clusters, reducing manual checking time.

### Use Case 2: Performance Troubleshooting

A customer reports intermittent packet drops in their JCNR environment:

```bash
# YAMS provides comprehensive analysis
analyze_logs: cluster_name="customer-prod", pattern="drop|error|fail"
execute_dpdk_command: "dropstats"
execute_agent_command: "vif --get 0"
```

**Result**: Identification of packet drop sources and interface statistics across the infrastructure.

### Use Case 3: Incident Response

A critical JCNR pod crashes in production:

```bash
# YAMS enables rapid incident response
check_core_files: cluster_name="prod-cluster"
analyze_logs: pod_name="contrail-vrouter-dpdk-xyz", namespace="contrail"
```

**Result**: Core files located, logs analyzed, and debugging information gathered efficiently.

## Installation and Setup

### Docker Deployment (Recommended)

```bash
# Clone YAMS repository
git clone <yams-repository>
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
    "description": "Production JCNR environment",
    "environment": "production",
    "location": "us-east-1"
  },
  "jcnr-dev": {
    "kubeconfig_path": "/etc/kube/dev-config", 
    "description": "Development JCNR environment",
    "ssh": {
      "host": "dev-jump.company.com",
      "username": "devops",
      "key_path": "/home/user/.ssh/dev_key",
      "k8s_host": "localhost"
    }
  }
}
```

## Advanced Features

### 1. **Specialized JCNR Commands**

- **`execute_dpdk_command`**: Target all DPDK pods across clusters
- **`execute_agent_command`**: Execute commands in Contrail Agent pods
- **`execute_crpd_command`**: Interact with cRPD routing protocol daemons

### 2. **Diagnostic Tools**

- **`check_core_files`**: Automated core dump detection
- **`analyze_logs`**: Intelligent log analysis with error pattern recognition
- **`execute_command`**: Generic pod command execution

### 3. **Multi-Environment Support**

- **Direct kubeconfig access** for local clusters
- **SSH tunnel support** for remote/private clusters
- **Mixed environment management** in single configuration

## Security Considerations

YAMS includes security features for enterprise environments:

- **SSH key-based authentication** with tunnel management
- **SSL certificate handling** for tunneled connections
- **Temporary file cleanup** to prevent credential exposure
- **Kubernetes RBAC integration** for access control

## Benefits

Organizations using YAMS for JCNR management can see improvements in:

- **Reduced troubleshooting time** through centralized access
- **Fewer manual operations** across multiple clusters  
- **Faster incident response** with unified tooling
- **Reduced operational errors** through consistent interfaces

## Conclusion

YAMS provides a unified approach to JCNR management across multiple Kubernetes clusters. By using Model Context Protocol and integrating with modern development tools, YAMS helps network teams:

- **Manage operations** across multiple clusters from a single interface
- **Reduce troubleshooting complexity** with integrated tools
- **Improve operational consistency** through standardized commands
- **Work more efficiently** with natural language interfaces

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
