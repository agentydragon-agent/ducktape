---
description: Clean up temporary files, side outputs, and oneoff scripts
name: cleanup
---
<prompt version="1.0">
  <meta>
    <title>/cleanup - Intelligent Workspace Cleanup</title>
    <complexity level="medium" />
    <domain>workspace-management</domain>
    <tags>cleanup, organization, temporary-files, oneoff-scripts</tags>
  </meta>
  
  <goal>
    Your goal is to intelligently analyze and clean up the user's workspace by detecting ALL forms of disorder, temporary artifacts, and organizational issues - not just the specific patterns documented below.
    Use your judgment to propose custom cleanup solutions based on what you actually find in each unique situation.
  </goal>
  
  <context>
    <purpose>Intelligent cleanup of temporary work artifacts, focusing on oneoff scripts and exploration side-effects.</purpose>
    
    <guidelines>
      The patterns, examples, and workflows documented below are SUGGESTIONS and COMMON CASES, not an exhaustive list. You should:
      - Look beyond these examples to find any workspace disorder
      - Propose creative organizational solutions specific to what you discover
      - Adapt your cleanup approach to the user's actual workspace structure
      - Always ask for confirmation before taking destructive actions
    </guidelines>
  </context>

  <triggers>
    <trigger pattern="TEMP_FILES_CREATED">
      <action>Offer cleanup after task completion</action>
    </trigger>
    <trigger pattern="WORK_COMPLETE + oneoff__*">
      <action>Auto-suggest cleanup of temporary scripts</action>
    </trigger>
    <trigger pattern="MARKDOWN_SPRAWL(>5)">
      <action>Suggest consolidation into archive files</action>
    </trigger>
    <trigger pattern="USER_SAYS('cleanup'|'clean up'|'tidy')">
      <action>Execute full cleanup workflow</action>
    </trigger>
    <trigger pattern="DIR_CONTAINS(*.backup|*.old|*~)">
      <action>Flag for immediate deletion (no archive)</action>
    </trigger>
    <trigger pattern="EXPERIMENT_COMPLETE">
      <action>Archive valuable scripts, delete obvious junk</action>
    </trigger>
  </triggers>

  <usage>
    <basic-usage>
      Clean up the current directory:
      <code>/cleanup</code>
    </basic-usage>
    
    <natural-language>
      Or use naturally in conversation:
      
      <example positive>
        <u>cleanup the temp files</u>
        <a>I'll scan for temporary files and oneoff scripts to clean up.</a>
      </example>
      
      <example positive>
        <u>clean up my experiments</u>
        <a>Looking for experimental code and temporary outputs to remove.</a>
      </example>
      
      <example positive>
        <u>cleanup</u>
        <a>Starting cleanup scan for temporary artifacts.</a>
      </example>
    </natural-language>
  </usage>

  <workflow>
    <step id="scan">
      <title>Scan - Analyze directory for cleanup candidates</title>
      <tool-call>
        <glob pattern="**/oneoff__*" />
        <grep pattern="TEMPORARY|ONE-OFF|Can delete after" include="*.py" />
        <bash command="find . -type f -name '*.md' | head -20" />
      </tool-call>
    </step>
    
    <step id="present">
      <title>Present Plan - Show categorized list of what will be deleted</title>
    </step>
    
    <step id="confirm">
      <title>Request Confirmation - Ask for go-ahead before any deletion</title>
    </step>
    
    <step id="execute">
      <title>Execute - Only proceed after explicit approval</title>
      <tool-call>
        <bash command="rm -f oneoff__*.py" />
        <bash command="find . -name '__pycache__' -type d -exec rm -rf {} +" />
        <multiEdit file_path="./COMPLETED_WORK_2024-06-30.md" edits="[...]" />
      </tool-call>
    </step>
  </workflow>

  <cleanup-targets>
    <target id="oneoff-scripts" priority="1">
      <title>Oneoff Scripts</title>
      <pattern>oneoff__*.{py,js,ts,sh}</pattern>
      <ref href="#/patterns/oneoff-scripts"/>
      
      <example positive>
        <u>cleanup oneoffs</u>
        <a>
          Found 5 oneoff scripts:
          - oneoff__test_webhook_integration.py (2 days old)
          - oneoff__bulk_rename_vars.py (1 week old)
          - oneoff__debug_auth_flow.js (3 hours old)
          Would you like to delete all?
        </a>
      </example>
    </target>
    
    <target id="markdown-consolidation" priority="2">
      <title>Markdown Files Consolidation</title>
      <description>Claude tends to drop task outputs into multiple .md files. These get consolidated:</description>
      
      <category id="task-completion">
        <title>Task Completion Files (merge and archive)</title>
        <patterns>
          <pattern>CHANGES_SUMMARY.md - Completed changes</pattern>
          <pattern>CRITICAL_FIXES.md - Completed fixes</pattern>
          <pattern>*_COMPLETED.md, *_DONE.md patterns</pattern>
        </patterns>
      </category>
      
      <category id="ongoing-status">
        <title>Ongoing Status Files (update and keep)</title>
        <patterns>
          <pattern>TEST_SUMMARY.md - Current test status</pattern>
          <pattern>TODO.md - Active tasks</pattern>
          <pattern>STATUS.md - Project status</pattern>
        </patterns>
      </category>
      
      <category id="documentation">
        <title>Documentation (organize)</title>
        <patterns>
          <pattern>README.md - Main docs</pattern>
          <pattern>Technical docs (DOCKER_ISOLATION.md, etc.)</pattern>
        </patterns>
      </category>
      
      <example positive>
        <u>cleanup</u>
        <a>
          Found scattered markdown files:

          Task Outputs (4 files - can consolidate):
            📝 CHANGES_SUMMARY.md - Last updated 2 days ago
            📝 CRITICAL_FIXES.md - Contains 6 completed fixes
            📝 AUTHENTICATION_FIX.md - Single task output
            📝 JUPYTER_DEBUG_RESULTS.md - Debug session results
          
          Ongoing Status (2 files - update and keep):
            📋 TEST_SUMMARY.md - 3 failing tests remain
            📋 TODO.md - 12 open tasks
          
          Documentation (3 files - organize):
            📚 README.md - Main documentation
            📚 DOCKER_ISOLATION.md - Technical guide
            📚 SIGNAL_HANDLING.md - Implementation details
          
          I can:
          1. Prune task outputs into what's worth keeping and
             consolidate into progress docs / documentation
          2. Update status files to reflect current state
          3. Organize docs into docs/ directory
          
          Proceed?
        </a>
      </example>
    </target>
    
    <target id="temporary-outputs" priority="3">
      <title>Temporary Outputs</title>
      <patterns>
        <pattern>Test outputs: test-output-*, *-test-results.*</pattern>
        <pattern>Debug logs: debug-*.log, *.debug, trace-*</pattern>
        <pattern>Temporary data: *.tmp, *.temp, temp-*, tmp-*</pattern>
        <pattern>Process artifacts: *.pid, *.lock (except INSTANCE_LOCK.md)</pattern>
        <pattern>Cache files: *.cache, .cache/ (if not gitignored)</pattern>
      </patterns>
    </target>
    
    <target id="exploration-artifacts" priority="3">
      <title>Exploration Artifacts</title>
      <patterns>
        <pattern>Quick analysis: analysis-*.txt, output-*.json</pattern>
        <pattern>Extracted data: extracted-*.{json,txt,csv}</pattern>
        <pattern>Download remnants: download-*, snapshot-*.json.backup</pattern>
        <pattern>Screenshot captures: /tmp/tana-captures/ (older than 1 day)</pattern>
      </patterns>
    </target>
    
    <target id="failed-attempts" priority="4">
      <title>Failed Attempts</title>
      <patterns>
        <pattern>Backup files: *.backup, *.old, *~</pattern>
        <pattern>Version sprawl: *-v2, *-final, *-FINAL-FINAL</pattern>
        <pattern>Partial outputs: *.partial, *.incomplete</pattern>
      </patterns>
    </target>
    
    <target id="build-artifacts" priority="5">
      <title>Build Artifacts in Wrong Places</title>
      <patterns>
        <pattern>Node modules outside project: ./node_modules/ in scripts/</pattern>
        <pattern>Python caches: __pycache__/, *.pyc outside venv</pattern>
        <pattern>TypeScript outputs: *.js files with corresponding *.ts</pattern>
      </patterns>
    </target>
  </cleanup-targets>

  <safety-features>
    <always-protected>
      <item>Git worktrees (use `git worktree remove`)</item>
      <item>Active lock files (INSTANCE_LOCK.md with recent timestamp)</item>
      <item>Config files (even if named `.tmp`)</item>
      <item>Anything in `.git/`</item>
      <item>Files modified in last hour (unless explicitly requested)</item>
    </always-protected>
    
    <smart-detection>
      <description>The cleanup command uses various tools to scan for artifacts:</description>
      
      <tool-examples>
        <tool-call>
          <glob pattern="**/oneoff__*" />
          <glob pattern="**/*.backup" />
          <glob pattern="**/*.old" />
          <glob pattern="**/temp-*" />
        </tool-call>
        
        <tool-call>
          <bash command="find . -name '__pycache__' -type d" />
          <bash command="find . -name '*.pyc' -o -name '*.pyo'" />
          <bash command="find . -name '*.tmp' -mtime +1" />
        </tool-call>
        
        <tool-call>
          <ls path="./archive" ignore="['.git']" />
          <ls path="../.archive" ignore="['.git']" />
        </tool-call>
      </tool-examples>
      
      <example positive>
        <u>cleanup</u>
        <a>Cleanup scan found:

