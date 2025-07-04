# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "yt-dlp",
#     "fastmcp",
#     "tinydb",
#     "pygame",
# ]
# ///

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

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("llm_jukebox_mcp_debug.log"),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger(__name__)

mcp = FastMCP("LLM Jukebox")
download_path = Path(os.environ.get("DOWNLOAD_PATH", "./"))
download_path.mkdir(exist_ok=True)

db_path = download_path / "music_library.json"
db = TinyDB(db_path)
Track = Query()

logger.info(f"Starting LLM Jukebox MCP Server")
logger.info(f"Download path: {download_path}")
logger.info(f"Database path: {db_path}")

YT_DLP_BASE_OPTS = {
    "no_warnings": False,
    "audioquality": "0",  # Best quality
    "outtmpl": str(download_path / "%(title)s.%(ext)s"),
    "noplaylist": True,
}

def is_single_song(video_info: Dict[str, Any]) -> bool:
    """Check if a video appears to be a single song rather than a compilation/album.

    Args:
        video_info: Video information from yt-dlp

    Returns:
        True if it is a single song or False if not
    """
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

    if red_flags >= green_flags:
        return False

    return True

def cleanup_missing_files() -> Dict[str, int]:
    """Remove database entries for files that no longer exist on disk.

    Returns:
        Dict with 'total_checked', 'removed', and 'remaining' counts
    """
    logger.info("Starting cleanup of missing files from database")

    all_tracks = db.all()
    total_checked = len(all_tracks)
    removed_count = 0

    for track in all_tracks:
        file_path = Path(track.get("file_path", ""))
        if not file_path.exists():
            logger.warning(f"Removing missing file from database: {file_path}")
            db.remove(doc_ids=[track.doc_id])
            removed_count += 1
        else:
            logger.debug(f"File exists: {file_path}")

    remaining_count = total_checked - removed_count

    logger.info(
        f"Cleanup complete - checked: {total_checked}, removed: {removed_count}, remaining: {remaining_count}"
    )

    return {
        "total_checked": total_checked,
        "removed": removed_count,
        "remaining": remaining_count,
    }

def get_youtube_info(query: str) -> Optional[Dict[str, Any]]:
    """Get YouTube video information without downloading.
    
    Args:
        query: Search query for YouTube
        
    Returns:
        Video information dictionary or None if not found
    """
    info_opts = {
        "quiet": True,
        "no_warnings": False,
    }
    
    yt_query = f"ytsearch1:{query}"
    
    with yt_dlp.YoutubeDL(info_opts) as ydl:
        try:
            info = ydl.extract_info(yt_query, download=False)
            if not info or "entries" not in info or len(info["entries"]) == 0:
                return None
            
            return info["entries"][0]
            
        except Exception as e:
            logger.error(f"YouTube info extraction error: {str(e)}")
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
        title_match = Track.title.matches(f".*{re.escape(title)}.*", flags=re.IGNORECASE)
        artist_match = Track.artist.matches(f".*{re.escape(artist)}.*", flags=re.IGNORECASE)
        
        query_obj = title_match | artist_match
        tracks = db.search(query_obj)
        
        valid_tracks = []
        for track in tracks:
            file_path = Path(track.get("file_path", ""))
            if file_path.exists():
                valid_tracks.append(track)
            else:
                logger.warning(f"File missing during search: {file_path}")
                db.remove(doc_ids=[track.doc_id])
        
        return valid_tracks[0] if valid_tracks else None
        
    except Exception as e:
        logger.error(f"Library search error: {str(e)}")
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
        
        if not pygame.mixer.get_init():
            pygame.mixer.init()
            logger.info("Initialized audio system")

        try:
            pygame.mixer.music.load(str(file_path))
        except Exception as e:
            raise Exception(f"Failed to load audio file: {e}")

        pygame.mixer.music.play()

        logger.info(f"Playing: {track['title']} by {track['artist']}")
        return f"🎵 Now playing: '{track['title']}' by {track['artist']} (from library)"

    except Exception as e:
        logger.error(f"Playback error: {str(e)}")
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
            logger.info(f"Downloaded: {d['filename']}")

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
    }

    yt_query = f"ytsearch1:{query}"
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([yt_query])
            
            if downloaded_files:
                music_file = downloaded_files[0]
                music_file = os.path.splitext(music_file)[0] + ".mp3"

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

                existing = db.search(Track.file_path == music_file)
                if not existing:
                    db.insert(track_data)
                    logger.info(f"Added to music library: {title} by {artist}")

                result = play_track(track_data)

                success_msg = (
                    f"✅ Downloaded and playing: '{title}' by {artist}\n"
                    f"📁 File saved as: {Path(music_file).name}\n"
                    f"💾 Added to music library database.\n"
                )

                return success_msg
            else:
                return f"Download completed for: {query}, but no files were reported."
                
        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            raise

