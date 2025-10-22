#!/usr/bin/env python3
"""
Jarvis Prime - Workbench Module
Visual automation builder for Sentinel templates and Orchestrator playbooks
"""

import os
import json
import yaml
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file
import logging

logger = logging.getLogger('jarvis.workbench')

workbench_bp = Blueprint('workbench', __name__, url_prefix='/api/workbench')

# Paths
SENTINEL_TEMPLATES = '/share/jarvis_prime/sentinel/custom_templates'
ORCHESTRATOR_PLAYBOOKS = '/share/jarvis_prime/playbooks'
CONFIG_PATH = '/config/options.json'

os.makedirs(SENTINEL_TEMPLATES, exist_ok=True)
os.makedirs(ORCHESTRATOR_PLAYBOOKS, exist_ok=True)


def load_config():
    """Load Jarvis configuration"""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except:
        logger.error("Failed to load config")
        return {}


@workbench_bp.route('/config', methods=['GET'])
def get_workbench_config():
    """Get configuration for workbench (servers, gotify, etc)"""
    try:
        config = load_config()
        
        # Get servers from orchestrator
        servers = []
        for srv in config.get('orchestrator_servers', []):
            servers.append({
                'name': srv.get('name', srv.get('hostname')),
                'hostname': srv.get('hostname'),
                'groups': srv.get('groups', '').split(',') if srv.get('groups') else []
            })
        
        # Get Gotify config
        gotify = {
            'enabled': config.get('gotify_enabled', False),
            'url': config.get('gotify_url', ''),
            'token': config.get('gotify_app_token', '')
        }
        
        # Get proxy settings if they exist
        proxy = {
            'http': config.get('http_proxy', ''),
            'https': config.get('https_proxy', '')
        }
        
        return jsonify({
            'success': True,
            'servers': servers,
            'gotify': gotify,
            'proxy': proxy
        })
    except Exception as e:
        logger.error(f"Config error: {e}")
        return jsonify({'success': False, 'error': str(e)})


@workbench_bp.route('/validate', methods=['POST'])
def validate_automation():
    """Validate automation before saving"""
    try:
        data = request.json
        automation_type = data.get('type')  # 'sentinel' or 'orchestrator'
        
        errors = []
        warnings = []
        
        if automation_type == 'sentinel':
            # Validate Sentinel template
            if not data.get('name'):
                errors.append("Template needs a name")
            if not data.get('check_cmd'):
                errors.append("Check command is required")
            if not data.get('expected_output'):
                warnings.append("No expected output - template will only check if command succeeds")
            if not data.get('fix_cmd'):
                errors.append("Fix command is required")
                
        elif automation_type == 'orchestrator':
            # Validate Orchestrator playbook
            if not data.get('name'):
                errors.append("Playbook needs a name")
            if not data.get('tasks') or len(data.get('tasks', [])) == 0:
                errors.append("Playbook needs at least one task")
            
            # Check if tasks are properly formed
            for i, task in enumerate(data.get('tasks', [])):
                if not task.get('name'):
                    warnings.append(f"Task {i+1} has no name")
                if not task.get('module'):
                    errors.append(f"Task {i+1} needs a module (apt, command, uri, etc)")
        else:
            errors.append("Invalid automation type")
        
        return jsonify({
            'success': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        })
        
    except Exception as e:
        logger.error(f"Validation error: {e}")
        return jsonify({'success': False, 'error': str(e)})


@workbench_bp.route('/save', methods=['POST'])
def save_automation():
    """Save automation (Sentinel template or Orchestrator playbook)"""
    try:
        data = request.json
        automation_type = data.get('type')
        
        if automation_type == 'sentinel':
            return save_sentinel_template(data)
        elif automation_type == 'orchestrator':
            return save_orchestrator_playbook(data)
        else:
            return jsonify({'success': False, 'error': 'Invalid type'})
            
    except Exception as e:
        logger.error(f"Save error: {e}")
        return jsonify({'success': False, 'error': str(e)})


