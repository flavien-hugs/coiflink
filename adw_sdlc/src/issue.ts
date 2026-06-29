/**
 * GitHub-issue helpers the orchestrator's setup phase needs, ported from
 * adw/work_issue.py: branch derivation from issue metadata, issue-context
 * fetching (injected into token-less agent phases), and the best-effort
 * project-board status move.
 */

import { ghJson, note, runInherit } from './exec.js';

/**
 * Issue label -> branch prefix. Matched case-insensitively. Covers both the
 * namespaced `type:*` labels and plain (unnamespaced) labels (`bug`, `docs`,
 * `tech-debt`, `infra`, ...). Unlisted labels keep the "feat" default.
 */
export const TYPE_PREFIX: Record<string, string> = {
  'type:bug': 'fix',
  'type:docs': 'docs',
  'type:ci': 'ci',
  'type:testing': 'test',
  // Plain (unnamespaced) labels:
  bug: 'fix',
  docs: 'docs',
  documentation: 'docs',
  'tech-debt': 'refactor',
  infra: 'ci',
  ci: 'ci',
  test: 'test',
  testing: 'test',
  feature: 'feat',
};

/** Pick a branch prefix from issue labels (last match wins, case-insensitive). */
export function branchPrefix(labels: readonly string[]): string {
  let prefix = 'feat';
  for (const label of labels) {
    prefix = TYPE_PREFIX[label.toLowerCase()] ?? prefix;
  }
  return prefix;
}

/**
 * Slugify an issue title for use in a branch name: strips a leading
 * `Phase issue N:` prefix, lowercases, collapses runs of non-alphanumerics
 * to single hyphens, trims hyphens, and caps at 40 chars.
 */
export function slugifyTitle(title: string): string {
  const src = title.replace(/^Phase issue [0-9]+: */, '');
  const slug = src
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '') // strip diacritics so French titles slug cleanly
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug.slice(0, 40).replace(/-+$/, '');
}

/**
 * Derive a branch name `{prefix}/{issue}-[{adw_id}-]{slug}` for a phased run.
 * The optional adwId segment correlates the branch with its run state.
 */
export function deriveBranch(
  issue: number,
  title: string,
  labels: readonly string[],
  adwId?: string | null,
): string {
  const mid = adwId ? `${adwId}-` : '';
  return `${branchPrefix(labels)}/${issue}-${mid}${slugifyTitle(title)}`;
}

/** Issue context injected into the token-less agent phases. */
export interface IssueContext {
  title: string;
  body: string;
  labels: string[];
}

/** Fetch an issue's title/body/labels via gh, or null if unavailable. */
export function fetchIssue(ghBin: string | null, issue: number, repo: string): IssueContext | null {
  if (!ghBin) {
    return null;
  }
  const args = [ghBin, 'issue', 'view', String(issue)];
  if (repo) {
    args.push('--repo', repo);
  }
  args.push('--json', 'title,body,labels');
  const data = ghJson(args);
  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    return null;
  }
  const doc = data as Record<string, unknown>;
  const labels = Array.isArray(doc['labels'])
    ? doc['labels'].map((label) =>
        typeof label === 'object' && label !== null
          ? String((label as Record<string, unknown>)['name'] ?? '')
          : '',
      )
    : [];
  return {
    title: typeof doc['title'] === 'string' ? doc['title'] : '',
    body: typeof doc['body'] === 'string' ? doc['body'] : '',
    labels,
  };
}

function asObject(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/**
 * Best-effort move of the issue's project board card to `targetStatus`
 * (adw/work_issue.py:114-155). PROJECT_NUMBER comes from the parent env.
 */
export function setStatus(ghBin: string, owner: string, issue: number, targetStatus: string): void {
  const projectNumber = process.env['PROJECT_NUMBER'] ?? '1';

  const proj = asObject(ghJson([ghBin, 'project', 'view', projectNumber, '--owner', owner, '--format', 'json']));
  const projId = proj?.['id'];
  if (typeof projId !== 'string' || !projId) {
    note('project board not found; skipping status');
    return;
  }

  const items = asObject(
    ghJson([
      ghBin, 'project', 'item-list', projectNumber, '--owner', owner, '--format', 'json', '--limit', '300',
    ]),
  );
  const itemList = Array.isArray(items?.['items']) ? (items['items'] as unknown[]) : [];
  const item = itemList
    .map(asObject)
    .find((it) => it !== null && asObject(it['content'])?.['number'] === issue);
  const itemId = item?.['id'];
  if (typeof itemId !== 'string' || !itemId) {
    note('issue not on board; skipping status');
    return;
  }

  const fields = asObject(ghJson([ghBin, 'project', 'field-list', projectNumber, '--owner', owner, '--format', 'json']));
  const fieldList = Array.isArray(fields?.['fields']) ? (fields['fields'] as unknown[]) : [];
  const statusField = fieldList.map(asObject).find((f) => f !== null && f['name'] === 'Status') ?? null;
  const optionList = Array.isArray(statusField?.['options']) ? (statusField['options'] as unknown[]) : [];
  const option = optionList.map(asObject).find((o) => o !== null && o['name'] === targetStatus) ?? null;
  const optionId = option?.['id'];
  if (statusField === null || typeof optionId !== 'string' || !optionId) {
    note(`status option '${targetStatus}' not found; skipping`);
    return;
  }

  const rc = runInherit([
    ghBin, 'project', 'item-edit',
    '--id', itemId,
    '--project-id', projId,
    '--field-id', String(statusField['id']),
    '--single-select-option-id', optionId,
  ]);
  if (rc === 0) {
    note(`set board status of #${issue} -> ${targetStatus}`);
  } else {
    note('could not update board status');
  }
}
