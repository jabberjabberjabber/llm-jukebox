# LLM Jukebox MCP Server

A Model Context Protocol (MCP) server that enables LLMs to search, download, and extract information from YouTube music videos. 

## Features

- **YouTube Music Search**: Find music videos by artist, song title, album, or any search query
- **Audio Download**: Download and convert YouTube videos to high-quality MP3 files
- **Video Information**: Extract detailed metadata from YouTube videos
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

### Note

The file will be converted to MP3 after it downloads. The model does not know that this happens, so they might say something about it needing to be converted. It can be a project for you to figure out how to modify the server to tell the model about the MP3 conversion if you want.

## Available Tools

### `test_ytdlp()`
Tests if yt-dlp is properly installed and accessible.

**Returns**: Version information or error message

### `search_youtube_music(query: str)`
Searches YouTube for music content and returns the URL of the first result.

**Parameters**:
- `query`: Search terms (artist, song, album, etc.)

**Returns**: YouTube watch URL or "No results found" message

**Example**: 
```
search_youtube_music("Radiohead Creep")
# Returns: https://www.youtube.com/watch?v=XFkzRNyygfk
```

### `download_youtube_music(query: str)`
Searches for and downloads music, converting to MP3 format.

**Parameters**:
- `query`: Search terms for the desired music

**Returns**: Success message with file paths or error details

**Example**:
```
download_youtube_music("The Beatles Yesterday")
# Downloads and converts to MP3 in the configured directory
```

### `get_youtube_info(url: str)`
Extracts detailed information about a YouTube video without downloading.

**Parameters**:
- `url`: YouTube URL or video ID

**Returns**: JSON-formatted video metadata including title, uploader, duration, view count, upload date, and description

## File Naming

Downloaded files use the format: `{video_title}.mp3` and are saved to the configured download directory.

## Logging

The server creates detailed logs in `llm_jukebox_mcp_debug.log` including:
- Search and download operations
- Performance timing
- Error details
- File paths of successful downloads

## Legal Considerations

This tool is intended for personal use with content you have the right to download. Users are responsible for complying with:
- YouTube's Terms of Service
- Local copyright laws
- Content creators' rights

Always respect intellectual property and consider supporting artists through official channels.