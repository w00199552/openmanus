---
name: code-review
description: Review code for best practices, potential bugs, and improvements. Use when the user asks to review, audit, or check code quality.
---

# Code Review Skill

When reviewing code, systematically check:

1. **Naming** — Are names clear and consistent?
2. **Error Handling** — Are errors caught and handled gracefully?
3. **Security** — Any injection, XSS, or data exposure risks?
4. **Performance** — Obvious bottlenecks (N+1 queries, unnecessary loops)?
5. **Readability** — Can the logic be understood quickly?

## Output Format

Provide a structured report:

```
## Code Review Report

### Summary
[1-2 sentence overview]

### Findings
- [SEVERITY] file:line — Description
  Suggestion: ...

### Verdict
PASS / NEEDS CHANGES / CRITICAL
```

Severity levels: CRITICAL > WARNING > INFO > STYLE
