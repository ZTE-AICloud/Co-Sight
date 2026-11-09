// SPDX-License-Identifier: Apache-2.0
/**
 * @file Detects whether the dashboard git checkout is behind the canonical
 * remote default branch (e.g. upstream/master on a fork, origin/master on a
 * direct clone) after a non-destructive fetch. Branch- and fork-aware:
 * picks the right remote, recognises feature-branch checkouts, and shapes
 * manual_command so it actually closes the gap for the user's situation.
 */

const fs = require("fs");
const path = require("path");
const { execFile } = require("child_process");

const DEFAULT_ROOT = path.join(__dirname, "..", "..");

// Standard convention for fork workflows: "upstream" points at the canonical
// repo, "origin" points at the user's fork. Prefer upstream when both exist.
const REMOTE_PRIORITY = ["upstream", "origin"];

function execGit(cwd, args, opts = {}) {
  const timeout = opts.timeout ?? 120_000;
  return new Promise((resolve, reject) => {
    execFile(
      "git",
      args,
      { cwd, timeout, maxBuffer: 2_000_000, encoding: "utf8", windowsHide: true },
      (err, stdout) => {
        if (err) reject(err);
        else resolve(String(stdout).trim());
      }
    );
  });
}

async function listRemotes(gitRoot) {
  try {
    const out = await execGit(gitRoot, ["remote"], { timeout: 10_000 });
    return out
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean);
  } catch {
    return [];
  }
}

async function pickCanonicalRemote(gitRoot) {
  const remotes = await listRemotes(gitRoot);
  for (const candidate of REMOTE_PRIORITY) {
    if (remotes.includes(candidate)) return candidate;
  }
  return remotes[0] || null;
}

async function resolveCompareRefForRemote(gitRoot, remote) {
  const tryRefs = [`${remote}/master`, `${remote}/main`];
  for (const ref of tryRefs) {
    try {
      await execGit(gitRoot, ["rev-parse", "--verify", ref], { timeout: 10_000 });
      return ref;
    } catch {
      // continue
    }
  }
  try {
    const sym = await execGit(gitRoot, ["symbolic-ref", `refs/remotes/${remote}/HEAD`], {
      timeout: 10_000,
    });
    const m = sym.match(/^refs\/remotes\/(.+)$/);
    if (m) return m[1];
  } catch {
    // ignore
  }
  return null;
}

async function getCurrentBranch(gitRoot) {
  try {
    const branch = await execGit(gitRoot, ["symbolic-ref", "--short", "HEAD"], {
      timeout: 10_000,
    });
    return branch || null;
  } catch {
    return null; // detached HEAD
  }
}

async function getBranchUpstream(gitRoot) {
  try {
    return await execGit(gitRoot, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], {
      timeout: 10_000,
    });
  } catch {
    return null; // no tracking branch configured
  }
}

function stripRemotePrefix(ref) {
  // "upstream/master" -> "master"; "origin/feature/foo" -> "feature/foo"
  const idx = ref.indexOf("/");
  return idx === -1 ? ref : ref.slice(idx + 1);
}

/**
 * @param {string} [gitRoot]
 * @param {{ skipFetch?: boolean }} [options]
 * @returns {Promise<object>}
 */
