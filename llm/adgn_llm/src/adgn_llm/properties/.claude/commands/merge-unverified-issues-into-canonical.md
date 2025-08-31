# Merge unverified issues into canonical issues file

@../../README.md

From context, you should see that we are working with some particular piece of code, and gathering issues that are present in it.

We have:

* One central **canonical issues** file, likely named README.md, in which we are gathering:
  * canonical description of issues that I've validated,
  * possibly together with false positives.
* A bunch of other **gathered issue files** files in the same directory describing issues.
  They are not verified and they may include duplicates.

In the description below, by "README.md" we mean "the **canonical issues file**".

We will now go through issues described in these files - issue by issue - and
work on merging them into the README.md file.

## Main loop

Start by explaining your understanding of the context:

- Where is the **canonical issues** file
- Where are the **gathered issue files**
- Where is the source code which is being criticized by these issues

Ask me to confirm that your understanding is correct.

Once we're in sync, you will read each **gathered issue file**, and present to me *each issue* they contain.
For each issue in **gathered issue files**:

1. Describe it to me, and show it to me including the code that has it (including multiple examples if it's repeated).
   Including code snippet(s) before (with the issue), and after (how it would look fixed).
   DO NOT write the issue into a file yet.

2. I will tell you what to do about the issue. I may first ask you some questions about the issue so I have more understanding.

   If I tell you it's a true positive, that means we are blessing it into README.md. In that case:

   * Make a new entry in README.md in an appropriate place, describing the issue.
   * Make sure to unambiguously localize the issue in the original source code by including a file path (if it's not just a single file) and line number/range.
   * If it is not trivially described (e.g., "this typo on line 37"
     or "variable Foo should use time.Duration to represent duration not int"),
     also include a code snippet showing it.
   * Focus on describing it as *what's wrong* with the original code.
     You can also include a "here's how to fix it", but keep it light (e.g., "Extract helper method.").
   * If it's better described with a code example (e.g., specific refactor), include snippet of suggested fix.

   I may also tell you that it's a false positive or other resolutions which I'll tell you how to handle ad hoc.

3. Once the issue is handled, go over all **gathered issue files** and remove any duplicates of this issue that we've just handled.
