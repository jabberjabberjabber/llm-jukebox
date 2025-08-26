import asyncio
import json
import sys
import os
import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any, List, Union
from pathlib import Path
import base64

import yt_dlp
import pygame.mixer
from fastmcp import FastMCP
from tinydb import TinyDB, Query

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("LLM Jukebox")
download_path = Path(os.environ.get("DOWNLOAD_PATH", "./"))
download_path.mkdir(exist_ok=True)

db_path = download_path / "music_library.json"
db = TinyDB(db_path)
Track = Query()

YT_DLP_BASE_OPTS = {
    "no_warnings": False,
    "audioquality": "0",  # Best quality
    "outtmpl": str(download_path / "%(title)s.%(ext)s"),
    "noplaylist": True,
    "extract_flat": False,
}

def is_single_song(video_info: Dict[str, Any]) -> bool:
    """Check if a video appears to be a single song rather than a compilation/album.

    Args:
        video_info: Video information from yt-dlp

    Returns:
        True if it is a single song or False if not
    """
    try:
        title = video_info.get("title", "").lower()
        description = video_info.get("description", "").lower()
        duration = video_info.get("duration", 0)

        reasons = []
        red_flags = 0
        green_flags = 0

        if duration:
            if duration < 60:
                reasons.append(f"Very short duration ({duration}s)")
                red_flags += 1
            elif duration > 600:
                reasons.append(
                    f"Long duration ({duration//60}m {duration%60}s) suggests compilation"
                )
                red_flags += 2
            elif 120 <= duration <= 480:
                reasons.append(f"Good song length ({duration//60}m {duration%60}s)")
                green_flags += 2
            else:
                reasons.append(f"Acceptable duration ({duration//60}m {duration%60}s)")
                green_flags += 1

        compilation_keywords = [
            "best of",
            "greatest hits",
            "compilation",
            "full album",
            "entire album",
            "complete album",
            "whole album",
            "album completo",
            "discography",
            "collection",
            "anthology",
            "mix tape",
            "mixtape",
            "playlist",
            "all songs",
            "todas las canciones",
            "hours of",
            "hour mix",
            "non stop",
            "nonstop",
            "continuous",
            "mega mix",
            "super mix",
        ]

        for keyword in compilation_keywords:
            if keyword in title:
                reasons.append(f"Title contains '{keyword}'")
                red_flags += 2
                break

        track_patterns = [
            r"\d+\s*songs?",
            r"\d+\s*tracks?",
            r"\d+\s*hits?",
            r"\(\d+\s*songs?\)",
            r"\[\d+\s*tracks?\]",
        ]

        for pattern in track_patterns:
            if re.search(pattern, title):
                reasons.append("Title suggests multiple tracks")
                red_flags += 2
                break

        if description:
            desc_compilation_signs = [
                "track list",
                "tracklist",
                "track listing",
                "song list",
                "1.",
                "2.",
                "3.",
                "00:00",
                "01:",
                "02:",
                "full album",
                "complete album",
                "entire album",
            ]

            compilation_indicators = sum(
                1 for sign in desc_compilation_signs if sign in description
            )
            if compilation_indicators >= 2:
                reasons.append("Description contains track listing or timestamps")
                red_flags += 2
            elif compilation_indicators == 1:
                red_flags += 1

        song_indicators = [
            "official video",
            "official audio",
            "music video",
            "lyric video",
            "official lyric",
            "lyrics",
            "single",
            "new single",
        ]

        for indicator in song_indicators:
            if indicator in title or indicator in description:
                reasons.append(f"Contains '{indicator}' suggesting single song")
                green_flags += 1
                break

        logger.info(f"Song analysis - Red flags: {red_flags}, Green flags: {green_flags}")
        return red_flags < green_flags

    except Exception as e:
        logger.error(f"Error analyzing song: {e}")
        return True  # Default to allowing download if analysis fails

def cleanup_missing_files() -> Dict[str, int]:
    """Remove database entries for files that no longer exist on disk.

    Returns:
        Dict with 'total_checked', 'removed', and 'remaining' counts
    """
    try:
        all_tracks = db.all()
        total_checked = len(all_tracks)
        removed_count = 0

        for track in all_tracks:
            file_path = Path(track.get("file_path", ""))
            if not file_path.exists():
                db.remove(doc_ids=[track.doc_id])
                removed_count += 1

        remaining_count = total_checked - removed_count

        return {
            "total_checked": total_checked,
            "removed": removed_count,
            "remaining": remaining_count,
        }
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        return {"total_checked": 0, "removed": 0, "remaining": 0}

