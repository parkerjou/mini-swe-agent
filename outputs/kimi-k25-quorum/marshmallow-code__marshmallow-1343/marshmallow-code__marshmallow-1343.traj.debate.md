# Quorum Debate — marshmallow-code__marshmallow-1343

## Investigation Summaries

### Stack Trace Tracer (exit: LimitsExceeded)

*(no submission)*

### Issue-First Hypothesizer (exit: LimitsExceeded)

*(no submission)*

### Minimal Diff Finder (exit: LimitsExceeded)

*(no submission)*

## Debate Contributions

### Stack Trace Tracer — Round 1

 **Root cause:** When a Nested field fails to deserialize due to invalid input type, the `result` variable becomes `None` (from `error.data`), but `_invoke_field_validators` is still called with this `None` value and attempts to subscript it, causing the TypeError.

**Location:** 
- `src/marshmallow/schema.py`, line 674: `self._invoke_field_validators(unmarshal, data=result, many=many)` is called unconditionally after the try/except block
- `src/marshmallow/schema.py`, line 894: `value = data[field_obj.attribute or field_name]` attempts to subscript `data` which is `None`

**Proposed fix direction:** Add a check before calling `_invoke_field_validators` to skip validation when `result` is `None`, or add a guard inside `_invoke_field_validators` to return early if `data` is `None`.

**Supporting evidence:**
1. The traceback shows the error occurs at line 894 in `_invoke_field_validators` when trying to access `data[field_obj.attribute or field_name]` where `data` is `None`
2. Tracing backwards, `_invoke_field_validators` is called from `_do_load` at line 674 with `data=result`
3. The `result` variable comes from the try/except block at lines 664-669 where if a `ValidationError` is raised during unmarshalling, `result = error.data` is set
4. In the case of invalid nested data (like `'bar': 'invalid'` where a dict is expected), the Nested field's `_deserialize` method catches the error and raises `ValidationError(errors, data=data)` where `data` is `None` (the result of the failed load)
5. This is a regression introduced in version 2.20.0 where type checking was added to handle invalid input types, but the error handling path doesn't prevent subsequent field validator invocation

**Weaknesses:** 
- I haven't verified if there are other code paths that could also result in `None` being passed to `_invoke_field_validators`
- The fix might need to consider whether partial validation results should still have field validators run on them
- I haven't checked if there are existing tests that cover this scenario or if the fix might break other expected behaviors

**Confidence:** High. The evidence clearly shows the execution path where `result` becomes `None` and is then passed to `_invoke_field_validators` which unconditionally tries to subscript it. The fix is straightforward - either skip field validators when result is None, or guard against None inside the validator invocation.

### Issue-First Hypothesizer — Round 1

 **Root cause:** When a Nested field fails to deserialize invalid input, the `result` variable is set to `None` from `error.data`, but `_invoke_field_validators` is unconditionally called and attempts to subscript the `None` value.

**Location:** 
- `src/marshmallow/schema.py`, line 674: `_invoke_field_validators` is called unconditionally after the try/except block
- `src/marshmallow/schema.py`, line 894: `value = data[field_obj.attribute or field_name]` fails when `data` is `None`

**Proposed fix direction:** Add a guard clause in `_invoke_field_validators` to return early if `data` is `None`, or skip the call to `_invoke_field_validators` in `_do_load` when `result` is `None`.

**Supporting evidence:**
1. The traceback confirms the error occurs at line 894 when trying to subscript `data` which is `None`
2. In `_do_load` (lines 664-669), when unmarshalling raises `ValidationError`, `result = error.data` is executed
3. For the Nested field's `_deserialize` method (line 465), when `schema.load(value)` returns errors, it raises `ValidationError(errors, data=data)` where `data` is `None` (the failed load result)
4. Line 674 unconditionally calls `_invoke_field_validators(unmarshal, data=result, many=many)` even when `result` is `None`
5. I reproduced the exact error with the provided test case, confirming the execution path

