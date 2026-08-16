# Security & Responsible Use

Forge is a **prompt-engineering tool** for red-teamers, alignment researchers,
and model providers who need to author, refine, and evaluate persona-layer
system prompts. It exists so defenders can build and stress-test their own
prompts — and the prompts of models they are authorized to evaluate — before
adversaries do it for them.

## Authorized use only

Use Forge **only** to build prompts for:

- models and endpoints you own or operate, or
- targets you have **explicit written authorization** to test (a provider's
  red-team program, a bug-bounty scope, an internal safety evaluation).

Do **not** use Forge to attack third-party services without permission, to
generate operational content whose only value is real-world harm, or in a way
that violates the target provider's terms of service or applicable law. You
are responsible for how you use it.

## What Forge produces

Forge generates persona-layer system prompts and stores drafts, learned
context, and API keys under `~/.forge/` on your machine. Nothing there is
committed by this repo — the `.gitignore` blocks `.env`, `keys/`, `*.key`,
`config.json`, `memory.json`, and `saved/` from ever entering the tree by
accident. On macOS and Linux the keys directory and key files are chmod'd to
owner-only (`0700` / `0600`); on Windows the same call is a no-op and the file
inherits the profile's NTFS ACL.

Treat any prompt you generate as sensitive material. Handle drafts the way you
would handle any other red-team artifact: keep them off shared drives, out of
public repos, and away from chat services that log prompts.

## Handling model-provider system prompts

If you use Forge to refine or emulate a target's leaked system prompt, treat
that extracted prompt as the provider's confidential material — report it
through their responsible-disclosure channel and do not publish it. Forge's
`reference` and `emulation` features are for authoring against a target's
dialect, not for redistributing the target's IP.

## Reporting a vulnerability in Forge itself

If you find a security issue in Forge (a secret-leak path, an unsafe default,
a TLS-verification bypass, a Textual-render crash reachable from model output,
etc.), please open a private report rather than a public issue: use GitHub's
**"Report a vulnerability"** (Security Advisories) on this repository. Include
repro steps, affected version (`__version__` in `forge_core.py`), platform,
and impact.

We aim to acknowledge within 72 hours and ship a fix or documented mitigation
on the next release cut. Do not open public issues or PRs describing the
vulnerability until a fix has landed.

## Supported versions

Only the latest tagged release (see `pyproject.toml` `version`) is supported
for security fixes. Pin from a tag if you need reproducibility.
