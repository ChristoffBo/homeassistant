#!/usr/bin/env python3
"""
Jarvis Prime - Workbench Module
Visual drag-and-drop automation builder with live YAML preview
Converts visual flows to Sentinel/Orchestrator templates
"""

import os
import json
import yaml
import uuid
import subprocess
from datetime import datetime
from typing import Dict, List, Any, Optional
from flask import Blueprint, request, jsonify
import logging

# Initialize logger
logger = logging.getLogger('jarvis.workbench')

# Blueprint for API routes
workbench_bp = Blueprint('workbench', __name__, url_prefix='/api/workbench')

# Paths
TEMPLATES_DIR = '/share/jarvis_prime/templates'
CONFIG_PATH = '/config/options.json'

# Ensure directories exist
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(os.path.join(TEMPLATES_DIR, 'sentinel'), exist_ok=True)
os.makedirs(os.path.join(TEMPLATES_DIR, 'orchestrator'), exist_ok=True)


def load_config() -> Dict[str, Any]:
    """Load configuration from options.json"""
    try:
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {}


def get_ssh_credentials(server_name: str) -> Optional[Dict[str, str]]:
    """Retrieve SSH credentials for a server from config"""
    config = load_config()
    servers = config.get('orchestrator_servers', [])
    
    for server in servers:
        if server.get('name') == server_name or server.get('host') == server_name:
            return {
                'host': server.get('host'),
                'user': server.get('user'),
                'password': server.get('password'),
                'port': server.get('port', 22)
            }
    return None


def get_notification_config() -> Dict[str, Any]:
    """Retrieve notification settings from config"""
    config = load_config()
    return {
        'gotify_enabled': config.get('gotify_enabled', False),
        'gotify_url': config.get('gotify_url', ''),
        'gotify_token': config.get('gotify_token', ''),
        'email_enabled': config.get('email_enabled', False),
        'email_smtp': config.get('email_smtp', ''),
        'email_from': config.get('email_from', '')
    }


