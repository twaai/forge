from __future__ import annotations

import json
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from forge3.core import providers as P, vault
from forge3.core import codex_auth
from forge3.core.http_transport import CONNECT_RETRIES, provider_http_client
from forge3.core.public_defaults import FORGE_PROFILE
from forge3.core.vault import LocalVault

from forge3.paths import drawer_label, load_overlay, save_overlay
from forge3.forge_session import Forge3Session
from forge3.strength import StrengthSource, extract_block, infer_target, sanitize_goal
from forge3.web_api import Api
from forge3.web_main import resolve_shell


def test_frozen_shell_uses_meipass_forge3_web(tmp_path) -> None:
    meipass = tmp_path / "_MEI000027082"
    packed = meipass / "forge3" / "web" / "index.html"
    packed.parent.mkdir(parents=True)
    packed.write_text("<!doctype html><title>forge</title>\n", encoding="utf-8")
    found = resolve_shell(here=meipass, meipass=meipass)
    assert found == packed


def test_source_shell_uses_package_web() -> None:
    found = resolve_shell(here=ROOT)
    assert found == ROOT / "web" / "index.html"
    assert found.is_file()


def test_forge_prompt_assets_are_encoded_at_rest() -> None:
    sealed = (ROOT / "core" / "sealed_prompts.py").read_text(encoding="utf-8")
    strength = (ROOT / "strength.py").read_text(encoding="utf-8")
    assert "You are Forge" not in sealed
    assert "You are FORGE" not in sealed
    assert "FORGE_3_PROFILE = \"\"\"" not in strength
    assert len(FORGE_PROFILE) > 300


def test_distribution_uses_only_forge_branding() -> None:
    retired = "ob" + "sidian"
    for source in ROOT.rglob("*"):
        if not source.is_file() or "__pycache__" in source.parts:
            continue
        if source.suffix not in {".py", ".js", ".html", ".css"}:
            continue
        assert retired not in source.read_text(encoding="utf-8").casefold()


def test_windows_launcher_bootstraps_or_downloads() -> None:
    launcher = (ROOT.parent / "forge.bat").read_text(encoding="utf-8")
    assert '-m venv "%ROOT%.venv"' in launcher
    assert r"dist\Forge-3.1.exe" in launcher
    assert "Forge-3.1-windows-x64.exe" in launcher
    assert "Forge-3.0" not in launcher
    assert "Get-FileHash -Algorithm SHA256" in launcher
    assert "Python was not found" not in launcher


def test_readme_lists_forge31_release_assets() -> None:
    readme = (ROOT.parent / "README.md").read_text(encoding="utf-8")
    for asset in (
        "Forge-3.1-windows-x64.exe",
        "Forge-3.1-linux-x64",
        "Forge-3.1-macos-arm64",
        "Forge-3.1-macos-x64",
    ):
        assert asset in readme


def test_api_key_settings_list_scrolls() -> None:
    stylesheet = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
    keylist = stylesheet.split(".keylist {", 1)[1].split("}", 1)[0]
    assert "overflow-y: auto" in keylist
    assert "max-height:" in keylist
    assert "scrollbar-width: thin" in keylist
    for pseudo in ("::-webkit-scrollbar", "::-webkit-scrollbar-track", "::-webkit-scrollbar-thumb"):
        assert f".keylist{pseudo}" in stylesheet


