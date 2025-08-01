document.addEventListener('DOMContentLoaded', function() {
    const chatMessages = document.getElementById('chat-messages');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const modelSelector = document.getElementById('model-selector');
    let isLoading = false;

    // Auto-resize textarea
    userInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
    });

    // Send message function
    async function sendMessage() {
        const message = userInput.value.trim();
        if (message && !isLoading) {
            isLoading = true;
            sendButton.disabled = true;
            sendButton.innerHTML = '<span class="loading"></span>';
            
            addMessage('user', message);
            userInput.value = '';
            userInput.style.height = 'auto';
            
            try {
                const model = modelSelector.value;
                const response = await fetch('/api/send_message', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        message: message,
                        model: model
                    })
                });
                
                const data = await response.json();
                addMessage('assistant', data.response, true, data.model);
            } catch (error) {
                showStatus('Error sending message', 'error');
            } finally {
                isLoading = false;
                sendButton.disabled = false;
                sendButton.textContent = 'Send';
            }
        }
    }

    // Add message to chat
    function addMessage(sender, content, isFile = false, model = null) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message message-${sender}`;
        
        const contentDiv = document.createElement('div');
        contentDiv.textContent = content;
        messageDiv.appendChild(contentDiv);
        
        const metaDiv = document.createElement('div');
        metaDiv.className = 'message-meta';
        
        const now = new Date();
        metaDiv.textContent = now.toLocaleTimeString();
        
        if (model) {
            metaDiv.textContent += ` · ${model}`;
        }
        
        messageDiv.appendChild(metaDiv);
        
        if (isFile && sender === 'assistant') {
            const actionsDiv = document.createElement('div');
            actionsDiv.className = 'file-actions';
            
            actionsDiv.appendChild(createActionButton('Copy', 'copy', content));
            actionsDiv.appendChild(createActionButton('Download', 'download', content));
            actionsDiv.appendChild(createActionButton('Save to HA', 'save', content));
            
            messageDiv.appendChild(actionsDiv);
        }
        
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function createActionButton(text, action, content) {
        const btn = document.createElement('button');
        btn.className = 'action-btn';
        btn.dataset.action = action;
        btn.dataset.content = content;
        
        const iconSpan = document.createElement('span');
        iconSpan.className = `fas fa-${action}`;
        btn.appendChild(iconSpan);
        
        const textSpan = document.createElement('span');
        textSpan.textContent = text;
        btn.appendChild(textSpan);
        
        btn.addEventListener('click', handleFileAction);
        
        return btn;
    }

    async function handleFileAction(e) {
        const action = this.dataset.action;
        const content = this.dataset.content;
        const filename = `ai_export_${new Date().toISOString().slice(0,10)}.txt`;
        
        try {
            switch(action) {
                case 'copy':
                    await navigator.clipboard.writeText(content);
                    showStatus('Copied to clipboard!', 'success');
                    break;
                    
                case 'download':
                    const response = await fetch('/api/download_file', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            content: content,
                            filename: filename
                        })
                    });
                    
                    if (response.ok) {
                        const blob = await response.blob();
                        const url = window.URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = filename;
                        document.body.appendChild(a);
                        a.click();
                        a.remove();
                        showStatus('Download started!', 'success');
                    }
                    break;
                    
                case 'save':
                    const saveResponse = await fetch('/api/save_to_ha', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            content: content,
                            filename: filename
                        })
                    });
                    
                    const saveData = await saveResponse.json();
                    if (saveResponse.ok) {
                        showStatus(`Saved to ${saveData.path}`, 'success');
                    } else {
                        showStatus(`Error: ${saveData.message}`, 'error');
                    }
                    break;
            }
        } catch (error) {
            showStatus(`Error during ${action}: ${error.message}`, 'error');
        }
    }

    function showStatus(message, type) {
        const statusDiv = document.createElement('div');
        statusDiv.className = `status-message status-${type}`;
        statusDiv.textContent = message;
        
        chatMessages.appendChild(statusDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        
        setTimeout(() => {
            statusDiv.remove();
        }, 3000);
    }

    // Event listeners
    sendButton.addEventListener('click', sendMessage);
    
    userInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
});
