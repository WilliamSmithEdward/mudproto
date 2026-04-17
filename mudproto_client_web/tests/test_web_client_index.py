from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_CLIENT_INDEX = PROJECT_ROOT / "mudproto_client_web" / "index.html"


def test_web_client_index_contains_mudproto_websocket_ui() -> None:
    assert WEB_CLIENT_INDEX.exists(), "Expected mudproto_client_web/index.html to exist."

    content = WEB_CLIENT_INDEX.read_text(encoding="utf-8")

    assert "MudProto Web Client" in content
    assert "new WebSocket" in content
    assert "function buildInputMessage" in content
    assert "function renderDisplayMessage" in content
    assert 'id="connectionBtn"' in content
    assert 'id="helpBtn"' in content
    assert 'id="menuBtn"' in content
    assert 'id="settingsModal"' in content
    assert 'id="helpModal"' in content
    assert 'id="helpHomeView"' in content
    assert 'id="helpDetailView"' in content
    assert 'id="helpBackBtn"' in content
    assert "toggleConnection()" in content
    assert "Save Config" in content
    assert "Save Config As..." in content
    assert "Load Config" in content
    assert "Load New Config" in content
    assert 'id="loadNewConfigBtn"' in content
    assert "Customization" in content
    assert "Aliases" in content
    assert "Key Bindings" in content
    assert "Aliases..." not in content
    assert "Key Bindings..." not in content
    assert "Alias tools will open in their own modal next." not in content
    assert "Local commands stay client-side" not in content
    assert "Focus Input" not in content
    assert "Clear Output" not in content
    assert "Structured protocol renderer" not in content
    assert "Pure HTML + CSS + JavaScript" not in content
    assert "Local controls:" not in content
    assert "height: calc(100vh - 28px);" in content
    assert "overflow: hidden;" in content
    assert "scrollbar-gutter: stable;" in content
    assert "flex-wrap: nowrap;" in content
    assert "white-space: nowrap;" in content
    assert "::-webkit-scrollbar" in content
    assert "scrollbar-color: #3a3a3a #070707;" in content
    assert "requestAnimationFrame" in content
    assert "createDocumentFragment" in content
    assert "text-rendering: optimizeLegibility;" in content
    assert "#clear" in content
    assert "#quit" in content
    assert "#alias" in content
    assert "#bind" in content
    assert "#unalias" in content
    assert "#unbind" in content
    assert 'splitCommandLine(commandLine)' in content
    assert 'executeCommandLine(rawText' in content
    assert 'handleAliasCommand(commandText)' in content
    assert 'handleBindCommand(commandText)' in content
    assert 'handleUnaliasCommand(commandText)' in content
    assert 'handleUnbindCommand(commandText)' in content
    assert 'normalizeBindKeyName(keyName)' in content
    assert 'trimmed.startsWith("{")' in content
    assert 'MAX_ALIAS_EXPANSION_DEPTH = 8' in content
    assert 'localCommand === "#clear"' in content
    assert 'localCommand === "#quit"' in content
    assert 'localCommand === "#unalias"' in content
    assert 'localCommand === "#unbind"' in content
    assert '<select id="bindKeyInput">' in content
    assert "populateBindKeyOptions()" in content


def test_web_client_prunes_old_output_and_history() -> None:
    content = WEB_CLIENT_INDEX.read_text(encoding="utf-8")

    assert "MAX_OUTPUT_GROUPS = 400" in content
    assert "MAX_RENDER_QUEUE_GROUPS = 100" in content
    assert "MAX_COMMAND_HISTORY = 100" in content
    assert 'const DEFAULT_KEY_BINDINGS = {' in content
    assert 'numpad2: "south"' in content
    assert 'numpad4: "west"' in content
    assert 'numpad6: "east"' in content
    assert 'numpad8: "north"' in content
    assert 'numpad_add: "down"' in content
    assert 'numpad_subtract: "up"' in content
    assert 'key_bindings' in content
    assert 'this.keyBindings' in content
    assert 'mergeClientConfig(currentConfig, incomingConfig)' in content
    assert 'this.pendingLoadMode = "merge"' in content
    assert 'this.pendingLoadMode = "replace"' in content
    assert 'window.localStorage.setItem("mudproto.clientConfig"' in content
    assert "downloadClientConfig(fileName)" in content
    assert "countLeadingBlankLines(lines)" in content
    assert "countTrailingBlankLines(lines)" in content
    assert "normalizeBoundarySpacing(lines)" in content
    assert ".modal-body {" in content
    assert ".modal-placeholder {" in content
    assert '#helpModal .modal-panel {' in content
    assert '#helpModal .modal-panel.help-wide {' in content
    assert 'width: min(760px, 100%);' in content
    assert 'width: min(300px, 100%);' in content
    assert 'width: min(280px, 100%);' in content
    assert 'max-width: 100%;' in content
    assert 'text-align: center;' in content
    assert '#helpDetailView.hidden {' in content
    assert 'display: none;' in content
    assert "pruneOutput()" in content
    assert "childElementCount > MAX_OUTPUT_GROUPS" in content
    assert "firstElementChild?.remove()" in content
    assert 'document.createElement("span")' in content
    assert 'this.renderQueue.splice(0, this.renderQueue.length - MAX_RENDER_QUEUE_GROUPS)' in content
    assert '.output-group {' in content
    assert 'display: inline;' in content
    assert 'state === "connected" || state === "connecting" ? "Disconnect" : "Connect"' in content