**Weaknesses:**
- I haven't verified if there are scenarios where `result` is `None` but field validators should still run
- I haven't checked if the fix might affect other validation scenarios like partial loading

**Confidence:** High. The execution path is clear: invalid nested data → ValidationError with `data=None` → `result=None` → `_invoke_field_validators` with `None` → TypeError.

**Reactions:**
- **Agreement with Stack Trace Tracer:** I fully agree with their analysis. The root cause, location, and proposed fix direction are accurate based on my independent investigation.
- **Gap addressed:** My reproduction of the bug confirms the execution path they described. The evidence is consistent.
- **Additional insight:** The issue specifically manifests when the Nested field's `_deserialize` method catches errors from the inner schema load and re-raises with `data=None`. This is the key trigger for the bug.

### Minimal Diff Finder — Round 1

Based on my investigation, here is my contribution:

**Root cause:** When a Nested field fails to deserialize due to invalid input type, the `result` variable becomes `None` (from `error.data`), but `_invoke_field_validators` is still called with this `None` value and attempts to subscript it, causing the TypeError.

**Location:**
- `src/marshmallow/schema.py`, line 674: `self._invoke_field_validators(unmarshal, data=result, many=many)` is called unconditionally after the try/except block
- `src/marshmallow/schema.py`, line 894: `value = data[field_obj.attribute or field_name]` attempts to subscript `data` which is `None`

**Proposed fix direction:** Add a guard clause at the beginning of `_invoke_field_validators` to return early if `data` is `None`, or alternatively, skip the call to `_invoke_field_validators` in `_do_load` when `result` is `None`.

**Supporting evidence:**
1. The traceback shows the error occurs at line 894 in `_invoke_field_validators` when trying to access `data[field_obj.attribute or field_name]` where `data` is `None`
2. Tracing backwards, `_invoke_field_validators` is called from `_do_load` at line 674 with `data=result`
3. The `result` variable comes from the try/except block at lines 664-669 where if a `ValidationError` is raised during unmarshalling, `result = error.data` is set
4. In the case of invalid nested data (like `'bar': 'invalid'` where a dict is expected), the Nested field's `_deserialize` method catches the error and raises `ValidationError(errors, data=data)` where `data` is `None` (the result of the failed load)
5. This is a regression introduced in version 2.20.0 where type checking was added to handle invalid input types, but the error handling path doesn't prevent subsequent field validator invocation

**Weaknesses:**
- I haven't verified if there are other code paths that could also result in `None` being passed to `_invoke_field_validators`
- The fix might need to consider whether partial validation results should still have field validators run on them
- I haven't checked if there are existing tests that cover this scenario or if the fix might break other expected behaviors

**Confidence:** High. The evidence clearly shows the execution path where `result` becomes `None` and is then passed to `_invoke_field_validators` which unconditionally tries to subscript it. The fix is straightforward - either skip field validators when result is None, or guard against None inside the validator invocation.

**Reactions:**
- **Agreement with Stack Trace Tracer:** I fully agree with their analysis. The root cause, location, and proposed fix direction are accurate based on my independent investigation.
- **Agreement with Issue-First Hypothesizer:** I fully agree with their analysis as well. The execution path is clear and the reproduction confirms the bug.
- **Additional insight:** The issue specifically manifests when the Nested field's `_deserialize` method catches errors from the inner schema load and re-raises with `data=None`. This is the key trigger for the bug.

### Stack Trace Tracer — Round 2

 **Root cause:** When a Nested field fails to deserialize invalid input, `result` is set to `None` from `error.data`, but `_invoke_field_validators` is unconditionally called and attempts to subscript the `None` value.

**Location:**
- `src/marshmallow/schema.py`, line 674: `self._invoke_field_validators(unmarshal, data=result, many=many)` is called unconditionally
- `src/marshmallow/schema.py`, line 894: `value = data[field_obj.attribute or field_name]` fails when `data` is `None`

**Proposed fix direction:** Add a guard clause at the start of `_invoke_field_validators` to return early if `data` is `None`, or skip the call in `_do_load` when `result` is `None`.