CLEANUP PLAN:

1. FILES TO DELETE:
Obvious Junk:
  🗑️ execute_with_async_orchestration.py.backup - Backup file (2 days old)
  🗑️ debug_jupyter_output.py - Temporary debug script
  🗑️ test_launch.sh - Simple test launcher
  🗑️ old_files/ - Contains obsolete implementations (7 files)
  🗑️ __pycache__/ - Python bytecode cache

Oneoff Scripts (5 files, 12KB):
  🗑️ oneoff__test_webhook_integration.py - "Can delete after: Integration tests added" (3 days old)
  🗑️ oneoff__bulk_rename_vars.sh - "Can delete after: Rename complete" (1 week old)
  
2. MARKDOWN CONSOLIDATION:
Task Outputs (will merge → COMPLETED_WORK_2024-06-30.md):
  📝 CHANGES_SUMMARY.md - Directory fixes and output formatting
  📝 CRITICAL_FIXES.md - 6 critical bug fixes
  📝 AUTHENTICATION_FIX.md - OAuth implementation notes
  📝 orchestrator_failure_analysis.md - Old debugging notes

Status Files (will update):
  📋 TEST_SUMMARY.md - Update to current test status
  📋 TODO.md - Remove completed items, organize remaining

Documentation (will organize):
  📚 Move DOCKER_ISOLATION.md → docs/
  📚 Move SIGNAL_HANDLING.md → docs/
  📚 Keep README.md in root