@mcp.tool()
async def download_and_play(query: str) -> str:
    """Search for and play a song. If the song is already in the library it will
        play the existing version, otherwise it will download it first.

    Args:
        query: Search query for music (artist, song, album, etc.)

    Returns:
        Success message with file info, or error message if download/play failed
    """
    logger.info(f"Starting download_and_play for query: {query}")

    try:
        video_info = await asyncio.get_event_loop().run_in_executor(
            None, get_youtube_info, query
        )
        
        if not video_info:
            return "No search results found on YouTube"
        
        if not is_single_song(video_info):
            logger.warning(f"Download blocked - appears to be compilation")
            return (
                f"❌ Download blocked - this appears to be a compilation/album, not a single song.\n\n"
                f"- Title: {video_info.get('title', 'Unknown')}")
        
        youtube_title = video_info.get("title", "")
        youtube_artist = video_info.get("uploader", "")
        
        existing_track = await asyncio.get_event_loop().run_in_executor(
            None, search_library_by_metadata, youtube_title, youtube_artist
        )
        
        if existing_track:
            logger.info(f"Found existing track: {existing_track['title']} by {existing_track['artist']}")
            result = await asyncio.get_event_loop().run_in_executor(
                None, play_track, existing_track
            )
            return result
        
        logger.info(f"Track not found in library, downloading: {youtube_title} by {youtube_artist}")
        
        start_time = datetime.now()
        result = await asyncio.get_event_loop().run_in_executor(
            None, download_and_store_track, video_info, query
        )
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logger.info(f"Download completed in {duration:.2f} seconds")
        return result

    except yt_dlp.DownloadError as e:
        logger.error(f"yt-dlp download error: {str(e)}")
        return f"Download failed: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected download error: {str(e)}")
        return f"Download error: {str(e)}"

@mcp.tool()
async def stop_playback() -> str:
    """Stop any currently playing song.

    Returns:
        Success message or indication that no song was playing
    """
    logger.info("Request to stop playback")

    def stop_current_song():
        try:
            if not pygame.mixer.get_init():
                msg = "Audio system not initialized"
                logger.warning(msg)
                return {"status": "not_initialized", "message": msg}

            try:
                pygame.mixer.music.stop()
                pygame.mixer.quit()
            except Exception as e:
                raise Exception(f"Failed to stop playback: {e}")

            msg = "Playback stopped"
            logger.info(msg)
            return msg

        except Exception as e:
            logger.error(f"Stop error: {str(e)}")
            return f"Stop error: {str(e)}"

    try:
        result = await asyncio.get_event_loop().run_in_executor(None, stop_current_song)
        return result
    except Exception as e:
        logger.error(f"Unexpected stop error: {str(e)}")
        return f"Stop error: {str(e)}"


if __name__ == "__main__":
    logger.info("Performing startup database cleanup...")
    startup_stats = cleanup_missing_files()
    if startup_stats["removed"] > 0:
        logger.info(
            f"Startup cleanup removed {startup_stats['removed']} missing files from database"
        )
    else:
        logger.info("No missing files found during startup cleanup")

    mcp.run(transport="stdio")