def get_youtube_info(query: str) -> Optional[Dict[str, Any]]:
    """Get YouTube video information without downloading.
    
    Args:
        query: Search query for YouTube
        
    Returns:
        Video information dictionary or None if not found
    """
    info_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }
    
    try:
        yt_query = f"ytsearch1:{query}"
        
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(yt_query, download=False)
            if not info or "entries" not in info or len(info["entries"]) == 0:
                return None
            
            return info["entries"][0]
            
    except Exception as e:
        logger.error(f"Error getting YouTube info: {e}")
        return None

def search_library_by_metadata(title: str, artist: str) -> Optional[Dict[str, Any]]:
    """Search the library using YouTube metadata.
    
    Args:
        title: YouTube video title
        artist: YouTube uploader/artist name
        
    Returns:
        Track dictionary if found, None otherwise
    """
    try:
        # Escape special regex characters and create case-insensitive search
        safe_title = re.escape(title.lower())
        safe_artist = re.escape(artist.lower())
        
        tracks = db.all()
        
        for track in tracks:
            track_title = track.get("title", "").lower()
            track_artist = track.get("artist", "").lower()
            
            # Check if file still exists
            file_path = Path(track.get("file_path", ""))
            if not file_path.exists():
                db.remove(doc_ids=[track.doc_id])
                continue
            
            # Simple substring matching
            if safe_title in track_title or safe_artist in track_artist:
                return track
                
        return None
        
    except Exception as e:
        logger.error(f"Error searching library: {e}")
        return None

def play_track(track: Dict[str, Any]) -> str:
    """Play a track from the library.
    
    Args:
        track: Track dictionary from database
        
    Returns:
        Success message or error message
    """
    try:
        file_path = Path(track["file_path"])
        if not file_path.exists():
            db.remove(doc_ids=[track.doc_id])
            return f"Audio file not found: {file_path}. Removed from database."

        supported_formats = {".mp3", ".ogg", ".wav"}
        if file_path.suffix.lower() not in supported_formats:
            return f"Unsupported audio format: {file_path.suffix}. Try re-downloading to get .mp3 format."
        
        # Initialize pygame mixer if not already initialized
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)

        # Stop any currently playing music
        pygame.mixer.music.stop()
        
        # Load and play the new track
        pygame.mixer.music.load(str(file_path))
        pygame.mixer.music.play()

        return f"🎵 Now playing: '{track['title']}' by {track['artist']} (from library)"

    except Exception as e:
        logger.error(f"Playback error: {e}")
        return f"Playback error: {str(e)}"

def download_and_store_track(video_info: Dict[str, Any], query: str) -> str:
    """Download a track and store it in the library.
    
    Args:
        video_info: YouTube video information
        query: Original search query
        
    Returns:
        Success message or error message
    """
    downloaded_files = []

    def progress_hook(d):
        if d["status"] == "finished":
            downloaded_files.append(d["filename"])

    ydl_opts = {
        **YT_DLP_BASE_OPTS,
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
    }

    try:
        yt_query = f"ytsearch1:{query}"
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([yt_query])
            
            if downloaded_files:
                music_file = downloaded_files[0]
                # Ensure .mp3 extension
                music_file_path = Path(music_file)
                if music_file_path.suffix.lower() != ".mp3":
                    music_file = str(music_file_path.with_suffix(".mp3"))

                title = video_info.get("title", "Unknown Title")
                artist = video_info.get("uploader", "Unknown Artist")
                duration_seconds = video_info.get("duration")

                track_data = {
                    "title": title,
                    "artist": artist,
                    "file_path": music_file,
                    "download_date": datetime.now().isoformat(),
                    "duration": duration_seconds,
                    "original_query": query,
                    "youtube_url": video_info.get("webpage_url", ""),
                }

                # Check if track already exists in database
                existing = db.search(Track.file_path == music_file)
                if not existing:
                    db.insert(track_data)

                # Play the downloaded track
                result = play_track(track_data)

                success_msg = (
                    f"✅ Downloaded and playing: '{title}' by {artist}\n"
                    f"📁 File saved as: {Path(music_file).name}\n"
                    f"💾 Added to music library database.\n"
                )

                return success_msg
            else:
                return f"Download completed for: {query}, but no files were found."
                
    except Exception as e:
        logger.error(f"Download error: {e}")
        raise Exception(f"Failed to download track: {str(e)}")

