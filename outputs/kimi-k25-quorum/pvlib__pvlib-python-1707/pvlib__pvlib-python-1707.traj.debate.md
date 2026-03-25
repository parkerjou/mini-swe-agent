# Quorum Debate — pvlib__pvlib-python-1707

## Investigation Summaries

### Stack Trace Tracer (exit: Submitted)

ROOT CAUSE: The physical() function was rewritten in commit a19b528 to add AR coating support, but the handling for aoi > 90 degrees was removed. When n=1 and aoi > 90, costheta becomes 0, causing division by zero in the reflectance calculations (0/0) resulting in NaN.
LOCATION: /testbed/pvlib/iam.py, lines 155-215 (physical function)
EVIDENCE: When n=1 and aoi=100, costheta=max(0,cos(100))=0, sintheta=1, and after refraction with n1/n2=1, sintheta stays 1, making costheta=sqrt(1-1)=0. This causes all denominators in rho12_s, rho12_p calculations to be 0, resulting in 0/0=NaN. The old code had explicit handling: iam = np.where(aoi > 90, 0, iam) which was removed in the rewrite.
CONFIDENCE: high

### Issue-First Hypothesizer (exit: LimitsExceeded)

*(no submission)*

### Minimal Diff Finder (exit: LimitsExceeded)

*(no submission)*

## Debate Contributions

### Stack Trace Tracer — Round 1

**Root cause:** The `physical()` function was rewritten to add AR coating support but lost the explicit handling for AOI > 90 degrees; when n=1 and AOI > 90, this causes division by zero (0/0) in reflectance calculations, producing NaN instead of 0.

**Location:** `/testbed/pvlib/iam.py`, lines 155-215, specifically the `physical()` function. The missing handling was previously at lines 180-190 in the old implementation.

**Proposed fix direction:** Add back the explicit check for AOI >= 90 (or abs(AOI) >= 90) at the end of the function to return 0 for those angles, similar to how the `ashrae()` and `schlick()` functions in the same file handle this case. This should be done with `np.where()` to handle array inputs properly.

**Supporting evidence:** 
1. Reproduced the bug: `physical(aoi=100, n=1)` returns `nan` with RuntimeWarnings for "invalid value encountered in scalar divide" and "divide by zero"
2. Traced execution: When n=1 and aoi=100, `costheta = max(0, cos(100°)) = 0`, `sintheta = 1`, after refraction `sintheta = 1/1 * 1 = 1`, so `costheta = sqrt(1-1) = 0`
3. This makes all denominators in `rho12_s` and `rho12_p` calculations equal to 0, causing 0/0 = NaN
4. Git diff shows the old code had `iam = np.where(aoi > 90, 0, iam)` which was removed in commit a19b528
5. Other IAM functions in the same file (`ashrae`, `schlick`) still have this handling: `iam = np.where(np.abs(aoi) >= 90.0, 0.0, iam)`

**Weaknesses:** I haven't verified if there are other edge cases (e.g., n slightly different from 1, or very large AOI values) that might also cause issues. The fix might need to handle `abs(aoi) >= 90` rather than just `aoi > 90` to match the behavior of other functions.

**Confidence:** High. The evidence is clear from the git history, code comparison, and direct reproduction of the bug with step-by-step tracing of the calculation.

### Issue-First Hypothesizer — Round 1

**Root cause:** The `physical()` function was rewritten in commit a19b528 to add AR coating support, but the explicit check `iam = np.where(aoi > 90, 0, iam)` that handled AOI > 90 degrees was removed; when n=1 and AOI > 90, this causes 0/0 division in the reflectance calculations, producing NaN instead of 0.

**Location:** `/testbed/pvlib/iam.py`, lines 155-215, specifically the `physical()` function. The missing check was previously at the end of the function (around line 186 in the old implementation).

