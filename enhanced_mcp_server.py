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
            cmd = command.split() if isinstance(command, str) else command
            
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
    
    def execute_crpd_command(self, command: str, cluster_name: str = None) -> List[Dict[str, Any]]:
        """Execute a command in all cRPD pods in jcnr namespace."""
        results = []
        clusters_to_check = [cluster_name] if cluster_name else list(self.clusters_config.keys())
        
        for cluster in clusters_to_check:
            try:
                # Get pods in jcnr namespace
                pods = self.list_pods("jcnr", cluster)
                crpd_pods = [pod for pod in pods if "crpd" in pod["name"].lower()]
                
                for pod in crpd_pods:
                    try:
                        result = self.execute_pod_command(
                            pod["name"], "jcnr", command, None, cluster
                        )
                        result["pod_type"] = "cRPD"
                        results.append(result)
                    except Exception as e:
                        results.append({
                            "pod": pod["name"],
                            "namespace": "jcnr",
                            "command": command,
                            "cluster": cluster,
                            "pod_type": "cRPD",
                            "output": f"Failed to execute command: {str(e)}",
                            "status": "error"
                        })
                        
            except Exception as e:
                results.append({
                    "cluster": cluster,
                    "namespace": "jcnr",
                    "command": command,
                    "pod_type": "cRPD",
                    "output": f"Failed to access cluster: {str(e)}",
                    "status": "error"
                })
        
        return results


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
                        name="execute_crpd_command",
                        description="Execute a command in cRPD pods in jcnr namespace across all clusters",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "description": "Command to execute in cRPD pods"
                                },
                                "cluster_name": {
                                    "type": "string",
                                    "description": "Name of the cluster (optional, executes on all clusters if not specified)"
                                }
                            },
                            "required": ["command"]
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
                
                elif name == "execute_crpd_command":
                    if not KUBERNETES_AVAILABLE:
                        return [types.TextContent(type="text", text="Error: Kubernetes library not available")]
                    
                    command = arguments.get("command")
                    cluster_name = arguments.get("cluster_name")
                    
                    if not command:
                        return [types.TextContent(type="text", text="Error: command parameter is required")]
                    
                    try:
                        results = self.k8s_manager.execute_crpd_command(command, cluster_name)
                        
                        if not results:
                            return [types.TextContent(type="text", text="No cRPD pods found in jcnr namespace")]
                        
                        output_lines = [f"cRPD Command Execution Results for: {command}"]
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
- execute_crpd_command: Execute commands in all cRPD pods in jcnr namespace
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
