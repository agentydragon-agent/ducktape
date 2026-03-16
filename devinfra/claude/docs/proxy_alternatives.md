# Bazel Proxy Auth: Alternative Approaches

The current approach (native JVM proxy auth) was chosen after evaluating these alternatives.

## Current Approach: Native JVM Auth ✓

Bazel authenticates directly with Anthropic's egress proxy via `--repo_env=HTTPS_PROXY` + JVM startup flags. See <../README.md> for details.

## Alternatives Evaluated

### Bazel Credential Helpers ❌

Credential helpers are for endpoint authentication (`Authorization` header), not proxy
authentication (`Proxy-Authorization`). Designed for remote cache/execution services
and external repositories — not HTTPS proxy tunneling.

### .netrc File ❌

Same issue as credential helpers — for endpoint auth, not proxy auth.

### Pre-fetch with --distdir ⚠️

Download all dependencies manually, use `--distdir` for local copies. Only viable for
air-gapped environments. Impractical for active development: must pre-fetch all
transitive deps, breaks `bazel mod` and BCR resolution, must update on dep changes.

### Patch Bazel ⚠️

Modify `ProxyHelper.java` to set `Proxy-Authorization` via `setRequestProperty()`.
Could be a long-term upstream fix, but requires maintaining a Bazel fork.

### Transparent/IP-Allowlisted Proxy ❌

Requires changes to Claude Code web infrastructure, not user-controllable.

## References

- [Bazel Issue #14675](https://github.com/bazelbuild/bazel/issues/14675) - Authenticated HTTPS proxy
- [Bazel ProxyHelper.java](https://github.com/bazelbuild/bazel/blob/master/src/main/java/com/google/devtools/build/lib/bazel/repository/downloader/ProxyHelper.java)
- [JDK-8210814](https://bugs.openjdk.org/browse/JDK-8210814) - Cannot use Proxy Authentication with HTTPS