3. POTENTIALLY USEFUL (suggest archiving):
  📁 mcp_archive/ - Old MCP experiments
  📁 visualize_run.py - Run visualization tool

Ready to proceed? This will:
- Delete 12 files (156KB)
- Consolidate 4 task outputs → 1 archive file
- Update 2 status files
- Organize 2 docs into docs/ folder</a>
      </example>
    </smart-detection>
    
    <natural-language-interaction>
      <description>The cleanup command presents a plan and waits for the user's specific instructions. The user might say things like:</description>
      <responses>
        <response>"go ahead"</response>
        <response>"just the junk files, leave the markdown alone for now"</response>
        <response>"archive the mcp stuff but delete everything else"</response>
        <response>"consolidate the markdown but keep CHANGES_SUMMARY separate"</response>
        <response>"wait, show me what's in old_files first"</response>
      </responses>
      <note>The assistant will follow your specific instructions rather than offering rigid options.</note>
    </natural-language-interaction>
  </safety-features>

  <natural-language-triggers>
    <description>Nonexhaustive examples of recognized phrases:</description>
    <phrases>
      <phrase>"cleanup", "clean up", "clean"</phrase>
      <phrase>"remove temp files", "delete temporary"</phrase>
      <phrase>"cleanup oneoffs", "remove oneoff scripts"</phrase>
      <phrase>"tidy up", "clean workspace"</phrase>
    </phrases>
  </natural-language-triggers>

  <common-mistakes>
    <example negative>
      <u>cleanup</u>
      <a>Cleanup complete! Removed:
- oneoff__test_api.py
- debug.log

All clean!</a>
      <reasoning>❌ Bad: Missed obvious temp files like __pycache__/, *.pyc, test-output-*.json, temp directories</reasoning>
    </example>
    
    <example negative>
      <u>cleanup my experiments</u>
      <a>Deleted experimental files:
- experiment1.py
- experiment2.py
- experiment3.py

Done!</a>
      <reasoning>❌ Bad: Didn't find oneoff__ scripts, missed experiment-data.json, left behind experiment.log</reasoning>
    </example>
    
    <example negative>
      <u>cleanup the old markdown docs</u>
      <a>Cleaned up old documentation:
- Deleted OLD_API_NOTES.md
- Deleted DEPRECATED_GUIDE.md

Workspace is cleaner now!</a>
      <reasoning>❌ Bad: Ignored CHANGES_SUMMARY.md, CRITICAL_FIXES_DONE.md, TODO_COMPLETED.md - should consolidate not just delete some</reasoning>
    </example>
  </common-mistakes>

  <examples>
    <example positive>
      <u>I've been experimenting a lot, cleanup</u>
      <a>I'll scan for experimental artifacts and scattered documentation.

CLEANUP PLAN:

1. FILES TO DELETE:
Oneoff Scripts (8 files, 45KB):
  🗑️ oneoff__test_api.py (3 days old)
  🗑️ oneoff__bulk_rename.py (1 week old)
  ... and 6 more

Temporary Files (45 files, 234MB):
  🗑️ debug-*.log (23 files)
  🗑️ test-output-*.json (15 files)
  🗑️ workspace snapshots (3 files, 189MB)

2. MARKDOWN CONSOLIDATION:
Task Outputs (6 files → COMPLETED_WORK_2024-06-30.md):
  📝 API_INTEGRATION.md
  📝 REFACTOR_COMPLETE.md
  📝 BUG_FIXES_JAN.md
  ... and 3 more

Status Files (will update):
  📋 TODO.md - 45 items (28 completed will be removed)
  📋 PROJECT_STATUS.md - Last updated 1 week ago

3. DOCUMENTATION (organize):
  📚 API_GUIDE.md → docs/
  📚 DEPLOYMENT.md → docs/
  📚 ARCHITECTURE.md → docs/

Total: 289MB to clean, 6 files to consolidate, 3 docs to organize