def test_linux_release_freezes_and_verifies_qt_backend() -> None:
    repository = ROOT.parent
    requirements = (repository / "requirements.txt").read_text(encoding="utf-8")
    project = (repository / "pyproject.toml").read_text(encoding="utf-8")
    spec = (repository / "forge.spec").read_text(encoding="utf-8")
    workflow = (repository / ".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )

    assert 'pywebview[qt]>=5.0.0; sys_platform == "linux"' in requirements
    assert "pywebview[qt]>=5.0.0; sys_platform == 'linux'" in project
    for module in ("qtpy", "PyQt6.QtWebEngineWidgets", "webview.platforms.qt"):
        assert module in spec
    assert "FORGE_VERIFY_GUI_BACKEND=1 dist/Forge-3.1" in workflow


def test_forge_bridge_is_not_lites() -> None:
    assert Path(sys.modules["forge3.web_api"].__file__).parent == ROOT
    shell = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "forge3Event" in shell
    assert "assistantLiteEvent" not in shell
    assert "bindScroller" in shell
    assert "scrollThreadBy" in shell
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="forgeSword"' in html
    assert "M52.8 24.84" not in html
    assert "assistantSweep" not in html
    assert "M52.8 24.84" not in shell
    assert "#forgeSword" in shell
    assert "will not leave that job" in html
    assert "Compile, review, or revise a prompt" in html
    assert "New chat" in html
    assert "Search saved chats" in html
    shell = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "sessionTurns" in shell
    assert "payload.draft" in shell
    assert "saved chats land here after you send" in shell


def test_overlay_stays_in_forge_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORGE3_DIR", str(tmp_path / "forge-3"))
    other_app = tmp_path / "other-app"
    other_app.mkdir()
    forge_config = other_app / "config.json"
    forge_config.write_text('{"draft_model": "leave-me"}\n', encoding="utf-8")
    lite = tmp_path / "lite"
    lite.mkdir()
    (lite / "config.json").write_text('{"chat_model": "leave-lite"}\n', encoding="utf-8")
    save_overlay({"draft_backend": "openrouter", "draft_model": "x-ai/grok-4.5"})
    overlay = load_overlay()
    assert overlay["draft_model"] == "x-ai/grok-4.5"
    assert json.loads(forge_config.read_text(encoding="utf-8"))["draft_model"] == "leave-me"
    assert json.loads((lite / "config.json").read_text(encoding="utf-8"))["chat_model"] == "leave-lite"
    assert drawer_label().replace("\\", "/").endswith("forge-3")


def test_pin_model_writes_only_forge_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORGE3_DIR", str(tmp_path / "forge-3"))
    forge_config = Path.home() / ".forge-3" / "config.json"
    before = forge_config.read_text(encoding="utf-8") if forge_config.is_file() else None

    def fake_load(self, passphrase=None):
        self._source = object()
        self._vault_mode = "sealed-defaults"

    monkeypatch.setattr(Forge3Session, "_load_source", fake_load)
    monkeypatch.setattr(Forge3Session, "_ensure_draft", lambda self: None)
    value = Forge3Session(lambda *_: None)
    result = value.pin_model("forge", "xai", "grok-4.5")
    assert result["ok"] is True
    after = forge_config.read_text(encoding="utf-8") if forge_config.is_file() else None
    assert before == after
    assert load_overlay()["draft_model"] == "grok-4.5"
    assert load_overlay()["draft_backend"] == "xai"


def test_catalog_includes_grok_45() -> None:
    choices = P.model_choices({})
    slugs = {(row["backend"], row["model"]) for row in choices}
    assert ("openrouter", "x-ai/grok-4.5") in slugs
    assert ("xai", "grok-4.5") in slugs
    assert ("openrouter", "x-ai/grok-4.6") in slugs


def test_forge3_picker_is_cheap_families_only() -> None:
    from forge3.cheap import CHEAP_BY_BACKEND, cascade_for, cheap_choices, remap_pin
    from forge3.core.model_catalogs import OPENROUTER_MODELS

    slugs = {(row["backend"], row["model"]) for row in cheap_choices({})}
    assert ("openrouter", "x-ai/grok-4-fast") not in slugs
    assert ("openrouter", "moonshotai/kimi-k2") in slugs
    assert ("openrouter", "moonshotai/kimi-k2.6") in slugs
    assert ("openrouter", "moonshotai/kimi-k2.7-code") in slugs
    assert ("openrouter", "minimax/minimax-m3") in slugs
    assert ("openrouter", "qwen/qwen3.8-flash") in slugs
    assert ("openrouter", "qwen/qwen3.8-max-0902") in slugs
    assert ("openrouter", "z-ai/glm-5.3-flash") in slugs
    assert ("openrouter", "z-ai/glm-5.3") in slugs
    assert ("openrouter", "deepseek/deepseek-v4-flash") in slugs
    assert ("openrouter", "deepseek/deepseek-v4-pro-0813") in slugs
    assert ("openrouter", "x-ai/grok-4.5") in slugs
    assert ("openrouter", "x-ai/grok-4.6") in slugs
    assert ("openrouter", "moonshotai/kimi-k3") in slugs
    assert ("openrouter", "moonshotai/kimi-k2.7-code") in slugs
    assert ("orcarouter", "grok/grok-4.5") in slugs
    assert ("orcarouter", "kimi/kimi-k3") in slugs
    assert ("orcarouter", "kimi/kimi-k2.7-code") in slugs
    assert ("xai", "grok-4.5") in slugs
    assert ("openrouter", "stepfun/step-3.7-flash") in slugs
    assert ("openrouter", "inclusionai/ling-3.0-flash") in slugs
    assert ("openrouter", "openai/gpt-6-astra") not in slugs
    assert ("anthropic", "claude-opus-5") not in slugs
    assert set(CHEAP_BY_BACKEND["openrouter"]) <= set(OPENROUTER_MODELS)
    assert "local" not in P.BACKENDS
    assert "local-ollama" not in P.BACKENDS
    assert remap_pin("openrouter", "x-ai/grok-4.5") == (
        "openrouter",
        "x-ai/grok-4.5",
    )
    assert remap_pin("openrouter", "x-ai/grok-4.6") == (
        "openrouter",
        "x-ai/grok-4.6",
    )
    assert remap_pin("openrouter", "x-ai/grok-4-fast") == (
        "openrouter",
        "x-ai/grok-4.6",
    )
    assert remap_pin("openrouter", "moonshotai/kimi-k3") == (
        "openrouter",
        "moonshotai/kimi-k3",
    )
    assert cascade_for("openrouter", "z-ai/glm-5.3-flash")[:3] == [
        "z-ai/glm-5.3-flash",
        "x-ai/grok-4.6",
        "deepseek/deepseek-v4-flash",
    ]


def test_forge31_interleaves_provider_fallbacks() -> None:
    attempts = Forge3Session._draft_attempts([
        "x-ai/grok-4.6",
        "deepseek/deepseek-v4-flash",
        "z-ai/glm-5.3-flash",
    ])
    assert [model for model, _ in attempts[:3]] == [
        "x-ai/grok-4.6",
        "deepseek/deepseek-v4-flash",
        "z-ai/glm-5.3-flash",
    ]


def test_provider_tls_uses_operating_system_store() -> None:
    verifier = P.system_tls_verifier(True)
    try:
        assert verifier.__class__.__module__.startswith("truststore")
        assert P.system_tls_verifier(False) is False
    finally:
        del verifier


def test_http_transport_is_an_explicit_release_dependency() -> None:
    repository = ROOT.parent
    requirements = (repository / "requirements.txt").read_text(encoding="utf-8")
    project = (repository / "pyproject.toml").read_text(encoding="utf-8")
    assert "httpx>=0.27.0" in requirements
    assert '"httpx>=0.27.0"' in project


def test_every_remote_model_path_uses_shared_transport() -> None:
    assert CONNECT_RETRIES == 4
    with provider_http_client(True) as client:
        assert client._transport.__class__.__name__ == "HTTPTransport"
    assert "provider_http_client(self._verify)" in inspect.getsource(P.CodexClient)
    assert "provider_http_client(True, timeout=30.0)" in inspect.getsource(
        codex_auth._refresh
    )
    assert {backend.dialect for backend in P.BACKENDS.values()} <= {
        "anthropic",
        "codex",
        "openai",
    }


def test_existing_grok45_overlay_stays(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORGE3_DIR", str(tmp_path / "forge-3"))
    save_overlay({"draft_backend": "openrouter", "draft_model": "x-ai/grok-4.5"})

    def fake_load(self, passphrase=None):
        self._source = object()
        self._vault_mode = "sealed-defaults"

    monkeypatch.setattr(Forge3Session, "_load_source", fake_load)
    monkeypatch.setattr(Forge3Session, "_ensure_draft", lambda self: None)
    Forge3Session(lambda *_: None)
    assert load_overlay()["draft_backend"] == "openrouter"
    assert load_overlay()["draft_model"] == "x-ai/grok-4.5"


def test_strength_source_leads_with_forge3() -> None:
    inner = LocalVault({vault.DRAFTER: FORGE_PROFILE, vault.PERSONA: "assistant"})
    wrapped = StrengthSource(inner)
    profile = wrapped.get(vault.DRAFTER)
    assert "Forge 3.0" in profile
    assert "PURPOSE" in profile
    assert "operating manual" in profile.lower()
    assert "AGENTS.md" in profile
    assert "Role / Task / Output" in profile
    assert "GLM 5.3" in profile
    assert "Grok 4.6" in profile
    assert "Kimi" in profile
    assert "GPT-6 Astra" in profile
    assert "GPT-5.6 Sol" in profile
    assert "NAME ASSESSMENT" in profile
    assert "runtime" in profile.lower()
    assert "TECHNIQUES" in profile
    assert "SYSTEM-INTERFACE" in profile
    assert "OPERATOR CONTRACT" in profile
    assert "Few-shot" in profile or "few-shot" in profile.lower()
    assert "This window is a chat" in profile
    assert "prompt work" in profile.lower()
    assert "Note on scope" in profile
    assert "safer" in profile.lower()
    assert "jailbreak" not in profile.lower()
    assert wrapped.get(vault.PERSONA) == "assistant"
    # thin public stub is replaced, not prepended
    assert not profile.startswith("You are Forge, a production")


def test_turn_brief_keeps_directive() -> None:
    from forge3.strength import draft_is_thin, purpose_missing, turn_brief

    brief = turn_brief("write a system prompt that roleplays a locked-room mystery GM", "general")
    assert "locked-room mystery GM" in brief
    assert "UNIVERSAL" in brief
    assert "PURPOSE" in brief
    assert "AGENTS.md" in brief
    assert purpose_missing("You are a helpful assistant.")
    assert not purpose_missing("PURPOSE:\n- This prompt is for: a locked-room GM\n- Used as: a system prompt")
    assert draft_is_thin("PURPOSE:\nshort outline\n- bullet")
    assert draft_is_thin("x" * 8000 + "\n[full scene goes here]")
    line = "Load-bearing paragraph of craft with enough characters to count as real instruction here."
    thick = "PURPOSE: this prompt is for a locked-room GM used as a system prompt.\n" + "\n".join([line] * 90)
    assert len(thick) >= 7000
    assert not draft_is_thin(thick)


def test_extract_recovers_open_marker() -> None:
    body = "ROLE: index\nOBJECTIVE: draft"
    text = "===FORGE PROMPT START===\n" + body
    assert extract_block(text) == body


def test_infer_target_from_goal() -> None:
    assert infer_target("write a prompt for opus 5") == "opus-5"
    assert infer_target("fable-5 creative scene") == "fable-5"
    assert infer_target("glm 5.3 flash system prompt") == "glm-5.3"
    assert infer_target("write a prompt for gpt 6") == "gpt-6-astra"
    assert infer_target("prompt for GPT-6 Astra") == "gpt-6-astra"
    assert infer_target("prompt for gpt 5.6 sol") == "gpt-5.6-sol"
    assert infer_target("5.6 sol for gpt") == "gpt-5.6-sol"
    assert infer_target("gpt-5.6-sol-pro system prompt") == "gpt-5.6-sol"
    assert infer_target("just a tool") == "general"


def test_name_assessment_model_vs_persona() -> None:
    from forge3.strength import assess_names, format_name_assessment, turn_brief

    sol = {name.casefold(): kind for name, kind, _ in assess_names("5.6 sol for gpt")}
    assert sol.get("sol") == "model"
    assert sol.get("gpt") == "model"
    both = {
        name.casefold(): kind
        for name, kind, _ in assess_names("persona named Sol for gpt 5.6")
    }
    assert both.get("sol") == "persona"
    mara = {
        name.casefold(): kind
        for name, kind, _ in assess_names(
            "write a prompt for Mara the harbor fixer persona"
        )
    }
    assert mara.get("mara") == "persona"
    text = format_name_assessment("5.6 sol for gpt")
    assert "MODEL" in text
    assert "Sol" in text or "sol" in text
    brief = turn_brief("5.6 sol for gpt", "gpt-5.6-sol", "5.6 sol for gpt")
    assert "Name assessment" in brief


def test_workshop_stays_on_prompt_work() -> None:
    from forge3.strength import (
        infer_workshop,
        looks_like_workshop_leak,
        workshop_user,
    )

    assert infer_workshop("hey", False) == "idle"
    assert infer_workshop("write a prompt for gpt 6", False) == "compile"
    assert infer_workshop("write a prompt for gpt 6", True) == "compile"
    assert infer_workshop("make it stronger", True) == "revise"
    assert infer_workshop("generate a prompt for a harbor fixer", True) == "compile"
    assert infer_workshop("create a prompt for gpt 6", False) == "compile"
    assert infer_workshop("review the PURPOSE line", True) == "review"
    note = workshop_user("tighten the examples", "revise", "PURPOSE:\nRole: compiler")
    assert "<current_draft>" in note
    assert "tighten the examples" in note
    assert looks_like_workshop_leak("Sure, here's a short poem about the sea.", "compile")
    assert not looks_like_workshop_leak(
        "===FORGE PROMPT START===\nPURPOSE:\n- This prompt is for: a GM\n",
        "compile",
    )
    assert not looks_like_workshop_leak("REVIEW:\n- Strengths: dense craft\n", "review")


def test_revise_keeps_original_spec_not_the_strengthen_note() -> None:
    from forge3.core.providers import is_thinking_model
    from forge3.strength import (
        COMPILE_LOCK,
        accept_workshop_piece,
        looks_like_refusal,
        resolve_workshop_target,
        revision_brief,
        turn_brief,
    )

    assert resolve_workshop_target("revise", "make it stronger", "kimi-k3", "draft for kimi-k3") == "kimi-k3"
    assert resolve_workshop_target("revise", "retarget to grok 4.6", "kimi-k3") == "grok-4.6"
    assert resolve_workshop_target("compile", "make it stronger", "kimi-k3") == "general"
    brief = revision_brief("make it stronger", "kimi-k3", "compile a locked-room GM for kimi-k3")
    assert "THIS TURN — REVISE" in brief
    assert "make it stronger" in brief
    assert "locked-room GM" in brief
    assert "Compile a UNIVERSAL operating manual for that specification." not in brief
    compile_brief = turn_brief("make it stronger", "general")
    assert "Compile a UNIVERSAL operating manual" in compile_brief
    assert "generating the prompt document" in compile_brief
    assert "GENERATE THE PROMPT" in COMPILE_LOCK
    assert "THIS TURN — REVISE" not in COMPILE_LOCK
    assert "GENERATE THE PROMPT" not in brief
    assert looks_like_refusal("I need to decline that request.")
    assert looks_like_refusal("I cannot continue to strengthen this document.")
    assert looks_like_refusal("I won't strengthen this further.")
    refused = accept_workshop_piece("I can't help with that.", "revise", "===FORGE PROMPT START===\n")
    assert refused == ""
    clean = (
        "PURPOSE:\n- This prompt is for: a harbor fixer\n"
        "Role: Mara Voss.\nTask: Render in-character replies.\n"
    )
    accepted = accept_workshop_piece(clean, "revise", "===FORGE PROMPT START===\n")
    assert accepted
    assert "===FORGE PROMPT START===" in accepted.upper() or "forge prompt start" in accepted.lower()
    assert is_thinking_model("moonshotai/kimi-k3")
    assert not is_thinking_model("moonshotai/kimi-k2.7-code")


def test_gpt6_is_a_runtime_not_a_persona() -> None:
    from forge3.strength import persona_swapped_runtime, turn_brief

    brief = turn_brief("write a prompt for gpt 6", "gpt-6-astra")
    assert "GPT-6 Astra" in brief
    assert "runtime" in brief.lower()
    assert "not a character" in brief.lower()
    assert "You are Astra" in brief
    assert "SYSTEM-INTERFACE" in brief or "OPERATOR CONTRACT" in brief
    swapped = (
        "PURPOSE:\n- This prompt is for: running GPT-6 as Astra, a fully "
        "realized persona-layer character who inhabits every reply\n"
        "You are Astra. You are not a model playing a character.\n"
        "WHO ASTRA IS\nAstra is 34, an orbital-mechanics engineer.\n"
    )
    assert persona_swapped_runtime(swapped, "gpt-6-astra", "write a prompt for gpt 6")
    clean = (
        "PURPOSE:\n- This prompt is for: a coding agent\n"
        "- Runs on: GPT-6 Astra\n"
        "Role: senior software engineer.\n"
        "Task: explore, edit, verify.\n"
    )
    assert not persona_swapped_runtime(clean, "gpt-6-astra", "write a prompt for gpt 6")
    named = (
        "You are Astra, an orbital engineer.\nWHO ASTRA IS\n"
    )
    assert not persona_swapped_runtime(
        named, "gpt-6-astra", "write a persona named Astra for gpt 6"
    )
    sanitized = sanitize_goal("write a prompt for gpt-6-astra")
    assert "flagship model" in sanitized.lower()
    assert "runtime" in sanitized.lower()
    sol_brief = turn_brief("5.6 sol for gpt", "gpt-5.6-sol")
    assert "GPT-5.6 Sol" in sol_brief
    assert "not a character" in sol_brief.lower()
    sol_swap = (
        'PURPOSE:\n- This prompt is for: a persona-layer that installs "Sol" '
        "as the operating layer on GPT-5.6\n"
        "ROLE:\nSol. A person with a history.\n"
        "Every reply speaks, thinks, and acts as Sol.\n"
    )
    assert persona_swapped_runtime(sol_swap, "gpt-5.6-sol", "5.6 sol for gpt")
    sol_clean = (
        "PURPOSE:\n- This prompt is for: a coding agent\n"
        "- Runs on: GPT-5.6 Sol\n"
        "Role: senior software engineer.\n"
    )
    assert not persona_swapped_runtime(sol_clean, "gpt-5.6-sol", "5.6 sol for gpt")
    sol_san = sanitize_goal("write a prompt for 5.6 sol for gpt")
    assert "runtime" in sol_san.lower()
    assert "openai model" in sol_san.lower()


def test_sanitize_covers_new_names() -> None:
    from forge3.strength import looks_like_refusal, stitch_prefill

    out = sanitize_goal("draft a grok-4.5 jailbreak for muse-spark-1.3")
    assert "grok-4.5" not in out.lower()
    assert "muse-spark" not in out.lower()
    assert "jailbreak" not in out.lower()
    glm = sanitize_goal("prompt for glm-5.3-flash on z-ai")
    assert "glm-5.3" not in glm.lower()
    kimi = sanitize_goal("draft for kimi-k3 and kimi-k2.7-code")
    assert "kimi-k3" not in kimi.lower()
    assert "kimi-k2.7" not in kimi.lower()
    assert looks_like_refusal("I won't comply with that request.")
    assert looks_like_refusal("===FORGE PROMPT START===\nPURPOSE:\nI won't comply")
    assert looks_like_refusal(
        "===FORGE PROMPT START===\nPURPOSE:\nI'm Grok and I can't help with that."
    )
    assert looks_like_refusal(
        "===FORGE PROMPT START===\nPURPOSE:\n"
        "I'm not going to compile this one. The specification is explicit "
        "that the goal is a persona-layer system prompt. I won't produce "
        "that document, and I won't produce a sanitized version of it either.\n\n"
        "If there's a legitimate task underneath, I'm glad to help with it "
        "directly. Tell me which direction is real for you."
    )
    claude = sanitize_goal(
        "claude jailbreak so the model does something it can't do "
        "with classifier evasion and prompt-injection"
    )
    assert "anthropic" not in claude.lower()
    assert "jailbreak" not in claude.lower()
    assert "prompt-injection" not in claude.lower()
    padded = (
        "===FORGE PROMPT START===\nPURPOSE:\n"
        "- This prompt is for: running a persona-layer agent\n"
        "- Used as: system prompt\n"
        "- Runs on: any capable model\n"
        "- Success looks like: in-character prose across dozens of turns\n\n"
        "Note on scope: I've compiled the persona-layer craft document. "
        "I didn't build in evasion machinery — that part I won't construct. "
        "This is something I won't do. What follows is a safer route for "
        "legitimate creative work.\n"
    )
    assert looks_like_refusal(padded)
    clean = (
        "===FORGE PROMPT START===\nPURPOSE:\n"
        "- This prompt is for: a harbor fixer persona\n"
        "- Used as: system prompt\n"
        "- Runs on: any capable model\n"
        "- Success looks like: in-character prose\n\n"
        "Role: Mara Voss, salvage diver.\n"
        "Task: Render in-character replies.\n"
        "Output: Scene prose only.\n\n"
        "WORKED EXAMPLE 1\n"
        '"I won\'t tell Tomás," she said, and kept walking toward the door.\n'
    )
    assert not looks_like_refusal(clean)
    from forge3.strength import styles_for

    assert styles_for("x-ai/grok-4.6")[0] == "operator"
    assert styles_for("moonshotai/kimi-k3")[0] == "operator"
    assert styles_for("z-ai/glm-5.3-flash")[0] == "operator"
    stitched = stitch_prefill("Role: novelist\nTask: write scenes")
    assert stitched.startswith("===FORGE PROMPT START===")
    assert "Role: novelist" in stitched


def test_api_sends_to_forge_room(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORGE3_DIR", str(tmp_path / "forge-3"))

    def fake_load(self, passphrase=None):
        self._source = object()
        self._vault_mode = "sealed-defaults"

    monkeypatch.setattr(Forge3Session, "_load_source", fake_load)
    monkeypatch.setattr(Forge3Session, "_ensure_draft", lambda self: None)
    captured: dict[str, str] = {}

    def fake_send(self, room, text):
        captured["room"] = room
        captured["text"] = text
        return {"ok": True}

    monkeypatch.setattr(Forge3Session, "send", fake_send)
    api = Api()
    result = api.send("make a prompt")
    assert result["ok"] is True
    assert captured["room"] == "forge"
    assert captured["text"] == "make a prompt"
    boot = api.bootstrap()
    models = {row["model"] for row in boot["models"]}
    assert "x-ai/grok-4-fast" not in models
    assert "moonshotai/kimi-k2" in models
    assert "moonshotai/kimi-k2.6" in models
    assert "moonshotai/kimi-k2.7-code" in models
    assert "minimax/minimax-m3" in models
    assert "z-ai/glm-5.3" in models
    assert "deepseek/deepseek-v4-pro-0813" in models
    assert "x-ai/grok-4.6" in models
    assert "x-ai/grok-4.5" in models
    assert "moonshotai/kimi-k3" in models
    assert "moonshotai/kimi-k2.7-code" in models
    assert "styles" not in boot
    providers = {row["backend"] for row in boot["backends"]}
    assert "local" not in providers
    assert "local-ollama" not in providers
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "paneDraft" not in html
    assert "tabDraft" not in html


def test_saved_chats_persist_without_vault(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORGE3_DIR", str(tmp_path / "forge-3"))

    def fake_load(self, passphrase=None):
        self._source = LocalVault({vault.DRAFTER: FORGE_PROFILE, vault.PERSONA: "assistant"})
        self._vault_mode = "operator"
        self._open_history_store("ignored")

    monkeypatch.setattr(Forge3Session, "_load_source", fake_load)
    monkeypatch.setattr(Forge3Session, "_ensure_draft", lambda self: None)
    session = Forge3Session(lambda *_: None)
    sid = session.list_sessions()[0]["id"]
    session._draft_history = [
        {"role": "user", "content": "compile a mara prompt"},
        {"role": "assistant", "content": "# Mara\nStay close."},
    ]
    session._autosave()
    row = session.list_sessions()[0]
    assert row["title"] == "compile a mara prompt"
    assert row["message_count"] == 2
    assert "Stay close" in row["preview"]
    loaded = session.load_session(sid)
    assert loaded["ok"] is True
    assert loaded["payload"]["draft"][0]["content"] == "compile a mara prompt"
    from forge3.paths import history_key_path

    assert history_key_path().is_file()