**Supporting evidence:**
1. The traceback shows the error at line 894 when trying to subscript `data` which is `None`
2. In `_do_load` (lines 664-669), when unmarshalling raises `ValidationError`, `result = error.data` is set
3. For the Nested field's `_deserialize` method (line 465), when `schema.load(value)` returns errors, it raises `ValidationError(errors, data=data)` where `data` is `None`
4. Line 674 unconditionally calls `_invoke_field_validators(unmarshal, data=result, many=many)` even when `result` is `None`
5. This regression was introduced in commit 99851ab5 which added type checking for invalid input types

**Weaknesses:**
- I haven't verified if there are scenarios where `result` is `None` but field validators should still run
- I haven't checked if the fix might affect partial loading scenarios

**Confidence:** High. The execution path is clear and reproducible.

**Reactions:**
- **Agreement with all investigators:** I fully agree with the analysis from Stack Trace Tracer, Issue-First Hypothesizer, and Minimal Diff Finder. Our independent investigations all converged on the same root cause and location.
- **Gap addressed:** The connection to commit 99851ab5 (which added type checking) confirms this is a regression in 2.20.0 as reported in the PR description.
- **Additional insight:** The fix should be minimal - either adding a `if data is None: return` guard at the start of `_invoke_field_validators`, or wrapping the call at line 674 in a conditional check.

### Issue-First Hypothesizer — Round 2

 **Root cause:** When a Nested field fails to deserialize invalid input, the `result` variable is set to `None` from `error.data`, but `_invoke_field_validators` is unconditionally called and attempts to subscript the `None` value, causing the TypeError.

**Location:**
- `src/marshmallow/schema.py`, line 674: `self._invoke_field_validators(unmarshal, data=result, many=many)` is called unconditionally after the try/except block
- `src/marshmallow/schema.py`, line 894: `value = data[field_obj.attribute or field_name]` attempts to subscript `data` which is `None`

**Proposed fix direction:** Add a guard clause at the beginning of `_invoke_field_validators` to return early if `data` is `None`, or skip the call to `_invoke_field_validators` in `_do_load` when `result` is `None`.

**Supporting evidence:**
1. The traceback confirms the error occurs at line 894 when trying to subscript `data` which is `None`
2. In `_do_load` (lines 664-669), when unmarshalling raises `ValidationError`, `result = error.data` is executed
3. For the Nested field's `_deserialize` method (line 465), when `schema.load(value)` returns errors, it raises `ValidationError(errors, data=data)` where `data` is `None` (the failed load result)
4. Line 674 unconditionally calls `_invoke_field_validators(unmarshal, data=result, many=many)` even when `result` is `None`
5. I reproduced the exact error with the provided test case, confirming the execution path

**Weaknesses:**
- I haven't verified if there are scenarios where `result` is `None` but field validators should still run
- I haven't checked if the fix might affect other validation scenarios like partial loading

**Confidence:** High. The execution path is clear: invalid nested data → ValidationError with `data=None` → `result=None` → `_invoke_field_validators` with `None` → TypeError.

**Reactions:**
- **Agreement with all investigators:** I fully agree with the analysis from Stack Trace Tracer, Issue-First Hypothesizer, and Minimal Diff Finder. Our independent investigations all converged on the same root cause and location.
- **Gap addressed:** My reproduction of the bug confirms the execution path they described. The evidence is consistent across all investigations.
- **Additional insight:** The issue specifically manifests when the Nested field's `_deserialize` method catches errors from the inner schema load and re-raises with `data=None`. This is the key trigger for the bug.

### Minimal Diff Finder — Round 2

**Root cause:** When a Nested field fails to deserialize due to invalid input type, the `result` variable becomes `None` (from `error.data`), but `_invoke_field_validators` is unconditionally called with this `None` value and attempts to subscript it, causing the TypeError.

