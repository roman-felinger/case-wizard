# Skill: Generate Implementation Plan

## Overview

Convert a case brief into a detailed, step-by-step implementation plan.

## When to Use

- Creating guides from briefs
- Breaking down complex changes
- Generating testing strategy
- Planning for code review

## Inputs

```json
{
  "brief": "case-brief.md content",
  "repo_structure": "project layout and key files",
  "tech_stack": ["Node.js", "React", "PostgreSQL"],
  "constraints": ["no schema changes", "backwards compatible"],
  "deadline": "2025-08-25",
  "time_budget": "4 hours"
}
```

## Outputs

```markdown
# Implementation Plan: T2611845

## Overview
- **Problem:** Users can't log in on slow networks
- **Solution:** Add exponential backoff to auth service
- **Effort:** 1-2 hours implementation + 1 hour testing
- **Risk:** Low (isolated change, good test coverage)

## File Changes Summary
- `src/auth/login.ts` — Update timeout logic
- `tests/auth.test.ts` — Add timeout backoff test
- `src/middleware/retry.ts` — New generic retry helper

## Step-by-Step Plan

### Step 1: Create Retry Helper (15 min)
**File:** `src/middleware/retry.ts`
**What:** Extract exponential backoff into reusable function
**Why:** Keep code DRY, testable
```typescript
export async function withExponentialBackoff<T>(
  fn: () => Promise<T>,
  maxRetries = 3
): Promise<T> {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await fn();
    } catch (e) {
      const delay = Math.pow(2, i) * 1000;
      if (i === maxRetries - 1) throw e;
      await sleep(delay);
    }
  }
}
```
**Tests:** Write before implementing

### Step 2: Update Login Service (15 min)
**File:** `src/auth/login.ts`
**What:** Use retry helper in login function
**Why:** Apply backoff to actual login calls
**Before:**
```typescript
const result = await timeout(authRequest(), 5000);
```
**After:**
```typescript
const result = await withExponentialBackoff(
  () => timeout(authRequest(), 5000),
  3
);
```

### Step 3: Add Logging (10 min)
**File:** `src/auth/login.ts`
**What:** Log retry attempts
**Why:** Help debug timeout issues in production
```typescript
if (i > 0) {
  console.log(`Login retry ${i}, delay ${delay}ms`);
}
```

### Step 4: Write Tests (30 min)
**File:** `tests/auth.test.ts`
**What:** Test retry logic
**Why:** Ensure backoff works correctly
**Test cases:**
- Succeeds on first try
- Succeeds on second retry
- Fails after max retries
- Delays increase exponentially

### Step 5: Integration Test (15 min)
**File:** `tests/integration/slow-network.test.ts`
**What:** Test login on simulated slow network
**Why:** Verify fix works end-to-end

## Dependencies & Ordering

```
Step 1: Retry Helper
  ↓
Step 2: Update Login (depends on Step 1)
  ↓
Step 3: Add Logging (depends on Step 2)
  ↓
Step 4: Write Tests (tests Steps 1-3)
  ↓
Step 5: Integration Test (tests entire flow)
```

## Testing Strategy

- **Unit:** Test retry helper in isolation
- **Integration:** Test login with slow network
- **Manual:** Test in browser on throttled connection

## Deployment Plan

1. Branch: `case/T2611845`
2. Create PR
3. Code review + approval
4. Merge to `main`
5. Deploy to production

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Retry causes duplicate requests | Medium | Log all attempts, monitor |
| Exponential backoff too aggressive | Low | Start with 2s base, adjust later |
| Tests don't cover all cases | Medium | Add edge case tests |

## Success Criteria

- ✅ All tests pass
- ✅ Linter passes
- ✅ Build succeeds
- ✅ Manual test on slow network succeeds
- ✅ Code review approved
- ✅ Deployed to production
- ✅ Customer confirms fix works

## Rollback Plan

If issues in production:
1. Revert PR
2. Deploy previous version
3. Debug and iterate
```

## Implementation Steps

1. **Analyze brief**
   - Understand problem scope
   - Identify affected components
   - Note constraints

2. **Examine codebase**
   - Find files that need changes
   - Understand dependencies
   - Identify test locations

3. **Plan changes**
   - List each change (file, lines, what)
   - Order by dependency
   - Estimate effort

4. **Write plan document**
   - Clear steps, not too granular
   - Include code snippets
   - Explain rationale
   - Add test strategy

5. **Review plan**
   - Is it doable in time budget?
   - Are dependencies clear?
   - Are tests adequate?

## Error Handling

- Incomplete brief: Ask clarifying questions
- Unrealistic deadline: Flag and suggest phased approach
- Missing context: Request codebase structure
- Ambiguous scope: Offer multiple interpretations

## Progress Messages

```
📍 Analyzing brief...
✅ Problem understood: timeout too short
📍 Examining codebase...
✅ Found relevant files: auth.ts, login.tsx
✅ Identified 2 testing frameworks: jest, cypress
📍 Planning implementation...
✅ Created 5-step plan
✅ Effort estimate: 1-2 hours
📍 Plan generated and ready
```