def save_sentinel_template(data):
    """Save Sentinel health check template"""
    template_id = data.get('id') or f"wb_{uuid.uuid4().hex[:8]}"
    
    # Build Sentinel JSON template
    template = {
        'id': template_id,
        'name': data.get('name'),
        'description': data.get('description', ''),
        'check_cmd': data.get('check_cmd'),
        'expected_output': data.get('expected_output', ''),
        'fix_cmd': data.get('fix_cmd'),
        'verify_cmd': data.get('verify_cmd') or data.get('check_cmd'),
        'retry_count': int(data.get('retry_count', 2)),
        'retry_delay': int(data.get('retry_delay', 30)),
        'ttl_seconds': int(data.get('ttl_seconds', 300))
    }
    
    # Save to sentinel templates
    filename = f"{template_id}.json"
    filepath = os.path.join(SENTINEL_TEMPLATES, filename)
    
    with open(filepath, 'w') as f:
        json.dump(template, f, indent=2)
    
    logger.info(f"Saved Sentinel template: {template['name']}")
    
    return jsonify({
        'success': True,
        'id': template_id,
        'filename': filename,
        'message': f'Sentinel template "{template["name"]}" saved'
    })


def save_orchestrator_playbook(data):
    """Save Orchestrator Ansible playbook"""
    playbook_id = data.get('id') or f"wb_{uuid.uuid4().hex[:8]}"
    playbook_name = data.get('name').replace(' ', '_').lower()
    
    # Build Ansible playbook
    playbook = [{
        'name': data.get('name'),
        'hosts': data.get('hosts', 'all'),
        'become': data.get('become', True),
        'tasks': []
    }]
    
    # Add tasks
    for task_data in data.get('tasks', []):
        task = {
            'name': task_data.get('name', 'Task')
        }
        
        module = task_data.get('module')
        params = task_data.get('params', {})
        
        # Build task based on module
        if module == 'apt':
            task['ansible.builtin.apt'] = params
        elif module == 'command' or module == 'shell':
            task[f'ansible.builtin.{module}'] = params.get('cmd', '')
        elif module == 'uri':
            task['ansible.builtin.uri'] = params
        elif module == 'stat':
            task['ansible.builtin.stat'] = params
        elif module == 'set_fact':
            task['ansible.builtin.set_fact'] = params
        else:
            task[f'ansible.builtin.{module}'] = params
        
        # Add register if specified
        if task_data.get('register'):
            task['register'] = task_data['register']
        
        # Add when condition if specified
        if task_data.get('when'):
            task['when'] = task_data['when']
        
        playbook[0]['tasks'].append(task)
    
    # Add Gotify notification if enabled
    if data.get('notify_gotify'):
        config = load_config()
        gotify_url = config.get('gotify_url', '')
        gotify_token = config.get('gotify_app_token', '')
        
        if gotify_url and gotify_token:
            notify_task = {
                'name': f'Send notification to Gotify',
                'ansible.builtin.uri': {
                    'url': f"{gotify_url}/message?token={gotify_token}",
                    'method': 'POST',
                    'body_format': 'json',
                    'body': {
                        'title': f"{data.get('name')} on {{{{ inventory_hostname }}}}",
                        'message': data.get('notify_message', 'Playbook completed'),
                        'priority': int(data.get('notify_priority', 5))
                    },
                    'status_code': 200
                }
            }
            playbook[0]['tasks'].append(notify_task)
    
    # Save playbook
    filename = f"{playbook_name}.yml"
    filepath = os.path.join(ORCHESTRATOR_PLAYBOOKS, filename)
    
    with open(filepath, 'w') as f:
        yaml.dump(playbook, f, default_flow_style=False, sort_keys=False)
    
    logger.info(f"Saved Orchestrator playbook: {data.get('name')}")
    
    return jsonify({
        'success': True,
        'id': playbook_id,
        'filename': filename,
        'message': f'Orchestrator playbook "{data.get("name")}" saved'
    })


