#!/usr/bin/env python3
"""Show the database schema with table and column descriptions."""

import sqlite3
from database import init_database

def show_database_schema():
    """Display the database schema with descriptions."""
    
    # Initialize database
    print("Creating database with schema...")
    db_manager = init_database("sqlite:///schema_test.db")
    
    # Connect directly to SQLite to query schema
    conn = sqlite3.connect("schema_test.db")
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("DATABASE SCHEMA WITH DESCRIPTIONS")
    print("="*80)
    
    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = cursor.fetchall()
    
    for (table_name,) in tables:
        print(f"\n📊 TABLE: {table_name}")
        print("-" * 60)
        
        # Get table comment (if any) 
        cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}';")
        create_sql = cursor.fetchone()[0]
        if "COMMENT" in create_sql.upper():
            # Extract comment (simplified approach)
            parts = create_sql.split("COMMENT")
            if len(parts) > 1:
                comment = parts[1].split("'")[1] if "'" in parts[1] else "No description"
                print(f"Purpose: {comment}")
        
        # Get column information
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = cursor.fetchall()
        
        print("\nColumns:")
        for col in columns:
            cid, name, col_type, notnull, default_value, pk = col
            pk_marker = " (PRIMARY KEY)" if pk else ""
            null_marker = " NOT NULL" if notnull else " NULL"
            default_marker = f" DEFAULT {default_value}" if default_value else ""
            
            print(f"  • {name:<20} {col_type:<10}{pk_marker}{null_marker}{default_marker}")
        
        # Get foreign keys
        cursor.execute(f"PRAGMA foreign_key_list({table_name});")
        fkeys = cursor.fetchall()
        
        if fkeys:
            print("\nForeign Keys:")
            for fk in fkeys:
                id_fk, seq, target_table, from_col, to_col, on_update, on_delete, match = fk
                print(f"  • {from_col} → {target_table}.{to_col}")
    
    print("\n" + "="*80)
    print("SAMPLE QUERIES")
    print("="*80)
    
    queries = [
        ("Show all optimization runs", 
         "SELECT id, start_time, status, total_iterations FROM optimization_runs;"),
        
        ("Find tasks containing 'REST API'",
         "SELECT task_id, prompt FROM seed_tasks WHERE prompt LIKE '%REST API%' AND is_active = 1;"),
        
        ("Score evolution by iteration", 
         """SELECT r.iteration, AVG(gr.overall_score) as avg_score, COUNT(*) as rollout_count
            FROM grader_runs gr 
            JOIN rollouts r ON gr.rollout_id = r.id 
            GROUP BY r.iteration ORDER BY r.iteration;"""),
        
        ("Best performing system prompts",
         """SELECT sp.iteration, AVG(gr.overall_score) as avg_score, COUNT(*) as uses
            FROM system_prompts sp 
            JOIN rollouts r ON sp.id = r.system_prompt_id
            JOIN grader_runs gr ON r.id = gr.rollout_id
            GROUP BY sp.id ORDER BY avg_score DESC;"""),
        
        ("Files produced by rollouts scoring > 8.0",
         """SELECT rf.relative_path, rf.file_size, gr.overall_score
            FROM rollout_files rf
            JOIN rollouts r ON rf.rollout_id = r.id
            JOIN grader_runs gr ON r.id = gr.rollout_id
            WHERE gr.overall_score > 8.0
            ORDER BY gr.overall_score DESC;""")
    ]
    
    for description, query in queries:
        print(f"\n💡 {description}:")
        print(f"   {query}")
    
    print(f"\n" + "="*80)
    print("DATABASE FEATURES")
    print("="*80)
    print("✅ Full-text search on task prompts and grading criteria")
    print("✅ File integrity verification with SHA256 hashes") 
    print("✅ Content-based change detection for YAML sync")
    print("✅ Complete audit trail of optimization process")
    print("✅ Rich relationships enabling complex analysis queries")
    print("✅ Efficient storage (file content on disk, metadata in DB)")
    print("✅ CLI logging preserved (JSONL files removed)")
    
    conn.close()
    db_manager.close()
    
    print(f"\nTest database created at: schema_test.db")
    print("You can explore it with: sqlite3 schema_test.db")

if __name__ == "__main__":
    show_database_schema()