**Proposed fix direction:** Add back the explicit check for AOI > 90 at the end of the function to return 0 for those angles, using `np.where()` to handle array inputs properly. This should match the pattern used in other IAM functions in the same file (`ashrae()`, `schlick()`) which use `iam = np.where(np.abs(aoi) >= 90.0, 0.0, iam)`.

**Supporting evidence:**
1. Git diff of commit a19b528 clearly shows the removal of `iam = np.where(aoi > 90, 0, iam)` from the old implementation
2. Reproduced the bug: When n=1 and aoi=100, traced execution showing `costheta = max(0, cos(100°)) = 0`, `sintheta = 1`, after refraction `sintheta = 1/1 * 1 = 1`, so `costheta = sqrt(1-1) = 0`
3. This makes all `n*costheta` terms equal to 0, causing `rho12_s = ((0-0)/(0+0))**2 = 0/0 = NaN`
4. The NaN propagates through the rest of the calculation: `tau_s = 1 - NaN = NaN`, and finally `iam = NaN`
5. Other IAM functions (`ashrae`, `schlick`) in the same file still have this handling, confirming the pattern

**Weaknesses:** I haven't tested edge cases like n very close to 1 (e.g., 1.0001) or negative AOI values with n=1. The fix might need to use `abs(aoi) > 90` rather than just `aoi > 90` to handle negative angles symmetrically, matching the pattern in `ashrae()` and `schlick()`.

**Confidence:** High. The evidence from git history, code tracing, and comparison with other functions in the same file is conclusive.

**Reactions:**
- **Agree with Stack Trace Tracer:** Our root cause analyses are identical. The evidence from git history and code tracing confirms the same conclusion.
- **Gap identified:** We should verify whether the fix should use `aoi > 90` (as in the old code) or `abs(aoi) >= 90` (as in `ashrae()` and `schlick()`). The latter is more robust for negative angles.
- **Additional consideration:** The old code also had `iam = np.where(iam < 0, 0, iam)` which was removed. This might be needed for edge cases near 90 degrees where floating-point precision could produce tiny negative values.

### Minimal Diff Finder — Round 1

**Root cause:** The `physical()` function was refactored in commit a19b528 to add AR coating support, but the explicit check `iam = np.where(aoi > 90, 0, iam)` that handled AOI > 90 degrees was removed; when n=1 and AOI > 90, this causes 0/0 division in the reflectance calculations (specifically in `rho12_s` and `rho12_p` where denominators become 0), producing NaN instead of 0.

**Location:** `/testbed/pvlib/iam.py`, lines 155-218, specifically the `physical()` function. The missing check should be added just before the `return iam` statement at line 218.

**Proposed fix direction:** Add a single line before the return statement: `iam = np.where(np.abs(aoi) >= 90, 0, iam)`. This matches the pattern used in other IAM functions in the same file (`ashrae()` at line 87, `schlick()` at line 487) and handles both positive and negative AOI values symmetrically.

**Supporting evidence:**
1. Reproduced the bug: `physical(aoi=100, n=1)` returns `nan` with RuntimeWarnings for "invalid value encountered in scalar divide"
2. Step-by-step trace: When n=1 and aoi=100, `costheta = max(0, cos(100°)) = 0`, `sintheta = 1`, after refraction `sintheta = 1/1 * 1 = 1`, so `costheta = sqrt(1-1) = 0`
3. This makes all `n*costheta` terms equal to 0, causing `rho12_s = ((0-0)/(0+0))**2 = 0/0 = NaN`
4. Git diff of commit a19b528 clearly shows the removal of `iam = np.where(aoi > 90, 0, iam)` from the old implementation (lines 186-190)
5. Other IAM functions (`ashrae`, `schlick`) in the same file use `iam = np.where(np.abs(aoi) >= 90.0, 0.0, iam)`, confirming the pattern

**Weaknesses:** I haven't tested edge cases with n very close to 1 (e.g., 1.0001) or verified if the old code's additional check `iam = np.where(iam < 0, 0, iam)` for tiny negative values near 90° is also needed.