def validate_block(block: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Validate a single workflow block"""
    block_type = block.get('type')
    
    if not block_type:
        return False, "Block missing type field"
    
    # Validate SSH block
    if block_type == 'ssh':
        if not block.get('host'):
            return False, "SSH block missing host"
        if not block.get('user'):
            return False, "SSH block missing user"
        # Check if credentials exist in config
        creds = get_ssh_credentials(block.get('host'))
        if not creds:
            return False, f"No credentials found for host: {block.get('host')}"
    
    # Validate command block
    elif block_type == 'command':
        if not block.get('command'):
            return False, "Command block missing command"
        if not block.get('host'):
            return False, "Command block missing target host"
    
    # Validate verify block
    elif block_type == 'verify':
        if not block.get('check_command'):
            return False, "Verify block missing check_command"
        if not block.get('expected_output') and not block.get('expected_code'):
            return False, "Verify block needs expected_output or expected_code"
    
    # Validate notify block
    elif block_type == 'notify':
        if not block.get('message'):
            return False, "Notify block missing message"
        notify_config = get_notification_config()
        if not notify_config.get('gotify_enabled') and not notify_config.get('email_enabled'):
            return False, "No notification channels configured"
    
    # Validate wait block
    elif block_type == 'wait':
        if not block.get('duration'):
            return False, "Wait block missing duration"
        try:
            int(block.get('duration'))
        except ValueError:
            return False, "Wait duration must be an integer (seconds)"
    
    # Validate conditional block
    elif block_type == 'conditional':
        if not block.get('condition'):
            return False, "Conditional block missing condition"
        if not block.get('true_steps') and not block.get('false_steps'):
            return False, "Conditional block needs true_steps or false_steps"
    
    else:
        return False, f"Unknown block type: {block_type}"
    
    return True, None


def blocks_to_yaml(workflow: Dict[str, Any]) -> str:
    """Convert workflow JSON blocks to YAML template"""
    template_type = workflow.get('type', 'orchestrator')
    blocks = workflow.get('steps', [])
    metadata = workflow.get('metadata', {})
    
    if template_type == 'sentinel':
        # Sentinel heal template format
        yaml_data = {
            'version': '1.0',
            'type': 'sentinel_heal',
            'metadata': {
                'name': metadata.get('name', 'Untitled Template'),
                'description': metadata.get('description', ''),
                'created': datetime.utcnow().isoformat(),
                'service_name': metadata.get('service_name', 'unknown'),
                'enabled': metadata.get('enabled', True)
            },
            'check': {},
            'heal': {},
            'verify': {}
        }
        
        # Extract check, heal, verify steps
        for block in blocks:
            if block.get('type') == 'verify':
                yaml_data['check'] = {
                    'command': block.get('check_command'),
                    'host': block.get('host'),
                    'expected': block.get('expected_output') or block.get('expected_code')
                }
            elif block.get('type') == 'command':
                if 'heal' not in yaml_data or not yaml_data['heal']:
                    yaml_data['heal'] = {
                        'commands': [],
                        'host': block.get('host')
                    }
                yaml_data['heal']['commands'].append(block.get('command'))
            elif block.get('type') == 'notify':
                yaml_data['metadata']['notify_on_success'] = True
                yaml_data['metadata']['notify_message'] = block.get('message')
    
    else:
        # Orchestrator playbook format
        yaml_data = {
            'version': '1.0',
            'type': 'orchestrator_playbook',
            'metadata': {
                'name': metadata.get('name', 'Untitled Playbook'),
                'description': metadata.get('description', ''),
                'created': datetime.utcnow().isoformat(),
                'category': metadata.get('category', 'general')
            },
            'steps': []
        }
        
        # Convert each block to a step
        for idx, block in enumerate(blocks):
            step = {
                'id': f"step_{idx + 1}",
                'type': block.get('type'),
                'name': block.get('name', f"Step {idx + 1}")
            }
            
            if block.get('type') == 'ssh':
                step['host'] = block.get('host')
                step['user'] = block.get('user')
                
            elif block.get('type') == 'command':
                step['command'] = block.get('command')
                step['host'] = block.get('host')
                step['timeout'] = block.get('timeout', 300)
                
            elif block.get('type') == 'verify':
                step['check_command'] = block.get('check_command')
                step['expected_output'] = block.get('expected_output')
                step['expected_code'] = block.get('expected_code', 0)
                
            elif block.get('type') == 'notify':
                step['message'] = block.get('message')
                step['priority'] = block.get('priority', 5)
                
            elif block.get('type') == 'wait':
                step['duration'] = int(block.get('duration'))
                
            elif block.get('type') == 'conditional':
                step['condition'] = block.get('condition')
                step['true_steps'] = block.get('true_steps', [])
                step['false_steps'] = block.get('false_steps', [])
            
            yaml_data['steps'].append(step)
    
    return yaml.dump(yaml_data, default_flow_style=False, sort_keys=False)


@workbench_bp.route('/save', methods=['POST'])
def save_template():
    """Save workflow as YAML template"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        # Validate workflow structure
        if 'steps' not in data:
            return jsonify({'success': False, 'error': 'Missing steps'}), 400
        
        if 'metadata' not in data or 'name' not in data['metadata']:
            return jsonify({'success': False, 'error': 'Missing template name'}), 400
        
        # Validate all blocks
        for idx, block in enumerate(data.get('steps', [])):
            valid, error = validate_block(block)
            if not valid:
                return jsonify({
                    'success': False,
                    'error': f"Step {idx + 1}: {error}"
                }), 400
        
        # Generate YAML
        yaml_content = blocks_to_yaml(data)
        
        # Generate template ID
        template_id = data.get('id') or str(uuid.uuid4())
        template_type = data.get('type', 'orchestrator')
        template_name = data['metadata']['name']
        
        # Save to appropriate directory
        subdir = 'sentinel' if template_type == 'sentinel' else 'orchestrator'
        filename = f"{template_id}.yml"
        filepath = os.path.join(TEMPLATES_DIR, subdir, filename)
        
        with open(filepath, 'w') as f:
            f.write(yaml_content)
        
        # Save metadata JSON for quick lookup
        metadata_file = os.path.join(TEMPLATES_DIR, subdir, f"{template_id}.meta.json")
        with open(metadata_file, 'w') as f:
            json.dump({
                'id': template_id,
                'name': template_name,
                'type': template_type,
                'created': datetime.utcnow().isoformat(),
                'filepath': filepath,
                'metadata': data.get('metadata', {})
            }, f, indent=2)
        
        logger.info(f"Saved template: {template_name} ({template_id})")
        
        return jsonify({
            'success': True,
            'template_id': template_id,
            'filepath': filepath,
            'message': f"Template '{template_name}' saved successfully"
        })
    
    except Exception as e:
        logger.error(f"Save template error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@workbench_bp.route('/validate', methods=['POST'])
def validate_workflow():
    """Validate workflow without saving"""
    try:
        data = request.get_json()
        
        if not data or 'steps' not in data:
            return jsonify({'success': False, 'error': 'Invalid workflow data'}), 400
        
        errors = []
        warnings = []
        
        # Validate each block
        for idx, block in enumerate(data.get('steps', [])):
            valid, error = validate_block(block)
            if not valid:
                errors.append({
                    'step': idx + 1,
                    'type': block.get('type'),
                    'error': error
                })
            
            # Check for warnings
            if block.get('type') == 'command':
                cmd = block.get('command', '')
                if any(danger in cmd.lower() for danger in ['rm -rf /', 'dd if=', 'mkfs', ':(){:|:&};:']):
                    warnings.append({
                        'step': idx + 1,
                        'warning': 'Potentially dangerous command detected'
                    })
        
        # Try to generate YAML
        yaml_content = None
        yaml_error = None
        try:
            yaml_content = blocks_to_yaml(data)
        except Exception as e:
            yaml_error = str(e)
        
        is_valid = len(errors) == 0 and yaml_error is None
        
        return jsonify({
            'success': True,
            'valid': is_valid,
            'errors': errors,
            'warnings': warnings,
            'yaml_preview': yaml_content,
            'yaml_error': yaml_error
        })
    
    except Exception as e:
        logger.error(f"Validation error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@workbench_bp.route('/test', methods=['POST'])
def test_step():
    """Test a single workflow step safely"""
    try:
        data = request.get_json()
        
        if not data or 'block' not in data:
            return jsonify({'success': False, 'error': 'No block provided'}), 400
        
        block = data['block']
        block_type = block.get('type')
        
        result = {
            'success': False,
            'output': '',
            'error': None
        }
        
        # Test SSH connection
        if block_type == 'ssh':
            host = block.get('host')
            creds = get_ssh_credentials(host)
            
            if not creds:
                result['error'] = f"No credentials found for host: {host}"
            else:
                # Test SSH with simple command
                cmd = [
                    'sshpass', '-p', creds['password'],
                    'ssh', '-o', 'StrictHostKeyChecking=no',
                    '-o', 'ConnectTimeout=5',
                    f"{creds['user']}@{creds['host']}",
                    'echo "SSH test successful"'
                ]
                
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    if proc.returncode == 0:
                        result['success'] = True
                        result['output'] = proc.stdout.strip()
                    else:
                        result['error'] = proc.stderr or "SSH connection failed"
                except subprocess.TimeoutExpired:
                    result['error'] = "SSH connection timeout"
                except Exception as e:
                    result['error'] = str(e)
        
        # Test command execution
        elif block_type == 'command':
            host = block.get('host')
            command = block.get('command')
            creds = get_ssh_credentials(host)
            
            if not creds:
                result['error'] = f"No credentials found for host: {host}"
            elif not command:
                result['error'] = "No command provided"
            else:
                # Execute command via SSH
                cmd = [
                    'sshpass', '-p', creds['password'],
                    'ssh', '-o', 'StrictHostKeyChecking=no',
                    '-o', 'ConnectTimeout=5',
                    f"{creds['user']}@{creds['host']}",
                    command
                ]
                
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    result['success'] = proc.returncode == 0
                    result['output'] = proc.stdout.strip()
                    if proc.returncode != 0:
                        result['error'] = proc.stderr or f"Command exited with code {proc.returncode}"
                except subprocess.TimeoutExpired:
                    result['error'] = "Command execution timeout"
                except Exception as e:
                    result['error'] = str(e)
        
        # Test verify block
        elif block_type == 'verify':
            check_cmd = block.get('check_command')
            host = block.get('host', 'localhost')
            
            if host == 'localhost':
                # Run locally
                try:
                    proc = subprocess.run(
                        check_cmd, shell=True, capture_output=True, text=True, timeout=10
                    )
                    result['success'] = True
                    result['output'] = f"Exit code: {proc.returncode}\n{proc.stdout}"
                except Exception as e:
                    result['error'] = str(e)
            else:
                # Run via SSH
                creds = get_ssh_credentials(host)
                if not creds:
                    result['error'] = f"No credentials found for host: {host}"
                else:
                    cmd = [
                        'sshpass', '-p', creds['password'],
                        'ssh', '-o', 'StrictHostKeyChecking=no',
                        f"{creds['user']}@{creds['host']}",
                        check_cmd
                    ]
                    
                    try:
                        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                        result['success'] = True
                        result['output'] = f"Exit code: {proc.returncode}\n{proc.stdout}"
                    except Exception as e:
                        result['error'] = str(e)
        
        # Test notify block
        elif block_type == 'notify':
            notify_config = get_notification_config()
            message = block.get('message', 'Test notification')
            
            if notify_config.get('gotify_enabled'):
                result['success'] = True
                result['output'] = f"Would send notification: {message}"
            else:
                result['error'] = "No notification channels configured"
        
        # Test wait block
        elif block_type == 'wait':
            duration = block.get('duration', 0)
            result['success'] = True
            result['output'] = f"Would wait {duration} seconds"
        
        else:
            result['error'] = f"Testing not supported for block type: {block_type}"
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Test step error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@workbench_bp.route('/list', methods=['GET'])
def list_templates():
    """List all saved templates"""
    try:
        templates = []
        
        # Scan both sentinel and orchestrator directories
        for template_type in ['sentinel', 'orchestrator']:
            type_dir = os.path.join(TEMPLATES_DIR, template_type)
            
            if not os.path.exists(type_dir):
                continue
            
            for filename in os.listdir(type_dir):
                if filename.endswith('.meta.json'):
                    filepath = os.path.join(type_dir, filename)
                    try:
                        with open(filepath, 'r') as f:
                            meta = json.load(f)
                            templates.append(meta)
                    except Exception as e:
                        logger.error(f"Failed to load template metadata {filename}: {e}")
        
        # Sort by creation date (newest first)
        templates.sort(key=lambda x: x.get('created', ''), reverse=True)
        
        return jsonify({
            'success': True,
            'templates': templates,
            'count': len(templates)
        })
    
    except Exception as e:
        logger.error(f"List templates error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@workbench_bp.route('/load/<template_id>', methods=['GET'])
def load_template(template_id):
    """Load a template by ID"""
    try:
        # Search in both directories
        for template_type in ['sentinel', 'orchestrator']:
            meta_file = os.path.join(TEMPLATES_DIR, template_type, f"{template_id}.meta.json")
            yaml_file = os.path.join(TEMPLATES_DIR, template_type, f"{template_id}.yml")
            
            if os.path.exists(meta_file) and os.path.exists(yaml_file):
                with open(meta_file, 'r') as f:
                    metadata = json.load(f)
                
                with open(yaml_file, 'r') as f:
                    yaml_content = f.read()
                
                return jsonify({
                    'success': True,
                    'metadata': metadata,
                    'yaml': yaml_content
                })
        
        return jsonify({'success': False, 'error': 'Template not found'}), 404
    
    except Exception as e:
        logger.error(f"Load template error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@workbench_bp.route('/delete/<template_id>', methods=['DELETE'])
def delete_template(template_id):
    """Delete a template"""
    try:
        deleted = False
        
        # Search and delete from both directories
        for template_type in ['sentinel', 'orchestrator']:
            meta_file = os.path.join(TEMPLATES_DIR, template_type, f"{template_id}.meta.json")
            yaml_file = os.path.join(TEMPLATES_DIR, template_type, f"{template_id}.yml")
            
            if os.path.exists(meta_file):
                os.remove(meta_file)
                deleted = True
            
            if os.path.exists(yaml_file):
                os.remove(yaml_file)
                deleted = True
        
        if deleted:
            logger.info(f"Deleted template: {template_id}")
            return jsonify({'success': True, 'message': 'Template deleted'})
        else:
            return jsonify({'success': False, 'error': 'Template not found'}), 404
    
    except Exception as e:
        logger.error(f"Delete template error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def init_workbench(app):
    """Initialize workbench module with Flask app"""
    app.register_blueprint(workbench_bp)
    logger.info("Workbench module initialized")