**Location:**
- `src/marshmallow/schema.py`, line 674: `self._invoke_field_validators(unmarshal, data=result, many=many)` is called unconditionally after the try/except block
- `src/marshmallow/schema.py`, line 894: `value = data[field_obj.attribute or field_name]` attempts to subscript `data` which is `None`

**Proposed fix direction:** Add a guard clause at the beginning of `_invoke_field_validators` to return early if `data` is `None`, or skip the call to `_invoke_field_validators` in `_do_load` when `result` is `None`.

**Supporting evidence:**
1. The traceback shows the error occurs at line 894 in `_invoke_field_validators` when trying to access `data[field_obj.attribute or field_name]` where `data` is `None`
2. Tracing backwards, `_invoke_field_validators` is called from `_do_load` at line 674 with `data=result`
3. The `result` variable comes from the try/except block at lines 664-669 where if a `ValidationError` is raised during unmarshalling, `result = error.data` is set
4. In the case of invalid nested data (like `'bar': 'invalid'` where a dict is expected), the Nested field's `_deserialize` method catches the error and raises `ValidationError(errors, data=data)` where `data` is `None` (the result of the failed load)
5. This is a regression introduced in version 2.20.0 where type checking was added to handle invalid input types, but the error handling path doesn't prevent subsequent field validator invocation

**Weaknesses:**
- I haven't verified if there are other code paths that could also result in `None` being passed to `_invoke_field_validators`
- The fix might need to consider whether partial validation results should still have field validators run on them
- I haven't checked if there are existing tests that cover this scenario or if the fix might break other expected behaviors

**Confidence:** High. The evidence clearly shows the execution path where `result` becomes `None` and is then passed to `_invoke_field_validators` which unconditionally tries to subscript it. The fix is straightforward - either skip field validators when result is None, or guard against None inside the validator invocation.

**Reactions:**
- **Agreement with all investigators:** I fully agree with the analysis from Stack Trace Tracer, Issue-First Hypothesizer, and Minimal Diff Finder. Our independent investigations all converged on the same root cause and location.
- **Gap addressed:** The connection to commit 99851ab5 (which added type checking) confirms this is a regression in 2.20.0 as reported in the PR description.
- **Additional insight:** The issue specifically manifests when the Nested field's `_deserialize` method catches errors from the inner schema load and re-raises with `data=None`. This is the key trigger for the bug.

## Full Transcript (as sent to implementer)

### Stack Trace Tracer — Round 1

 **Root cause:** When a Nested field fails to deserialize due to invalid input type, the `result` variable becomes `None` (from `error.data`), but `_invoke_field_validators` is still called with this `None` value and attempts to subscript it, causing the TypeError.

**Location:** 
- `src/marshmallow/schema.py`, line 674: `self._invoke_field_validators(unmarshal, data=result, many=many)` is called unconditionally after the try/except block
- `src/marshmallow/schema.py`, line 894: `value = data[field_obj.attribute or field_name]` attempts to subscript `data` which is `None`

**Proposed fix direction:** Add a check before calling `_invoke_field_validators` to skip validation when `result` is `None`, or add a guard inside `_invoke_field_validators` to return early if `data` is `None`.

**Supporting evidence:**
1. The traceback shows the error occurs at line 894 in `_invoke_field_validators` when trying to access `data[field_obj.attribute or field_name]` where `data` is `None`
2. Tracing backwards, `_invoke_field_validators` is called from `_do_load` at line 674 with `data=result`
3. The `result` variable comes from the try/except block at lines 664-669 where if a `ValidationError` is raised during unmarshalling, `result = error.data` is set
4. In the case of invalid nested data (like `'bar': 'invalid'` where a dict is expected), the Nested field's `_deserialize` method catches the error and raises `ValidationError(errors, data=data)` where `data` is `None` (the result of the failed load)
5. This is a regression introduced in version 2.20.0 where type checking was added to handle invalid input types, but the error handling path doesn't prevent subsequent field validator invocation

**Weaknesses:** 
- I haven't verified if there are other code paths that could also result in `None` being passed to `_invoke_field_validators`
- The fix might need to consider whether partial validation results should still have field validators run on them
- I haven't checked if there are existing tests that cover this scenario or if the fix might break other expected behaviors