**Confidence:** High. The evidence from git history, code tracing, and comparison with other functions in the same file is conclusive.

**Reactions:**
- **Agree with both investigators:** Our root cause analyses are identical. The evidence confirms that the missing check is the issue.
- **Gap identified:** The old code used `aoi > 90` but `ashrae()` and `schlick()` use `abs(aoi) >= 90`. The latter is more robust for negative angles and should be preferred.
- **Additional consideration:** The old code also had `iam = np.where(iam < 0, 0, iam)` which was removed. While not causing the reported bug, this might be needed for edge cases near 90° where floating-point precision could produce tiny negative values.

### Stack Trace Tracer — Round 2

**Root cause:** The `physical()` function was rewritten in commit a19b528 to add AR coating support, but the explicit check for AOI > 90 degrees (`iam = np.where(aoi > 90, 0, iam)`) was removed; when n=1 and AOI > 90, this causes 0/0 division in the reflectance calculations because all `n*costheta` terms become zero, producing NaN instead of 0.

**Location:** `/testbed/pvlib/iam.py`, lines 155-218, specifically the `physical()` function. The missing check should be added just before the `return iam` statement.

**Proposed fix direction:** Add a check at the end of the function: `iam = np.where(np.abs(aoi) >= 90, 0, iam)`. This matches the pattern used in `ashrae()` (line 87) and `schlick()` (line 487) in the same file, using `abs(aoi)` to handle negative angles symmetrically.

**Supporting evidence:**
1. Reproduced the bug: `physical(aoi=100, n=1)` returns `nan` with RuntimeWarnings for "invalid value encountered in scalar divide"
2. Step-by-step trace: When n=1 and aoi=100, `costheta = max(0, cos(100°)) = 0`, `sintheta = 1`, after refraction `sintheta = 1/1 * 1 = 1`, so `costheta = sqrt(1-1) = 0`
3. This makes all `n*costheta` terms equal to 0, causing `rho12_s = ((0-0)/(0+0))**2 = 0/0 = NaN`
4. Git diff of commit a19b528 clearly shows the removal of `iam = np.where(aoi > 90, 0, iam)` from the old implementation
5. Other IAM functions (`ashrae`, `schlick`) in the same file use `iam = np.where(np.abs(aoi) >= 90.0, 0.0, iam)`, confirming the pattern

**Weaknesses:** I haven't tested edge cases with n very close to 1 (e.g., 1.0001) or verified if the old code's additional check `iam = np.where(iam < 0, 0, iam)` for tiny negative values near 90° is also needed.

**Confidence:** High. The evidence from git history, code tracing, and comparison with other functions in the same file is conclusive.

**Reactions:**
- **Agree with all investigators:** Our root cause analyses are identical. The evidence confirms that the missing check is the issue.
- **Gap identified:** The old code used `aoi > 90` but `ashrae()` and `schlick()` use `abs(aoi) >= 90`. The latter is more robust for negative angles and should be preferred.
- **Additional consideration:** The old code also had `iam = np.where(iam < 0, 0, iam)` which was removed. While not causing the reported bug, this might be needed for edge cases near 90° where floating-point precision could produce tiny negative values.

### Issue-First Hypothesizer — Round 2

**Root cause:** The `physical()` function was rewritten in commit a19b528 to add AR coating support, but the explicit check `iam = np.where(aoi > 90, 0, iam)` that handled AOI > 90 degrees was removed; when n=1 and AOI > 90, this causes 0/0 division in the reflectance calculations (specifically in `rho12_s` and `rho12_p` where denominators become 0), producing NaN instead of 0.

**Location:** `/testbed/pvlib/iam.py`, lines 155-218, specifically the `physical()` function. The missing check should be added just before the `return iam` statement at line 218.

