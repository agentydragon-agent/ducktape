SELECT DISTINCT family AS __text, family AS __value
FROM probe_results
WHERE $__timeFilter(start_time)
ORDER BY 1;