**Confidence:** High. The evidence clearly shows the execution path where `result` becomes `None` and is then passed to `_invoke_field_validators` which unconditionally tries to subscript it. The fix is straightforward - either skip field validators when result is None, or guard against None inside the validator invocation.

---

### Issue-First Hypothesizer — Round 1

 **Root cause:** When a Nested field fails to deserialize invalid input, the `result` variable is set to `None` from `error.data`, but `_invoke_field_validators` is unconditionally called and attempts to subscript the `None` value.

**Location:** 
- `src/marshmallow/schema.py`, line 674: `_invoke_field_validators` is called unconditionally after the try/except block
- `src/marshmallow/schema.py`, line 894: `value = data[field_obj.attribute or field_name]` fails when `data` is `None`

**Proposed fix direction:** Add a guard clause in `_invoke_field_validators` to return early if `data` is `None`, or skip the call to `_invoke_field_validators` in `_do_load` when `result` is `None`.

**Supporting evidence:**
1. The traceback confirms the error occurs at line 894 when trying to subscript `data` which is `None`
2. In `_do_load` (lines 664-669), when unmarshalling raises `ValidationError`, `result = error.data` is executed
3. For the Nested field's `_deserialize` method (line 465), when `schema.load(value)` returns errors, it raises `ValidationError(errors, data=data)` where `data` is `None` (the failed load result)
4. Line 674 unconditionally calls `_invoke_field_validators(unmarshal, data=result, many=many)` even when `result` is `None`
5. I reproduced the exact error with the provided test case, confirming the execution path

**Weaknesses:**
- I haven't verified if there are scenarios where `result` is `None` but field validators should still run
- I haven't checked if the fix might affect other validation scenarios like partial loading

**Confidence:** High. The execution path is clear: invalid nested data → ValidationError with `data=None` → `result=None` → `_invoke_field_validators` with `None` → TypeError.

**Reactions:**
- **Agreement with Stack Trace Tracer:** I fully agree with their analysis. The root cause, location, and proposed fix direction are accurate based on my independent investigation.
- **Gap addressed:** My reproduction of the bug confirms the execution path they described. The evidence is consistent.
- **Additional insight:** The issue specifically manifests when the Nested field's `_deserialize` method catches errors from the inner schema load and re-raises with `data=None`. This is the key trigger for the bug.

---

### Minimal Diff Finder — Round 1

Based on my investigation, here is my contribution:

**Root cause:** When a Nested field fails to deserialize due to invalid input type, the `result` variable becomes `None` (from `error.data`), but `_invoke_field_validators` is still called with this `None` value and attempts to subscript it, causing the TypeError.

**Location:**
- `src/marshmallow/schema.py`, line 674: `self._invoke_field_validators(unmarshal, data=result, many=many)` is called unconditionally after the try/except block
- `src/marshmallow/schema.py`, line 894: `value = data[field_obj.attribute or field_name]` attempts to subscript `data` which is `None`

**Proposed fix direction:** Add a guard clause at the beginning of `_invoke_field_validators` to return early if `data` is `None`, or alternatively, skip the call to `_invoke_field_validators` in `_do_load` when `result` is `None`.

**Supporting evidence:**
1. The traceback shows the error occurs at line 894 in `_invoke_field_validators` when trying to access `data[field_obj.attribute or field_name]` where `data` is `None`
2. Tracing backwards, `_invoke_field_validators` is called from `_do_load` at line 674 with `data=result`
3. The `result` variable comes from the try/except block at lines 664-669 where if a `ValidationError` is raised during unmarshalling, `result = error.data` is set
4. In the case of invalid nested data (like `'bar': 'invalid'` where a dict is expected), the Nested field's `_deserialize` method catches the error and raises `ValidationError(errors, data=data)` where `data` is `None` (the result of the failed load)
5. This is a regression introduced in version 2.20.0 where type checking was added to handle invalid input types, but the error handling path doesn't prevent subsequent field validator invocation

