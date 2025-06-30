# LLM Jukebox MCP Server

A Model Context Protocol (MCP) server that enables LLMs to search, download, and play YouTube music. 

## Features

- **YouTube Music Search**: Find music videos by artist, song title, album, or any search query
- **Audio Download**: Download and convert YouTube videos to high-quality MP3 files
- **Audio Playback**: Model can start and stop songs
- **Async Operations**: Non-blocking downloads and searches with progress tracking
- **Logging**: Debug-level logging to file and stderr

### Installation

- **Get the Files**: Clone the repo or download and extract the zip
- **Get FFMPEG**: Make sure you have ffmpeg. In windows open a terminal and type `winget install ffmpeg`, in Ubuntu or Debian do `sudo apt install ffmpeg`
- **Load a Tool Capable Model**: Ensure you have a model that is trained to handle tools properly. Qwen 3 and Gemma 3 are good choices.
- **Create JSON Entry**: In LM Studio, click Developer mode, then Program, Tools and Integrations, the the arrow next to the Install button, and Edit mcp.json. Add the entry below under mcpServers:

```json
"llm-jukebox": {
  "command": "uv",
  "args": [
	"run",
	"c:/path/to/llm-jukebox/server.py"
  ],
  "env": {
	"DOWNLOAD_PATH": "c:/path/to/downloads"
  }
}
```
Make sure to change the paths to fit which paths the repo is in and where you want to the downloads to go.

If you have no other entries, the full JSON should look something like this:

```json
{
  "mcpServers": {
    "llm-jukebox": {
      "command": "uv",
      "args": [
        "run",
        "c:/users/user/llm-jukebox/server.py"
      ],
      "env": {
        "DOWNLOAD_PATH": "c:/users/user/downloads"
      }
    }
  }
}
```

Click on the Save button or hit Ctrl+S. If it works you should be able to set the slider to turn on llm-jukebox.

Now you can ask the LLM to grab a song for you!

## Legal Considerations

This tool is intended for personal use with content you have the right to download. Users are responsible for complying with:
- YouTube's Terms of Service
- Local copyright laws
- Content creators' rights

Always respect intellectual property and consider supporting artists through official channels.

## Credit

Playback tool adapted from https://github.com/Here-and-Tomorrow-LLC/audio-player-mcp (MIT Licensed)

