"use strict";

function esc(x) {
  return x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function extractSystemSections(body) {
  const out = [];
  if (!body || typeof body !== 'object') return out;
  if (body.system) {
    const sys = body.system;
    if (typeof sys === 'string') out.push(sys);
    else if (Array.isArray(sys)) {
      for (const it of sys) if (it && it.type === 'text' && typeof it.text === 'string') out.push(it.text);
    }
  }
  if (Array.isArray(body.messages)) {
    for (const m of body.messages) {
      if (m && m.role === 'system') {
        const c = m.content;
        if (typeof c === 'string') out.push(c);
        else if (Array.isArray(c)) {
          for (const it of c) if (it && it.type === 'text' && typeof it.text === 'string') out.push(it.text);
        }
      }
    }
  }
  return out;
}

function mapSystemContent(content, fn) {
  if (typeof content === 'string') return fn(content);
  if (Array.isArray(content)) {
    return content.map((item) => {
      if (item && item.type === 'text' && typeof item.text === 'string') return { ...item, text: fn(item.text) };
      return item;
    });
  }
  return content;
}

/**
 * Extract core system blobs used by both the router plugin and CLI rewriter.
 * @param {string} s - full system string
 * @param {{toolsHeader?: string}} [opts]
 * @returns {{toolsBlob: string, envGitBlobs: string[], modelLine: string, mcpSection: string}}
 */
function extractSystemBlobs(s, opts) {
  if (typeof s !== 'string') return { toolsBlob: '', envGitBlobs: [], modelLine: '', mcpSection: '' };
  const toolsHeader = (opts && opts.toolsHeader) || process.env.TOOLS_HEADER || 'You can use the following tools without requiring user approval:';
  if (!s.includes(toolsHeader)) return { toolsBlob: '', envGitBlobs: [], modelLine: '', mcpSection: '' };

  const envIntro = 'Here is useful information about the environment you are running in:';
  const modelPrefix = 'You are powered by the model';
  const mcpHeader = '# MCP Server Instructions';

  const envGitBlobs = [];
  const envBlockRe = new RegExp(esc(envIntro) + '\n<env>[\\s\\S]*?<\\/env>\\s*', 'g');
  let m;
  while ((m = envBlockRe.exec(s))) envGitBlobs.push(m[0]);

  const iTools = s.indexOf(toolsHeader);
  let toolsBlob = '';
  if (iTools !== -1) {
    const after = iTools + toolsHeader.length;
    const nextEnv = s.indexOf(envIntro, after);
    const nextModel = s.indexOf(modelPrefix, after);
    const nextMcp = s.indexOf(mcpHeader, after);
    let end = s.length;
    if (nextEnv !== -1) end = Math.min(end, nextEnv);
    if (nextModel !== -1) end = Math.min(end, nextModel);
    if (nextMcp !== -1) end = Math.min(end, nextMcp);
    toolsBlob = s.slice(after, end);
  }

  const mm = s.match(new RegExp('^' + esc(modelPrefix) + "[^\n]*\n?", 'm'));
  const modelLine = mm ? mm[0] : '';

  let mcpSection = '';
  const iMcp = s.indexOf(mcpHeader);
  if (iMcp !== -1) {
    const nl = s.indexOf('\n', iMcp);
    mcpSection = nl === -1 ? '' : s.slice(nl + 1);
  }

  return { toolsBlob, envGitBlobs, modelLine, mcpSection };
}

module.exports = { extractSystemSections, mapSystemContent, extractSystemBlobs };