**Proposed fix direction:** Add a check at the end of the function: `iam = np.where(np.abs(aoi) >= 90, 0, iam)`. This matches the pattern used in `ashrae()` (line 87) and `schlick()` (line 487) in the same file, using `abs(aoi)` to handle negative angles symmetrically.

**Supporting evidence:**
1. Reproduced the bug: Traced execution showing `physical(aoi=100, n=1)` produces NaN with RuntimeWarnings for "invalid value encountered in scalar divide"
2. Step-by-step trace: When n=1 and aoi=100, `costheta = max(0, cos(100°)) = 0`, `sintheta = 1`, after refraction `sintheta = 1/1 * 1 = 1`, so `costheta = sqrt(1-1) = 0`
3. This makes all `n*costheta` terms equal to 0, causing `rho12_s = ((0-0)/(0+0))**2 = 0/0 = NaN`
4. Git diff of commit a19b528 clearly shows the removal of `iam = np.where(aoi > 90, 0, iam)` from the old implementation
5. Other IAM functions (`ashrae`, `schlick`) in the same file use `iam = np.where(np.abs(aoi) >= 90.0, 0.0, iam)`, confirming the pattern

**Weaknesses:** I haven't tested edge cases with n very close to 1 (e.g., 1.0001) or verified if the old code's additional check `iam = np.where(iam < 0, 0, iam)` for tiny negative values near 90° is also needed.

**Confidence:** High. The evidence from git history, code tracing, and comparison with other functions in the same file is conclusive.

**Reactions:**
- **Agree with all investigators:** Our root cause analyses are essentially identical. The evidence confirms that the missing check is the issue.
- **Gap identified:** The old code used `aoi > 90` but `ashrae()` and `schlick()` use `abs(aoi) >= 90`. The latter is more robust for negative angles and should be preferred.
- **Additional consideration:** The old code also had `iam = np.where(iam < 0, 0, iam)` which was removed. While not causing the reported bug, this might be needed for edge cases near 90° where floating-point precision could produce tiny negative values.

### Minimal Diff Finder — Round 2

**Root cause:** The `physical()` function was refactored in commit a19b528 to add AR coating support, but the explicit check `iam = np.where(aoi > 90, 0, iam)` that handled AOI > 90 degrees was removed; when n=1 and AOI > 90, this causes 0/0 division in the reflectance calculations because all `n*costheta` terms become zero, producing NaN instead of 0.

**Location:** `/testbed/pvlib/iam.py`, lines 155-218, specifically the `physical()` function. The missing check should be added just before the `return iam` statement at line 218.

**Proposed fix direction:** Add a single line before the return statement: `iam = np.where(np.abs(aoi) >= 90, 0, iam)`. This matches the pattern used in `ashrae()` (line 87) and `schlick()` (line 487) in the same file, using `abs(aoi)` to handle negative angles symmetrically.

**Supporting evidence:**
1. Reproduced the bug: `physical(aoi=100, n=1)` returns `nan` with RuntimeWarnings for "invalid value encountered in scalar divide" and "divide by zero"
2. Step-by-step trace: When n=1 and aoi=100, `costheta = max(0, cos(100°)) = 0`, `sintheta = 1`, after refraction `sintheta = 1/1 * 1 = 1`, so `costheta = sqrt(1-1) = 0`
3. This makes all `n*costheta` terms equal to 0, causing `rho12_s = ((0-0)/(0+0))**2 = 0/0 = NaN`
4. Git diff of commit a19b528 clearly shows the removal of `iam = np.where(aoi > 90, 0, iam)` from the old implementation
5. Other IAM functions (`ashrae`, `schlick`) in the same file use `iam = np.where(np.abs(aoi) >= 90.0, 0.0, iam)`, confirming the pattern

**Weaknesses:** I haven't tested edge cases with n very close to 1 (e.g., 1.0001) or verified if the old code's additional check `iam = np.where(iam < 0, 0, iam)` for tiny negative values near 90° is also needed.

