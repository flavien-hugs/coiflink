/**
 * Per-phase result schemas (PLAN.md Section 7), ported from the Python
 * dataclasses + `to_result` coercion in adw/_phases.py:209-353 and the
 * OUTPUT_CONTRACT at adw/_phases.py:397-410.
 *
 * Dual role: (a) the JSON Schema handed to native-schema backends is derived
 * from these via z.toJSONSchema(); (b) the parent ALWAYS re-validates runner
 * output against them (defense in depth), whatever the backend claims.
 *
 * Tolerance mirrors the Python reader where it is load-bearing: missing keys
 * default (to_result uses dict.get defaults throughout), integer counters
 * coerce from strings (_as_int exists because agents emit "2"), booleans
 * coerce via Python truthiness (to_result wraps every flag in bool(); a
 * native-schema backend can return success with a freestyle payload, so
 * "tests_added": [<the tests>] must coerce to true, and [] to false — JS
 * truthiness would get [] wrong), and scalar strings/list entries coerce via
 * str(). Deliberate tightenings vs Python, kept loud on purpose:
 * issue_class is the 7-value enum from OUTPUT_CONTRACT (Python accepts any
 * non-empty string); a container where a string belongs fails instead of
 * becoming repr() garbage; a bare string where a list belongs fails instead
 * of char-splitting (Python's list("a.rs")); non-scalar list entries drop.
 */

import { z } from 'zod';

import { AdwError } from './errors.js';
import type { JsonSchema } from './invoker.js';

export const ISSUE_CLASSES = ['feat', 'fix', 'docs', 'chore', 'ci', 'test', 'refactor'] as const;

/** Counter fields: agents sometimes emit "2"; mirror Python _as_int coercion. */
const count = z.coerce.number().int().default(0);

export const ClassifySchema = z.object({
  issue_class: z.enum(ISSUE_CLASSES),
  reason: z.string().default(''),
});

export const PlanResultSchema = z.object({
  plan_file: z.string().nullable().default(null),
  spec_created: z.boolean().default(false),
  summary: z.string().default(''),
});

export const ImplementResultSchema = z.object({
  summary: z.string().default(''),
  files_changed: z.array(z.string()).default([]),
});

export const TestsResultSchema = z.object({
  tests_added: z.boolean().default(false),
  summary: z.string().default(''),
});

export const ResolveResultSchema = z.object({
  resolved: count,
  remaining: count,
  summary: z.string().default(''),
});

export const E2EResultSchema = z.object({
  e2e_added: z.boolean().default(false),
  summary: z.string().default(''),
});

export const ReviewFindingSchema = z.object({
  // severity drives the patch blocker gate; default mirrors _phases.py:327.
  severity: z.string().default('skippable'),
  description: z.string().default(''),
  location: z.string().default(''),
});

export const ReviewResultSchema = z.object({
  findings: z.array(ReviewFindingSchema).default([]),
  // Commit message / PR body are authored to workspace files, not inlined.
  wrote_commit_message: z.boolean().default(false),
  wrote_pr_body: z.boolean().default(false),
});

export const PatchResultSchema = z.object({
  resolved: count,
  remaining: count,
  summary: z.string().default(''),
});

export const DocumentResultSchema = z.object({
  docs_updated: z.boolean().default(false),
  files: z.array(z.string()).default([]),
  summary: z.string().default(''),
  wrote_commit_message: z.boolean().default(false),
  wrote_pr_body: z.boolean().default(false),
});

export const PHASE_SCHEMAS = {
  classify: ClassifySchema,
  plan: PlanResultSchema,
  implement: ImplementResultSchema,
  tests: TestsResultSchema,
  resolve: ResolveResultSchema,
  e2e: E2EResultSchema,
  review: ReviewResultSchema,
  patch: PatchResultSchema,
  document: DocumentResultSchema,
} as const;

export type SchemaPhase = keyof typeof PHASE_SCHEMAS;

export type ClassifyResult = z.infer<typeof ClassifySchema>;
export type PlanResult = z.infer<typeof PlanResultSchema>;
export type ImplementResult = z.infer<typeof ImplementResultSchema>;
export type TestsResult = z.infer<typeof TestsResultSchema>;
export type ResolveResult = z.infer<typeof ResolveResultSchema>;
export type E2EResult = z.infer<typeof E2EResultSchema>;
export type ReviewFinding = z.infer<typeof ReviewFindingSchema>;
export type ReviewResult = z.infer<typeof ReviewResultSchema>;
export type PatchResult = z.infer<typeof PatchResultSchema>;
export type DocumentResult = z.infer<typeof DocumentResultSchema>;

/**
 * JSON Schema for a phase, for backends with native schema output
 * (claude outputFormat, codex outputSchema, opencode v2 format). Uses zod
 * v4's native conversion — the plan's zod-to-json-schema dep is unnecessary.
 */
export function phaseJsonSchema(phase: SchemaPhase): JsonSchema {
  // Drop the $schema meta-key: claude's --json-schema validator (ajv, draft-07)
  // rejects zod v4's draft 2020-12 identifier, and the shapes emitted here are
  // draft-agnostic anyway.
  const { $schema: _, ...schema } = z.toJSONSchema(PHASE_SCHEMAS[phase]) as Record<string, unknown>;
  return schema as JsonSchema;
}

