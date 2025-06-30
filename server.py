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
from datetime import datetime
from typing import Optional, Dict, Any, List, Union
from pathlib import Path

import yt_dlp
import pygame.mixer
from fastmcp import FastMCP
from tinydb import TinyDB, Query

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('llm_jukebox_mcp_debug.log'),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

mcp = FastMCP("LLM Jukebox")
download_path = Path(os.environ.get("DOWNLOAD_PATH", "./"))
download_path.mkdir(exist_ok=True)

db_path = download_path / 'music_library.json'
db = TinyDB(db_path)
Track = Query()

logger.info(f"Starting LLM Jukebox MCP Server")
logger.info(f"Download path: {download_path}")
logger.info(f"Database path: {db_path}")

YT_DLP_BASE_OPTS = {
    'no_warnings': False,
    'audioquality': '0',  # Best quality
    'outtmpl': str(download_path / '%(title)s.%(ext)s'),
    'noplaylist': True,
}

@mcp.tool()
async def search_youtube_music(query: str) -> str:
    """	Search YouTube for music and return the watch URL of the first result.
    
    Args:
        query: Search query for music (artist, song, album, etc.)
        
    Returns:
        YouTube watch URL of the first result, or error message if no results found
    """
    logger.info(f"Starting search for query: {query}")
    query = f'ytsearch1:{query}'
    def perform_search():
        ydl_opts = {
            'quiet': True,
            'no_warnings': False,
            'extract_flat': True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(query, download=False)
                
                if not info or 'entries' not in info or len(info['entries']) == 0:
                    return None
                
                first_result = info['entries'][0]
                if not first_result or 'id' not in first_result:
                    return None
                
                video_id = first_result['id']
                return f"https://www.youtube.com/watch?v={video_id}"
                
            except Exception as e:
                logger.error(f"Search error: {str(e)}")
                raise
    
    try:
        start_time = datetime.now()
        result = await asyncio.get_event_loop().run_in_executor(None, perform_search)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.info(f"Search completed in {duration:.2f} seconds")
        
        if result:
            logger.info(f"Successfully found video: {result}")
            return result
        else:
            logger.warning(f"No results found for query: {query}")
            return f"No results found for: {query}"
            
    except Exception as e:
        logger.error(f"Unexpected error in search: {str(e)}")
        return f"Search error: {str(e)}"

@mcp.tool()
async def download_youtube_music(query: str) -> str:
    """	Search YouTube for music, download the first result, discard video, and add to music library.
    
    Args:
        query: Search query for music (artist, song, album, etc.)
        
    Returns:
        Success message with file info, or error message if download failed
    """
    logger.info(f"Starting download for query: {query}")
    yt_query = f'ytsearch1:{query}'
    
    def perform_download():
        downloaded_files = []
        video_info = None

        def progress_hook(d):
            if d['status'] == 'finished':
                downloaded_files.append(d['filename'])
                logger.info(f"Downloaded: {d['filename']}")

        ydl_opts = {
            **YT_DLP_BASE_OPTS,
            'format': 'bestaudio/best',
            'postprocessors': [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }
            ],
            'progress_hooks': [progress_hook], 
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(yt_query, download=False)
                if info and 'entries' in info and len(info['entries']) > 0:
                    video_info = info['entries'][0]
                
                ydl.download([yt_query])
                return downloaded_files, video_info
            except Exception as e:
                logger.error(f"Download error: {str(e)}")
                raise
    
    try:
        start_time = datetime.now()
        downloaded_files, video_info = await asyncio.get_event_loop().run_in_executor(None, perform_download)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.info(f"Download completed in {duration:.2f} seconds")
        
        if downloaded_files and video_info:
            music_file = downloaded_files[0]
            music_file = os.path.splitext(music_file)[0] + '.mp3'

            title = video_info.get('title', 'Unknown Title')
            artist = video_info.get('uploader', 'Unknown Artist')
            duration_seconds = video_info.get('duration')
            
            track_data = {
                'title': title,
                'artist': artist,
                'file_path': music_file,
                'download_date': datetime.now().isoformat(),
                'duration': duration_seconds,
                'original_query': query,
                'youtube_url': video_info.get('webpage_url', '')
            }
            
            existing = db.search(Track.file_path == music_file)
            if not existing:
                db.insert(track_data)
                logger.info(f"Added to music library: {title} by {artist}")
            
            return f"Successfully downloaded song: '{title}' by {artist}\nFile saved as: {Path(music_file).name}\nAdded to music library database."
        else:
            return f"Download completed for: {query}, but no files were reported"
            
    except yt_dlp.DownloadError as e:
        logger.error(f"yt-dlp download error: {str(e)}")
        return f"Download failed: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected download error: {str(e)}")
        return f"Download error: {str(e)}"