**Confidence:** High. The evidence from git history, code tracing, and comparison with other functions in the same file is conclusive.

**Reactions:**
- **Agree with all investigators:** Our root cause analyses are essentially identical. The evidence confirms that the missing check is the issue.
- **Gap identified:** The old code used `aoi > 90` but `ashrae()` and `schlick()` use `abs(aoi) >= 90`. The latter is more robust for negative angles and should be preferred.
- **Additional consideration:** The old code also had `iam = np.where(iam < 0, 0, iam)` which was removed. While not causing the reported bug, this might be needed for edge cases near 90° where floating-point precision could produce tiny negative values.

## Full Transcript (as sent to implementer)

### Stack Trace Tracer — Round 1

**Root cause:** The `physical()` function was rewritten to add AR coating support but lost the explicit handling for AOI > 90 degrees; when n=1 and AOI > 90, this causes division by zero (0/0) in reflectance calculations, producing NaN instead of 0.

**Location:** `/testbed/pvlib/iam.py`, lines 155-215, specifically the `physical()` function. The missing handling was previously at lines 180-190 in the old implementation.

**Proposed fix direction:** Add back the explicit check for AOI >= 90 (or abs(AOI) >= 90) at the end of the function to return 0 for those angles, similar to how the `ashrae()` and `schlick()` functions in the same file handle this case. This should be done with `np.where()` to handle array inputs properly.

**Supporting evidence:** 
1. Reproduced the bug: `physical(aoi=100, n=1)` returns `nan` with RuntimeWarnings for "invalid value encountered in scalar divide" and "divide by zero"
2. Traced execution: When n=1 and aoi=100, `costheta = max(0, cos(100°)) = 0`, `sintheta = 1`, after refraction `sintheta = 1/1 * 1 = 1`, so `costheta = sqrt(1-1) = 0`
3. This makes all denominators in `rho12_s` and `rho12_p` calculations equal to 0, causing 0/0 = NaN
4. Git diff shows the old code had `iam = np.where(aoi > 90, 0, iam)` which was removed in commit a19b528
5. Other IAM functions in the same file (`ashrae`, `schlick`) still have this handling: `iam = np.where(np.abs(aoi) >= 90.0, 0.0, iam)`

**Weaknesses:** I haven't verified if there are other edge cases (e.g., n slightly different from 1, or very large AOI values) that might also cause issues. The fix might need to handle `abs(aoi) >= 90` rather than just `aoi > 90` to match the behavior of other functions.

**Confidence:** High. The evidence is clear from the git history, code comparison, and direct reproduction of the bug with step-by-step tracing of the calculation.

---

### Issue-First Hypothesizer — Round 1

**Root cause:** The `physical()` function was rewritten in commit a19b528 to add AR coating support, but the explicit check `iam = np.where(aoi > 90, 0, iam)` that handled AOI > 90 degrees was removed; when n=1 and AOI > 90, this causes 0/0 division in the reflectance calculations, producing NaN instead of 0.

**Location:** `/testbed/pvlib/iam.py`, lines 155-215, specifically the `physical()` function. The missing check was previously at the end of the function (around line 186 in the old implementation).

**Proposed fix direction:** Add back the explicit check for AOI > 90 at the end of the function to return 0 for those angles, using `np.where()` to handle array inputs properly. This should match the pattern used in other IAM functions in the same file (`ashrae()`, `schlick()`) which use `iam = np.where(np.abs(aoi) >= 90.0, 0.0, iam)`.

**Supporting evidence:**
1. Git diff of commit a19b528 clearly shows the removal of `iam = np.where(aoi > 90, 0, iam)` from the old implementation
2. Reproduced the bug: When n=1 and aoi=100, traced execution showing `costheta = max(0, cos(100°)) = 0`, `sintheta = 1`, after refraction `sintheta = 1/1 * 1 = 1`, so `costheta = sqrt(1-1) = 0`
3. This makes all `n*costheta` terms equal to 0, causing `rho12_s = ((0-0)/(0+0))**2 = 0/0 = NaN`
4. The NaN propagates through the rest of the calculation: `tau_s = 1 - NaN = NaN`, and finally `iam = NaN`
5. Other IAM functions (`ashrae`, `schlick`) in the same file still have this handling, confirming the pattern