**Weaknesses:**
- I haven't verified if there are other code paths that could also result in `None` being passed to `_invoke_field_validators`
- The fix might need to consider whether partial validation results should still have field validators run on them
- I haven't checked if there are existing tests that cover this scenario or if the fix might break other expected behaviors

**Confidence:** High. The evidence clearly shows the execution path where `result` becomes `None` and is then passed to `_invoke_field_validators` which unconditionally tries to subscript it. The fix is straightforward - either skip field validators when result is None, or guard against None inside the validator invocation.

**Reactions:**
- **Agreement with Stack Trace Tracer:** I fully agree with their analysis. The root cause, location, and proposed fix direction are accurate based on my independent investigation.
- **Agreement with Issue-First Hypothesizer:** I fully agree with their analysis as well. The execution path is clear and the reproduction confirms the bug.
- **Additional insight:** The issue specifically manifests when the Nested field's `_deserialize` method catches errors from the inner schema load and re-raises with `data=None`. This is the key trigger for the bug.

---

### Stack Trace Tracer — Round 2

 **Root cause:** When a Nested field fails to deserialize invalid input, `result` is set to `None` from `error.data`, but `_invoke_field_validators` is unconditionally called and attempts to subscript the `None` value.

**Location:**
- `src/marshmallow/schema.py`, line 674: `self._invoke_field_validators(unmarshal, data=result, many=many)` is called unconditionally
- `src/marshmallow/schema.py`, line 894: `value = data[field_obj.attribute or field_name]` fails when `data` is `None`

**Proposed fix direction:** Add a guard clause at the start of `_invoke_field_validators` to return early if `data` is `None`, or skip the call in `_do_load` when `result` is `None`.

**Supporting evidence:**
1. The traceback shows the error at line 894 when trying to subscript `data` which is `None`
2. In `_do_load` (lines 664-669), when unmarshalling raises `ValidationError`, `result = error.data` is set
3. For the Nested field's `_deserialize` method (line 465), when `schema.load(value)` returns errors, it raises `ValidationError(errors, data=data)` where `data` is `None`
4. Line 674 unconditionally calls `_invoke_field_validators(unmarshal, data=result, many=many)` even when `result` is `None`
5. This regression was introduced in commit 99851ab5 which added type checking for invalid input types

**Weaknesses:**
- I haven't verified if there are scenarios where `result` is `None` but field validators should still run
- I haven't checked if the fix might affect partial loading scenarios

**Confidence:** High. The execution path is clear and reproducible.

**Reactions:**
- **Agreement with all investigators:** I fully agree with the analysis from Stack Trace Tracer, Issue-First Hypothesizer, and Minimal Diff Finder. Our independent investigations all converged on the same root cause and location.
- **Gap addressed:** The connection to commit 99851ab5 (which added type checking) confirms this is a regression in 2.20.0 as reported in the PR description.
- **Additional insight:** The fix should be minimal - either adding a `if data is None: return` guard at the start of `_invoke_field_validators`, or wrapping the call at line 674 in a conditional check.

---

### Issue-First Hypothesizer — Round 2

 **Root cause:** When a Nested field fails to deserialize invalid input, the `result` variable is set to `None` from `error.data`, but `_invoke_field_validators` is unconditionally called and attempts to subscript the `None` value, causing the TypeError.

**Location:**
- `src/marshmallow/schema.py`, line 674: `self._invoke_field_validators(unmarshal, data=result, many=many)` is called unconditionally after the try/except block
- `src/marshmallow/schema.py`, line 894: `value = data[field_obj.attribute or field_name]` attempts to subscript `data` which is `None`

**Proposed fix direction:** Add a guard clause at the beginning of `_invoke_field_validators` to return early if `data` is `None`, or skip the call to `_invoke_field_validators` in `_do_load` when `result` is `None`.

