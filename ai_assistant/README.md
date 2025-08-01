AI Assistant Home Assistant Add-on

A simple AI assistant with text export capabilities.

SETUP:
1. Add this repository to Home Assistant
2. Install the "AI Assistant" add-on
3. Set your API keys in Configuration
4. Start the add-on

USAGE:
- Access via: http://[HA_IP]:5000
- Or through Home Assistant sidebar
- Type messages and click Send
- Use Export buttons to save responses

REQUIREMENTS:
- Home Assistant 2023.12+
- OpenAI or DeepSeek API key
- (Optional) GitHub token for cloud saving

TROUBLESHOOTING:
If you get "Bad Gateway":
1. Wait 1 minute after startup
2. Check add-on logs
3. Rebuild the add-on

For export issues:
- Verify GitHub token has repo access
- Check filename doesn't contain special chars