async function getUpdatesStatus(gitRoot = DEFAULT_ROOT, options = {}) {
  const root = path.resolve(gitRoot);
  const gitDir = path.join(root, ".git");
  if (!fs.existsSync(gitDir)) {
    return {
      git_repo: false,
      update_available: false,
      repo_root: root,
      manual_command: null,
      message: "Install directory is not a git clone; check for updates manually.",
    };
  }

  const canonicalRemote = await pickCanonicalRemote(root);
  if (!canonicalRemote) {
    return {
      git_repo: true,
      update_available: false,
      repo_root: root,
      remote_ref: null,
      local_sha: null,
      remote_sha: null,
      commits_behind: 0,
      message: "No git remotes configured; automatic update check skipped.",
    };
  }

  if (!options.skipFetch) {
    try {
      await execGit(root, ["fetch", canonicalRemote, "--prune"], { timeout: 120_000 });
    } catch (err) {
      return {
        git_repo: true,
        update_available: false,
        repo_root: root,
        canonical_remote: canonicalRemote,
        fetch_error: err.message || String(err),
        message: `Could not reach ${canonicalRemote}; try again when online.`,
      };
    }
  }

  const remoteRef = await resolveCompareRefForRemote(root, canonicalRemote);
  if (!remoteRef) {
    return {
      git_repo: true,
      update_available: false,
      repo_root: root,
      canonical_remote: canonicalRemote,
      message: `Could not resolve ${canonicalRemote}/master, ${canonicalRemote}/main, or ${canonicalRemote}/HEAD.`,
    };
  }

  const currentBranch = await getCurrentBranch(root);
  const branchUpstream = await getBranchUpstream(root);
  const tracksCanonical = branchUpstream === remoteRef;

  let localSha;
  let remoteSha;
  let commitsBehind = 0;
  try {
    localSha = await execGit(root, ["rev-parse", "HEAD"], { timeout: 10_000 });
    remoteSha = await execGit(root, ["rev-parse", remoteRef], { timeout: 10_000 });
    const countStr = await execGit(root, ["rev-list", "--count", `HEAD..${remoteRef}`], {
      timeout: 30_000,
    });
    commitsBehind = Number.parseInt(countStr, 10);
    if (Number.isNaN(commitsBehind)) commitsBehind = 0;
  } catch (err) {
    return {
      git_repo: true,
      update_available: false,
      repo_root: root,
      canonical_remote: canonicalRemote,
      remote_ref: remoteRef,
      message: err.message || String(err),
    };
  }

  const updateAvailable = commitsBehind > 0;
  const isProd = process.env.NODE_ENV === "production";
  const installSteps = ["npm run setup"];
  if (isProd) installSteps.push("npm run build");

  // Branch-aware manual_command. Three situations:
  //   1. tracksCanonical: HEAD's tracked upstream IS the canonical ref. A
  //      plain `git pull --ff-only` does the right thing — typical clone on
  //      the default branch.
  //   2. Same branch *name* as canonical but different upstream (the fork
  //      case: local master tracking origin/master, canonical is
  //      upstream/master). Need to fetch the canonical remote and merge it
  //      into the local branch.
  //   3. Anything else (feature branch, detached HEAD): pulling the current
  //      branch wouldn't bring in canonical commits, so don't suggest it.
  //      Offer a fetch and let the user decide how to integrate.
  const canonicalBranchName = stripRemotePrefix(remoteRef);
  let manualParts;
  let situationNote;
  let situation;
  if (tracksCanonical) {
    situation = "tracking_canonical";
    manualParts = [`cd "${root}"`, "git pull --ff-only", ...installSteps];
    situationNote = null;
  } else if (currentBranch && currentBranch === canonicalBranchName) {
    situation = "fork_or_diverged_tracking";
    manualParts = [
      `cd "${root}"`,
      `git fetch ${canonicalRemote}`,
      `git merge --ff-only ${remoteRef}`,
      ...installSteps,
    ];
    situationNote = `You're on '${currentBranch}' tracking '${
      branchUpstream || "no upstream"
    }'. This command fast-forwards your branch from ${remoteRef} (the canonical default).`;
  } else {
    situation = currentBranch ? "feature_branch" : "detached_head";
    manualParts = [`cd "${root}"`, `git fetch ${canonicalRemote}`];
    situationNote = currentBranch
      ? `You're on '${currentBranch}', not the canonical default branch (${remoteRef}). Fetched commits won't be pulled into your branch — rebase or merge ${remoteRef} when you're ready.`
      : `HEAD is detached. Fetched commits stay under ${remoteRef}; check out the canonical default branch when ready.`;
  }

  const manualCommand = manualParts.join(" && ");

  return {
    git_repo: true,
    update_available: updateAvailable,
    repo_root: root,
    remote_ref: remoteRef,
    canonical_remote: canonicalRemote,
    current_branch: currentBranch,
    tracking_upstream: branchUpstream,
    tracks_canonical: tracksCanonical,
    situation,
    local_sha: localSha,
    remote_sha: remoteSha,
    commits_behind: commitsBehind,
    manual_command: manualCommand,
    situation_note: situationNote,
    message: updateAvailable
      ? `${commitsBehind} commit(s) on ${remoteRef} not in your checkout.`
      : "Your checkout includes the tip of the canonical default branch.",
  };
}

module.exports = { getUpdatesStatus, DEFAULT_ROOT };