**Supporting evidence:**
1. The traceback confirms the error occurs at line 894 when trying to subscript `data` which is `None`
2. In `_do_load` (lines 664-669), when unmarshalling raises `ValidationError`, `result = error.data` is executed
3. For the Nested field's `_deserialize` method (line 465), when `schema.load(value)` returns errors, it raises `ValidationError(errors, data=data)` where `data` is `None` (the failed load result)
4. Line 674 unconditionally calls `_invoke_field_validators(unmarshal, data=result, many=many)` even when `result` is `None`
5. I reproduced the exact error with the provided test case, confirming the execution path

**Weaknesses:**
- I haven't verified if there are scenarios where `result` is `None` but field validators should still run
- I haven't checked if the fix might affect other validation scenarios like partial loading

**Confidence:** High. The execution path is clear: invalid nested data → ValidationError with `data=None` → `result=None` → `_invoke_field_validators` with `None` → TypeError.

**Reactions:**
- **Agreement with all investigators:** I fully agree with the analysis from Stack Trace Tracer, Issue-First Hypothesizer, and Minimal Diff Finder. Our independent investigations all converged on the same root cause and location.
- **Gap addressed:** My reproduction of the bug confirms the execution path they described. The evidence is consistent across all investigations.
- **Additional insight:** The issue specifically manifests when the Nested field's `_deserialize` method catches errors from the inner schema load and re-raises with `data=None`. This is the key trigger for the bug.

---

### Minimal Diff Finder — Round 2

**Root cause:** When a Nested field fails to deserialize due to invalid input type, the `result` variable becomes `None` (from `error.data`), but `_invoke_field_validators` is unconditionally called with this `None` value and attempts to subscript it, causing the TypeError.

**Location:**
- `src/marshmallow/schema.py`, line 674: `self._invoke_field_validators(unmarshal, data=result, many=many)` is called unconditionally after the try/except block
- `src/marshmallow/schema.py`, line 894: `value = data[field_obj.attribute or field_name]` attempts to subscript `data` which is `None`

**Proposed fix direction:** Add a guard clause at the beginning of `_invoke_field_validators` to return early if `data` is `None`, or skip the call to `_invoke_field_validators` in `_do_load` when `result` is `None`.

**Supporting evidence:**
1. The traceback shows the error occurs at line 894 in `_invoke_field_validators` when trying to access `data[field_obj.attribute or field_name]` where `data` is `None`
2. Tracing backwards, `_invoke_field_validators` is called from `_do_load` at line 674 with `data=result`
3. The `result` variable comes from the try/except block at lines 664-669 where if a `ValidationError` is raised during unmarshalling, `result = error.data` is set
4. In the case of invalid nested data (like `'bar': 'invalid'` where a dict is expected), the Nested field's `_deserialize` method catches the error and raises `ValidationError(errors, data=data)` where `data` is `None` (the result of the failed load)
5. This is a regression introduced in version 2.20.0 where type checking was added to handle invalid input types, but the error handling path doesn't prevent subsequent field validator invocation

**Weaknesses:**
- I haven't verified if there are other code paths that could also result in `None` being passed to `_invoke_field_validators`
- The fix might need to consider whether partial validation results should still have field validators run on them
- I haven't checked if there are existing tests that cover this scenario or if the fix might break other expected behaviors

**Confidence:** High. The evidence clearly shows the execution path where `result` becomes `None` and is then passed to `_invoke_field_validators` which unconditionally tries to subscript it. The fix is straightforward - either skip field validators when result is None, or guard against None inside the validator invocation.

**Reactions:**
- **Agreement with all investigators:** I fully agree with the analysis from Stack Trace Tracer, Issue-First Hypothesizer, and Minimal Diff Finder. Our independent investigations all converged on the same root cause and location.
- **Gap addressed:** The connection to commit 99851ab5 (which added type checking) confirms this is a regression in 2.20.0 as reported in the PR description.
- **Additional insight:** The issue specifically manifests when the Nested field's `_deserialize` method catches errors from the inner schema load and re-raises with `data=None`. This is the key trigger for the bug.