@workbench_bp.route('/list', methods=['GET'])
def list_automations():
    """List all saved automations"""
    try:
        automations = []
        
        # List Sentinel templates
        if os.path.exists(SENTINEL_TEMPLATES):
            for filename in os.listdir(SENTINEL_TEMPLATES):
                if filename.endswith('.json'):
                    try:
                        with open(os.path.join(SENTINEL_TEMPLATES, filename)) as f:
                            template = json.load(f)
                            automations.append({
                                'id': template.get('id'),
                                'name': template.get('name'),
                                'type': 'sentinel',
                                'description': template.get('description', ''),
                                'filename': filename
                            })
                    except:
                        pass
        
        # List Orchestrator playbooks
        if os.path.exists(ORCHESTRATOR_PLAYBOOKS):
            for filename in os.listdir(ORCHESTRATOR_PLAYBOOKS):
                if filename.endswith('.yml') or filename.endswith('.yaml'):
                    try:
                        with open(os.path.join(ORCHESTRATOR_PLAYBOOKS, filename)) as f:
                            playbook = yaml.safe_load(f)
                            if playbook and isinstance(playbook, list) and len(playbook) > 0:
                                automations.append({
                                    'id': filename.replace('.yml', '').replace('.yaml', ''),
                                    'name': playbook[0].get('name', filename),
                                    'type': 'orchestrator',
                                    'description': f"{len(playbook[0].get('tasks', []))} tasks",
                                    'filename': filename
                                })
                    except:
                        pass
        
        return jsonify({'success': True, 'automations': automations})
        
    except Exception as e:
        logger.error(f"List error: {e}")
        return jsonify({'success': False, 'error': str(e)})


@workbench_bp.route('/load/<automation_type>/<filename>', methods=['GET'])
def load_automation(automation_type, filename):
    """Load a specific automation for editing"""
    try:
        if automation_type == 'sentinel':
            filepath = os.path.join(SENTINEL_TEMPLATES, filename)
            if os.path.exists(filepath):
                with open(filepath) as f:
                    return jsonify({'success': True, 'data': json.load(f)})
        
        elif automation_type == 'orchestrator':
            filepath = os.path.join(ORCHESTRATOR_PLAYBOOKS, filename)
            if os.path.exists(filepath):
                with open(filepath) as f:
                    return jsonify({'success': True, 'data': yaml.safe_load(f)})
        
        return jsonify({'success': False, 'error': 'Automation not found'})
        
    except Exception as e:
        logger.error(f"Load error: {e}")
        return jsonify({'success': False, 'error': str(e)})


@workbench_bp.route('/delete/<automation_type>/<filename>', methods=['DELETE'])
def delete_automation(automation_type, filename):
    """Delete an automation"""
    try:
        if automation_type == 'sentinel':
            filepath = os.path.join(SENTINEL_TEMPLATES, filename)
        elif automation_type == 'orchestrator':
            filepath = os.path.join(ORCHESTRATOR_PLAYBOOKS, filename)
        else:
            return jsonify({'success': False, 'error': 'Invalid type'})
        
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"Deleted {automation_type}: {filename}")
            return jsonify({'success': True})
        
        return jsonify({'success': False, 'error': 'File not found'})
        
    except Exception as e:
        logger.error(f"Delete error: {e}")
        return jsonify({'success': False, 'error': str(e)})


@workbench_bp.route('/export/<automation_type>/<filename>', methods=['GET'])
def export_automation(automation_type, filename):
    """Export automation as downloadable file"""
    try:
        if automation_type == 'sentinel':
            filepath = os.path.join(SENTINEL_TEMPLATES, filename)
        elif automation_type == 'orchestrator':
            filepath = os.path.join(ORCHESTRATOR_PLAYBOOKS, filename)
        else:
            return jsonify({'success': False, 'error': 'Invalid type'})
        
        if os.path.exists(filepath):
            return send_file(filepath, as_attachment=True, download_name=filename)
        
        return jsonify({'success': False, 'error': 'File not found'})
        
    except Exception as e:
        logger.error(f"Export error: {e}")
        return jsonify({'success': False, 'error': str(e)})


def init_workbench(app):
    """Initialize Workbench module with Flask app"""
    app.register_blueprint(workbench_bp)
    logger.info("Workbench module initialized")
    return workbench_bp
