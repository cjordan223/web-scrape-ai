# Ollama Inference Runtime

TexTailor uses Ollama as its only local inference runtime. MLX lifecycle
management and MLX dashboard routes have been removed so scrape and tailoring
workflows share one always-on provider.

## Start On Login

Preferred Homebrew service:

```bash
brew services start ollama
```

Manual launchd alternative:

```bash
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.ollama.serve.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ollama.serve</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/ollama</string>
    <string>serve</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/ollama.out.log</string>
  <key>StandardErrorPath</key><string>/tmp/ollama.err.log</string>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.ollama.serve.plist
```

## Required Model

The discovery LLM gate expects `qwen2.5:7b` by default:

```bash
ollama pull qwen2.5:7b
ollama list
```

The scrape scheduler checks `http://localhost:11434/api/tags` at startup and
refuses to start if Ollama is unavailable or the configured model is missing.