@mcp.tool()
async def list_music_library(limit: int = 20, artist: Optional[str] = None, search: Optional[str] = None) -> str:
    """	List tracks in the music library with optional filtering.
    
    Args:
        limit: Maximum number of tracks to return (default: 20)
        artist: Filter by artist name (optional)
        search: Search in title or artist (optional)
        
    Returns:
        JSON formatted list of tracks in the music library
    """
    logger.info(f"Listing music library - limit: {limit}, artist: {artist}, search: {search}")
    
    try:
        query_obj = Track
        
        if artist:
            query_obj = query_obj.artist.matches(f'.*{artist}.*', flags=0)  # Case insensitive
        
        if search:
            title_match = Track.title.matches(f'.*{search}.*', flags=0)
            artist_match = Track.artist.matches(f'.*{search}.*', flags=0)
            query_obj = (title_match | artist_match)
        
        if artist or search:
            tracks = db.search(query_obj)
        else:
            tracks = db.all()
        
        tracks.sort(key=lambda x: x.get('download_date', ''), reverse=True)
        limited_tracks = tracks[:limit]
        
        formatted_tracks = []
        for track in limited_tracks:
            duration_str = ""
            if track.get('duration'):
                mins, secs = divmod(track['duration'], 60)
                duration_str = f" ({mins}:{secs:02d})"
            
            formatted_tracks.append({
                'id': track.doc_id,
                'title': track.get('title', 'Unknown'),
                'artist': track.get('artist', 'Unknown'),
                'filename': Path(track.get('file_path', '')).name,
                'duration': duration_str,
                'download_date': track.get('download_date', '')[:10] if track.get('download_date') else ''
            })
        
        result = {
            'total_tracks': len(tracks),
            'showing': len(limited_tracks),
            'tracks': formatted_tracks
        }
        
        logger.info(f"Retrieved {len(limited_tracks)} tracks from library")
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Error listing music library: {str(e)}")
        return f"Error listing music library: {str(e)}"

@mcp.tool()
async def play_song(identifier: Union[int, str]) -> str:
    """	Play a song from the music library by ID or title search.
    
    Args:
        identifier: Either a database ID (integer) or song title (string) to search for
        
    Returns:
        Success message with song info, or error message if song not found or playback failed
    """
    logger.info(f"Request to play song: {identifier}")
    
    def find_and_play_song():
        try:
            if isinstance(identifier, int):
                track = db.get(doc_id=identifier)
                if not track:
                    return f"No track found with ID: {identifier}"
            else:
                matches = db.search(Track.title.matches(f'.*{identifier}.*', flags=0))
                if not matches:
                    return f"No track found matching title: {identifier}"
                elif len(matches) > 1:
                    titles = [f"ID {track.doc_id}: {track['title']}" for track in matches[:5]]
                    return f"Multiple matches found. Please be more specific or use ID:\n" + "\n".join(titles)
                track = matches[0]
            
            file_path = Path(track['file_path'])
            if not file_path.exists():
                return f"Audio file not found: {file_path}"
            
            supported_formats = {'.mp3', '.ogg', '.wav'}
            if file_path.suffix.lower() not in supported_formats:
                return f"Unsupported audio format: {file_path.suffix}. Try re-downloading to get .mp3 format."
            
            if not pygame.mixer.get_init():
                pygame.mixer.init()
                logger.info("Initialized audio system")
            
            pygame.mixer.music.stop()
            
            try:
                pygame.mixer.music.load(str(file_path))
            except Exception as e:
                raise Exception(f"Failed to load audio file: {e}")
            
            pygame.mixer.music.play()
            
            logger.info(f"Playing: {track['title']} by {track['artist']}")
            return f"Now playing: '{track['title']}' by {track['artist']}"
            
        except Exception as e:
            logger.error(f"Playback error: {str(e)}")
            return f"Playback error: {str(e)}"
    
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, find_and_play_song)
        return result
    except Exception as e:
        logger.error(f"Unexpected playback error: {str(e)}")
        return f"Playback error: {str(e)}"

@mcp.tool()
async def stop_playback() -> str:
    """	Stop any currently playing song.
        
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

@mcp.tool()
async def get_youtube_info(url: str) -> str:
    """	Get information about a YouTube video without downloading.
    
    Args:
        url: YouTube URL or video ID
        
    Returns:
        JSON formatted information about the video or song
    """
    logger.info(f"Getting info for URL: {url}")
    
    def extract_info():
        ydl_opts = {
            'quiet': True,
            'no_warnings': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                return info
            except Exception as e:
                logger.error(f"Info extraction error: {str(e)}")
                raise
    
    try:
        start_time = datetime.now()
        info = await asyncio.get_event_loop().run_in_executor(None, extract_info)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.info(f"Info extraction completed in {duration:.2f} seconds")
        
        formatted_info = {
            "title": info.get("title", "N/A"),
            "uploader": info.get("uploader", "N/A"),
            "duration": info.get("duration", "N/A"),
            "view_count": info.get("view_count", "N/A"),
            "upload_date": info.get("upload_date", "N/A"),
            "webpage_url": info.get("webpage_url", "N/A"),
            "description": (info.get("description", "N/A")[:200] + "..." 
                          if info.get("description") and len(info.get("description", "")) > 200 
                          else info.get("description", "N/A"))
        }
        
        return json.dumps(formatted_info, indent=2)
        
    except yt_dlp.DownloadError as e:
        logger.error(f"yt-dlp info error: {str(e)}")
        return f"Failed to get video info: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected info error: {str(e)}")
        return f"Info extraction error: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="stdio")