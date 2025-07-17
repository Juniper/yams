#!/usr/bin/env python3
"""
Enhanced MCP HTTP Server with Kubernetes Integration

A Model Context Protocol server that runs over HTTP and provides Kubernetes cluster management.
This server can connect to remote Kubernetes clusters using kubeconfig files.
"""

import argparse
import asyncio
import json
import logging
import os
import tempfile
import time
import xml.etree.ElementTree as ET
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Awaitable

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import mcp.types as types
from mcp.server import Server
from mcp.server.models import InitializationOptions

try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
    from kubernetes.stream import stream
    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False
    print("Warning: kubernetes library not available. Install with: pip install kubernetes")

try:
    import paramiko
    from sshtunnel import SSHTunnelForwarder
    SSH_AVAILABLE = True
except ImportError:
    SSH_AVAILABLE = False
    print("Warning: SSH libraries not available. Install with: pip install paramiko sshtunnel")

try:
    import requests
    HTTP_AVAILABLE = True
except ImportError:
    HTTP_AVAILABLE = False
    print("Warning: requests library not available. Install with: pip install requests")



# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Pydantic models for HTTP requests/responses
class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[int] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None





class KubernetesManager:
    """Manages Kubernetes cluster connections and operations with SSH tunnel support."""
    
    def __init__(self, clusters_config_path: str = None):
        self.clusters_config = {}
        self.active_tunnels = {}  # Store active SSH tunnels
        self.temp_kubeconfigs = {}  # Store temporary kubeconfig file paths
        if clusters_config_path and os.path.exists(clusters_config_path):
            self.load_clusters_config(clusters_config_path)
    
    def load_clusters_config(self, config_path: str):
        """Load clusters configuration from JSON file."""
        try:
            with open(config_path, 'r') as f:
                self.clusters_config = json.load(f)
            logger.info(f"Loaded {len(self.clusters_config)} cluster configurations")
        except Exception as e:
            logger.error(f"Failed to load clusters config: {e}")
            self.clusters_config = {}
    
    def get_k8s_client(self, cluster_name: str = None):
        """Get Kubernetes client for specified cluster or default, with SSH tunnel support."""
        if not KUBERNETES_AVAILABLE:
            raise Exception("Kubernetes library not available")
        
        if cluster_name and cluster_name in self.clusters_config:
            cluster_config = self.clusters_config[cluster_name]
            kubeconfig_path = cluster_config["kubeconfig_path"]
            
            # Check if SSH tunnel is required
            ssh_config = cluster_config.get("ssh")
            if ssh_config and SSH_AVAILABLE:
                self._setup_ssh_tunnel(cluster_name, ssh_config)
                # Create a temporary kubeconfig with tunnel URL
                kubeconfig_path = self._create_tunneled_kubeconfig(cluster_name, cluster_config)
            elif ssh_config and not SSH_AVAILABLE:
                raise Exception("SSH tunnel required but SSH libraries not available. Install with: pip install paramiko sshtunnel")
            
            # Only check local file existence if NOT using SSH tunnel
            if not ssh_config and not os.path.exists(kubeconfig_path):
                raise Exception(f"Kubeconfig file not found: {kubeconfig_path}")
            
            # Load specific kubeconfig
            config.load_kube_config(config_file=kubeconfig_path)
        else:
            # Use default kubeconfig
            try:
                config.load_kube_config()
            except Exception:
                # Try in-cluster config
                config.load_incluster_config()
        
        return client.CoreV1Api()
    
    def _setup_ssh_tunnel(self, cluster_name: str, ssh_config: dict):
        """Set up SSH tunnel for cluster access."""
        if cluster_name in self.active_tunnels:
            # Tunnel already exists
            return
        
        try:
            ssh_host = ssh_config["host"]
            ssh_port = ssh_config.get("port", 22)
            ssh_username = ssh_config["username"]
            ssh_key_path = ssh_config.get("key_path")
            ssh_password = ssh_config.get("password")
            
            # Kubernetes API server details (accessible from SSH host)
            k8s_host = ssh_config.get("k8s_host", "localhost")
            k8s_port = ssh_config.get("k8s_port", 6443)
            local_port = ssh_config.get("local_port", 6443)
            
            # Create SSH tunnel with disabled host key checking
            tunnel = SSHTunnelForwarder(
                (ssh_host, ssh_port),
                ssh_username=ssh_username,
                ssh_pkey=ssh_key_path if ssh_key_path else None,
                ssh_password=ssh_password if ssh_password else None,
                remote_bind_address=(k8s_host, k8s_port),
                local_bind_address=('127.0.0.1', local_port),
                # Disable host key verification to avoid yes/no prompts
                ssh_config_file=None,
                set_keepalive=30,
                host_pkey_directories=[],
                allow_agent=False,
                compression=False
            )
            
            # Set SSH client options to disable host key checking
            tunnel.ssh_transport_factory = self._create_ssh_transport_factory()
            
            tunnel.start()
            self.active_tunnels[cluster_name] = tunnel
            logger.info(f"SSH tunnel established for cluster {cluster_name}: localhost:{local_port} -> {ssh_host}:{ssh_port} -> {k8s_host}:{k8s_port}")
            
        except Exception as e:
            logger.error(f"Failed to establish SSH tunnel for cluster {cluster_name}: {e}")
            raise Exception(f"SSH tunnel setup failed: {str(e)}")
    
    def _create_ssh_transport_factory(self):
        """Create SSH transport factory with disabled host key checking."""
        def transport_factory(sock):
            transport = paramiko.Transport(sock)
            # Disable host key verification
            transport.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            return transport
        return transport_factory
    
    def close_ssh_tunnels(self):
        """Close all active SSH tunnels and clean up temporary files."""
        for cluster_name, tunnel in self.active_tunnels.items():
            try:
                tunnel.stop()
                logger.info(f"SSH tunnel closed for cluster {cluster_name}")
            except Exception as e:
                logger.error(f"Error closing SSH tunnel for {cluster_name}: {e}")
        self.active_tunnels.clear()
        
        # Clean up temporary kubeconfig files
        for cluster_name, temp_path in self.temp_kubeconfigs.items():
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                    logger.info(f"Cleaned up temporary kubeconfig for {cluster_name}: {temp_path}")
            except Exception as e:
                logger.error(f"Error cleaning up temporary kubeconfig for {cluster_name}: {e}")
        self.temp_kubeconfigs.clear()
    
    def _create_tunneled_kubeconfig(self, cluster_name: str, cluster_config: dict) -> str:
        """Create a temporary kubeconfig file with SSH tunnel server URL."""
        try:
            ssh_config = cluster_config["ssh"]
            original_kubeconfig_path = cluster_config["kubeconfig_path"]
            local_port = ssh_config.get("local_port", 6443)
            
            # Read the original kubeconfig from remote host via SSH
            ssh_host = ssh_config["host"]
            ssh_port = ssh_config.get("port", 22)
            ssh_username = ssh_config["username"]
            ssh_key_path = ssh_config.get("key_path")
            ssh_password = ssh_config.get("password")
            
            # Use paramiko to read the remote file
            if not SSH_AVAILABLE:
                raise Exception("SSH libraries not available for kubeconfig reading")
            
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            try:
                # Connect via SSH
                if ssh_key_path:
                    ssh_client.connect(ssh_host, port=ssh_port, username=ssh_username, 
                                     key_filename=ssh_key_path)
                else:
                    ssh_client.connect(ssh_host, port=ssh_port, username=ssh_username, 
                                     password=ssh_password)
                
                # Read the remote kubeconfig file
                sftp = ssh_client.open_sftp()
                with sftp.open(original_kubeconfig_path, 'r') as remote_file:
                    kubeconfig_yaml = remote_file.read()
                sftp.close()
                
            finally:
                ssh_client.close()
            
            # Parse the kubeconfig YAML
            kubeconfig_content = yaml.safe_load(kubeconfig_yaml)
            
            # Update server URLs to point to local tunnel and disable SSL verification
            if 'clusters' in kubeconfig_content:
                for cluster in kubeconfig_content['clusters']:
                    if 'cluster' in cluster and 'server' in cluster['cluster']:
                        # Replace the server URL with tunnel endpoint
                        original_server = cluster['cluster']['server']
                        cluster['cluster']['server'] = f"https://127.0.0.1:{local_port}"
                        # Disable SSL verification for tunneled connections
                        cluster['cluster']['insecure-skip-tls-verify'] = True
                        logger.info(f"Redirected {original_server} -> https://127.0.0.1:{local_port} (SSL verification disabled)")
            
            # Create temporary file with modified kubeconfig
            temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
            yaml.dump(kubeconfig_content, temp_file, default_flow_style=False)
            temp_file.close()
            
            # Store the temporary file path for cleanup
            self.temp_kubeconfigs[cluster_name] = temp_file.name
            
            logger.info(f"Created tunneled kubeconfig for {cluster_name}: {temp_file.name}")
            return temp_file.name
            
        except Exception as e:
            logger.error(f"Failed to create tunneled kubeconfig for {cluster_name}: {e}")
            raise Exception(f"Tunneled kubeconfig creation failed: {str(e)}")
    
    def load_jcnr_command_list(self, cluster_name: str = None) -> Dict[str, Any]:
        """Load JCNR command list configuration for the specified cluster.
        
        This method now requires a jcnr_command_list file to be configured in the cluster config.
        No default commands are provided - configuration must be explicit.
        
        Supports two formats:
        1. Simple array: ["cmd1", "cmd2", ...] - converted to full structure
        2. Full object: {"datapath_commands": [...], "http_endpoints": {...}, ...}
        """
        try:
            # Require cluster name to be specified
            if not cluster_name:
                raise Exception("Cluster name is required for JCNR summary. No default configuration available.")
            
            # Require cluster to exist in configuration
            if cluster_name not in self.clusters_config:
                raise Exception(f"Cluster '{cluster_name}' not found in configuration")
            
            cluster_config = self.clusters_config[cluster_name]
            command_list_path = cluster_config.get("jcnr_command_list")
            
            # Require jcnr_command_list to be configured
            if not command_list_path:
                raise Exception(f"No jcnr_command_list configured for cluster '{cluster_name}'. This field is required for jcnr_summary tool.")
            
            # Require the file to exist
            if not os.path.exists(command_list_path):
                raise Exception(f"JCNR command list file not found for cluster {cluster_name}: {command_list_path}")
            
            with open(command_list_path, 'r') as f:
                data = json.load(f)
            
            # Handle different formats
            if isinstance(data, list):
                # Simple array format - convert to full structure
                command_config = {
                    "datapath_commands": data,
                    "http_endpoints": {
                        "nh_list": "Snh_NhListReq?type=&nh_index=&policy_enabled=",
                        "vrf_list": "Snh_VrfListReq?name=",
                        "inet4_routes": "Snh_Inet4UcRouteReq?x=0"
                    },
                    "http_port": 8085,
                    "analysis_config": {
                        "max_display_lines": 50,
                        "max_http_display_chars": 5000,
                        "enable_detailed_analysis": True,
                        "truncate_large_outputs": True
                    }
                }
            elif isinstance(data, dict):
                # Full object format - use as-is but ensure required fields
                command_config = data
                if "datapath_commands" not in command_config:
                    raise Exception(f"JCNR command file missing 'datapath_commands' field: {command_list_path}")
            else:
                raise Exception(f"Invalid JCNR command file format. Expected list or object, got {type(data)}: {command_list_path}")
                
            logger.info(f"Loaded JCNR command list for cluster {cluster_name} from {command_list_path}")
            return command_config
            
        except Exception as e:
            logger.error(f"Failed to load JCNR command list for cluster {cluster_name}: {e}")
            # Re-raise the exception instead of returning defaults
            raise e
    


    def list_clusters(self) -> List[Dict[str, str]]:
        """List all configured clusters."""
        clusters = []
        for name, config_data in self.clusters_config.items():
            clusters.append({
                "name": name,
                "kubeconfig_path": config_data.get("kubeconfig_path", ""),
                "description": config_data.get("description", ""),
                "status": "configured"
            })
        return clusters
    
    def list_namespaces(self, cluster_name: str = None) -> List[Dict[str, str]]:
        """List namespaces in the specified cluster."""
        try:
            k8s_client = self.get_k8s_client(cluster_name)
            namespaces = k8s_client.list_namespace()
            
            result = []
            for ns in namespaces.items:
                result.append({
                    "name": ns.metadata.name,
                    "status": ns.status.phase,
                    "created": str(ns.metadata.creation_timestamp),
                    "cluster": cluster_name or "default"
                })
            
            return result
        except Exception as e:
            logger.error(f"Error listing namespaces: {e}")
            raise Exception(f"Failed to list namespaces: {str(e)}")
    
    def list_pods(self, namespace: str, cluster_name: str = None) -> List[Dict[str, Any]]:
        """List pods in the specified namespace and cluster."""
        try:
            k8s_client = self.get_k8s_client(cluster_name)
            pods = k8s_client.list_namespaced_pod(namespace=namespace)
            
            result = []
            for pod in pods.items:
                result.append({
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "status": pod.status.phase,
                    "ready": self._get_pod_ready_status(pod),
                    "restarts": self._get_pod_restart_count(pod),
                    "created": str(pod.metadata.creation_timestamp),
                    "node": pod.spec.node_name,
                    "cluster": cluster_name or "default"
                })
            
            return result
        except Exception as e:
            logger.error(f"Error listing pods: {e}")
            raise Exception(f"Failed to list pods: {str(e)}")
    
    def _get_pod_ready_status(self, pod) -> str:
        """Get pod ready status as string."""
        if not pod.status.container_statuses:
            return "0/0"
        
        ready_count = sum(1 for cs in pod.status.container_statuses if cs.ready)
        total_count = len(pod.status.container_statuses)
        return f"{ready_count}/{total_count}"
    
    def _get_pod_restart_count(self, pod) -> int:
        """Get total restart count for pod."""
        if not pod.status.container_statuses:
            return 0
        
        return sum(cs.restart_count for cs in pod.status.container_statuses)
    
    def execute_pod_command(self, pod_name: str, namespace: str, command: str, container: str = None, cluster_name: str = None) -> Dict[str, Any]:
        """Execute a command in a specific pod."""
        try:
            if not KUBERNETES_AVAILABLE:
                raise Exception("Kubernetes library not available")
            
            k8s_client = self.get_k8s_client(cluster_name)
            
            # Check if pod exists
            try:
                pod = k8s_client.read_namespaced_pod(name=pod_name, namespace=namespace)
            except Exception as e:
                raise Exception(f"Pod '{pod_name}' not found in namespace '{namespace}': {str(e)}")
            
            # If no container specified, use the first container
            if not container and pod.spec.containers:
                container = pod.spec.containers[0].name
            elif not container:
                raise Exception(f"No containers found in pod '{pod_name}'")
            
            # Prepare command for execution
            if isinstance(command, str):
                # Special handling for cRPD CLI commands
                if namespace == "jcnr" and "crpd" in pod_name.lower() and command.startswith("cli "):
                    # Use a shell to preserve the entire command as a single unit for cRPD
                    cmd = ["sh", "-c", command]
                else:
                    cmd = command.split()
            else:
                cmd = command
            
            # Execute command
            try:
                resp = stream(
                    k8s_client.connect_get_namespaced_pod_exec,
                    pod_name,
                    namespace,
                    command=cmd,
                    container=container,
                    stderr=True,
                    stdin=False,
                    stdout=True,
                    tty=False
                )
                
                return {
                    "pod": pod_name,
                    "namespace": namespace,
                    "container": container,
                    "command": command,
                    "cluster": cluster_name or "default",
                    "output": resp,
                    "status": "success"
                }
                
            except Exception as e:
                return {
                    "pod": pod_name,
                    "namespace": namespace,
                    "container": container,
                    "command": command,
                    "cluster": cluster_name or "default",
                    "output": f"Command execution failed: {str(e)}",
                    "status": "error"
                }
                
        except Exception as e:
            logger.error(f"Error executing command in pod: {e}")
            raise Exception(f"Failed to execute command: {str(e)}")
    
    def execute_dpdk_command(self, command: str, cluster_name: str = None) -> List[Dict[str, Any]]:
        """Execute a command in all DPDK pods (vrdpdk) in contrail namespace."""
        results = []
        clusters_to_check = [cluster_name] if cluster_name else list(self.clusters_config.keys())
        
        for cluster in clusters_to_check:
            try:
                # Get pods in contrail namespace
                pods = self.list_pods("contrail", cluster)
                dpdk_pods = [pod for pod in pods if "vrdpdk" in pod["name"]]
                
                for pod in dpdk_pods:
                    try:
                        result = self.execute_pod_command(
                            pod["name"], "contrail", command, None, cluster
                        )
                        result["pod_type"] = "DPDK"
                        results.append(result)
                    except Exception as e:
                        results.append({
                            "pod": pod["name"],
                            "namespace": "contrail",
                            "command": command,
                            "cluster": cluster,
                            "pod_type": "DPDK",
                            "output": f"Failed to execute command: {str(e)}",
                            "status": "error"
                        })
                        
            except Exception as e:
                results.append({
                    "cluster": cluster,
                    "namespace": "contrail",
                    "command": command,
                    "pod_type": "DPDK",
                    "output": f"Failed to access cluster: {str(e)}",
                    "status": "error"
                })
        
        return results
    
    def execute_agent_command(self, command: str, cluster_name: str = None) -> List[Dict[str, Any]]:
        """Execute a command in all Contrail Agent pods (vrouter-nodes) in contrail namespace."""
        results = []
        clusters_to_check = [cluster_name] if cluster_name else list(self.clusters_config.keys())
        
        for cluster in clusters_to_check:
            try:
                # Get pods in contrail namespace
                pods = self.list_pods("contrail", cluster)
                agent_pods = [pod for pod in pods if "vrouter-nodes" in pod["name"] and "vrdpdk" not in pod["name"]]
                
                for pod in agent_pods:
                    try:
                        result = self.execute_pod_command(
                            pod["name"], "contrail", command, None, cluster
                        )
                        result["pod_type"] = "Agent"
                        results.append(result)
                    except Exception as e:
                        results.append({
                            "pod": pod["name"],
                            "namespace": "contrail",
                            "command": command,
                            "cluster": cluster,
                            "pod_type": "Agent",
                            "output": f"Failed to execute command: {str(e)}",
                            "status": "error"
                        })
                        
            except Exception as e:
                results.append({
                    "cluster": cluster,
                    "namespace": "contrail",
                    "command": command,
                    "pod_type": "Agent",
                    "output": f"Failed to access cluster: {str(e)}",
                    "status": "error"
                })
        
        return results
    
    def execute_junos_cli_commands(self, command: str, cluster_name: str = None) -> List[Dict[str, Any]]:
        """Execute a command in all cRPD and cSRX pods in jcnr namespace.
        Automatically prepends 'cli -c' to commands for proper Junos CLI execution."""
        results = []
        clusters_to_check = [cluster_name] if cluster_name else list(self.clusters_config.keys())
        
        # If command doesn't start with cli -c, prepend it
        if not command.startswith("cli -c") and not command.startswith("cli -C"):
            # Strip any existing "cli " prefix if it exists
            if command.startswith("cli "):
                command = command[4:].strip()
            # Format the command properly for Junos CLI
            command = f"cli -c '{command}'"
        
        for cluster in clusters_to_check:
            try:
                # Get pods in jcnr namespace
                pods = self.list_pods("jcnr", cluster)
                # Look for both cRPD and cSRX pods
                junos_pods = [pod for pod in pods if any(pod_type in pod["name"].lower() for pod_type in ["crpd", "csrx"])]
                
                for pod in junos_pods:
                    try:
                        result = self.execute_pod_command(
                            pod["name"], "jcnr", command, None, cluster
                        )
                        # Determine pod type based on name
                        if "crpd" in pod["name"].lower():
                            result["pod_type"] = "cRPD"
                        elif "csrx" in pod["name"].lower():
                            result["pod_type"] = "cSRX"
                        else:
                            result["pod_type"] = "Junos"
                        results.append(result)
                    except Exception as e:
                        pod_type = "cRPD" if "crpd" in pod["name"].lower() else ("cSRX" if "csrx" in pod["name"].lower() else "Junos")
                        results.append({
                            "pod": pod["name"],
                            "namespace": "jcnr",
                            "command": command,
                            "cluster": cluster,
                            "pod_type": pod_type,
                            "output": f"Failed to execute command: {str(e)}",
                            "status": "error"
                        })
                        
            except Exception as e:
                results.append({
                    "cluster": cluster,
                    "namespace": "jcnr",
                    "command": command,
                    "pod_type": "Junos",
                    "output": f"Failed to access cluster: {str(e)}",
                    "status": "error"
                })
        
        return results
        
        return results
    
    def check_core_files(self, cluster_name: str = None, search_paths: List[str] = None, max_age_days: int = 7) -> List[Dict[str, Any]]:
        """Check for core files on nodes in Kubernetes clusters."""
        results = []
        clusters_to_check = [cluster_name] if cluster_name else list(self.clusters_config.keys())
        
        # Default search paths for core files
        default_search_paths = [
            "/cores",
            "/var/cores",
            "/var/crash",
            "/var/log/crash",
            "/var/log/cores"
        ]
        
        paths_to_search = search_paths if search_paths else default_search_paths
        
        for cluster in clusters_to_check:
            try:
                # Get Kubernetes client for this specific cluster
                self.get_k8s_client(cluster)
                v1 = client.CoreV1Api()
                nodes = v1.list_node()
                
                for node in nodes.items:
                    node_name = node.metadata.name
                    try:
                        # Try to find a pod running on this node to execute commands
                        # We'll use any pod that has host filesystem access
                        pods = v1.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={node_name}")
                        
                        # Look for privileged pods or system pods that can access host filesystem
                        suitable_pods = []
                        for pod in pods.items:
                            if (pod.metadata.namespace in ["kube-system", "contrail", "jcnr"] or
                                any("system" in container.name or "node" in container.name 
                                    for container in pod.spec.containers)):
                                suitable_pods.append(pod)
                        
                        if not suitable_pods:
                            results.append({
                                "cluster": cluster,
                                "node": node_name,
                                "error": "No suitable pod found on node to execute core file check",
                                "core_files": []
                            })
                            continue
                        
                        # Use the first suitable pod
                        pod = suitable_pods[0]
                        
                        # Build find command to search for core files
                        find_commands = []
                        for path in paths_to_search:
                            # Search for files named core* that are newer than max_age_days
                            # Use ls -la with find for better portability across different systems
                            find_cmd = f"find {path} -name 'core*' -type f -mtime -{max_age_days} -exec ls -la {{}} \\; 2>/dev/null || true"
                            find_commands.append(find_cmd)
                        
                        # Combine all find commands with semicolons instead of &&
                        full_command = "; ".join(find_commands)
                        
                        # Execute the command
                        command_result = self.execute_pod_command(
                            pod.metadata.name, 
                            pod.metadata.namespace, 
                            f"sh -c '{full_command}'", 
                            None, 
                            cluster
                        )
                        
                        core_files = []
                        if command_result.get("status") == "success" and command_result.get("output"):
                            output_lines = command_result["output"].strip().split('\n')
                            for line in output_lines:
                                if line.strip() and ("core" in line.lower() or line.startswith('-')):
                                    try:
                                        # Parse ls -la output format: permissions owner group size date time filename
                                        # Example: -rw-r--r-- 1 root root 12345678 Dec 15 10:30 /path/to/core.12345
                                        parts = line.strip().split()
                                        if len(parts) >= 9 and parts[0].startswith('-'):  # File (not directory)
                                            file_path = " ".join(parts[8:])  # Join remaining parts for full path
                                            size_bytes = parts[4] if parts[4].isdigit() else "0"
                                            
                                            # Extract date and time (parts 5, 6, 7)
                                            date_str = f"{parts[5]} {parts[6]} {parts[7]}" if len(parts) >= 8 else "unknown"
                                            
                                            # Convert size to human readable format
                                            size_mb = int(size_bytes) / (1024 * 1024) if size_bytes.isdigit() else 0
                                            size_str = f"{size_mb:.1f} MB" if size_mb > 1 else f"{size_bytes} bytes"
                                            
                                            core_files.append({
                                                "path": file_path,
                                                "size": size_str,
                                                "modified": date_str,
                                                "age_days": f"< {max_age_days}"
                                            })
                                    except Exception as e:
                                        logger.warning(f"Failed to parse ls output line: {line}, error: {e}")
                                        # Fallback: if parsing fails but line contains 'core', treat it as a potential core file
                                        if "core" in line.lower():
                                            core_files.append({
                                                "path": line.strip(),
                                                "size": "unknown",
                                                "modified": "unknown", 
                                                "age_days": f"< {max_age_days}"
                                            })
                        
                        results.append({
                            "cluster": cluster,
                            "node": node_name,
                            "core_files": core_files,
                            "search_paths": paths_to_search,
                            "pod_used": f"{pod.metadata.namespace}/{pod.metadata.name}"
                        })
                        
                    except Exception as e:
                        results.append({
                            "cluster": cluster,
                            "node": node_name,
                            "error": f"Failed to check core files: {str(e)}",
                            "core_files": []
                        })
                        
            except Exception as e:
                results.append({
                    "cluster": cluster,
                    "error": f"Failed to access cluster: {str(e)}",
                    "core_files": []
                })
        
        return results
    
    def analyze_logs(self, cluster_name: str = None, pod_name: str = None, namespace: str = None, 
                    log_paths: List[str] = None, max_age_days: int = 7, max_lines: int = 100, 
                    pattern: str = None) -> List[Dict[str, Any]]:
        """Analyze log files in /var/log/ and /log/ directories, with enhanced JCNR log support for DPDK pods."""
        results = []
        clusters_to_check = [cluster_name] if cluster_name else list(self.clusters_config.keys())
        
        # Default log paths to search
        default_log_paths = [
            "/var/log",
            "/log",
            "/var/log/containers",
            "/var/log/pods",
            "/var/log/syslog*",
            "/var/log/messages*",
            "/var/log/kern.log*",
            "/var/log/dmesg*",
            "/var/log/contrail",
            "/var/log/jcnr"
        ]
        
        # Enhanced JCNR log paths for DPDK pods
        jcnr_log_paths = [
            "/var/log/jcnr/contrail-vrouter*",
            "/var/log/jcnr/jcnr*", 
            "/var/log/jcnr/messages",
            "/var/log/jcnr",
            "/var/log/contrail-vrouter*",
            "/var/log/jcnr*"
        ]
        
        paths_to_search = log_paths if log_paths else default_log_paths
        
        for cluster in clusters_to_check:
            try:
                # Get Kubernetes client for this specific cluster
                self.get_k8s_client(cluster)
                v1 = client.CoreV1Api()
                
                # If specific pod is requested, analyze only that pod
                if pod_name and namespace:
                    try:
                        # Get the specific pod
                        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
                        
                        # Check if this is a DPDK pod and enhance log paths accordingly
                        is_dpdk_pod = self._is_dpdk_pod(pod)
                        enhanced_paths = paths_to_search.copy()
                        if is_dpdk_pod:
                            enhanced_paths.extend(jcnr_log_paths)
                        
                        # Analyze logs for this specific pod
                        log_analysis = self._analyze_pod_logs(pod, cluster, enhanced_paths, pattern, max_lines, is_dpdk_pod)
                        
                        results.append({
                            "cluster": cluster,
                            "pod": pod_name,
                            "namespace": namespace,
                            "node": pod.spec.node_name,
                            "pod_type": "DPDK" if is_dpdk_pod else "Standard",
                            "log_analysis": log_analysis,
                            "search_paths": enhanced_paths,
                            "pattern_used": pattern or "error|fail|panic|segfault|oops|bug|critical|fatal"
                        })
                        
                    except Exception as e:
                        results.append({
                            "cluster": cluster,
                            "pod": pod_name,
                            "namespace": namespace,
                            "error": f"Failed to analyze logs for pod '{pod_name}': {str(e)}",
                            "log_analysis": {}
                        })
                else:
                    # Original behavior: scan all nodes
                    nodes = v1.list_node()
                    
                    for node in nodes.items:
                        node_name = node.metadata.name
                        try:
                            # Find a suitable pod running on this node
                            pods = v1.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={node_name}")
                            
                            # Look for privileged pods or system pods that can access host filesystem
                            suitable_pods = []
                            dpdk_pods = []
                            for pod in pods.items:
                                is_dpdk = self._is_dpdk_pod(pod)
                                if is_dpdk:
                                    dpdk_pods.append(pod)
                                if (pod.metadata.namespace in ["kube-system", "contrail", "jcnr"] or
                                    any("system" in container.name or "node" in container.name 
                                        for container in pod.spec.containers)):
                                    suitable_pods.append(pod)
                            
                            # Prefer DPDK pods for JCNR log analysis, fallback to suitable pods
                            target_pod = dpdk_pods[0] if dpdk_pods else (suitable_pods[0] if suitable_pods else None)
                            
                            if not target_pod:
                                results.append({
                                    "cluster": cluster,
                                    "node": node_name,
                                    "error": "No suitable pod found on node to access logs",
                                    "log_analysis": {}
                                })
                                continue
                            
                            # Enhance log paths if using DPDK pod
                            is_dpdk_pod = target_pod in dpdk_pods
                            enhanced_paths = paths_to_search.copy()
                            if is_dpdk_pod:
                                enhanced_paths.extend(jcnr_log_paths)
                            
                            # Analyze logs for this node via the pod
                            log_analysis = self._analyze_pod_logs(target_pod, cluster, enhanced_paths, pattern, max_lines, is_dpdk_pod)
                            
                            results.append({
                                "cluster": cluster,
                                "node": node_name,
                                "pod_type": "DPDK" if is_dpdk_pod else "Standard",
                                "log_analysis": log_analysis,
                                "search_paths": enhanced_paths,
                                "pod_used": f"{target_pod.metadata.namespace}/{target_pod.metadata.name}",
                                "pattern_used": pattern or "error|fail|panic|segfault|oops|bug|critical|fatal"
                            })
                            
                        except Exception as e:
                            results.append({
                                "cluster": cluster,
                                "node": node_name,
                                "error": f"Failed to analyze logs: {str(e)}",
                                "log_analysis": {}
                            })
                            
            except Exception as e:
                results.append({
                    "cluster": cluster,
                    "error": f"Failed to access cluster: {str(e)}",
                    "log_analysis": {}
                })
        
        return results
    
    def _is_dpdk_pod(self, pod) -> bool:
        """Check if a pod is a DPDK pod based on its name and containers."""
        pod_name = pod.metadata.name.lower()
        namespace = pod.metadata.namespace.lower()
        
        # Check pod name patterns
        if ("vrdpdk" in pod_name or "vrouter-nodes-vrdpdk" in pod_name or 
            "contrail-vrouter" in pod_name and "dpdk" in pod_name):
            return True
            
        # Check if running in contrail namespace with DPDK containers
        if namespace == "contrail":
            for container in pod.spec.containers:
                container_name = container.name.lower()
                if ("dpdk" in container_name or "vrdpdk" in container_name):
                    return True
                    
        return False
    
    def pod_command_and_summary(self, pod_name: str, namespace: str, 
                                   container: str = None, cluster_name: str = None) -> Dict[str, Any]:
        """Run a set of commands on a pod and summarize the outputs with execution statistics.
        
        Commands are loaded exclusively from a file referenced in the cluster configuration's 
        'pod_command_list' field. This tool only runs if the cluster config has this field.
        """
        import time
        
        result = {
            "pod": pod_name,
            "namespace": namespace,
            "container": container,
            "cluster": cluster_name or "default",
            "commands_executed": 0,
            "commands_successful": 0,
            "commands_failed": 0,
            "results": [],
            "total_output_size_bytes": 0,
            "estimated_execution_time": "Unknown",
            "command_source": "unknown"
        }
        
        # Only load commands from cluster configuration's pod_command_list field
        try:
            cluster_config = self.clusters_config.get(cluster_name, {}) if cluster_name else {}
            command_list_path = cluster_config.get("pod_command_list")
            
            if not command_list_path:
                result["error"] = f"No pod_command_list configured for cluster '{cluster_name}'. This tool requires a pod_command_list field in the cluster configuration."
                return result
                
            final_commands = self._load_commands_from_file(command_list_path)
            result["command_source"] = f"cluster_config: {command_list_path}"
            
        except Exception as e:
            result["error"] = f"Failed to load commands from cluster configuration: {str(e)}"
            return result
        
        if not final_commands:
            result["error"] = f"No commands found in file: {command_list_path}"
            return result
        
        result["commands_to_execute"] = final_commands
        start_time = time.time()
        
        try:
            for i, command in enumerate(final_commands, 1):
                cmd_result = {
                    "command_number": i,
                    "command": command,
                    "status": "unknown",
                    "output_size_bytes": 0,
                    "output_lines": 0,
                    "output_preview": {}
                }
                
                try:
                    # Execute the command
                    response = self.execute_pod_command(pod_name, namespace, command, container, cluster_name)
                    
                    result["commands_executed"] += 1
                    
                    if response.get("status") == "success":
                        result["commands_successful"] += 1
                        cmd_result["status"] = "success"
                        
                        output = response.get("output", "")
                        cmd_result["output_size_bytes"] = len(output.encode('utf-8'))
                        result["total_output_size_bytes"] += cmd_result["output_size_bytes"]
                        
                        # Count lines and create preview
                        lines = output.strip().split('\n') if output.strip() else []
                        cmd_result["output_lines"] = len(lines)
                        
                        # Create output preview
                        if lines:
                            if len(lines) <= 3:
                                cmd_result["output_preview"]["content"] = output.strip()
                            else:
                                cmd_result["output_preview"]["first_line"] = lines[0] if lines else ""
                                cmd_result["output_preview"]["last_line"] = lines[-1] if lines else ""
                                cmd_result["output_preview"]["total_lines"] = len(lines)
                            cmd_result["full_output_available"] = len(lines) > 3
                        
                    else:
                        result["commands_failed"] += 1
                        cmd_result["status"] = "failed"
                        cmd_result["error"] = response.get("output", "Unknown error")
                        
                except Exception as e:
                    result["commands_failed"] += 1
                    cmd_result["status"] = "error" 
                    cmd_result["error"] = str(e)
                
                result["results"].append(cmd_result)
            
            # Calculate execution time and success rate
            end_time = time.time()
            execution_time = end_time - start_time
            result["estimated_execution_time"] = f"{execution_time:.2f} seconds"
            
            if result["commands_executed"] > 0:
                success_rate = (result["commands_successful"] / result["commands_executed"]) * 100
                result["success_rate"] = f"{success_rate:.1f}%"
            else:
                result["success_rate"] = "0%"
                
        except Exception as e:
            result["error"] = f"Failed to execute commands: {str(e)}"
        
        return result

    def _load_commands_from_file(self, file_path: str) -> List[str]:
        """Load commands from a JSON file containing either:
        1. A simple list of command strings: ["cmd1", "cmd2", ...]
        2. An object with description and commands: {"description": "...", "commands": ["cmd1", "cmd2", ...]}
        3. A list of objects with command/description: [{"command": "cmd", "description": "desc"}, ...]
        
        Args:
            file_path: Path to the JSON file containing the command list
            
        Returns:
            List of command strings
            
        Raises:
            Exception: If file cannot be read or parsed
        """
        try:
            # Handle relative paths - make them relative to the current working directory
            if not os.path.isabs(file_path):
                file_path = os.path.join(os.getcwd(), file_path)
            
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            commands = []
            
            if isinstance(data, list):
                # Handle list format (legacy or enhanced)
                for item in data:
                    if isinstance(item, str):
                        # Simple string format
                        commands.append(item)
                    elif isinstance(item, dict) and 'command' in item:
                        # Object format with command and description
                        commands.append(str(item['command']))
                    else:
                        raise ValueError(f"Invalid command format: {item}")
            
            elif isinstance(data, dict):
                # Handle object format with description and commands array
                if 'commands' in data:
                    command_list = data['commands']
                    if isinstance(command_list, list):
                        commands = [str(cmd) for cmd in command_list if cmd]
                    else:
                        raise ValueError(f"'commands' field must be a list, got {type(command_list)}")
                else:
                    raise ValueError("Object format must contain 'commands' field")
            
            else:
                raise ValueError(f"Expected a list or object with commands, got {type(data)}")
            
            # Filter out empty commands
            commands = [cmd.strip() for cmd in commands if cmd and cmd.strip()]
            return commands
                
        except FileNotFoundError:
            raise Exception(f"Command file not found: {file_path}")
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON in command file {file_path}: {str(e)}")
        except Exception as e:
            raise Exception(f"Error loading commands from {file_path}: {str(e)}")

    def _analyze_pod_logs(self, pod, cluster: str, paths_to_search: List[str], pattern: str, max_lines: int, is_dpdk_pod: bool = False) -> Dict[str, Any]:
        """Helper method to analyze logs within a specific pod, with enhanced JCNR support for DPDK pods."""
        log_analysis = {}
        
        # Enhanced JCNR log analysis for DPDK pods
        if is_dpdk_pod:
            log_analysis.update(self._analyze_jcnr_logs(pod, cluster, pattern, max_lines))
        
        # 1. List recent log files recursively including subdirectories (use ls instead of find)
        recent_logs_result = self.execute_pod_command(
            pod.metadata.name, 
            pod.metadata.namespace, 
            ["sh", "-c", "ls /var/log/*.log /var/log/*/*.log /var/log/messages* /var/log/*/messages* 2>/dev/null | head -20"], 
            None, 
            cluster
        )
        
        if recent_logs_result.get("status") == "success":
            log_files = [f.strip() for f in recent_logs_result["output"].strip().split('\n') if f.strip()]
            log_analysis["recent_log_files"] = log_files[:10]  # Limit to 10 files
        else:
            log_analysis["recent_log_files"] = []
        
        # 2. Check for errors in recent logs - use direct grep on known paths
        if pattern:
            # Use custom pattern - search in main log files and contrail subdirectory
            error_result = self.execute_pod_command(
                pod.metadata.name, 
                pod.metadata.namespace, 
                ["sh", "-c", f"grep -i '{pattern}' /var/log/*.log /var/log/contrail/*.log /var/log/messages* /var/log/contrail/messages* 2>/dev/null | head -50 || echo 'No matches found'"], 
                None, 
                cluster
            )
        else:
            # Default error patterns - search for common error keywords
            error_result = self.execute_pod_command(
                pod.metadata.name, 
                pod.metadata.namespace, 
                ["sh", "-c", "grep -i -E 'error|fail|panic|warning|critical' /var/log/*.log /var/log/contrail/*.log /var/log/messages* /var/log/contrail/messages* 2>/dev/null | head -50 || echo 'No error patterns found'"], 
                None, 
                cluster
            )
        
        if error_result.get("status") == "success" and error_result.get("output"):
            error_lines = [line.strip() for line in error_result["output"].strip().split('\n') if line.strip()]
            log_analysis["error_patterns"] = error_lines
        else:
            log_analysis["error_patterns"] = []
        
        # 3. Get disk usage of log directories including subdirectories
        du_result = self.execute_pod_command(
            pod.metadata.name, 
            pod.metadata.namespace, 
            ["sh", "-c", "ls -la /var/log/ && echo '--- /var/log/contrail ---' && ls -la /var/log/contrail/ 2>/dev/null || echo 'No contrail logs'"], 
            None, 
            cluster
        )
        
        if du_result.get("status") == "success" and du_result.get("output"):
            disk_usage = [line.strip() for line in du_result["output"].strip().split('\n') if line.strip()]
            log_analysis["log_directory_listing"] = disk_usage
        else:
            log_analysis["log_directory_listing"] = []
        
        # 4. Check for large log files - use ls with size check
        large_files_result = self.execute_pod_command(
            pod.metadata.name, 
            pod.metadata.namespace, 
            ["sh", "-c", "ls -lh /var/log/*.log /var/log/contrail/*.log 2>/dev/null | grep -E '[0-9]+M|[0-9]+G' | head -10 || echo 'No large log files found'"], 
            None, 
            cluster
        )
        
        if large_files_result.get("status") == "success" and large_files_result.get("output"):
            large_files = [line.strip() for line in large_files_result["output"].strip().split('\n') if line.strip()]
            log_analysis["large_files"] = large_files
        else:
            log_analysis["large_files"] = []
        
        # 5. Get recent system messages - try to access log file contents
        recent_result = self.execute_pod_command(
            pod.metadata.name, 
            pod.metadata.namespace, 
            ["sh", "-c", f"find /var/log -type f \\( -name '*.log' -o -name 'messages*' -o -name 'syslog*' \\) 2>/dev/null | {{ count=0; while read file && [ $count -lt 3 ]; do echo '=== '$file' ==='; tail -{max_lines//5} \"$file\" 2>/dev/null || echo 'Cannot read '$file; count=$((count+1)); done; }}"], 
            None, 
            cluster
        )
        
        if recent_result.get("status") == "success" and recent_result.get("output"):
            recent_lines = recent_result["output"].strip().split('\n')[-max_lines:]  # Last max_lines lines
            log_analysis["recent_messages"] = [line.strip() for line in recent_lines if line.strip()]
        else:
            log_analysis["recent_messages"] = []
        
        return log_analysis
    
    def _analyze_jcnr_logs(self, pod, cluster: str, pattern: str, max_lines: int) -> Dict[str, Any]:
        """Enhanced JCNR log analysis for DPDK pods."""
        jcnr_analysis = {}
        
        # 1. Check for JCNR log directory existence and list contrail logs
        jcnr_dir_result = self.execute_pod_command(
            pod.metadata.name,
            pod.metadata.namespace,
            ["sh", "-c", "ls -la /var/log/jcnr/ 2>/dev/null || (ls -la /var/log/contrail/ 2>/dev/null && echo 'Using /var/log/contrail instead of /var/log/jcnr') || echo 'Neither JCNR nor contrail log directory found'"],
            None,
            cluster
        )
        
        if jcnr_dir_result.get("status") == "success":
            jcnr_analysis["jcnr_log_directory"] = jcnr_dir_result["output"].strip().split('\n')[:20]
        else:
            jcnr_analysis["jcnr_log_directory"] = []
        
        # 2. Analyze contrail-vrouter logs (check both /var/log/jcnr and /var/log/contrail)
        vrouter_log_result = self.execute_pod_command(
            pod.metadata.name,
            pod.metadata.namespace,
            ["sh", "-c", f"for file in /var/log/jcnr/contrail-vrouter* /var/log/contrail/contrail-vrouter*; do if [ -f \"$file\" ]; then echo '=== '$file' ==='; tail -{max_lines//3} \"$file\" 2>/dev/null || echo 'Cannot read '$file; fi; done | head -200"],
            None,
            cluster
        )
        
        if vrouter_log_result.get("status") == "success" and vrouter_log_result.get("output"):
            jcnr_analysis["contrail_vrouter_logs"] = vrouter_log_result["output"].strip().split('\n')
        else:
            jcnr_analysis["contrail_vrouter_logs"] = []
        
        # 3. Analyze JCNR-specific logs (check both directories)
        jcnr_log_result = self.execute_pod_command(
            pod.metadata.name,
            pod.metadata.namespace,
            ["sh", "-c", f"for file in /var/log/jcnr/jcnr* /var/log/contrail/jcnr*; do if [ -f \"$file\" ]; then echo '=== '$file' ==='; tail -{max_lines//3} \"$file\" 2>/dev/null || echo 'Cannot read '$file; fi; done | head -200"],
            None,
            cluster
        )
        
        if jcnr_log_result.get("status") == "success" and jcnr_log_result.get("output"):
            jcnr_analysis["jcnr_specific_logs"] = jcnr_log_result["output"].strip().split('\n')
        else:
            jcnr_analysis["jcnr_specific_logs"] = []
        
        # 4. Check JCNR messages file (check both directories)
        jcnr_messages_result = self.execute_pod_command(
            pod.metadata.name,
            pod.metadata.namespace,
            ["sh", "-c", f"if [ -f /var/log/jcnr/messages ]; then echo '=== /var/log/jcnr/messages ==='; tail -{max_lines//2} /var/log/jcnr/messages 2>/dev/null; elif [ -f /var/log/contrail/messages ]; then echo '=== /var/log/contrail/messages ==='; tail -{max_lines//2} /var/log/contrail/messages 2>/dev/null; else echo 'JCNR/Contrail messages file not found'; fi"],
            None,
            cluster
        )
        
        if jcnr_messages_result.get("status") == "success" and jcnr_messages_result.get("output"):
            jcnr_analysis["jcnr_messages"] = jcnr_messages_result["output"].strip().split('\n')
        else:
            jcnr_analysis["jcnr_messages"] = []
        
        # 5. Search for JCNR-specific error patterns
        if pattern:
            jcnr_pattern = pattern
        else:
            # JCNR-specific error patterns
            jcnr_pattern = "error|fail|panic|segfault|core.*dump|exception|abort|fatal|crash|dpdk.*error|vrouter.*error|contrail.*error"
        
        jcnr_error_result = self.execute_pod_command(
            pod.metadata.name,
            pod.metadata.namespace,
            ["sh", "-c", f"grep -i -E '{jcnr_pattern}' /var/log/jcnr/* /var/log/contrail/* 2>/dev/null | head -{max_lines//2} || echo 'No JCNR error patterns found'"],
            None,
            cluster
        )
        
        if jcnr_error_result.get("status") == "success" and jcnr_error_result.get("output"):
            error_lines = [line.strip() for line in jcnr_error_result["output"].strip().split('\n') if line.strip() and "No JCNR error patterns found" not in line]
            jcnr_analysis["jcnr_error_patterns"] = error_lines
        else:
            jcnr_analysis["jcnr_error_patterns"] = []
        
        # 6. Get DPDK-specific log information
        dpdk_log_result = self.execute_pod_command(
            pod.metadata.name,
            pod.metadata.namespace,
            ["sh", "-c", "for file in /var/log/*dpdk* /var/log/*/*dpdk* /var/log/*vrouter* /var/log/*/*vrouter*; do if [ -f \"$file\" ]; then echo \"File: $file Size: $(ls -lh \"$file\" | awk '{print $5}')\"; fi; done | head -10"],
            None,
            cluster
        )
        
        if dpdk_log_result.get("status") == "success" and dpdk_log_result.get("output"):
            jcnr_analysis["dpdk_log_files"] = dpdk_log_result["output"].strip().split('\n')
        else:
            jcnr_analysis["dpdk_log_files"] = []
            
        return jcnr_analysis


