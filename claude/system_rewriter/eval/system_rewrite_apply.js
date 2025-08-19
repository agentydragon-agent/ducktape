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
  // Ensure each placeholder appears exactly once
  const placeholders = ['${toolsBlob}','${envGitBlobs}','${modelLine}','${mcpSection}'];
  for (const ph of placeholders) {
    const count = (template.match(new RegExp(esc(ph), 'g')) || []).length;
    if (count !== 1) {
      console.error(`template placeholder ${ph} count=${count} (expected 1)`);
      process.exit(3);
    }
  }
  let out = template
    .replace('${toolsBlob}', toolsBlob)
    .replace('${envGitBlobs}', envGitBlobs.join(''))
    .replace('${modelLine}', modelLine)
    .replace('${mcpSection}', mcpSection);
  // Double-check placeholders no longer present
  for (const ph of placeholders) {
    if (out.includes(ph)) {
      console.error(`placeholder ${ph} still present after replacement`);
      process.exit(4);
    }
  }
  process.stdout.write(out);
})();