**Weaknesses:** I haven't tested edge cases like n very close to 1 (e.g., 1.0001) or negative AOI values with n=1. The fix might need to use `abs(aoi) > 90` rather than just `aoi > 90` to handle negative angles symmetrically, matching the pattern in `ashrae()` and `schlick()`.

**Confidence:** High. The evidence from git history, code tracing, and comparison with other functions in the same file is conclusive.

**Reactions:**
- **Agree with Stack Trace Tracer:** Our root cause analyses are identical. The evidence from git history and code tracing confirms the same conclusion.
- **Gap identified:** We should verify whether the fix should use `aoi > 90` (as in the old code) or `abs(aoi) >= 90` (as in `ashrae()` and `schlick()`). The latter is more robust for negative angles.
- **Additional consideration:** The old code also had `iam = np.where(iam < 0, 0, iam)` which was removed. This might be needed for edge cases near 90 degrees where floating-point precision could produce tiny negative values.

---

### Minimal Diff Finder — Round 1

**Root cause:** The `physical()` function was refactored in commit a19b528 to add AR coating support, but the explicit check `iam = np.where(aoi > 90, 0, iam)` that handled AOI > 90 degrees was removed; when n=1 and AOI > 90, this causes 0/0 division in the reflectance calculations (specifically in `rho12_s` and `rho12_p` where denominators become 0), producing NaN instead of 0.

**Location:** `/testbed/pvlib/iam.py`, lines 155-218, specifically the `physical()` function. The missing check should be added just before the `return iam` statement at line 218.

**Proposed fix direction:** Add a single line before the return statement: `iam = np.where(np.abs(aoi) >= 90, 0, iam)`. This matches the pattern used in other IAM functions in the same file (`ashrae()` at line 87, `schlick()` at line 487) and handles both positive and negative AOI values symmetrically.

**Supporting evidence:**
1. Reproduced the bug: `physical(aoi=100, n=1)` returns `nan` with RuntimeWarnings for "invalid value encountered in scalar divide"
2. Step-by-step trace: When n=1 and aoi=100, `costheta = max(0, cos(100°)) = 0`, `sintheta = 1`, after refraction `sintheta = 1/1 * 1 = 1`, so `costheta = sqrt(1-1) = 0`
3. This makes all `n*costheta` terms equal to 0, causing `rho12_s = ((0-0)/(0+0))**2 = 0/0 = NaN`
4. Git diff of commit a19b528 clearly shows the removal of `iam = np.where(aoi > 90, 0, iam)` from the old implementation (lines 186-190)
5. Other IAM functions (`ashrae`, `schlick`) in the same file use `iam = np.where(np.abs(aoi) >= 90.0, 0.0, iam)`, confirming the pattern

**Weaknesses:** I haven't tested edge cases with n very close to 1 (e.g., 1.0001) or verified if the old code's additional check `iam = np.where(iam < 0, 0, iam)` for tiny negative values near 90° is also needed.

**Confidence:** High. The evidence from git history, code tracing, and comparison with other functions in the same file is conclusive.

**Reactions:**
- **Agree with both investigators:** Our root cause analyses are identical. The evidence confirms that the missing check is the issue.
- **Gap identified:** The old code used `aoi > 90` but `ashrae()` and `schlick()` use `abs(aoi) >= 90`. The latter is more robust for negative angles and should be preferred.
- **Additional consideration:** The old code also had `iam = np.where(iam < 0, 0, iam)` which was removed. While not causing the reported bug, this might be needed for edge cases near 90° where floating-point precision could produce tiny negative values.

