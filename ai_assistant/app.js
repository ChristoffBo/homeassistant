// Global state
let state = {
    currentMode: 'chat',
    chatHistory: [],
    codeContent: '',
    lessonData: null
};

// DOM Elements
const elements = {
    modeSwitcher: document.querySelector('.mode-switcher'),
    chatContainer: document.getElementById('mode-chat'),
    codeContainer: document.getElementById('mode-code'),
    teachContainer: document.getElementById('mode-teach'),
    chatInput: document.getElementById('chat-input'),
    chatSendBtn: document.getElementById('chat-send'),
    chatHistory: document.getElementById('chat-history'),
    codeEditor: document.getElementById('code-editor'),
    codePushBtn: document.getElementById('code-push'),
    lessonType: document.getElementById('lesson-type'),
    lessonTopic: document.getElementById('lesson-topic'),
    lessonGenerateBtn: document.getElementById('lesson-generate'),
    lessonOutput: document.getElementById('lesson-output')
};

// Mode switching
function setMode(mode) {
    state.currentMode = mode;
    
    // Hide all modes
    elements.chatContainer.style.display = 'none';
    elements.codeContainer.style.display = 'none';
    elements.teachContainer.style.display = 'none';
    
    // Show current mode
    document.getElementById(`mode-${mode}`).style.display = 'block';
    
    // Update active tab
    document.querySelectorAll('.mode-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.mode === mode);
    });
    
    // Initialize mode-specific UI
    if (mode === 'chat') initChat();
    else if (mode === 'code') initCode();
    else if (mode === 'teach') initTeach();
}

// Chat functions
function initChat() {
    if (state.chatHistory.length === 0) {
        fetch('/api/chat/init')
            .then(res => res.json())
            .then(data => {
                state.chatHistory = data.history;
                renderChat();
            });
    }
}

function sendChatMessage() {
    const message = elements.chatInput.value.trim();
    if (!message) return;
    
    fetch('/api/chat/send', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message})
    })
    .then(res => res.json())
    .then(data => {
        if (data.error) throw new Error(data.error);
        state.chatHistory.push({
            user: message,
            ai: data.response,
            timestamp: new Date().toISOString()
        });
        renderChat();
        elements.chatInput.value = '';
    })
    .catch(err => {
        console.error("Chat error:", err);
        alert(`Error: ${err.message}`);
    });
}

function renderChat() {
    elements.chatHistory.innerHTML = state.chatHistory
        .map(msg => `
            <div class="message ${msg.user ? 'user' : 'ai'}">
                <div class="timestamp">${new Date(msg.timestamp).toLocaleTimeString()}</div>
                <div class="content">${msg.user || msg.ai}</div>
            </div>
        `)
        .join('');
    elements.chatHistory.scrollTop = elements.chatHistory.scrollHeight;
}

// Code functions
function initCode() {
    elements.codeEditor.value = state.codeContent || '';
}

function pushCode() {
    const code = elements.codeEditor.value;
    const filename = prompt("Enter filename (e.g., my_script.py):");
    const commitMsg = prompt("Enter commit message:");
    
    if (!filename || !commitMsg) return;
    
    fetch('/api/code/push', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            code,
            filename,
            commit_message: commitMsg
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.error) throw new Error(data.error);
        alert("Successfully pushed to Git!");
    })
    .catch(err => {
        console.error("Push error:", err);
        alert(`Error: ${err.message}`);
    });
}

// Teaching functions
function initTeach() {
    if (!state.lessonData) {
        elements.lessonOutput.innerHTML = '<p>Generate a new lesson to get started</p>';
    }
}

function generateLesson() {
    const type = elements.lessonType.value;
    const topic = elements.lessonTopic.value.trim();
    
    if (!topic) {
        alert("Please enter a lesson topic");
        return;
    }
    
    fetch('/api/teach/generate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({type, topic})
    })
    .then(res => res.json())
    .then(data => {
        if (data.error) throw new Error(data.error);
        state.lessonData = data;
        renderLesson();
    })
    .catch(err => {
        console.error("Lesson error:", err);
        alert(`Error: ${err.message}`);
    });
}

function renderLesson() {
    if (!state.lessonData) return;
    
    elements.lessonOutput.innerHTML = `
        <h2>${state.lessonData.title}</h2>
        <div class="lesson-sections">
            ${state.lessonData.content.map(section => `
                <div class="lesson-section ${section.type}">
                    <h3>${section.type.toUpperCase()}</h3>
                    <p>${section.text}</p>
                </div>
            `).join('')}
        </div>
        <div class="lesson-actions">
            <button onclick="exportLesson('pdf')">Export as PDF</button>
            <button onclick="exportLesson('docx')">Export as Word</button>
        </div>
    `;
}

function exportLesson(format) {
    if (!state.lessonData) return;
    
    alert(`Exporting lesson as ${format.toUpperCase()}...`);
    // Actual export implementation would go here
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Set up event listeners
    document.querySelectorAll('.mode-tab').forEach(tab => {
        tab.addEventListener('click', () => setMode(tab.dataset.mode));
    });
    
    elements.chatSendBtn.addEventListener('click', sendChatMessage);
    elements.chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendChatMessage();
    });
    
    elements.codePushBtn.addEventListener('click', pushCode);
    elements.lessonGenerateBtn.addEventListener('click', generateLesson);
    
    // Load default mode
    setMode('chat');
});