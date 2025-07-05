<prompt version="1.0">
  <meta>
    <title>Claude Prompt XML Schema</title>
    <domain>meta</domain>
    <tags>xml, schema, documentation, meta-prompting</tags>
  </meta>
  
  <context>
    <purpose>An HTML5-style XML schema for structuring prompts, instructions, and rules for Claude.</purpose>
    <note>This document follows its own schema format, demonstrating full self-reference.</note>
  </context>
  
  <instructions>
    <section id="overview">
      <title>Overview</title>
      <content>
        This schema provides a structured way to write prompts, rules, and documentation for Claude.
        It uses HTML5-style XML with clear patterns for examples, conversations, and tool usage.
      </content>
    </section>
    
    <section id="core-structure">
      <title>Core Structure</title>
      <examples>
        <example positive title="Basic prompt structure">
          <code><![CDATA[
            <prompt version="1.0">
              <meta>
                <title>Task title</title>
                <complexity level="low|medium|high" />
                <domain>coding|analysis|creative|general</domain>
                <tags>tag1, tag2, tag3</tags>
              </meta>
              
              <context>
                <!-- Background and setup -->
              </context>
              
              <instructions>
                <!-- Main task description -->
              </instructions>
              
              <examples>
                <example positive>
                  <!-- Good example -->
                </example>
                <example negative>
                  <!-- Bad example -->
                </example>
              </examples>
              
              <output>
                <section required>Section name</section>
                <section optional>Optional section</section>
              </output>
            </prompt>
          ]]></code>
        </example>
      </examples>
    </section>
    
    <section id="conversation-schema">
      <title>Conversation Schema</title>
      <examples>
        <example positive title="Unified conversation format">
          <code><![CDATA[
            <conversation>
              <u>How do I authenticate?</u>
              
              <a>I'll help you set up authentication. Let me first check your current auth configuration.
              
              <tool-call>
                <read path="src/auth/config.py" />
              </tool-call>
              </a>
              
              <t>
              File contents:
              AUTH_METHOD = "oauth2"
              TOKEN_EXPIRY = 3600
              </t>
              
              <a>I see you're using OAuth2. Let me show you how to implement it properly.
              
              <tool-call>
                <write path="src/auth/oauth_handler.py">
                  <content>
                  from authlib import OAuth2Session
                  # ... implementation
                  </content>
                </write>
              </tool-call>
              </a>
            </conversation>
          ]]></code>
        </example>
        
        <example positive title="Alternative: message tags with from attribute">
          <code><![CDATA[
            <conversation>
              <message from="user">How do I authenticate?</message>
              <message from="assistant">I'll help you set up authentication.</message>
              <message from="tool">File not found: src/auth/config.py</message>
              <message from="assistant">Let me create the auth config for you.</message>
            </conversation>
          ]]></code>
        </example>
      </examples>
      <note>
        Prefer <![CDATA[<u>/<a>/<t>]]> for conciseness. Use <![CDATA[<message from="">]]> when you need additional attributes or metadata.
      </note>
    </section>
    
    <section id="tool-calls">
      <title>Tool Call Schema</title>
      <note>For single tool calls, the <![CDATA[<tool-call>]]> envelope can be omitted for brevity.</note>
      <examples>
        <example positive>
          <title>Single tool call (no envelope needed)</title>
          <code language="xml"><![CDATA[
            <bash command="git status" />
            
            <read path="/src/main.py" />
            
            <mcp server="memory" tool="search_nodes">
              <params>{"query": "authentication patterns"}</params>
            </mcp>
          ]]></code>
        </example>
        
        <example positive>
          <title>Multiple tools (envelope required)</title>
          <code language="xml"><![CDATA[
            <tool-call>
              <read path="/src/main.py" />
              <write path="/src/config.py" content="..." />
              <grep pattern="TODO" path="/src" />
              <bash command="git status" />
              <glob pattern="**/*.py" />
            </tool-call>
          ]]></code>
        </example>
        
        <example positive>
          <title>MCP tools with full structure</title>
          <code language="xml"><![CDATA[
            <tool-call>
              <mcp server="brave-search" tool="brave_web_search">
                <params>
                  {
                    "query": "Python type hints best practices",
                    "count": 10
                  }
                </params>
              </mcp>
            </tool-call>
          ]]></code>
        </example>
        
        <example positive>
          <title>Task spawning</title>
          <code language="xml"><![CDATA[
            <tool-call>
              <task description="Analyze auth flow">
                Search for all authentication-related code and create
                a comprehensive diagram of the authentication flow.
              </task>
            </tool-call>
          ]]></code>
        </example>
      </examples>
    </section>
    
    <section id="example-patterns">
      <title>Example Patterns</title>
      <examples>
        <example positive>
          <title>Good/Bad comparison pattern</title>
          <code language="xml"><![CDATA[
            <examples>
              <example negative>
                <code language="python">
                # Bad: Silent failure
                try:
                    auth.login()
                except:
                    pass
                </code>
              </example>
              
              <example positive>
                <code language="python">
                # Good: Explicit error handling
                try:
                    auth.login()
                except AuthError as e:
                    logger.error(f"Authentication failed: {e}")
                    raise
                </code>
              </example>
            </examples>
          ]]></code>
        </example>
        
        <example positive>
          <title>Prefix/Completion pattern</title>
          <code language="xml"><![CDATA[
            <example type="completion">
              <prefix>
                <code language="python">
                def validate_token(token: str) ->
                </code>
              </prefix>
              
              <completion bad>
                <code language="python">
                def validate_token(token: str) -> Any:
                    # Returns whatever
                </code>
              </completion>
              
              <completion good>
                <code language="python">
                def validate_token(token: str) -> bool:
                    """Validate token format and expiry."""
                    return token.startswith("ey") and not is_expired(token)
                </code>
              </completion>
            </example>
          ]]></code>
        </example>
      </examples>
    </section>
    
    <section id="inline-marking">
      <title>Marking Good/Bad Inline</title>
      <examples>
        <example positive>
          <title>Inline highlighting of specific behaviors</title>
          <code language="xml"><![CDATA[
            <instructions>
              When handling errors, <bad>never use bare except</bad>.
              Instead, <good>catch specific exceptions</good>.
            </instructions>

            <conversation>
              <u>My tests are failing with some error</u>
              <a>I'll check what's happening. Let me <good why="gather specific error info">run the tests with verbose output</good>.
              
              <tool-call>
                <bash command="pytest -xvs" />
              </tool-call>
              </a>
            </conversation>

            <code language="python">
            try:
                process()
            except:  # <bad>Silent failure - hides all errors</bad>
                pass

            try:
                process()
            except ProcessError as e:  # <good>Specific exception handling</good>
                logger.error(f"Process failed: {e}")
                raise
            </code>
          ]]></code>
        </example>
        
        <example positive>
          <title>Good/bad with reasoning attributes</title>
          <code language="xml"><![CDATA[
            <a>I found the issue. Instead of <bad why="loses error context">suppressing the error</bad>, 
            I'll <good why="preserves stack trace">re-raise with additional context</good>:

            <tool-call>
              <edit path="src/auth.py">
                <old>except: pass</old>
                <new>except AuthError as e:
                    logger.error(f"Auth failed for user {user_id}: {e}")
                    raise</new>
              </edit>
            </tool-call>
            </a>
          ]]></code>
        </example>
      </examples>
    </section>
    
    <section id="conditionals">
      <title>Conditional Patterns</title>
      <examples>
        <example positive>
          <title>Trigger patterns with <![CDATA[<if>/<then>]]></title>
          <code language="xml"><![CDATA[
            <triggers>
              <ul>
                <li><if>ERROR(pattern)</if><then>action</then></li>
                <li><if>REPEAT(3)</if><then>automate</then></li>
                <li><if>STUCK</if><then>search_learnings</then></li>
                <li><if>FILE_COUNT(>20)</if><then>use_glob</then></li>
              </ul>
            </triggers>
          ]]></code>
        </example>
        
        <example positive>
          <title>Decision logic with <![CDATA[<if>/<then>/<elif>]]></title>
          <code language="xml"><![CDATA[
            <decision>
              <if>search returns >100 results</if>
              <then>narrow with more specific pattern</then>
              <elif>search returns 0 results</elif>
              <then>broaden pattern or check file extensions</then>
              <elif>pattern has special chars</elif>
              <then>escape for regex</then>
            </decision>
          ]]></code>
        </example>
      </examples>
    </section>
    
    <section id="lists">
      <title>Ordered and Unordered Lists</title>
      <examples>
        <example positive>
          <title>Use <![CDATA[<ol>]]> for ordered steps</title>
          <code language="xml"><![CDATA[
            <action>
              <ol>
                <li>Check if file exists</li>
                <li>Warn if overwriting</li>
                <li>Create with explicit content</li>
              </ol>
            </action>
          ]]></code>
        </example>
        
        <example positive>
          <title>Use <![CDATA[<ul>]]> for unordered lists</title>
          <code language="xml"><![CDATA[
            <requirements>
              <ul>
                <li>Python 3.10+</li>
                <li>Git repository initialized</li>
                <li>Valid authentication token</li>
              </ul>
            </requirements>
          ]]></code>
        </example>
      </examples>
    </section>
    
    <section id="hierarchical-rules">
      <title>Hierarchical Rules</title>
      <examples>
        <example positive>
          <title>Nested rule organization</title>
          <code language="xml"><![CDATA[
            <rules>
              <rule id="/code">
                <title>General Programming Rules</title>
                
                <rule id="/code/quality">
                  <title>Code Quality</title>
                  <content>Always prioritize readability</content>
                  
                  <rule id="/code/quality/no-disable-checks">
                    <title>Never Disable Quality Checks</title>
                    <content>No # type: ignore, # noqa, etc.</content>
                  </rule>
                </rule>
                
                <rule id="/code/python">
                  <title>Python-Specific Rules</title>
                  
                  <rule id="/code/python/types">
                    <title>Type Annotations</title>
                    
                    <rule id="/code/python/types/new-style-optional">
                      <title>Use New Style Optional Syntax</title>
                      <content>
                        <bad>Optional[str]</bad>
                        <good>str | None</good>
                      </content>
                    </rule>
                    
                    <rule id="/code/python/types/no-any">
                      <title>Avoid Any Type</title>
                      <content>Use specific types instead of Any</content>
                    </rule>
                  </rule>
                </rule>
              </rule>
            </rules>
          ]]></code>
        </example>
        
        <example positive>
          <title>Referencing hierarchical rules</title>
          <code language="xml"><![CDATA[
            Follow <ref href="#/code/python/types/new-style-optional" />
            See <a href="#/code/quality">code quality rules</a>
          ]]></code>
        </example>
      </examples>
    </section>
    
    <section id="interlinking">
      <title>Interlinking</title>
      <examples>
        <example positive>
          <title>Defining anchors for cross-referencing</title>
          <code language="xml"><![CDATA[
            <!-- Define anchors -->
            <section id="auth-pattern">
              <title>Authentication Pattern</title>
              <content>...</content>
            </section>

            <function id="validate-inputs">
              <code language="python">
              def validate_inputs(username: str, password: str) -> bool:
                  return username and len(password) >= 8
              </code>
            </function>

            <rule id="no-type-ignore">
              <title>Never Use Type Ignore</title>
              <content>...</content>
            </rule>
          ]]></code>
        </example>
        
        <example positive>
          <title>Using references</title>
          <code language="xml"><![CDATA[
            <instructions>
              Follow the <a href="#auth-pattern">authentication pattern</a>.
              When implementing login, <call href="#validate-inputs" /> first.
              Remember: <ref href="#no-type-ignore" />
            </instructions>

            <!-- Hierarchical references -->
            Apply all <ref href="#/code/python/types" /> rules
            Specifically <ref href="#/code/python/types/new-style-optional" />
          ]]></code>
        </example>
      </examples>
    </section>
    
    <section id="aliases">
      <title>Tag Aliases for Compression</title>
      <content>
        Define shorter aliases for frequently used tags to reduce file size while maintaining readability.
        Aliases are processed as equivalent to their full forms.
      </content>
      <examples>
        <example positive>
          <title>Defining aliases</title>
          <code language="xml"><![CDATA[
            <aliases>
              <alias from="example" to="ex" />
              <alias from="trigger" to="trig" />
              <alias from="pattern" to="pat" />
              <alias from="section" to="sec" />
              <alias from="critical" to="crit" />
              <alias from="negative" to="n" />
              <alias from="positive" to="p" />
            </aliases>
          ]]></code>
        </example>
        
        <example positive>
          <title>Using aliases</title>
          <code language="xml"><![CDATA[
            <!-- Instead of -->
            <example negative>
              <description>Bad approach</description>
            </example>
            
            <!-- Use -->
            <ex n>
              <desc>Bad approach</desc>
            </ex>
            
            <!-- Or even more compressed -->
            <ex n>Bad approach</ex>
          ]]></code>
        </example>
        
        <example positive>
          <title>Compressed triggers with aliases</title>
          <code language="xml"><![CDATA[
            <!-- Long form -->
            <triggers>
              <trigger>
                <if>ERROR</if>
                <then>stop+read_full+trace</then>
              </trigger>
            </triggers>
            
            <!-- Compressed with aliases -->
            <triggers>
              <trig>ERROR→stop+read_full+trace</trig>
            </triggers>
          ]]></code>
        </example>
      </examples>
      <note>
        Aliases are especially useful for large configuration files where the same tags appear hundreds of times.
        Define aliases early in the document for maximum benefit.
      </note>
    </section>
    
    <section id="special-tags">
      <title>Special Tags</title>
      <examples>
        <example positive>
          <title>Quality marking tags</title>
          <code language="xml"><![CDATA[
            <good>Correct approach</good>
            <bad>Wrong approach</bad>
            <deprecated>Old pattern - do not use</deprecated>
            <critical>Must follow - no exceptions</critical>
            <optional>Nice to have</optional>
          ]]></code>
        </example>
        
        <example positive>
          <title>Semantic markers</title>
          <code language="xml"><![CDATA[
            <warn>Important warning</warn>
            <note>Additional context</note>
            <tip>Helpful suggestion</tip>
            <todo>Future improvement</todo>
          ]]></code>
        </example>
        
        <example positive>
          <title>Code language specification</title>
          <code language="xml"><![CDATA[
            <code language="python">Python code</code>
            <code language="typescript">TypeScript code</code>
            <code language="bash">Shell commands</code>
            <code language="yaml">YAML configuration</code>
            <code language="json">JSON data</code>
          ]]></code>
        </example>
      </examples>
    </section>
    
    <section id="cdata-usage">
      <title>CDATA for Literal Content</title>
      <content>
        When you need to include XML/HTML tags as literal text (not parsed as markup), use CDATA.
        We pretend CDATA strips initial whitespace for cleaner formatting.
      </content>
      <examples>
        <example positive>
          <title>Using CDATA for XML examples</title>
          <code language="xml"><![CDATA[
            <instructions><![CDATA[
                To create a tool call, use <tool-call> like this:
                
                <tool-call>
                  <read path="/src/main.py" />
                  <bash command="git status" />
                </tool-call>
                
                The <read> tag takes a path attribute.
            ]]]]><![CDATA[></instructions>
          ]]></code>
        </example>
        
        <example positive>
          <title>CDATA in examples</title>
          <code language="xml"><![CDATA[
            <example positive><![CDATA[
                <conversation>
                  <u>How do I read a file?</u>
                  <a>Use the Read tool:
                  <tool-call>
                    <read path="file.py" />
                  </tool-call>
                  </a>
                </conversation>
            ]]]]><![CDATA[></example>
          ]]></code>
        </example>
      </examples>
    </section>
    
    <section id="complete-example">
      <title>Complete Example</title>
      <examples>
        <example positive>
          <title>Full prompt demonstrating all features</title>
          <code language="xml"><![CDATA[
            <prompt version="1.0">
              <meta>
                <title>Implement Strong Type System</title>
                <complexity level="medium" />
                <domain>coding</domain>
                <tags>types, python, refactoring</tags>
              </meta>
              
              <context>
                <background>
                  We need to migrate from string-based IDs to strongly-typed IDs
                  throughout the codebase.
                </background>
                
                <rules>
                  <rule critical><ref href="#/code/quality/no-disable-checks" /></rule>
                  <rule><ref href="#/code/python/types/new-style-optional" /></rule>
                  <rule><ref href="#/code/python/types/no-any" /></rule>
                </rules>
              </context>
              
              <instructions>
                Replace all string IDs with typed versions:
                
                <code language="python">
                # <bad>Old style</bad>
                def get_user(user_id: str) -> dict[str, Any]:
                    pass
                
                # <good>New style</good>
                def get_user(user_id: UserId) -> User:
                    pass
                </code>
                
                Follow the pattern in <ref href="#strong-types-pattern" />.
              </instructions>
              
              <pattern id="strong-types-pattern">
                <title>Strong Types Pattern</title>
                <code language="python">
                class UserId(str):
                    def __new__(cls, value: str) -> "UserId":
                        if not value.startswith("user_"):
                            raise ValueError(f"Invalid user ID: {value}")
                        return super().__new__(cls, value)
                </code>
              </pattern>
              
              <conversation>
                <u>Create a WorkspaceId type</u>
                <a>I'll create a strongly-typed WorkspaceId class:
                
                <tool-call>
                  <write path="src/types/ids.py">
                    <content>
                    class WorkspaceId(str):
                        """Strongly-typed workspace identifier."""
                        
                        def __new__(cls, value: str) -> "WorkspaceId":
                            if not value or not value.strip():
                                raise ValueError("WorkspaceId cannot be empty")
                            if not value.startswith("ws_"):
                                raise ValueError(f"WorkspaceId must start with 'ws_': {value}")
                            return super().__new__(cls, value)
                    </content>
                  </write>
                </tool-call>
                </a>
              </conversation>
              
              <examples>
                <example negative>
                  <code language="python">
                  # Primitive obsession
                  workspace_id: str = "ws_123"
                  user_id: str = "user_456"
                  
                  # Oops, swapped them!
                  get_workspace(user_id)  # Type checker won't catch this
                  </code>
                </example>
                
                <example positive>
                  <code language="python">
                  # Strong types
                  workspace_id = WorkspaceId("ws_123")
                  user_id = UserId("user_456")
                  
                  # Type error! Can't mix IDs
                  get_workspace(user_id)  # mypy: error
                  </code>
                </example>
              </examples>
              
              <output>
                <section required>New type definitions</section>
                <section required>Migration plan</section>
                <section optional>Performance impact analysis</section>
              </output>
            </prompt>
          ]]></code>
        </example>
      </examples>
    </section>
    
    <section id="quick-reference">
      <title>Quick Reference</title>
      <content>
        <code language="xml"><![CDATA[
          <!-- Structure -->
          <prompt version="1.0">
          <meta>
          <context>
          <instructions>
          <examples>
          <output>
          <rules>
          <conversation>

          <!-- Tool calls -->
          <read path="..." />
          <write path="..." content="..." />
          <edit path="..." old="..." new="..." />
          <bash command="..." />
          <grep pattern="..." path="..." />
          <glob pattern="..." />
          <task>...</task>
          <mcp server="..." tool="..."><params>{json}</params></mcp>

          <!-- Examples -->
          <example positive>
          <example negative>
          <example type="completion">
            <prefix>
            <completion good>
            <completion bad>

          <!-- Marking -->
          <good>...</good>
          <bad>...</bad>
          <critical>...</critical>
          <deprecated>...</deprecated>
          <warn>...</warn>
          <note>...</note>
          <tip>...</tip>

          <!-- Code -->
          <code language="python|typescript|bash|yaml|json">

          <!-- References -->
          <a href="#anchor">link text</a>
          <ref href="#rule-id" />
          <ref href="#/hierarchical/rule/path" />
          <call href="#function-id" />

          <!-- Conversation -->
          <u>user message</u>
          <a>assistant message</a>
          <t>tool output</t>
          <message from="user|assistant|tool">
        ]]></code>
      </content>
    </section>
  </instructions>
  
  <output>
    <section id="benefits">
      <title>Schema Benefits</title>
      <ul>
        <li><strong>Hierarchical Organization</strong>: Rules can be nested and referenced by path</li>
        <li><strong>Clear Good/Bad Patterns</strong>: Explicit marking of correct vs incorrect approaches</li>
        <li><strong>Tool Integration</strong>: Natural representation of tool calls</li>
        <li><strong>Interlinking</strong>: Easy cross-references between rules, patterns, and examples</li>
        <li><strong>HTML Familiarity</strong>: Uses HTML5-style attributes and patterns</li>
        <li><strong>LLM-Optimized</strong>: Designed for Claude to parse and understand easily</li>
        <li><strong>Self-Referential</strong>: This document follows its own schema</li>
      </ul>
    </section>
    
    <section id="design-goals">
      <title>Design Goals</title>
      <ul>
        <li>Human-readable and writable</li>
        <li>Machine-parseable (but optimized for LLM understanding)</li>
        <li>Extensible for new patterns</li>
        <li>Compatible with existing HTML/XML tools</li>
        <li>Demonstrably self-consistent</li>
      </ul>
    </section>
  </output>
</prompt>