@mcp.tool()
async def download_and_play(query: str) -> str:
    """Search for and play a song. If the song is already in the library it will
        play the existing version, otherwise it will download it first.

    Args:
        query: Search query for music (artist, song, album, etc.)

    Returns:
        Success message with file info, or error message if download/play failed
    """
    try:
        logger.info(f"Processing query: {query}")
        
        # Get video information
        video_info = await asyncio.get_event_loop().run_in_executor(
            None, get_youtube_info, query
        )
        
        if not video_info:
            return "❌ No search results found on YouTube for your query."
        
        logger.info(f"Found video: {video_info.get('title', 'Unknown')}")
        
        # Check if it's a single song
        if not is_single_song(video_info):
            return (
                f"⚠️ Download blocked - this appears to be a compilation/album, not a single song.\n\n"
                f"- Title: {video_info.get('title', 'Unknown')}\n"
                f"- Duration: {video_info.get('duration', 0)} seconds\n\n"
                f"Try searching for a specific song title instead."
            )
        
        # Search existing library
        youtube_title = video_info.get("title", "")
        youtube_artist = video_info.get("uploader", "")
        
        existing_track = await asyncio.get_event_loop().run_in_executor(
            None, search_library_by_metadata, youtube_title, youtube_artist
        )
        
        if existing_track:
            logger.info("Found existing track in library")
            result = await asyncio.get_event_loop().run_in_executor(
                None, play_track, existing_track
            )
            return result
        
        # Download new track
        logger.info("Downloading new track")
        result = await asyncio.get_event_loop().run_in_executor(
            None, download_and_store_track, video_info, query
        )
        
        return result

    except Exception as e:
        error_msg = f"❌ Error processing request: {str(e)}"
        logger.error(error_msg)
        return error_msg

@mcp.tool()
async def stop_playback() -> str:
    """Stop any currently playing song.

    Returns:
        Success message or indication that no song was playing
    """
    def stop_current_song():
        try:
            if not pygame.mixer.get_init():
                return "🔇 Audio system not initialized - no music playing"

            pygame.mixer.music.stop()
            return "⏹️ Playback stopped"

        except Exception as e:
            logger.error(f"Stop error: {e}")
            return f"❌ Error stopping playback: {str(e)}"

    try:
        result = await asyncio.get_event_loop().run_in_executor(None, stop_current_song)
        return result
    except Exception as e:
        error_msg = f"❌ Error stopping playback: {str(e)}"
        logger.error(error_msg)
        return error_msg

@mcp.tool()
async def list_library() -> str:
    """List all songs in the music library.

    Returns:
        Formatted list of songs in the library
    """
    try:
        cleanup_result = await asyncio.get_event_loop().run_in_executor(
            None, cleanup_missing_files
        )
        
        all_tracks = db.all()
        
        if not all_tracks:
            return "🎵 Your music library is empty. Use download_and_play to add some songs!"
        
        response = f"🎵 Music Library ({len(all_tracks)} songs):\n\n"
        
        for i, track in enumerate(all_tracks, 1):
            title = track.get("title", "Unknown Title")
            artist = track.get("artist", "Unknown Artist")
            duration = track.get("duration")
            
            duration_str = ""
            if duration:
                minutes = duration // 60
                seconds = duration % 60
                duration_str = f" ({minutes}:{seconds:02d})"
            
            response += f"{i}. '{title}' by {artist}{duration_str}\n"
        
        if cleanup_result["removed"] > 0:
            response += f"\n🧹 Cleaned up {cleanup_result['removed']} missing files"
        
        return response
        
    except Exception as e:
        error_msg = f"❌ Error listing library: {str(e)}"
        logger.error(error_msg)
        return error_msg

if __name__ == "__main__":
    try:
        logger.info("Starting MCP Music Server")
        mcp.run(transport="stdio")
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        sys.exit(1)