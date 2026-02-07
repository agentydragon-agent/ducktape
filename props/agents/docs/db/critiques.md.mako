# Critiques: Reported Issues

Critic agents write issues and occurrences to the database via tools (not raw SQL).

${describe_relation("reported_issues")}
${describe_relation("reported_issue_occurrences")}

## Reading Critiques

```sql
SELECT ri.issue_id, ri.rationale, rio.locations
FROM reported_issues ri
JOIN reported_issue_occurrences rio USING (agent_run_id, reported_issue_id)
WHERE ri.agent_run_id = '<run_id>';
```