class XMLTableFormatter:
    """Helper class to convert Sandesh XML responses to readable table format."""
    
    @staticmethod
    def parse_nh_list(xml_data: str, max_rows: int = 20) -> str:
        """Parse next-hop list XML and convert to table format."""
        try:
            root = ET.fromstring(xml_data)
            
            # Find all NhSandeshData elements
            nh_elements = root.findall(".//NhSandeshData")
            
            if not nh_elements:
                return "No next-hop data found in XML response"
            
            # Create table header
            table_lines = []
            table_lines.append("=" * 120)
            table_lines.append("NEXT-HOP TABLE (HTTP API)")
            table_lines.append("=" * 120)
            table_lines.append(f"{'ID':<5} {'Type':<15} {'RefCnt':<8} {'Valid':<6} {'Policy':<8} {'Interface':<15} {'VxLAN':<6}")
            table_lines.append("-" * 120)
            
            # Parse each next-hop entry
            count = 0
            for nh in nh_elements[:max_rows]:
                nh_id = nh.find("nh_index").text if nh.find("nh_index") is not None else "N/A"
                nh_type = nh.find("type").text if nh.find("type") is not None else "N/A"
                ref_count = nh.find("ref_count").text if nh.find("ref_count") is not None else "0"
                valid = "Yes" if nh.find("valid") is not None and nh.find("valid").text == "true" else "No"
                policy = "Yes" if nh.find("policy") is not None and "enabled" in nh.find("policy").text else "No"
                interface = nh.find("itf").text if nh.find("itf") is not None else "N/A"
                vxlan_flag = "Yes" if nh.find("vxlan_flag") is not None and nh.find("vxlan_flag").text == "true" else "No"
                
                table_lines.append(f"{nh_id:<5} {nh_type:<15} {ref_count:<8} {valid:<6} {policy:<8} {interface:<15} {vxlan_flag:<6}")
                count += 1
            
            if len(nh_elements) > max_rows:
                table_lines.append(f"... and {len(nh_elements) - max_rows} more entries (showing first {max_rows})")
            
            table_lines.append("-" * 120)
            table_lines.append(f"Total Next-hops: {len(nh_elements)}")
            table_lines.append("=" * 120)
            
            return "\n".join(table_lines)
            
        except Exception as e:
            return f"Error parsing next-hop XML: {str(e)}"
    
    @staticmethod
    def parse_vrf_list(xml_data: str) -> str:
        """Parse VRF list XML and convert to table format."""
        try:
            root = ET.fromstring(xml_data)
            
            # Find all VrfSandeshData elements
            vrf_elements = root.findall(".//VrfSandeshData")
            
            if not vrf_elements:
                return "No VRF data found in XML response"
            
            # Create table header
            table_lines = []
            table_lines.append("=" * 100)
            table_lines.append("VRF TABLE (HTTP API)")
            table_lines.append("=" * 100)
            table_lines.append(f"{'Name':<40} {'UC Index':<10} {'L2 Index':<10} {'VxLAN ID':<10} {'RD':<15}")
            table_lines.append("-" * 100)
            
            # Parse each VRF entry
            for vrf in vrf_elements:
                name = vrf.find("name").text if vrf.find("name") is not None else "N/A"
                uc_index = vrf.find("ucindex").text if vrf.find("ucindex") is not None else "N/A"
                l2_index = vrf.find("l2index").text if vrf.find("l2index") is not None else "N/A"
                vxlan_id = vrf.find("vxlan_id").text if vrf.find("vxlan_id") is not None else "N/A"
                rd = vrf.find("RD").text if vrf.find("RD") is not None else "N/A"
                
                # Truncate long names
                if len(name) > 35:
                    name = name[:32] + "..."
                
                table_lines.append(f"{name:<40} {uc_index:<10} {l2_index:<10} {vxlan_id:<10} {rd:<15}")
            
            table_lines.append("-" * 100)
            table_lines.append(f"Total VRFs: {len(vrf_elements)}")
            table_lines.append("=" * 100)
            
            return "\n".join(table_lines)
            
        except Exception as e:
            return f"Error parsing VRF XML: {str(e)}"
    
    @staticmethod
    def parse_route_list(xml_data: str, max_rows: int = 15, route_type: str = "IPv4") -> str:
        """Parse route list XML and convert to table format."""
        try:
            root = ET.fromstring(xml_data)
            
            # Find all RouteUcSandeshData elements
            route_elements = root.findall(".//RouteUcSandeshData")
            
            if not route_elements:
                return f"No {route_type} route data found in XML response"
            
            # Create table header
            table_lines = []
            table_lines.append("=" * 120)
            table_lines.append(f"{route_type} ROUTE TABLE (HTTP API)")
            table_lines.append("=" * 120)
            table_lines.append(f"{'Prefix':<25} {'Len':<4} {'VRF':<30} {'Next-hop':<10} {'Label':<8} {'Peer':<15}")
            table_lines.append("-" * 120)
            
            # Parse each route entry
            count = 0
            for route in route_elements[:max_rows]:
                src_ip = route.find("src_ip").text if route.find("src_ip") is not None else "N/A"
                src_plen = route.find("src_plen").text if route.find("src_plen") is not None else "0"
                prefix = f"{src_ip}/{src_plen}"
                
                vrf_elem = route.find("src_vrf")
                vrf = vrf_elem.text if vrf_elem is not None else "N/A"
                if len(vrf) > 25:
                    vrf = vrf[:22] + "..."
                
                # Get path information (first path)
                path_list = route.find("path_list")
                nh_index = "N/A"
                label = "N/A"
                peer = "N/A"
                
                if path_list is not None:
                    path_data = path_list.find(".//PathSandeshData")
                    if path_data is not None:
                        nh_elem = path_data.find(".//nh_index")
                        if nh_elem is not None:
                            nh_index = nh_elem.text
                        
                        label_elem = path_data.find("label")
                        if label_elem is not None:
                            label = label_elem.text
                        
                        peer_elem = path_data.find("peer")
                        if peer_elem is not None:
                            peer = peer_elem.text
                            if len(peer) > 12:
                                peer = peer[:9] + "..."
                
                table_lines.append(f"{prefix:<25} {src_plen:<4} {vrf:<30} {nh_index:<10} {label:<8} {peer:<15}")
                count += 1
            
            if len(route_elements) > max_rows:
                table_lines.append(f"... and {len(route_elements) - max_rows} more routes (showing first {max_rows})")
            
            table_lines.append("-" * 120)
            table_lines.append(f"Total {route_type} Routes: {len(route_elements)}")
            table_lines.append("=" * 120)
            
            return "\n".join(table_lines)
            
        except Exception as e:
            return f"Error parsing {route_type} route XML: {str(e)}"
    
    @staticmethod
    def parse_interface_list(xml_data: str, max_rows: int = 10) -> str:
        """Parse interface list XML and convert to table format."""
        try:
            root = ET.fromstring(xml_data)
            
            # Find all ItfSandeshData elements
            intf_elements = root.findall(".//ItfSandeshData")
            
            if not intf_elements:
                return "No interface data found in XML response"
            
            # Create table header
            table_lines = []
            table_lines.append("=" * 120)
            table_lines.append("INTERFACE TABLE (HTTP API)")
            table_lines.append("=" * 120)
            table_lines.append(f"{'Index':<6} {'Name':<15} {'Type':<8} {'Status':<8} {'VRF':<25} {'IP Address':<15} {'MAC Address':<18}")
            table_lines.append("-" * 120)
            
            # Parse each interface entry
            count = 0
            for intf in intf_elements[:max_rows]:
                index = intf.find("index").text if intf.find("index") is not None else "N/A"
                name = intf.find("name").text if intf.find("name") is not None else "N/A"
                intf_type = intf.find("type").text if intf.find("type") is not None else "N/A"
                active = intf.find("active").text if intf.find("active") is not None else "N/A"
                vrf_name = intf.find("vrf_name").text if intf.find("vrf_name") is not None else "N/A"
                ip_addr = intf.find("ip_addr").text if intf.find("ip_addr") is not None else "N/A"
                mac_addr = intf.find("mac_addr").text if intf.find("mac_addr") is not None else "N/A"
                
                # Truncate long VRF names
                if len(vrf_name) > 20:
                    vrf_name = vrf_name[:17] + "..."
                
                table_lines.append(f"{index:<6} {name:<15} {intf_type:<8} {active:<8} {vrf_name:<25} {ip_addr:<15} {mac_addr:<18}")
                count += 1
            
            if len(intf_elements) > max_rows:
                table_lines.append(f"... and {len(intf_elements) - max_rows} more interfaces (showing first {max_rows})")
            
            table_lines.append("-" * 120)
            table_lines.append(f"Total Interfaces: {len(intf_elements)}")
            table_lines.append("=" * 120)
            
            return "\n".join(table_lines)
            
        except Exception as e:
            return f"Error parsing interface XML: {str(e)}"


