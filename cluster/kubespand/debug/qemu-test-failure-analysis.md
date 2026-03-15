# QEMU Test Failure Analysis (2026-03-14)

## Summary

`kubespan_test` and `doublenat_test` timed out with "timed out waiting for N peers
(180s)". Root cause: `bufio.Scanner` EOF caching bug in the test harness, not a
kubespand networking issue. **Fixed and all 4 tests pass.**

## Root Cause

`WaitForPeers` in `kubespanlib.go` used a single `bufio.Scanner` to tail
`/tmp/kubespand.log`. Go's `bufio.Scanner` caches `io.EOF` internally — once it reads
past the end of the file, it sets an internal error flag and returns `false` for all
subsequent `Scan()` calls, even if the file has been appended to.

### Timeline

1. kubespand starts, writes initial controller startup logs
2. `WaitForPeers` opens the log file, creates a `bufio.Scanner`
3. Scanner reads all existing lines (no "configuring peer" yet — discovery in progress)
4. Scanner hits EOF → stores `err = io.EOF` internally
5. Outer retry loop calls `scanner.Scan()` → returns `false` immediately (cached EOF)
6. kubespand discovers peer, writes "configuring peer" to log file
7. Scanner never reads it — dead forever
8. 180s timeout expires

### Evidence

The diagnostic `dumpLogTail` function (added during debugging) uses `os.ReadFile`,
which opens the file fresh each time. Its output showed the "configuring peer" line
was present in the log:

```text
[WaitForPeers] still waiting for 1/1 peers, 2m45s remaining
--- last 20 lines of /tmp/kubespand.log ---
...
{"level":"info","caller":"kubespan/manager.go:375","msg":"configuring peer",...}
...
--- end /tmp/kubespand.log ---
```

The scanner didn't see it because it was already in the EOF-cached state.

### Fix

Replaced the single-Scanner tail with `os.ReadFile` + `strings.Split` on each poll
iteration. This re-reads the entire file each cycle, correctly picking up new data.
The `seen` map prevents duplicate processing.

Removed unused `bufio` import.

## How the Bug Survived

- The `talos_test` uses a different peer detection mechanism (Talos API resources, not
  kubespand log parsing), so it was unaffected.
- The `nft_test` doesn't use `WaitForPeers` at all.
- `kubespan_test` and `doublenat_test` were the only consumers, and they were the two
  tests that were never working after the recent restructure.

## Pre-Fix Hypotheses (Considered but Not the Cause)

These were investigated before the `bufio.Scanner` bug was identified:

### 1. rp_filter race condition (NOT the cause)

Test VMs set `rp_filter=2` on `conf/all` and `conf/default` before kubespand starts.
kubespand's `WireguardLinkController` later sets `rp_filter=0` on `conf/kubespan`
and `conf/all`. Hypothesis: the per-interface default (still =2) might take effect
on new interfaces. **This was not the cause** — kubespand was successfully discovering
peers and configuring WireGuard; the test harness just couldn't see the log line.

### 2. Discovery service connectivity (NOT the cause)

Discovery service was running and both VMs were successfully publishing/reading
affiliates (visible in the kubespand logs dumped by `dumpLogTail`).

### 3. WireGuard handshake failure (NOT the cause)

kubespand was cycling endpoints and applying WireGuard configs (visible in logs).
The full COSI controller chain completed successfully.

### 4. nftables / routing table conflicts (NOT the cause)

nftables chains and routing table 180 were configured correctly (visible in logs).

## Lessons Learned

1. **`bufio.Scanner` is not suitable for tailing files.** It caches EOF and never
   retries. Use `os.ReadFile` or manual `Read()` calls for polling patterns.
2. **Diagnostic logging (dumpLogTail) was the key.** It proved the data existed in the
   file but the scanner wasn't reading it, pointing directly to the scanner as the bug.
3. **When test infrastructure fails, the symptoms look like the system under test is
   broken.** Always verify the test harness before investigating the SUT.
