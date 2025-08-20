#!/usr/bin/env node
const fs = require('fs');

const TOOLS_HEADER = process.env.TOOLS_HEADER || 'You can use the following tools without requiring user approval:';
const ENV_INTRO = 'Here is useful information about the environment you are running in:';
const MODEL_PREFIX = 'You are powered by the model';
const MCP_HEADER = '# MCP Server Instructions';

function esc(x){
  return x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function extractBlobs(s){
  const envGitBlobs = [];
  const envBlockRe = new RegExp(esc(ENV_INTRO) + '\\n<env>[\\s\\S]*?<\\/env>\\s*', 'g');
  let m;
  while ((m = envBlockRe.exec(s))) envGitBlobs.push(m[0]);

  const iTools = s.indexOf(TOOLS_HEADER);
  let toolsBlob = '';
  if (iTools !== -1){
    const after = iTools + TOOLS_HEADER.length;
    const nextEnv = s.indexOf(ENV_INTRO, after);
    const nextModel = s.indexOf(MODEL_PREFIX, after);
    const nextMcp = s.indexOf(MCP_HEADER, after);
    let end = s.length;
    if (nextEnv !== -1) end = Math.min(end, nextEnv);
    if (nextModel !== -1) end = Math.min(end, nextModel);
    if (nextMcp !== -1) end = Math.min(end, nextMcp);
    toolsBlob = s.slice(after, end);
  }

  const mm = s.match(new RegExp('^' + esc(MODEL_PREFIX) + '[^\n]*\n?', 'm'));
  const modelLine = mm ? mm[0] : '';

  let mcpSection = '';
  const iMcp = s.indexOf(MCP_HEADER);
  if (iMcp !== -1){
    const nl = s.indexOf('\n', iMcp);
    mcpSection = nl === -1 ? '' : s.slice(nl + 1);
  }

  return { toolsBlob, envGitBlobs, modelLine, mcpSection };
}

async function readAllStdin(){
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => data += chunk);
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

(async () => {
  const templatePath = process.argv[2];
  if (!templatePath) {
    console.error('usage: system_rewrite_apply.js <template-file> < input-system.txt > output-system.txt');
    process.exit(2);
  }
  const template = fs.readFileSync(templatePath, 'utf8');
  const sysIn = await readAllStdin();
  const { toolsBlob, envGitBlobs, modelLine, mcpSection } = extractBlobs(String(sysIn));
  const ctx = {
    toolsBlob,
    envGitBlobs: envGitBlobs.join(''),
    modelLine,
    mcpSection,
  };

  // Use mustache for optional sections/vars. Require at runtime; no fallback.
  let Mustache;
  try {
    Mustache = require('mustache');
  } catch (e) {
    console.error("Missing dependency 'mustache'. Please run: npm install mustache");
    process.exit(5);
  }

  // Optional: enforce each core var appears at most once to avoid accidental duplication
  const coreVars = ['toolsBlob','envGitBlobs','modelLine','mcpSection'];
  for (const name of coreVars) {
    const reVar = new RegExp(`\\{\\{${esc(name)}\\}\\}`, 'g');
    const count = (template.match(reVar) || []).length;
    if (count > 1) {
      console.error(`template variable ${name} appears ${count} times (expected ≤1)`);
      process.exit(6);
    }
  }

  let out = Mustache.render(template, ctx);

  // Legacy ${name} placeholders are not supported; use mustache {{name}} only

  // Validate no unreplaced tokens remain
  const leftover = out.match(/\{\{[#\/]?\w+}}/);
  if (leftover) {
    console.error(`template contains unreplaced tokens, e.g. '${leftover[0]}'`);
    process.exit(4);
  }

  process.stdout.write(out);
})();