/** Python bool() over JSON values: bool([]) and bool({}) are False, bool("false") is True. */
function pythonTruthy(value: unknown): boolean {
  if (typeof value === 'number') {
    return value !== 0;
  }
  if (typeof value === 'string') {
    return value !== '';
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  if (typeof value === 'object') {
    return value !== null && Object.keys(value).length > 0;
  }
  return Boolean(value);
}

/** Python str() for the scalars agents actually emit; containers pass through to fail validation. */
function coerceScalarString(value: unknown): unknown {
  return typeof value === 'number' || typeof value === 'boolean' ? String(value) : value;
}

/**
 * Per-phase coercion targets, the TS twin of to_result's explicit bool()/str()
 * wrapping (adw/_phases.py:293-353). Counter fields are absent on purpose:
 * `count` already coerces numeric strings at the schema layer.
 */
const BOOL_FIELDS: Partial<Record<SchemaPhase, readonly string[]>> = {
  plan: ['spec_created'],
  tests: ['tests_added'],
  e2e: ['e2e_added'],
  review: ['wrote_commit_message', 'wrote_pr_body'],
  document: ['docs_updated', 'wrote_commit_message', 'wrote_pr_body'],
};

const STRING_FIELDS: Partial<Record<SchemaPhase, readonly string[]>> = {
  classify: ['reason'],
  plan: ['summary'], // plan_file stays untouched: string|null IS its contract
  implement: ['summary'],
  tests: ['summary'],
  resolve: ['summary'],
  e2e: ['summary'],
  patch: ['summary'],
  document: ['summary'],
};

const LIST_OF_STRING_FIELDS: Partial<Record<SchemaPhase, readonly string[]>> = {
  implement: ['files_changed'],
  document: ['files'],
};

/** Float counters truncate like Python int(2.7) == 2; "2.7" still fails, as int("2.7") does. */
const FLOAT_TRUNC_FIELDS: Partial<Record<SchemaPhase, readonly string[]>> = {
  resolve: ['resolved', 'remaining'],
  patch: ['resolved', 'remaining'],
};

/**
 * Parse a raw runner payload with to_result's tolerance (adw/_phases.py:293-353):
 * non-object payloads and unparseable values raise AdwError; null-valued fields
 * fall back to their defaults (real agents emit null for empty lists — Python
 * guards every list with `or []`); booleans/strings/list entries coerce per the
 * tables above; non-dict entries inside review findings are dropped
 * (adw/_phases.py:332). The schemas themselves stay coercion-free so
 * phaseJsonSchema() keeps asking backends for the clean canonical shape.
 */
export function parsePhaseResult<P extends SchemaPhase>(
  phase: P,
  data: unknown,
): z.infer<(typeof PHASE_SCHEMAS)[P]> {
  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    throw new AdwError(`${phase} phase output must be a JSON object`);
  }
  const normalized: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(data)) {
    if (value === null) {
      continue; // defaults apply, mirroring `data.get(key, default) or default`
    }
    normalized[key] = value;
  }
  if (typeof normalized['issue_class'] === 'string') {
    // Python strips issue_class before validating (adw/_phases.py:299);
    // without this, " feat " would pass the py engine and fail the ts one.
    normalized['issue_class'] = normalized['issue_class'].trim();
  }
  for (const key of BOOL_FIELDS[phase] ?? []) {
    if (key in normalized) {
      normalized[key] = pythonTruthy(normalized[key]);
    }
  }
  for (const key of STRING_FIELDS[phase] ?? []) {
    if (key in normalized) {
      normalized[key] = coerceScalarString(normalized[key]);
    }
  }
  for (const key of LIST_OF_STRING_FIELDS[phase] ?? []) {
    const value = normalized[key];
    if (Array.isArray(value)) {
      normalized[key] = value
        .map(coerceScalarString)
        .filter((entry): entry is string => typeof entry === 'string');
    }
  }
  for (const key of FLOAT_TRUNC_FIELDS[phase] ?? []) {
    const value = normalized[key];
    if (typeof value === 'number' && Number.isFinite(value)) {
      normalized[key] = Math.trunc(value);
    }
  }
  if (phase === 'review' && Array.isArray(normalized['findings'])) {
    normalized['findings'] = normalized['findings']
      .filter((f): f is Record<string, unknown> => typeof f === 'object' && f !== null && !Array.isArray(f))
      .map((f) => {
        const finding = { ...f };
        for (const key of ['severity', 'description', 'location']) {
          if (finding[key] === null) {
            delete finding[key]; // defaults apply, same as the top-level null strip
          } else if (key in finding) {
            finding[key] = coerceScalarString(finding[key]);
          }
        }
        return finding;
      });
  }
  const parsed = PHASE_SCHEMAS[phase].safeParse(normalized);
  if (!parsed.success) {
    throw new AdwError(`${phase} phase output does not match its contract: ${parsed.error.message}`, {
      cause: parsed.error,
    });
  }
  return parsed.data as z.infer<(typeof PHASE_SCHEMAS)[P]>;
}