class EnhancedMCPHTTPServer:
    """Enhanced HTTP-based MCP Server with Kubernetes and gNMI integration."""
    
    def __init__(self, port: int = 40041, clusters_config_path: str = None):
        self.port = port
        self.app = FastAPI(
            title="Enhanced MCP HTTP Server with Kubernetes",
            description="Model Context Protocol server with Kubernetes cluster management",
            version="2.1.0"
        )
        
        # Add CORS middleware for VS Code compatibility
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Initialize Kubernetes manager
        self.k8s_manager = KubernetesManager(clusters_config_path)
        
        # Initialize the MCP server
        self.mcp_server = Server("enhanced-mcp-http-server")
        
        # Store handler references
        self.tools_handler: Optional[Callable[[], Awaitable[List[types.Tool]]]] = None
        self.call_tool_handler: Optional[Callable[[str, Dict[str, Any]], Awaitable[List[types.TextContent]]]] = None
        self.resources_handler: Optional[Callable[[], Awaitable[List[types.Resource]]]] = None
        self.read_resource_handler: Optional[Callable[[str], Awaitable[str]]] = None
        
        self._setup_mcp_handlers()
        self._setup_http_routes()
    
    def _setup_mcp_handlers(self):
        """Set up MCP server handlers for tools and resources."""
        
        @self.mcp_server.list_tools()
        async def handle_list_tools() -> List[types.Tool]:
            """List available tools."""
            tools = []
            
            # Add Kubernetes tools if available
            if KUBERNETES_AVAILABLE:
                k8s_tools = [
                    types.Tool(
                        name="list_clusters",
                        description="List all configured Kubernetes clusters",
                        inputSchema={
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    ),
                    types.Tool(
                        name="list_namespaces",
                        description="List namespaces in a Kubernetes cluster",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "cluster_name": {
                                    "type": "string",
                                    "description": "Name of the cluster (optional, uses default if not specified)"
                                }
                            },
                            "required": []
                        }
                    ),
                    types.Tool(
                        name="list_pods",
                        description="List pods in a specific namespace and cluster",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "namespace": {
                                    "type": "string",
                                    "description": "Kubernetes namespace name"
                                },
                                "cluster_name": {
                                    "type": "string",
                                    "description": "Name of the cluster (optional, uses default if not specified)"
                                }
                            },
                            "required": ["namespace"]
                        }
                    ),
                    types.Tool(
                        name="execute_command",
                        description="Execute a command in a specific pod",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "pod_name": {
                                    "type": "string",
                                    "description": "Name of the pod"
                                },
                                "namespace": {
                                    "type": "string",
                                    "description": "Kubernetes namespace name"
                                },
                                "command": {
                                    "type": "string",
                                    "description": "Command to execute in the pod"
                                },
                                "container": {
                                    "type": "string",
                                    "description": "Container name (optional, defaults to first container)"
                                },
                                "cluster_name": {
                                    "type": "string",
                                    "description": "Name of the cluster (optional, uses default if not specified)"
                                }
                            },
                            "required": ["pod_name", "namespace", "command"]
                        }
                    ),
                    types.Tool(
                        name="execute_dpdk_command",
                        description="Execute a command in DPDK pods (vrdpdk) in contrail namespace across all clusters",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "description": "Command to execute in DPDK pods"
                                },
                                "cluster_name": {
                                    "type": "string",
                                    "description": "Name of the cluster (optional, executes on all clusters if not specified)"
                                }
                            },
                            "required": ["command"]
                        }
                    ),
                    types.Tool(
                        name="execute_agent_command",
                        description="Execute a command in Contrail Agent pods (vrouter-nodes) in contrail namespace across all clusters",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "description": "Command to execute in Agent pods"
                                },
                                "cluster_name": {
                                    "type": "string",
                                    "description": "Name of the cluster (optional, executes on all clusters if not specified)"
                                }
                            },
                            "required": ["command"]
                        }
                    ),
                    types.Tool(
                        name="execute_junos_cli_commands",
                        description="Execute a command in all cRPD and cSRX pods in jcnr namespace across all clusters. Automatically prepends 'cli -c' to commands for proper Junos CLI execution.",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "description": "Command to execute in cRPD/cSRX pods"
                                },
                                "cluster_name": {
                                    "type": "string",
                                    "description": "Name of the cluster (optional, executes on all clusters if not specified)"
                                }
                            },
                            "required": ["command"]
                        }
                    ),
                    types.Tool(
                        name="check_core_files",
                        description="Check for core files on nodes in a Kubernetes cluster. Searches common locations for core dumps",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "cluster_name": {
                                    "type": "string",
                                    "description": "Name of the cluster (optional, checks all clusters if not specified)"
                                },
                                "search_paths": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Custom paths to search for core files (optional, uses default paths if not specified)"
                                },
                                "max_age_days": {
                                    "type": "integer",
                                    "description": "Maximum age of core files to report in days (optional, defaults to 7 days)"
                                }
                            },
                            "required": []
                        }
                    ),
                    types.Tool(
                        name="analyze_logs",
                        description="Analyze log files in /var/log/ and /log/ directories on cluster nodes. Searches for errors, large files, and recent activity",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "cluster_name": {
                                    "type": "string",
                                    "description": "Name of the cluster (optional, analyzes all clusters if not specified)"
                                },
                                "pod_name": {
                                    "type": "string",
                                    "description": "Name of a specific pod to analyze logs for (optional, scans all nodes if not specified)"
                                },
                                "namespace": {
                                    "type": "string",
                                    "description": "Kubernetes namespace of the pod (required if pod_name is specified)"
                                },
                                "log_paths": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Custom paths to search for log files (optional, uses default paths if not specified)"
                                },
                                "max_age_days": {
                                    "type": "integer",
                                    "description": "Maximum age of log files to analyze in days (optional, defaults to 7 days)"
                                },
                                "max_lines": {
                                    "type": "integer",
                                    "description": "Maximum number of lines to return from log analysis (optional, defaults to 100)"
                                },
                                "pattern": {
                                    "type": "string",
                                    "description": "Custom regex pattern to search for in logs (optional, defaults to common error patterns)"
                                }
                            },
                            "required": []
                        }
                    ),
                    types.Tool(
                        name="pod_command_and_summary",
                        description="Run a set of commands on a pod and summarize the outputs with execution statistics. Commands are loaded exclusively from a file referenced in the cluster configuration's 'pod_command_list' field.",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "pod_name": {
                                    "type": "string",
                                    "description": "Name of the pod to execute commands on"
                                },
                                "namespace": {
                                    "type": "string",
                                    "description": "Kubernetes namespace of the pod"
                                },
                                "container": {
                                    "type": "string",
                                    "description": "Container name (optional, defaults to first container)"
                                },
                                "cluster_name": {
                                    "type": "string",
                                    "description": "Name of the cluster (optional, uses default if not specified)"
                                }
                            },
                            "required": ["pod_name", "namespace"]
                        }
                    ),
                    types.Tool(
                        name="jcnr_summary",
                        description="Get JCNR datapath summary by running commands and fetching HTTP API data from DPDK pods. Commands are loaded exclusively from the jcnr_command_list file specified in cluster configuration.",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "cluster_name": {
                                    "type": "string",
                                    "description": "Name of the cluster (required - cluster must have jcnr_command_list configured)"
                                }
                            },
                            "required": ["cluster_name"]
                        }
                    )
                ]
                tools.extend(k8s_tools)
            
            return tools
        
        @self.mcp_server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
            """Handle tool calls."""
            try:
                if name == "list_clusters":
                    if not KUBERNETES_AVAILABLE:
                        return [types.TextContent(type="text", text="Error: Kubernetes library not available")]
                    
                    clusters = self.k8s_manager.list_clusters()
                    if not clusters:
                        return [types.TextContent(type="text", text="No clusters configured. Please provide a clusters configuration file.")]
                    
                    result = "Configured Kubernetes Clusters:\n"
                    for cluster in clusters:
                        result += f"- {cluster['name']}: {cluster['kubeconfig_path']}\n"
                        if cluster['description']:
                            result += f"  Description: {cluster['description']}\n"
                    
                    return [types.TextContent(type="text", text=result)]
                
                elif name == "list_namespaces":
                    if not KUBERNETES_AVAILABLE:
                        return [types.TextContent(type="text", text="Error: Kubernetes library not available")]
                    
                    cluster_name = arguments.get("cluster_name")
                    try:
                        namespaces = self.k8s_manager.list_namespaces(cluster_name)
                        
                        result = f"Namespaces in cluster '{cluster_name or 'default'}':\n"
                        for ns in namespaces:
                            result += f"- {ns['name']} (Status: {ns['status']}, Created: {ns['created']})\n"
                        
                        return [types.TextContent(type="text", text=result)]
                    except Exception as e:
                        return [types.TextContent(type="text", text=f"Error listing namespaces: {str(e)}")]
                
                elif name == "list_pods":
                    if not KUBERNETES_AVAILABLE:
                        return [types.TextContent(type="text", text="Error: Kubernetes library not available")]
                    
                    namespace = arguments.get("namespace")
                    cluster_name = arguments.get("cluster_name")
                    
                    if not namespace:
                        return [types.TextContent(type="text", text="Error: namespace parameter is required")]
                    
                    try:
                        pods = self.k8s_manager.list_pods(namespace, cluster_name)
                        
                        if not pods:
                            return [types.TextContent(type="text", text=f"No pods found in namespace '{namespace}'")]
                        
                        result = f"Pods in namespace '{namespace}' (cluster: {cluster_name or 'default'}):\n"
                        for pod in pods:
                            result += f"- {pod['name']}\n"
                            result += f"  Status: {pod['status']}, Ready: {pod['ready']}, Restarts: {pod['restarts']}\n"
                            result += f"  Node: {pod['node']}, Created: {pod['created']}\n\n"
                        
                        return [types.TextContent(type="text", text=result)]
                    except Exception as e:
                        return [types.TextContent(type="text", text=f"Error listing pods: {str(e)}")]
                
                elif name == "execute_command":
                    if not KUBERNETES_AVAILABLE:
                        return [types.TextContent(type="text", text="Error: Kubernetes library not available")]
                    
                    pod_name = arguments.get("pod_name")
                    namespace = arguments.get("namespace")
                    command = arguments.get("command")
                    container = arguments.get("container")
                    cluster_name = arguments.get("cluster_name")
                    
                    if not pod_name or not namespace or not command:
                        return [types.TextContent(type="text", text="Error: pod_name, namespace, and command parameters are required")]
                    
                    try:
                        response = self.k8s_manager.execute_pod_command(pod_name, namespace, command, container, cluster_name)
                        
                        output = response.get("output", "")
                        if response.get("status") == "success":
                            return [types.TextContent(type="text", text=f"Command output:\n{output}")]
                        else:
                            return [types.TextContent(type="text", text=f"Command failed: {output}")]
                    except Exception as e:
                        return [types.TextContent(type="text", text=f"Error executing command: {str(e)}")]
                
                elif name == "execute_dpdk_command":
                    if not KUBERNETES_AVAILABLE:
                        return [types.TextContent(type="text", text="Error: Kubernetes library not available")]
                    
                    command = arguments.get("command")
                    cluster_name = arguments.get("cluster_name")
                    
                    if not command:
                        return [types.TextContent(type="text", text="Error: command parameter is required")]
                    
                    try:
                        results = self.k8s_manager.execute_dpdk_command(command, cluster_name)
                        
                        if not results:
                            return [types.TextContent(type="text", text="No DPDK pods found in contrail namespace")]
                        
                        output_lines = [f"DPDK Command Execution Results for: {command}"]
                        output_lines.append("=" * 60)
                        
                        for result in results:
                            cluster = result.get("cluster", "unknown")
                            pod = result.get("pod", "unknown")
                            status = result.get("status", "unknown")
                            pod_output = result.get("output", "")
                            
                            output_lines.append(f"\nCluster: {cluster}")
                            output_lines.append(f"Pod: {pod}")
                            output_lines.append(f"Status: {status}")
                            output_lines.append(f"Output:\n{pod_output}")
                            output_lines.append("-" * 40)
                        
                        return [types.TextContent(type="text", text="\n".join(output_lines))]
                    except Exception as e:
                        return [types.TextContent(type="text", text=f"Error executing DPDK command: {str(e)}")]
                
                elif name == "execute_agent_command":
                    if not KUBERNETES_AVAILABLE:
                        return [types.TextContent(type="text", text="Error: Kubernetes library not available")]
                    
                    command = arguments.get("command")
                    cluster_name = arguments.get("cluster_name")
                    
                    if not command:
                        return [types.TextContent(type="text", text="Error: command parameter is required")]
                    
                    try:
                        results = self.k8s_manager.execute_agent_command(command, cluster_name)
                        
                        if not results:
                            return [types.TextContent(type="text", text="No Agent pods found in contrail namespace")]
                        
                        output_lines = [f"Agent Command Execution Results for: {command}"]
                        output_lines.append("=" * 60)
                        
                        for result in results:
                            cluster = result.get("cluster", "unknown")
                            pod = result.get("pod", "unknown")
                            status = result.get("status", "unknown")
                            pod_output = result.get("output", "")
                            
                            output_lines.append(f"\nCluster: {cluster}")
                            output_lines.append(f"Pod: {pod}")
                            output_lines.append(f"Status: {status}")
                            output_lines.append(f"Output:\n{pod_output}")
                            output_lines.append("-" * 40)
                        
                        return [types.TextContent(type="text", text="\n".join(output_lines))]
                    except Exception as e:
                        return [types.TextContent(type="text", text=f"Error executing Agent command: {str(e)}")]
                
                elif name == "execute_junos_cli_commands":
                    if not KUBERNETES_AVAILABLE:
                        return [types.TextContent(type="text", text="Error: Kubernetes library not available")]
                    
                    command = arguments.get("command")
                    cluster_name = arguments.get("cluster_name")
                    
                    if not command:
                        return [types.TextContent(type="text", text="Error: command parameter is required")]
                    
                    try:
                        results = self.k8s_manager.execute_junos_cli_commands(command, cluster_name)
                        
                        if not results:
                            return [types.TextContent(type="text", text="No cRPD or cSRX pods found in jcnr namespace")]
                        
                        output_lines = [f"Junos CLI Command Execution Results for: {command}"]
                        output_lines.append("=" * 60)
                        
                        for result in results:
                            cluster = result.get("cluster", "unknown")
                            pod = result.get("pod", "unknown")
                            status = result.get("status", "unknown")
                            pod_output = result.get("output", "")
                            
                            output_lines.append(f"\nCluster: {cluster}")
                            output_lines.append(f"Pod: {pod}")
                            output_lines.append(f"Status: {status}")
                            output_lines.append(f"Output:\n{pod_output}")
                            output_lines.append("-" * 40)
                        
                        return [types.TextContent(type="text", text="\n".join(output_lines))]
                    except Exception as e:
                        return [types.TextContent(type="text", text=f"Error executing cRPD command: {str(e)}")]
                
                elif name == "check_core_files":
                    if not KUBERNETES_AVAILABLE:
                        return [types.TextContent(type="text", text="Error: Kubernetes library not available")]
                    
                    cluster_name = arguments.get("cluster_name")
                    search_paths = arguments.get("search_paths")
                    max_age_days = arguments.get("max_age_days", 7)
                    
                    try:
                        results = self.k8s_manager.check_core_files(cluster_name, search_paths, max_age_days)
                        
                        if not results:
                            return [types.TextContent(type="text", text="No core files found on any nodes")]
                        
                        output_lines = [f"Core Files Check Results (showing files from last {max_age_days} days)"]
                        output_lines.append("=" * 60)
                        
                        total_core_files = 0
                        for result in results:
                            cluster = result.get("cluster", "unknown")
                            node = result.get("node", "unknown")
                            core_files = result.get("core_files", [])
                            error = result.get("error")
                            
                            output_lines.append(f"\nCluster: {cluster}")
                            output_lines.append(f"Node: {node}")
                            
                            if error:
                                output_lines.append(f"Error: {error}")
                            elif core_files:
                                output_lines.append(f"Core files found ({len(core_files)}):")
                                for core_file in core_files:
                                    total_core_files += 1
                                    output_lines.append(f"  - {core_file['path']}")
                                    output_lines.append(f"    Size: {core_file['size']}")
                                    output_lines.append(f"    Modified: {core_file['modified']}")
                                    output_lines.append(f"    Age: {core_file['age_days']} days")
                            else:
                                output_lines.append("No core files found")
                            output_lines.append("-" * 40)
                        
                        output_lines.insert(1, f"Total core files found: {total_core_files}")
                        output_lines.insert(2, "=" * 60);
                        
                        return [types.TextContent(type="text", text="\n".join(output_lines))]
                    except Exception as e:
                        return [types.TextContent(type="text", text=f"Error checking core files: {str(e)}")]
                
                elif name == "analyze_logs":
                    if not KUBERNETES_AVAILABLE:
                        return [types.TextContent(type="text", text="Error: Kubernetes library not available")]
                    
                    cluster_name = arguments.get("cluster_name")
                    pod_name = arguments.get("pod_name")
                    namespace = arguments.get("namespace")
                    log_paths = arguments.get("log_paths")
                    max_age_days = arguments.get("max_age_days", 7)
                    max_lines = arguments.get("max_lines", 100)
                    pattern = arguments.get("pattern")
                    
                    try:
                        results = self.k8s_manager.analyze_logs(cluster_name, pod_name, namespace, log_paths, max_age_days, max_lines, pattern)
                        
                        if not results:
                            return [types.TextContent(type="text", text="No clusters found or accessible for log analysis")]
                        
                        # Determine the analysis scope for the title
                        if pod_name and namespace:
                            scope = f"for pod {pod_name} in namespace {namespace}"
                        else:
                            scope = "for all cluster nodes"
                        
                        output_lines = [f"Log Analysis Results {scope} (last {max_age_days} days, max {max_lines} lines)"]
                        output_lines.append("=" * 60)
                        
                        for result in results:
                            cluster = result.get("cluster", "unknown")
                            pod = result.get("pod")
                            namespace_result = result.get("namespace")
                            node = result.get("node", "unknown")
                            error = result.get("error")
                            log_analysis = result.get("log_analysis", {})
                            
                            output_lines.append(f"\nCluster: {cluster}")
                            if pod and namespace_result:
                                output_lines.append(f"Pod: {pod}")
                                output_lines.append(f"Namespace: {namespace_result}")
                                output_lines.append(f"Node: {node}")
                            else:
                                output_lines.append(f"Node: {node}")
                                pod_used = result.get("pod_used")
                                if pod_used:
                                    output_lines.append(f"Analysis pod: {pod_used}")
                            
                            if error:
                                output_lines.append(f"Error: {error}")
                            else:
                                # Recent log files
                                recent_files = log_analysis.get("recent_log_files", [])
                                if recent_files:
                                    output_lines.append(f"Recent log files ({len(recent_files)}):")
                                    for log_file in recent_files[:5]:  # Show first 5
                                        output_lines.append(f"  - {log_file}")
                                    if len(recent_files) > 5:
                                        output_lines.append(f"  ... and {len(recent_files) - 5} more files")
                                else:
                                    output_lines.append("No recent log files found")
                                
                                # Error patterns
                                error_patterns = log_analysis.get("error_patterns", [])
                                if error_patterns:
                                    output_lines.append(f"\nError/Warning patterns found ({len(error_patterns)}):")
                                    for error_line in error_patterns[:10]:  # Show first 10
                                        output_lines.append(f"  {error_line}")
                                    if len(error_patterns) > 10:
                                        output_lines.append(f"  ... and {len(error_patterns) - 10} more entries")
                                else:
                                    output_lines.append("\nNo error patterns found")
                                
                                # Log directory listing
                                log_directory_listing = log_analysis.get("log_directory_listing", [])
                                if log_directory_listing:
                                    output_lines.append(f"\nLog directory contents:")
                                    for listing_line in log_directory_listing:
                                        output_lines.append(f"  {listing_line}")
                                
                                # Large files
                                large_files = log_analysis.get("large_files", [])
                                if large_files:
                                    output_lines.append(f"\nLarge log files (>10MB):")
                                   
                                    for large_file in large_files[:5]:  # Show first 5
                                        output_lines.append(f"  {large_file}")
                                    if len(large_files) > 5:
                                        output_lines.append(f"  ... and {len(large_files) - 5} more files")
                                
                                # Recent messages sample
                                recent_messages = log_analysis.get("recent_messages", [])
                                if recent_messages:
                                    output_lines.append(f"\nRecent system messages (last {min(len(recent_messages), 5)}):")
                                    for msg in recent_messages[-5:]:  # Show last 5
                                        output_lines.append(f"  {msg}")
                            
                            output_lines.append("-" * 40)
                        
                        return [types.TextContent(type="text", text="\n".join(output_lines))]
                    except Exception as e:
                        return [types.TextContent(type="text", text=f"Error analyzing logs: {str(e)}")]
                
                elif name == "pod_command_and_summary":
                    if not KUBERNETES_AVAILABLE:
                        return [types.TextContent(type="text", text="Error: Kubernetes library not available")]
                    
                    pod_name = arguments.get("pod_name")
                    namespace = arguments.get("namespace")
                    container = arguments.get("container")
                    cluster_name = arguments.get("cluster_name")
                    
                    if not pod_name or not namespace:
                        return [types.TextContent(type="text", text="Error: pod_name and namespace are required")]
                    
                    if not cluster_name:
                        return [types.TextContent(type="text", text="Error: cluster_name is required - this tool requires a cluster with pod_command_list configuration")]
                    
                    try:
                        result = self.k8s_manager.pod_command_and_summary(
                            pod_name, namespace, container, cluster_name
                        )
                        
                        output_lines = ["Command Execution Summary"]
                        output_lines.append("=" * 50)
                        
                        # Basic info
                        output_lines.append(f"Pod: {result['pod']}")
                        output_lines.append(f"Namespace: {result['namespace']}")
                        output_lines.append(f"Container: {result.get('container', 'N/A')}")
                        output_lines.append(f"Cluster: {result['cluster']}")
                        output_lines.append(f"Command Source: {result.get('command_source', 'unknown')}")
                        
                        # Show commands to be executed
                        if result.get('commands_to_execute'):
                            output_lines.append(f"Commands to Execute: {len(result['commands_to_execute'])}")
                            for i, cmd in enumerate(result['commands_to_execute'], 1):
                                output_lines.append(f"  {i}. {cmd}")
                        
                        # Check for errors
                        if result.get("error"):
                            output_lines.append(f"Error: {result['error']}")
                            return [types.TextContent(type="text", text="\n".join(output_lines))]
                        
                        # Execution summary
                        output_lines.append("")
                        output_lines.append("Execution Summary:")
                        output_lines.append(f"  Commands executed: {result['commands_executed']}")
                        output_lines.append(f"  Successful: {result['commands_successful']}")
                        output_lines.append(f"  Failed: {result['commands_failed']}")
                        output_lines.append(f"  Success rate: {result.get('success_rate', '0%')}")
                        output_lines.append(f"  Total output size: {result.get('total_output_size_bytes', 0)} bytes")
                        output_lines.append(f"  Estimated execution time: {result.get('estimated_execution_time', 'Unknown')}")
                        
                        # Individual command results
                        output_lines.append("")
                        output_lines.append("Command Details:")
                        output_lines.append("-" * 50)
                        
                        for cmd_result in result.get("results", []):
                            cmd_num = cmd_result.get("command_number", "?")
                            command = cmd_result.get("command", "Unknown")
                            status = cmd_result.get("status", "unknown")
                            output_size = cmd_result.get("output_size_bytes", 0)
                            output_lines_count = cmd_result.get("output_lines", 0)
                            
                            # Status indicator
                            status_icon = "✓" if status == "success" else "✗"
                            
                            output_lines.append(f"\n{status_icon} Command {cmd_num}: {command}")
                            output_lines.append(f"   Status: {status}")
                            output_lines.append(f"   Output: {output_lines_count} lines, {output_size} bytes")
                            
                            # Show error if present
                            if cmd_result.get("error"):
                                output_lines.append(f"   Error: {cmd_result['error']}")
                            
                            # Show output preview
                            preview = cmd_result.get("output_preview", {})
                            if preview.get("content"):
                                if preview.get("total_lines", 0) <= 3:
                                    output_lines.append(f"   Output: {preview['content']}")
                                else:
                                    output_lines.append(f"   First line: {preview.get('first_line', 'N/A')}")
                                    output_lines.append(f"   Last line: {preview.get('last_line', 'N/A')}")
                                    output_lines.append(f"   ({preview.get('total_lines', 0)} total lines)")
                            
                            # Show if output was truncated
                            if cmd_result.get("full_output_available"):
                                output_lines.append("   [Output truncated - use individual command execution for full output]")
                        
                        # Footer
                        output_lines.append("")
                        output_lines.append("=" * 50)
                        output_lines.append("Use individual execute_command calls for full command outputs")
                        
                        return [types.TextContent(type="text", text="\n".join(output_lines))]
                    except Exception as e:
                        return [types.TextContent(type="text", text=f"Error running commands: {str(e)}")]
                
                elif name == "jcnr_summary":
                    if not KUBERNETES_AVAILABLE:
                        return [types.TextContent(type="text", text="Error: Kubernetes library not available")]
                    
                    cluster_name = arguments.get("cluster_name")
                    
                    # Load JCNR command configuration for the cluster - now requires file configuration
                    try:
                        jcnr_config = self.k8s_manager.load_jcnr_command_list(cluster_name)
                        datapath_commands = jcnr_config.get("datapath_commands", [])
                        junos_cli_commands = jcnr_config.get("junos_cli_commands", [])
                        http_endpoints = jcnr_config.get("http_endpoints", {})
                        http_port = jcnr_config.get("http_port", 8085)
                        analysis_config = jcnr_config.get("analysis_config", {})
                    except Exception as e:
                        return [types.TextContent(type="text", text=f"Error loading JCNR configuration: {str(e)}")]
                    
                    try:
                        # Get all DPDK pods in contrail namespace
                        results = []
                        clusters_to_check = [cluster_name] if cluster_name else list(self.k8s_manager.clusters_config.keys())
                        
                        for cluster in clusters_to_check:
                            try:
                                # Use the existing logic from execute_dpdk_command to find DPDK pods
                                if not KUBERNETES_AVAILABLE:
                                    continue
                                
                                # Use the proper get_k8s_client method which handles SSH tunnels and kubeconfig loading
                                v1 = self.k8s_manager.get_k8s_client(cluster)
                                
                                # List pods in contrail namespace and filter for DPDK pods only
                                pods = v1.list_namespaced_pod(namespace="contrail")
                                
                                dpdk_pods_found = 0
                                for pod in pods.items:
                                    # Look for DPDK pods specifically - must contain "vrdpdk" in name and be Running
                                    # This ensures we only target DPDK datapath pods, not Agent pods
                                    if ("vrdpdk" in pod.metadata.name.lower() and 
                                        pod.status.phase == "Running" and
                                        pod.status.container_statuses and 
                                        all(container.ready for container in pod.status.container_statuses)):
                                        
                                        dpdk_pods_found += 1
                                        
                                        # Prepare summary result structure
                                        summary_result = {
                                            "cluster": cluster,
                                            "pod_name": pod.metadata.name,
                                            "pod_type": "DPDK",
                                            "namespace": "contrail",
                                            "commands_executed": [],
                                            "http_api_results": {},
                                            "analysis": {}
                                        }
                                        
                                        # Execute each datapath command on this DPDK pod
                                        for cmd in datapath_commands:
                                            try:
                                                cmd_result = self.k8s_manager.execute_pod_command(
                                                    pod.metadata.name, "contrail", cmd, None, cluster
                                                )
                                                summary_result["commands_executed"].append({
                                                    "command": cmd,
                                                    "status": cmd_result.get("status", "unknown"),
                                                    "output_length": len(cmd_result.get("output", "")),
                                                    "output": cmd_result.get("output", "")[:500] + "..." if len(cmd_result.get("output", "")) > 500 else cmd_result.get("output", "")
                                                })
                                            except Exception as cmd_e:
                                                summary_result["commands_executed"].append({
                                                    "command": cmd,
                                                    "status": "error",
                                                    "output": f"Error: {str(cmd_e)}"
                                                })
                                        
                                        # Add pod metadata
                                        summary_result["pod_ready_containers"] = len([c for c in pod.status.container_statuses if c.ready])
                                        summary_result["total_containers"] = len(pod.status.container_statuses) if pod.status.container_statuses else 0
                                        results.append(summary_result)
                                
                                # Log if no DPDK pods found in this cluster
                                if dpdk_pods_found == 0:
                                    results.append({
                                        "cluster": cluster,
                                        "error": "No DPDK pods (vrdpdk) found or none are ready in contrail namespace"
                                    })
                                
                                # Now process cRPD pods for Junos CLI commands if we have any
                                if junos_cli_commands:
                                    try:
                                        # List pods in jcnr namespace and filter for cRPD pods
                                        jcnr_pods = v1.list_namespaced_pod(namespace="jcnr")
                                        
                                        crpd_pods_found = 0
                                        for pod in jcnr_pods.items:
                                            # Look for cRPD pods specifically - must contain "crpd" in name and be Running
                                            if "crpd" in pod.metadata.name.lower() and pod.status.phase == "Running":
                                                # Check if all containers are ready
                                                if pod.status.container_statuses and all(c.ready for c in pod.status.container_statuses):
                                                    crpd_pods_found += 1
                                                    
                                                    # Prepare cRPD summary result structure
                                                    crpd_summary_result = {
                                                        "cluster": cluster,
                                                        "pod_name": pod.metadata.name,
                                                        "pod_type": "cRPD",
                                                        "namespace": "jcnr",
                                                        "junos_commands_executed": [],
                                                        "analysis": {}
                                                    }
                                                    
                                                    # Execute each Junos CLI command on this cRPD pod
                                                    for cmd in junos_cli_commands:
                                                        try:
                                                            # Format command with cli -c if needed
                                                            formatted_cmd = cmd
                                                            if not cmd.startswith("cli -c") and not cmd.startswith("cli -C"):
                                                                if cmd.startswith("cli "):
                                                                    formatted_cmd = cmd[4:].strip()
                                                                formatted_cmd = f"cli -c '{formatted_cmd}'"
                                                            
                                                            cmd_result = self.k8s_manager.execute_pod_command(
                                                                pod.metadata.name, "jcnr", formatted_cmd, None, cluster
                                                            )
                                                            crpd_summary_result["junos_commands_executed"].append({
                                                                "command": cmd,
                                                                "status": cmd_result.get("status", "unknown"),
                                                                "output_length": len(cmd_result.get("output", "")),
                                                                "output": cmd_result.get("output", "")[:500] + "..." if len(cmd_result.get("output", "")) > 500 else cmd_result.get("output", "")
                                                            })
                                                        except Exception as cmd_e:
                                                            crpd_summary_result["junos_commands_executed"].append({
                                                                "command": cmd,
                                                                "status": "error",
                                                                "output": f"Error: {str(cmd_e)}"
                                                            })
                                                    
                                                    # Add pod metadata
                                                    crpd_summary_result["pod_ready_containers"] = len([c for c in pod.status.container_statuses if c.ready])
                                                    crpd_summary_result["total_containers"] = len(pod.status.container_statuses) if pod.status.container_statuses else 0
                                                    results.append(crpd_summary_result)
                                        
                                        # Log if no cRPD pods found in this cluster
                                        if crpd_pods_found == 0 and junos_cli_commands:
                                            results.append({
                                                "cluster": cluster,
                                                "warning": "No cRPD pods found or none are ready in jcnr namespace for Junos CLI commands"
                                            })
                                            
                                    except Exception as crpd_e:
                                        results.append({
                                            "cluster": cluster,
                                            "error": f"Failed to process cRPD pods: {str(crpd_e)}"
                                        })
                                        
                            except Exception as e:
                                results.append({
                                    "cluster": cluster,
                                    "error": f"Failed to process cluster: {str(e)}"
                                })
                        
                        if not results:
                            return [types.TextContent(type="text", text="No DPDK pods found in contrail namespace across any clusters")]
                        
                        # Format the output with enhanced analysis
                        output_lines = [f"JCNR Datapath Summary with Route/Next-hop/Flow Analysis + HTTP API + Junos CLI"]
                        output_lines.append("=" * 80)
                        output_lines.append(f"DPDK Commands: {', '.join(datapath_commands)}")
                        if junos_cli_commands:
                            output_lines.append(f"Junos CLI Commands: {', '.join(junos_cli_commands[:5])}{'...' if len(junos_cli_commands) > 5 else ''} ({len(junos_cli_commands)} total)")
                        endpoint_names = list(http_endpoints.keys())
                        output_lines.append(f"HTTP API Endpoints: {', '.join(endpoint_names)}")
                        output_lines.append(f"HTTP Port: {http_port}")
                        if cluster_name:
                            output_lines.append(f"Configuration loaded for cluster: {cluster_name}")
                        output_lines.append("=" * 80)
                        
                        for result in results:
                            cluster = result.get("cluster", "unknown")
                            pod = result.get("pod", result.get("pod_name", "unknown"))  # Try both pod and pod_name fields
                            pod_type = result.get("pod_type", "unknown")
                            status = result.get("status", "unknown")
                            
                            if result.get("error"):
                                output_lines.append(f"\nCluster: {cluster}")
                                output_lines.append(f"Error: {result['error']}")
                                output_lines.append("-" * 40)
                                continue
                            
                            if result.get("warning"):
                                output_lines.append(f"\nCluster: {cluster}")
                                output_lines.append(f"Warning: {result['warning']}")
                                output_lines.append("-" * 40)
                                continue
                            
                            output_lines.append(f"\n🖥️  Cluster: {cluster} | Pod: {pod} | Type: {pod_type}")
                            output_lines.append("=" * 80)
                            
                            # Initialize command_outputs variable
                            command_outputs = {}
                            
                            # Handle DPDK pods (original datapath analysis)
                            if pod_type == "DPDK":
                                # Execution summary
                                commands_executed = result.get('commands_executed', 0)
                                commands_successful = result.get('commands_successful', 0)
                                commands_failed = result.get('commands_failed', 0)
                                success_rate = result.get('success_rate', '0%')
                                
                                output_lines.append(f"📊 Execution Summary: {commands_executed} commands, {success_rate} success rate")
                                
                                # Get full command outputs by executing individual commands for DPDK pods
                                # Add debug information
                                output_lines.append(f"\n🔍 Debug: Attempting to get full outputs for pod {pod} in cluster {cluster}")
                                
                                try:
                                    for command in datapath_commands:
                                        try:
                                            cmd_results = self.k8s_manager.execute_dpdk_command(command, cluster)
                                            output_lines.append(f"Debug: Got {len(cmd_results) if cmd_results else 0} results for command '{command}'")
                                            
                                            for cmd_result in cmd_results:
                                                result_cluster = cmd_result.get("cluster", "")
                                                result_pod = cmd_result.get("pod", "")
                                                result_status = cmd_result.get("status", "")
                                                
                                                output_lines.append(f"Debug: Result - cluster:{result_cluster}, pod:{result_pod}, status:{result_status}")
                                                
                                                if (result_cluster == cluster and 
                                                    pod in result_pod and  # Use 'in' instead of exact match
                                                    result_status == "success"):
                                                    command_outputs[command] = cmd_result.get("output", "")
                                                    output_lines.append(f"Debug: Stored output for {command} ({len(command_outputs[command])} chars)")
                                                    break
                                        except Exception as cmd_e:
                                            output_lines.append(f"Debug: Error with command '{command}': {str(cmd_e)}")
                                            
                                except Exception as e:
                                    output_lines.append(f"Note: Could not retrieve full command outputs: {str(e)}")
                            
                            # Handle cRPD pods (Junos CLI analysis)
                            elif pod_type == "cRPD":
                                # Get Junos CLI command outputs from the result
                                junos_commands_executed = result.get('junos_commands_executed', [])
                                
                                output_lines.append(f"📊 Junos CLI Execution Summary: {len(junos_commands_executed)} commands executed")
                                output_lines.append(f"🔍 Debug: Processing cRPD pod {pod} in cluster {cluster}")
                                
                                # Store Junos CLI outputs in command_outputs for consistent processing
                                for cmd_result in junos_commands_executed:
                                    command = cmd_result.get("command", "")
                                    status = cmd_result.get("status", "unknown")
                                    output = cmd_result.get("output", "")
                                    
                                    if status == "success":
                                        command_outputs[command] = output
                                        output_lines.append(f"Debug: Stored Junos CLI output for '{command}' ({len(output)} chars)")
                                    else:
                                        output_lines.append(f"Debug: Junos CLI command '{command}' failed: {status}")
                                
                                output_lines.append(f"Debug: Total Junos CLI commands with outputs: {len(command_outputs)}")
                            
                            output_lines.append(f"Debug: Total commands with outputs: {len(command_outputs)}")
                            
                            # Get HTTP API outputs from Sandesh HTTP server (port 8085) - only for DPDK pods
                            http_outputs = {}
                            if pod_type == "DPDK" and HTTP_AVAILABLE:
                                try:
                                    # Get pod IP for HTTP requests
                                    v1 = self.k8s_manager.get_k8s_client(cluster)
                                    pod_info = v1.read_namespaced_pod(name=pod, namespace="contrail")
                                    pod_ip = pod_info.status.pod_ip
                                    
                                    if pod_ip:
                                        output_lines.append(f"🌐 Fetching HTTP API data from pod IP: {pod_ip}:{http_port}")
                                        
                                        # Use configurable HTTP API endpoints
                                        for endpoint_name, endpoint_config in http_endpoints.items():
                                            try:
                                                endpoint_uri = endpoint_config.get("uri", endpoint_config) if isinstance(endpoint_config, dict) else endpoint_config
                                                url = f"http://{pod_ip}:{http_port}/{endpoint_uri}"
                                                output_lines.append(f"Debug: Requesting {url}")
                                                
                                                response = requests.get(url, timeout=10)
                                                if response.status_code == 200:
                                                    # Store both endpoint name and URI for flexible access
                                                    http_outputs[endpoint_name] = {
                                                        "data": response.text,
                                                        "uri": endpoint_uri
                                                    }
                                                    output_lines.append(f"Debug: Got {len(response.text)} chars from {endpoint_name}")
                                                else:
                                                    output_lines.append(f"Debug: HTTP {response.status_code} for {endpoint_name}")
                                                    
                                            except Exception as http_e:
                                                output_lines.append(f"Debug: Error fetching {endpoint_name}: {str(http_e)}")
                                    else:
                                        output_lines.append("Debug: Pod IP not available for HTTP requests")
                                        
                                except Exception as e:
                                    output_lines.append(f"Debug: Could not get pod info for HTTP requests: {str(e)}")
                            elif pod_type == "DPDK":
                                output_lines.append("Debug: HTTP requests library not available")
                            
                            # Full Command Outputs Section
                            output_lines.append("\n📄 FULL COMMAND OUTPUTS")
                            output_lines.append("=" * 80)
                            
                            # Determine which commands to display based on pod type
                            commands_to_display = []
                            if pod_type == "DPDK":
                                commands_to_display = datapath_commands
                            elif pod_type == "cRPD":
                                commands_to_display = junos_cli_commands
                            
                            for command in commands_to_display:
                                cmd_output = command_outputs.get(command, "")
                                output_lines.append(f"\n🔧 Command: {command}")
                                output_lines.append("-" * 60)
                                if cmd_output:
                                    # Use configurable output limits
                                    max_lines = analysis_config.get("max_display_lines", 50)
                                    lines = cmd_output.strip().split('\n')
                                    if analysis_config.get("truncate_large_outputs", True) and len(lines) > max_lines:
                                        output_lines.append(f"[Showing first {max_lines} lines of {len(lines)} total lines]")
                                        output_lines.extend(lines[:max_lines])
                                        output_lines.append(f"[... {len(lines) - max_lines} more lines truncated for display]")
                                    else:
                                        output_lines.append(cmd_output.strip())
                                else:
                                    output_lines.append("No output available or command failed")
                                output_lines.append("")
                            
                            # HTTP API Outputs Section (only for DPDK pods with XML to table translation)
                            if http_outputs and pod_type == "DPDK":
                                output_lines.append("\n🌐 SANDESH HTTP API OUTPUTS")
                                output_lines.append("=" * 80)
                                
                                for endpoint_name, endpoint_info in http_outputs.items():
                                    output_lines.append(f"\n🔗 API Endpoint: {endpoint_name}")
                                    output_lines.append("-" * 60)
                                    
                                    # Extract data and URI
                                    http_data = endpoint_info.get("data", "") if isinstance(endpoint_info, dict) else endpoint_info
                                    endpoint_uri = endpoint_info.get("uri", "") if isinstance(endpoint_info, dict) else ""
                                    
                                    if http_data:
                                        # Try to format XML data as readable tables using URI patterns instead of endpoint names
                                        try:
                                            formatter = XMLTableFormatter()
                                            
                                            # Use URI patterns for more stable matching
                                            if "NhListReq" in endpoint_uri:
                                                formatted_output = formatter.parse_nh_list(http_data, 
                                                    analysis_config.get("max_table_rows", 20))
                                                output_lines.append(formatted_output)
                                            elif "VrfListReq" in endpoint_uri:
                                                formatted_output = formatter.parse_vrf_list(http_data)
                                                output_lines.append(formatted_output)
                                            elif "Inet4UcRouteReq" in endpoint_uri:
                                                formatted_output = formatter.parse_route_list(http_data, 
                                                    analysis_config.get("max_table_rows", 15), "IPv4")
                                                output_lines.append(formatted_output)
                                            elif "Inet6UcRouteReq" in endpoint_uri:
                                                formatted_output = formatter.parse_route_list(http_data, 
                                                    analysis_config.get("max_table_rows", 15), "IPv6")
                                                output_lines.append(formatted_output)
                                            elif "ItfReq" in endpoint_uri:
                                                formatted_output = formatter.parse_interface_list(http_data, 
                                                    analysis_config.get("max_table_rows", 10))
                                                output_lines.append(formatted_output)
                                            else:
                                                # For other endpoints, show truncated raw XML
                                                max_chars = analysis_config.get("max_http_display_chars", 5000)
                                                if analysis_config.get("truncate_large_outputs", True) and len(http_data) > max_chars:
                                                    output_lines.append(f"[Showing first {max_chars} characters of {len(http_data)} total characters]")
                                                    output_lines.append(http_data[:max_chars])
                                                    output_lines.append(f"[... {len(http_data) - max_chars} more characters truncated for display]")
                                                else:
                                                    output_lines.append(http_data)
                                        except Exception as format_e:
                                            # If formatting fails, fall back to truncated raw XML
                                            output_lines.append(f"Note: XML formatting failed ({str(format_e)}), showing raw data:")
                                            max_chars = analysis_config.get("max_http_display_chars", 5000)
                                            if analysis_config.get("truncate_large_outputs", True) and len(http_data) > max_chars:
                                                output_lines.append(f"[Showing first {max_chars} characters of {len(http_data)} total characters]")
                                                output_lines.append(http_data[:max_chars])
                                                output_lines.append(f"[... {len(http_data) - max_chars} more characters truncated for display]")
                                            else:
                                                output_lines.append(http_data)
                                    else:
                                        output_lines.append("No data available from this endpoint")
                                    output_lines.append("")
                            
                            # Simple Command Execution Summary
                            output_lines.append("\n Command Execution Summary")
                            output_lines.append("-" * 80)
                            if pod_type == "DPDK":
                                for cmd_result in result.get("results", []):
                                    cmd_num = cmd_result.get("command_number", "?")
                                    command = cmd_result.get("command", "Unknown")
                                    cmd_status = cmd_result.get("status", "unknown")
                                    output_lines_count = cmd_result.get("output_lines", 0)
                                    
                                    status_icon = "✓" if cmd_status == "success" else "✗"
                                    output_lines.append(f"  {status_icon} Command {cmd_num}: {command} ({cmd_status}, {output_lines_count} lines)")
                            elif pod_type == "cRPD":
                                for cmd_result in result.get("junos_commands_executed", []):
                                    command = cmd_result.get("command", "Unknown")
                                    cmd_status = cmd_result.get("status", "unknown")
                                    output_length = cmd_result.get("output_length", 0)
                                    
                                    status_icon = "✓" if cmd_status == "success" else "✗"
                                    output_lines.append(f"  {status_icon} Junos CLI: {command} ({cmd_status}, {output_length} chars)")
                            
                            output_lines.append("-" * 80)
                            
                            output_lines.append("-" * 80)
                        
                        return [types.TextContent(type="text", text="\n".join(output_lines))]
                        
                    except Exception as e:
                        return [types.TextContent(type="text", text=f"Error getting JCNR summary: {str(e)}")]
                
                else:
                    raise ValueError(f"Unknown tool: {name}")
            
            except Exception as e:
                logger.error(f"Error in tool call {name}: {e}")
                return [types.TextContent(type="text", text=f"Error: {str(e)}")]
        
        @self.mcp_server.list_resources()
        async def handle_list_resources() -> List[types.Resource]:
            """List available resources."""
            resources = [
                types.Resource(
                    uri="memory://server-info",
                    name="Server Information",
                    description="Information about this Enhanced MCP HTTP server",
                    mimeType="text/plain"
                )
            ]
            
            if KUBERNETES_AVAILABLE:
                resources.append(
                    types.Resource(
                        uri="memory://k8s-help",
                        name="Kubernetes Help",
                        description="Help and examples for Kubernetes operations",
                        mimeType="text/plain"
                    )
                )
            
            return resources
        
        @self.mcp_server.read_resource()
        async def handle_read_resource(uri: str) -> str:
            """Read a resource by URI."""
            if uri == "memory://server-info":
                k8s_status = "Available" if KUBERNETES_AVAILABLE else "Not Available (install with: pip install kubernetes)"
                ssh_status = "Available" if SSH_AVAILABLE else "Not Available (install with: pip install paramiko sshtunnel)"
                return f"""Enhanced MCP HTTP Server Information
===============================================

Server: enhanced-mcp-http-server
Port: {self.port}
Protocol: HTTP
Status: Running
Kubernetes Support: {k8s_status}
SSH Tunnel Support: {ssh_status}
Configured Clusters: {len(self.k8s_manager.clusters_config)}
Active SSH Tunnels: {len(self.k8s_manager.active_tunnels)}

This server provides MCP functionality including:
- Kubernetes tools: Cluster, namespace, and pod management
- SSH tunnel support for remote cluster access
- Server info resource: This information

The server is compatible with VS Code and other MCP clients.

Available Tools:
- list_clusters: List configured Kubernetes clusters
- list_namespaces: List namespaces in a cluster
- list_pods: List pods in a namespace
- execute_command: Execute commands in pods
- execute_dpdk_command: Execute commands in all DPDK pods (vrdpdk) in contrail namespace
- execute_agent_command: Execute commands in all Agent pods (vrouter-nodes) in contrail namespace
- execute_junos_cli_commands: Execute commands in all cRPD and cSRX pods in jcnr namespace
- pod_command_and_summary: Run multiple commands on a pod and get execution summary
- jcnr_summary: Get JCNR datapath summary from DPDK pods (commands loaded from jcnr_command_list file)
"""
            
            elif uri == "memory://k8s-help":
                return """Kubernetes Operations Help
============================

Setup:
1. Create a clusters.json file with your cluster configurations
2. Start the server with: python enhanced_mcp_server.py --clusters-config clusters.json

Example clusters.json:
{
  "production": {
    "kubeconfig_path": "/path/to/prod-kubeconfig",
    "description": "Production Kubernetes cluster"
  },
  "staging": {
    "kubeconfig_path": "/path/to/staging-kubeconfig", 
    "description": "Staging environment"
  }
}

Usage Examples:
- List all clusters: list_clusters
- List namespaces: list_namespaces --cluster_name production
- List pods: list_pods --namespace default --cluster_name production

The server will use the default kubeconfig if no cluster name is specified.
"""
            
            else:
                raise ValueError(f"Unknown resource: {uri}")
        
        # Store handler references for HTTP endpoint use
        self.tools_handler = handle_list_tools
        self.call_tool_handler = handle_call_tool
        self.resources_handler = handle_list_resources
        self.read_resource_handler = handle_read_resource
    
    def _setup_http_routes(self):
        """Set up HTTP routes for the FastAPI application."""
        
        @self.app.get("/")
        async def root():
            """Root endpoint with server information."""
            return {
                "name": "Enhanced MCP HTTP Server with Kubernetes",
                "version": "2.1.0",
                "protocol": "Model Context Protocol over HTTP",
                "port": self.port,
                "kubernetes_support": KUBERNETES_AVAILABLE,
                "configured_clusters": len(self.k8s_manager.clusters_config),
                "endpoints": {
                    "mcp": "/mcp",
                    "health": "/health"
                }
            }
        
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return {
                "status": "healthy", 
                "port": self.port,
                "kubernetes_available": KUBERNETES_AVAILABLE,
                "clusters_configured": len(self.k8s_manager.clusters_config)
            }
        
        @self.app.post("/mcp", response_model=MCPResponse)
        @self.app.post("/mcp/", response_model=MCPResponse)  # Handle both with and without trailing slash
        async def mcp_endpoint(request: MCPRequest):
            """Main MCP endpoint that handles all MCP requests."""
            try:
                logger.info(f"Received MCP request: {request.method}")
                
                # Handle initialization
                if request.method == "initialize":
                    params = request.params or {}
                    capabilities = params.get("capabilities", {})
                    client_info = params.get("clientInfo", {})
                    
                    logger.info(f"Initializing with client: {client_info}")
                    
                    result = {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {"listChanged": True},
                            "resources": {"subscribe": True, "listChanged": True}
                        },
                        "serverInfo": {
                            "name": "enhanced-mcp-http-server",
                            "version": "2.0.0"
                        }
                    }
                    
                    return MCPResponse(id=request.id, result=result)
                
                # Handle tools/list
                elif request.method == "tools/list":
                    if self.tools_handler is None:
                        raise ValueError("Tools handler not initialized")
                    tools = await self.tools_handler()
                    result = {"tools": [tool.model_dump() for tool in tools]}
                    return MCPResponse(id=request.id, result=result)
                
                # Handle tools/call
                elif request.method == "tools/call":
                    if self.call_tool_handler is None:
                        raise ValueError("Call tool handler not initialized")
                    params = request.params or {}
                    name = params.get("name")
                    arguments = params.get("arguments", {})
                    
                    if not name:
                        raise ValueError("Tool name is required")
                    
                    content = await self.call_tool_handler(name, arguments)
                    result = {"content": [item.model_dump() for item in content]}
                    return MCPResponse(id=request.id, result=result)
                
                # Handle resources/list
                elif request.method == "resources/list":
                    if self.resources_handler is None:
                        raise ValueError("Resources handler not initialized")
                    resources = await self.resources_handler()
                    result = {"resources": [resource.model_dump() for resource in resources]}
                    return MCPResponse(id=request.id, result=result)
                
                # Handle resources/read
                elif request.method == "resources/read":
                    if self.read_resource_handler is None:
                        raise ValueError("Read resource handler not initialized")
                    params = request.params or {}
                    uri = params.get("uri")
                    
                    if not uri:
                        raise ValueError("Resource URI is required")
                    
                    content = await self.read_resource_handler(uri)
                    result = {
                        "contents": [{
                            "uri": uri,
                            "mimeType": "text/plain",
                            "text": content
                        }]
                    }
                    return MCPResponse(id=request.id, result=result)
                
                # Handle notifications/initialized
                elif request.method == "notifications/initialized":
                    logger.info("Client initialized successfully")
                    return MCPResponse(id=request.id, result={})
                
                else:
                    error = {
                        "code": -32601,
                        "message": f"Method not found: {request.method}"
                    }
                    return MCPResponse(id=request.id, error=error)
                    
            except Exception as e:
                logger.error(f"Error handling request: {e}")
                error = {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}"
                }
                return MCPResponse(id=request.id, error=error)
    
    async def start(self):
        """Start the HTTP server."""
        logger.info(f"Starting Enhanced MCP HTTP Server on port {self.port}")
        logger.info(f"Kubernetes support: {KUBERNETES_AVAILABLE}")
        logger.info(f"SSH tunnel support: {SSH_AVAILABLE}")
        logger.info(f"Configured clusters: {len(self.k8s_manager.clusters_config)}")
        
        config = uvicorn.Config(
            app=self.app,
            host="0.0.0.0",
            port=self.port,
            log_level="info"
        )
        
        server = uvicorn.Server(config)
        
        try:
            await server.serve()
        finally:
            # Clean up SSH tunnels on shutdown
            self.k8s_manager.close_ssh_tunnels()


async def main():
    """Main function to run the Enhanced MCP HTTP server."""
    parser = argparse.ArgumentParser(description="Enhanced MCP HTTP Server with Kubernetes")
    parser.add_argument(
        "--port", 
        type=int, 
        default=40041,
        help="Port to run the server on (default: 40041)"
    )
    parser.add_argument(
        "--clusters-config",
        type=str,
        help="Path to JSON file containing cluster configurations"
    )
    
    args = parser.parse_args()
    
    # Create and start the server
    server = EnhancedMCPHTTPServer(
        port=args.port, 
        clusters_config_path=args.clusters_config
    )
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
