"""
FORGE 3.0 — unified core.

FORGE 3.0 (persona/chat) + Forge (targeted prompt drafting) + Anvil (closed-loop
target testing) over one engine: one provider layer, one encrypted prompt
store, one memory. Frontends (CLI now, app later) are thin shells over this
package and never touch a plaintext prompt — everything sensitive is resolved
through a PromptSource (see core.vault).

Codename "forge3" until renamed.
"""

__version__ = "3.0.0"
