# AI to File - Home Assistant Add-on

![AI to File Screenshot](https://brands.home-assistant.io/_/homeassistant/icon.png)

A modern interface for chatting with AI models (ChatGPT/DeepSeek) and exporting conversations to files directly from Home Assistant.

## Features

- 🆓 Free tier support for ChatGPT and DeepSeek
- ⚙️ Configurable API endpoints (free/pro/custom)
- 📁 Multiple export options:
  - Copy to clipboard
  - Download as file
  - Save to Home Assistant
- 📱 Responsive design for desktop and mobile
- 🔄 Conversation history
- 🛡️ Secure API key storage

## Installation

1. Add this repository to your Home Assistant add-on store
2. Install the "AI to File" add-on
3. Configure your preferred default model and API settings
4. Start the add-on
5. Access the web UI from the add-on page or via `http://[HA_IP]:5000`

## Configuration

| Option | Description |
|--------|-------------|
| `port` | Web interface port (default: 5000) |
| `default_model` | Default AI model (chatgpt/deepseek) |
| `apis.chatgpt.type` | ChatGPT API type (free/pro/custom) |
| `apis.chatgpt.api_key` | ChatGPT API key (if using pro/custom) |
| `apis.deepseek.type` | DeepSeek API type (free/pro/custom) |
| `apis.deepseek.api_key` | DeepSeek API key (if using pro/custom) |

## Usage

1. Select your preferred AI model from the dropdown
2. Type your message in the input box
3. Receive response from the AI
4. Use the action buttons to:
   - 📋 Copy the conversation
   - ⬇️ Download as text file
   - 💾 Save to Home Assistant

## Support

For issues or feature requests, please [open an issue](https://github.com/ChristoffBo/ai_to_file/issues).

## License

MIT License