---

### Stack Trace Tracer — Round 2

**Root cause:** The `physical()` function was rewritten in commit a19b528 to add AR coating support, but the explicit check for AOI > 90 degrees (`iam = np.where(aoi > 90, 0, iam)`) was removed; when n=1 and AOI > 90, this causes 0/0 division in the reflectance calculations because all `n*costheta` terms become zero, producing NaN instead of 0.

**Location:** `/testbed/pvlib/iam.py`, lines 155-218, specifically the `physical()` function. The missing check should be added just before the `return iam` statement.

**Proposed fix direction:** Add a check at the end of the function: `iam = np.where(np.abs(aoi) >= 90, 0, iam)`. This matches the pattern used in `ashrae()` (line 87) and `schlick()` (line 487) in the same file, using `abs(aoi)` to handle negative angles symmetrically.

**Supporting evidence:**
1. Reproduced the bug: `physical(aoi=100, n=1)` returns `nan` with RuntimeWarnings for "invalid value encountered in scalar divide"
2. Step-by-step trace: When n=1 and aoi=100, `costheta = max(0, cos(100°)) = 0`, `sintheta = 1`, after refraction `sintheta = 1/1 * 1 = 1`, so `costheta = sqrt(1-1) = 0`
3. This makes all `n*costheta` terms equal to 0, causing `rho12_s = ((0-0)/(0+0))**2 = 0/0 = NaN`
4. Git diff of commit a19b528 clearly shows the removal of `iam = np.where(aoi > 90, 0, iam)` from the old implementation
5. Other IAM functions (`ashrae`, `schlick`) in the same file use `iam = np.where(np.abs(aoi) >= 90.0, 0.0, iam)`, confirming the pattern

**Weaknesses:** I haven't tested edge cases with n very close to 1 (e.g., 1.0001) or verified if the old code's additional check `iam = np.where(iam < 0, 0, iam)` for tiny negative values near 90° is also needed.

**Confidence:** High. The evidence from git history, code tracing, and comparison with other functions in the same file is conclusive.

**Reactions:**
- **Agree with all investigators:** Our root cause analyses are identical. The evidence confirms that the missing check is the issue.
- **Gap identified:** The old code used `aoi > 90` but `ashrae()` and `schlick()` use `abs(aoi) >= 90`. The latter is more robust for negative angles and should be preferred.
- **Additional consideration:** The old code also had `iam = np.where(iam < 0, 0, iam)` which was removed. While not causing the reported bug, this might be needed for edge cases near 90° where floating-point precision could produce tiny negative values.

---

### Issue-First Hypothesizer — Round 2

**Root cause:** The `physical()` function was rewritten in commit a19b528 to add AR coating support, but the explicit check `iam = np.where(aoi > 90, 0, iam)` that handled AOI > 90 degrees was removed; when n=1 and AOI > 90, this causes 0/0 division in the reflectance calculations (specifically in `rho12_s` and `rho12_p` where denominators become 0), producing NaN instead of 0.

**Location:** `/testbed/pvlib/iam.py`, lines 155-218, specifically the `physical()` function. The missing check should be added just before the `return iam` statement at line 218.

**Proposed fix direction:** Add a check at the end of the function: `iam = np.where(np.abs(aoi) >= 90, 0, iam)`. This matches the pattern used in `ashrae()` (line 87) and `schlick()` (line 487) in the same file, using `abs(aoi)` to handle negative angles symmetrically.

