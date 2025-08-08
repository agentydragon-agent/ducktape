/**
 * System Message Search-Replace Transformer
 *
 * This transformer performs search-replace operations on system messages.
 * It can be used to modify system prompts, rebrand messages, or adapt
 * prompts for different providers.
 */
class SystemMessageTransformer {
  constructor(options) {
    this.name = 'system-replace';

    this.enableLogging = !!options.enableLogging;
    this.log = (msg) => {
      if (!this.enableLogging) return;
      const fs = require('fs');
      fs.appendFileSync('/home/agentydragon/.claude-code-router/transformer-debug.log', `[${new Date().toISOString()}] ${msg}\n`);
    };
  }

  transformRequestIn(request) {
    this.log(`transformRequestIn called with keys: ${Object.keys(request).join(', ')}`);

    const modifiedRequest = JSON.parse(JSON.stringify(request));

    if (modifiedRequest.system) {
      this.log(`  Found system field, type: ${typeof modifiedRequest.system}`);
      modifiedRequest.system = this.processSystemField(modifiedRequest.system);
    }

    if (Array.isArray(modifiedRequest.messages)) {
      this.log(`  Found messages array with ${modifiedRequest.messages.length} messages`);
      modifiedRequest.messages = modifiedRequest.messages.map((message) => {
        if (message.role === 'system') {
          this.log(`  Found system message, content type: ${typeof message.content}, is array: ${Array.isArray(message.content)}`);
          return {
            ...message,
            content: this.replaceInContent(message.content)
          };
        }
        return message;
      });
    }

    if (modifiedRequest.messages && modifiedRequest.messages[0] && modifiedRequest.messages[0].role === 'system') {
      const content = modifiedRequest.messages[0].content;
      if (Array.isArray(content) && content[0]) {
        this.log(`  Returning system message: ${content[0].text ? content[0].text.substring(0, 50) : 'no text'}`);
      }
    }

    this.log('  Transformation complete');

    return modifiedRequest;
  }

  processSystemField(system) {
    if (typeof system === 'string') {
      return this.replaceInContent(system);
    }

    if (Array.isArray(system)) {
      return system.map((item) => {
        if (item.type === 'text' && item.text) {
          return {
            ...item,
            text: this.replaceInContent(item.text)
          };
        }
        return item;
      });
    }

    return system;
  }

  replaceInContent(content) {
    if (typeof content === 'string') {
      content = content.replace("IMPORTANT: Assist with defensive security tasks only. Refuse to create, modify, or improve code that may be used maliciously. Allow security analysis, detection rules, vulnerability explanations, defensive tools, and security documentation.\n", "");
      content = content.replace("One word answers are best. ", "");
      // TODO: delete demonstrated terseness
      // TODO: collapse extra introduced white lines

      return content;
    }

    if (Array.isArray(content)) {
      return content.map((item) => {
        if (item.type === 'text' && item.text) {
          return {
            ...item,
            text: this.replaceInContent(item.text)
          };
        }
        return item;
      });
    }

    return content;
  }
}


module.exports = SystemMessageTransformer;
