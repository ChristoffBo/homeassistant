document.addEventListener('DOMContentLoaded', () => {
    const chatWindow = document.getElementById('chat-window');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const copyButton = document.getElementById('copy-button');
    const downloadButton = document.getElementById('download-button');
    const githubButton = document.getElementById('github-button');
    const modelSelect = document.getElementById('model-select');

    // Load default model from select
    let currentModel = modelSelect.value;

    // Update model when changed
    modelSelect.addEventListener('change', () => {
        currentModel = modelSelect.value;
    });

    // Send message to AI
    async function sendMessage() {
        const message = userInput.value.trim();
        if (!message) return;

        // Add user message to chat
        addMessage(message, 'user');
        userInput.value = '';
        userInput.style.height = 'auto';

        try {
            // Get AI response
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: message,
                    model: currentModel
                })
            });

            const data = await response.json();
            
            if (data.error) {
                throw new Error(data.error);
            }

            addMessage(data.response, 'ai');
        } catch (error) {
            console.error('Error:', error);
            addMessage(`Error: ${error.message}`, 'error');
        }
    }

    // Add message to chat window
    function addMessage(text, sender) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${sender}-message`;
        messageDiv.textContent = text;
        chatWindow.appendChild(messageDiv);
        chatWindow.scrollTop = chatWindow.scrollHeight;
    }

    // Copy entire chat to clipboard
    copyButton.addEventListener('click', () => {
        const chatText = Array.from(chatWindow.children)
            .map(el => `${el.className.includes('user-message') ? 'You' : 'AI'}: ${el.textContent}`)
            .join('\n\n');

        navigator.clipboard.writeText(chatText)
            .then(() => {
                alert('Chat copied to clipboard!');
            })
            .catch(err => {
                console.error('Failed to copy:', err);
                alert('Failed to copy chat');
            });
    });

    // Download chat as text file
    downloadButton.addEventListener('click', () => {
        const chatText = Array.from(chatWindow.children)
            .map(el => `${el.className.includes('user-message') ? 'You' : 'AI'}: ${el.textContent}`)
            .join('\n\n');

        const blob = new Blob([chatText], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `ai_chat_${new Date().toISOString().slice(0,10)}.txt`;
        a.click();
        URL.revokeObjectURL(url);
    });

    // Save to GitHub
    githubButton.addEventListener('click', async () => {
        const chatText = Array.from(chatWindow.children)
            .map(el => `${el.className.includes('user-message') ? 'You' : 'AI'}: ${el.textContent}`)
            .join('\n\n');

        const filename = prompt('Enter filename for GitHub (e.g., english_lesson.txt):', 
                              `ai_chat_${new Date().toISOString().slice(0,10)}.txt`);

        if (filename) {
            try {
                const response = await fetch('/api/export', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        method: 'github',
                        content: chatText,
                        filename: filename
                    })
                });

                const data = await response.json();
                
                if (data.error) {
                    throw new Error(data.error);
                }

                alert('Successfully saved to GitHub!');
            } catch (error) {
                console.error('Error:', error);
                alert(`Failed to save: ${error.message}`);
            }
        }
    });

    // Send message on button click or Shift+Enter
    sendButton.addEventListener('click', sendMessage);
    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Auto-resize textarea
    userInput.addEventListener('input', () => {
        userInput.style.height = 'auto';
        userInput.style.height = `${Math.min(userInput.scrollHeight, 150)}px`;
    });
});