**Supporting evidence:**
1. Reproduced the bug: Traced execution showing `physical(aoi=100, n=1)` produces NaN with RuntimeWarnings for "invalid value encountered in scalar divide"
2. Step-by-step trace: When n=1 and aoi=100, `costheta = max(0, cos(100°)) = 0`, `sintheta = 1`, after refraction `sintheta = 1/1 * 1 = 1`, so `costheta = sqrt(1-1) = 0`
3. This makes all `n*costheta` terms equal to 0, causing `rho12_s = ((0-0)/(0+0))**2 = 0/0 = NaN`
4. Git diff of commit a19b528 clearly shows the removal of `iam = np.where(aoi > 90, 0, iam)` from the old implementation
5. Other IAM functions (`ashrae`, `schlick`) in the same file use `iam = np.where(np.abs(aoi) >= 90.0, 0.0, iam)`, confirming the pattern

**Weaknesses:** I haven't tested edge cases with n very close to 1 (e.g., 1.0001) or verified if the old code's additional check `iam = np.where(iam < 0, 0, iam)` for tiny negative values near 90° is also needed.

**Confidence:** High. The evidence from git history, code tracing, and comparison with other functions in the same file is conclusive.

**Reactions:**
- **Agree with all investigators:** Our root cause analyses are essentially identical. The evidence confirms that the missing check is the issue.
- **Gap identified:** The old code used `aoi > 90` but `ashrae()` and `schlick()` use `abs(aoi) >= 90`. The latter is more robust for negative angles and should be preferred.
- **Additional consideration:** The old code also had `iam = np.where(iam < 0, 0, iam)` which was removed. While not causing the reported bug, this might be needed for edge cases near 90° where floating-point precision could produce tiny negative values.

---

### Minimal Diff Finder — Round 2

**Root cause:** The `physical()` function was refactored in commit a19b528 to add AR coating support, but the explicit check `iam = np.where(aoi > 90, 0, iam)` that handled AOI > 90 degrees was removed; when n=1 and AOI > 90, this causes 0/0 division in the reflectance calculations because all `n*costheta` terms become zero, producing NaN instead of 0.

**Location:** `/testbed/pvlib/iam.py`, lines 155-218, specifically the `physical()` function. The missing check should be added just before the `return iam` statement at line 218.

**Proposed fix direction:** Add a single line before the return statement: `iam = np.where(np.abs(aoi) >= 90, 0, iam)`. This matches the pattern used in `ashrae()` (line 87) and `schlick()` (line 487) in the same file, using `abs(aoi)` to handle negative angles symmetrically.

**Supporting evidence:**
1. Reproduced the bug: `physical(aoi=100, n=1)` returns `nan` with RuntimeWarnings for "invalid value encountered in scalar divide" and "divide by zero"
2. Step-by-step trace: When n=1 and aoi=100, `costheta = max(0, cos(100°)) = 0`, `sintheta = 1`, after refraction `sintheta = 1/1 * 1 = 1`, so `costheta = sqrt(1-1) = 0`
3. This makes all `n*costheta` terms equal to 0, causing `rho12_s = ((0-0)/(0+0))**2 = 0/0 = NaN`
4. Git diff of commit a19b528 clearly shows the removal of `iam = np.where(aoi > 90, 0, iam)` from the old implementation
5. Other IAM functions (`ashrae`, `schlick`) in the same file use `iam = np.where(np.abs(aoi) >= 90.0, 0.0, iam)`, confirming the pattern

**Weaknesses:** I haven't tested edge cases with n very close to 1 (e.g., 1.0001) or verified if the old code's additional check `iam = np.where(iam < 0, 0, iam)` for tiny negative values near 90° is also needed.

**Confidence:** High. The evidence from git history, code tracing, and comparison with other functions in the same file is conclusive.

**Reactions:**
- **Agree with all investigators:** Our root cause analyses are essentially identical. The evidence confirms that the missing check is the issue.
- **Gap identified:** The old code used `aoi > 90` but `ashrae()` and `schlick()` use `abs(aoi) >= 90`. The latter is more robust for negative angles and should be preferred.
- **Additional consideration:** The old code also had `iam = np.where(iam < 0, 0, iam)` which was removed. While not causing the reported bug, this might be needed for edge cases near 90° where floating-point precision could produce tiny negative values.