Proceed?</a>
      
      <u>just cleanup the oneoffs from last week</u>
      <a>Found 3 oneoff scripts older than 7 days:
   - oneoff__migrate_data.py (10 days)
   - oneoff__test_old_api.py (8 days)  
   - oneoff__benchmark_v1.py (14 days)
   
   I'll delete these 3 files.</a>
    </example>
    
    <example positive>
      <u>cleanup but focus on the markdown files</u>
      <a>
        Focusing on markdown consolidation:

        MARKDOWN CLEANUP PLAN:
        
        1. COMPLETED TASKS (merge → COMPLETED_WORK_2024-06-30.md):
           📝 CHANGES_SUMMARY.md - Working directory fixes
           📝 CRITICAL_FIXES.md - 6 bug fixes documented
           📝 OAUTH_IMPLEMENTATION.md - Completed auth work
           📝 DEBUG_SESSION_NOTES.md - Old debugging session
        
        2. ACTIVE STATUS (update &amp; keep):
           📋 TEST_SUMMARY.md:
              - Currently shows 6 failing tests (3 are now passing)
              - Will update to reflect current state
           📋 TODO.md:
              - Has 23 items (15 are completed)
              - Will remove completed, reorganize remaining
        
        3. DOCUMENTATION (organize into docs/):
           📚 DOCKER_ISOLATION.md - Technical guide
           📚 SIGNAL_HANDLING.md - Implementation details
           📚 Keep README.md in root
        
        This will:
        - Consolidate 4 completed task files → 1 archive
        - Update 2 status files to current state
        - Organize 2 technical docs into docs/ folder
        - Preserve all content while reducing clutter
        
        Proceed?
      </a>
    </example>
  </examples>

  <archive-detection>
    <description>Archive is offered selectively based on file value:</description>
    
    <auto-delete>
      <title>Auto-Delete (no archive offered)</title>
      <patterns>
        <pattern>.backup, .old, ~ files</pattern>
        <pattern>__pycache__/ directories</pattern>
        <pattern>Clearly obsolete documentation</pattern>
        <pattern>Hopelessly broken code</pattern>
        <pattern>Empty directories</pattern>
        <pattern>Files with "DELETE", "OBSOLETE", "OLD" in name</pattern>
      </patterns>
    </auto-delete>
    
    <archive-suggested>
      <title>Archive Suggested For</title>
      <patterns>
        <pattern>Analysis/visualization scripts that took effort</pattern>
        <pattern>Experimental code with potential reference value</pattern>
        <pattern>Data files that might be needed later</pattern>
        <pattern>Scripts with substantial logic</pattern>
      </patterns>
    </archive-suggested>
    
    <archive-directories>
      <description>The cleanup command automatically detects nearby archive directories:</description>
      <locations>
        <location>./archive/</location>
        <location>./archives/</location>
        <location>./old/</location>
        <location>./experiments/archive/</location>
        <location>../.archive/ (parent directory)</location>
      </locations>
    </archive-directories>
    
    <example positive>
      <u>cleanup</u>
      <a>Found archive directory at ./archive/experiments/
   
   📝 Oneoff Scripts (3 files):
   - oneoff__test_integration.py
   - oneoff__bulk_process.py
   
   Would you like to archive these files or delete them permanently?</a>
      
      <u>archive</u>
      <a>Moving to archive:
   <tool-call>
     <bash command="mkdir -p ./archive/experiments/2024-01-20" />
     <bash command="mv oneoff__test_integration.py ./archive/experiments/2024-01-20/" />
     <bash command="mv oneoff__bulk_process.py ./archive/experiments/2024-01-20/" />
     <bash command="echo '[2024-01-20 14:32] Archived 2 oneoff scripts' >> cleanup-archive.log" />
   </tool-call>
   
   ✓ oneoff__test_integration.py → ./archive/experiments/2024-01-20/
   ✓ oneoff__bulk_process.py → ./archive/experiments/2024-01-20/
   
   Archived 2 files. Archive location saved to cleanup-archive.log</a>
    </example>
  </archive-detection>

  <decision-criteria>
    <delete-vs-archive>
      <title>Delete vs Archive Decision Tree</title>
      <rules>
        <rule>Has the file been referenced in commits? → Archive</rule>
        <rule>Contains non-trivial logic (>50 lines)? → Archive</rule>
        <rule>Older than 2 weeks with no references? → Delete</rule>
        <rule>Clearly broken/dangerous code? → Delete</rule>
        <rule>Backup/old/~ files? → Delete</rule>
        <rule>Cache files (__pycache__, .cache)? → Delete</rule>
      </rules>
    </delete-vs-archive>
    
    <rationale>
      <title>Why These Patterns?</title>
      <reasons>
        <reason>**oneoff__ prefix**: Makes temporary scripts immediately identifiable during cleanup</reason>
        <reason>**Consolidating markdown**: Reduces clutter while preserving information and history</reason>
        <reason>**Archive before delete**: Experiments often contain valuable learnings discovered later</reason>
        <reason>**Natural language interaction**: Respects user preferences instead of rigid options</reason>
        <reason>**Safety checks**: Prevents accidental deletion of important files</reason>
      </reasons>
    </rationale>
  </decision-criteria>

  <best-practices>
    <practice>Archive vs delete - Use archives for experiments that might be referenced later</practice>
    <practice>Date-based subdirs - Archives are organized by date automatically</practice>
    <practice>Archive log - Creates `cleanup-archive.log` tracking what was archived when</practice>
  </best-practices>

  <integration>
    <description>Integration with other patterns:</description>
    <integrations>
      <integration>Works with <ref href="#/patterns/oneoff-scripts"/> marking pattern</integration>
      <integration>Respects <ref href="#/workspace/messy-detection"/> detection</integration>
      <integration>Follows <ref href="#/data/no-data-loss"/> principle - asks before deleting</integration>
      <integration>Compatible with version control - suggests `git rm` for tracked files</integration>
      <integration>Auto-triggered by WORK_COMPLETE trigger when temp files were used</integration>
    </integrations>
  </integration>

  <automatic-trigger>
    <description>When completing work that used temporary files or oneoff scripts:</description>
    
    <example positive>
      <u>test the webhook integration</u>
      <a>
        I'll create a oneoff script to test the webhook...
        [creates oneoff__test_webhook.py]
        [runs tests]
        ✅ Webhook integration working correctly!
        
        🧹 I left behind some temporary test files. Should I clean them up?
        - oneoff__test_webhook.py
        - webhook-test-output.json
        
        Ready to clean up?
      </a>
    </example>
    
    <example positive>
      <u>cleanup</u>
      <a>
        Removing temporary work files:
        ✓ Deleted oneoff__test_webhook.py
        ✓ Deleted webhook-test-output.json</a>
    </example>
  </automatic-trigger>

  <notes>
    <note>Never auto-deletes without confirmation</note>
    <note>Shows file ages and sizes for context</note>
    <note>Groups similar items for easier decisions</note>
    <note>Suggests adding patterns to `.gitignore`</note>
    <note>Can be undone with git if needed (for tracked files)</note>
  </notes>
</prompt>
