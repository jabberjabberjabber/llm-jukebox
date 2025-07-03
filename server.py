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

def is_single_song(video_info: Dict[str, Any]) -> Dict[str, Any]:
    """Check if a video appears to be a single song rather than a compilation/album.
    
    Args:
        video_info: Video information from yt-dlp
        
    Returns:
        Dict with 'is_single_song' (bool), 'reason' (str), and 'confidence' (str)
    """
    title = video_info.get('title', '').lower()
    description = video_info.get('description', '').lower()
    duration = video_info.get('duration', 0)
    
    reasons = []
    red_flags = 0
    green_flags = 0
    
    # Check duration - most individual songs are 1-10 minutes
    if duration:
        if duration < 60:  # Less than 1 minute
            reasons.append(f"Very short duration ({duration}s)")
            red_flags += 1
        elif duration > 600:  # More than 10 minutes
            reasons.append(f"Long duration ({duration//60}m {duration%60}s) suggests compilation")
            red_flags += 2
        elif 120 <= duration <= 480:  # 2-8 minutes is typical for songs
            reasons.append(f"Good song length ({duration//60}m {duration%60}s)")
            green_flags += 2
        else:
            reasons.append(f"Acceptable duration ({duration//60}m {duration%60}s)")
            green_flags += 1
    
    # Check title for compilation indicators
    compilation_keywords = [
        'best of', 'greatest hits', 'compilation', 'full album', 'entire album',
        'complete album', 'whole album', 'album completo', 'discography',
        'collection', 'anthology', 'mix tape', 'mixtape', 'playlist',
        'all songs', 'todas las canciones', 'hours of', 'hour mix',
        'non stop', 'nonstop', 'continuous', 'mega mix', 'super mix'
    ]
    
    for keyword in compilation_keywords:
        if keyword in title:
            reasons.append(f"Title contains '{keyword}'")
            red_flags += 2
            break
    
    # Check for track count indicators in title
    import re
    track_patterns = [
        r'\d+\s*songs?', r'\d+\s*tracks?', r'\d+\s*hits?',
        r'\(\d+\s*songs?\)', r'\[\d+\s*tracks?\]'
    ]
    
    for pattern in track_patterns:
        if re.search(pattern, title):
            reasons.append("Title suggests multiple tracks")
            red_flags += 2
            break
    
    # Check description for compilation signs
    if description:
        desc_compilation_signs = [
            'track list', 'tracklist', 'track listing', 'song list',
            '1.', '2.', '3.',  # Numbered track listings
            '00:00', '01:', '02:',  # Timestamps suggesting multiple tracks
            'full album', 'complete album', 'entire album'
        ]
        
        compilation_indicators = sum(1 for sign in desc_compilation_signs if sign in description)
        if compilation_indicators >= 2:
            reasons.append("Description contains track listing or timestamps")
            red_flags += 2
        elif compilation_indicators == 1:
            red_flags += 1
    
    # Look for positive song indicators
    song_indicators = [
        'official video', 'official audio', 'music video', 'lyric video',
        'official lyric', 'lyrics', 'single', 'new single'
    ]
    
    for indicator in song_indicators:
        if indicator in title or indicator in description:
            reasons.append(f"Contains '{indicator}' suggesting single song")
            green_flags += 1
            break
    
    # Make decision
    is_single = red_flags <= green_flags
    confidence = "high" if abs(red_flags - green_flags) >= 2 else "medium" if abs(red_flags - green_flags) == 1 else "low"
    
    return {
        'is_single_song': is_single,
        'reason': ' | '.join(reasons) if reasons else 'No clear indicators found',
        'confidence': confidence,
        'red_flags': red_flags,
        'green_flags': green_flags,
        'duration_minutes': f"{duration//60}:{duration%60:02d}" if duration else "unknown"
    }

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
        file_path = Path(track.get('file_path', ''))
        if not file_path.exists():
            logger.warning(f"Removing missing file from database: {file_path}")
            db.remove(doc_ids=[track.doc_id])
            removed_count += 1
        else:
            logger.debug(f"File exists: {file_path}")
    
    remaining_count = total_checked - removed_count
    
    logger.info(f"Cleanup complete - checked: {total_checked}, removed: {removed_count}, remaining: {remaining_count}")
    
    return {
        'total_checked': total_checked,
        'removed': removed_count,
        'remaining': remaining_count
    }

# Internal helper function - not exposed as MCP tool
async def validate_song_internal(query: str) -> str:
    """Internal validation function - check if result appears to be a single song."""
    logger.info(f"Internal validation for query: {query}")
    yt_query = f'ytsearch1:{query}'
    
    def perform_validation():
        info_opts = {
            'quiet': True,
            'no_warnings': False,
        }
        
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            try:
                info = ydl.extract_info(yt_query, download=False)
                if not info or 'entries' not in info or len(info['entries']) == 0:
                    return None
                
                video_info = info['entries'][0]
                validation = is_single_song(video_info)
                
                return video_info, validation
                
            except Exception as e:
                logger.error(f"Validation error: {str(e)}")
                raise
    
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, perform_validation)
        return result
    except Exception as e:
        logger.error(f"Unexpected validation error: {str(e)}")
        return None

# Internal helper function - not exposed as MCP tool  
async def cleanup_database_internal() -> str:
    """Internal cleanup function - remove missing files from database."""
    logger.info("Internal database cleanup")
    
    try:
        stats = cleanup_missing_files()
        return f"Cleanup: checked {stats['total_checked']}, removed {stats['removed']}, remaining {stats['remaining']}"
    except Exception as e:
        logger.error(f"Error during database cleanup: {str(e)}")
        return f"Cleanup error: {str(e)}"

# Internal helper function - not exposed as MCP tool
async def search_youtube_music_internal(query: str, include_validation: bool = False) -> str:
    """Internal search function used by download_youtube_music."""
    logger.info(f"Internal search for query: {query}")
    query = f'ytsearch1:{query}'
    def perform_search():
        ydl_opts = {
            'quiet': True,
            'no_warnings': False,
            'extract_flat': not include_validation
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(query, download=False)
                
                if not info or 'entries' not in info or len(info['entries']) == 0:
                    return None, None
                
                first_result = info['entries'][0]
                if not first_result or 'id' not in first_result:
                    return None, None
                
                video_id = first_result['id']
                url = f"https://www.youtube.com/watch?v={video_id}"
                
                validation_result = None
                if include_validation:
                    validation_result = is_single_song(first_result)
                
                return url, validation_result
                
            except Exception as e:
                logger.error(f"Search error: {str(e)}")
                raise
    
    try:
        result, validation = await asyncio.get_event_loop().run_in_executor(None, perform_search)
        return result, validation
            
    except Exception as e:
        logger.error(f"Unexpected error in search: {str(e)}")
        return None, None

@mcp.tool()
async def download_youtube_music(query: str, force_download: bool = False) -> str:
    """	Search YouTube for music, download the first result, discard video, and add to music library.
    
    Args:
        query: Search query for music (artist, song, album, etc.)
        force_download: If True, bypass single-song validation and download anyway
        
    Returns:
        Success message with file info, or error message if download failed
    """
    logger.info(f"Starting download for query: {query} (force_download: {force_download})")
    yt_query = f'ytsearch1:{query}'
    
    def perform_download():
        downloaded_files = []
        video_info = None

        def progress_hook(d):
            if d['status'] == 'finished':
                downloaded_files.append(d['filename'])
                logger.info(f"Downloaded: {d['filename']}")

        # First, extract info to validate before downloading
        info_opts = {
            'quiet': True,
            'no_warnings': False,
        }
        
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            try:
                info = ydl.extract_info(yt_query, download=False)
                if not info or 'entries' not in info or len(info['entries']) == 0:
                    raise Exception("No search results found")
                
                video_info = info['entries'][0]
                
                # Validate if this appears to be a single song
                if not force_download:
                    validation = is_single_song(video_info)
                    logger.info(f"Song validation result: {validation}")
                    
                    if not validation['is_single_song']:
                        return None, video_info, validation
                
            except Exception as e:
                logger.error(f"Info extraction error: {str(e)}")
                raise

        # Proceed with download if validation passed or was forced
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
                ydl.download([yt_query])
                return downloaded_files, video_info, None
            except Exception as e:
                logger.error(f"Download error: {str(e)}")
                raise
    
    try:
        start_time = datetime.now()
        downloaded_files, video_info, validation_result = await asyncio.get_event_loop().run_in_executor(None, perform_download)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Handle validation failure
        if validation_result and not force_download:
            logger.warning(f"Download blocked - appears to be compilation: {validation_result['reason']}")
            return f"❌ Download blocked - this appears to be a compilation/album, not a single song.\n\n" \
                   f"📊 Analysis:\n" \
                   f"- Duration: {validation_result['duration_minutes']}\n" \
                   f"- Reason: {validation_result['reason']}\n" \
                   f"- Confidence: {validation_result['confidence']}\n" \
                   f"- Title: {video_info.get('title', 'Unknown')}\n\n" \
                   f"💡 If you're sure this is a single song, use force_download=True to override this check."
        
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
                'youtube_url': video_info.get('webpage_url', ''),
                'forced_download': force_download
            }
            
            existing = db.search(Track.file_path == music_file)
            if not existing:
                db.insert(track_data)
                logger.info(f"Added to music library: {title} by {artist}")
            
            success_msg = f"✅ Successfully downloaded song: '{title}' by {artist}\n" \
                         f"📁 File saved as: {Path(music_file).name}\n" \
                         f"💾 Added to music library database."
            
            if force_download:
                success_msg += f"\n⚠️  Note: Validation was bypassed (forced download)"
            
            return success_msg
        else:
            return f"Download completed for: {query}, but no files were reported"
            
    except yt_dlp.DownloadError as e:
        logger.error(f"yt-dlp download error: {str(e)}")
        return f"Download failed: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected download error: {str(e)}")
        return f"Download error: {str(e)}"

@mcp.tool()
async def list_music_library(limit: int = 50, artist: Optional[str] = None, search: Optional[str] = None, cleanup: bool = True) -> str:
    """	List tracks in the music library with optional filtering.
    
    Args:
        limit: Maximum number of tracks to return (default: 50)
        artist: Filter by artist name (optional)
        search: Search in title or artist (optional)
        
    Returns:
        JSON formatted list of tracks in the music library
    """
    logger.info(f"Listing music library - limit: {limit}, artist: {artist}, search: {search}")
    
    try:
        # Always perform cleanup of missing files
        cleanup_stats = cleanup_missing_files()
        
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
        
        # Additional file existence check (in case files were deleted since cleanup)
        valid_tracks = []
        for track in tracks:
            file_path = Path(track.get('file_path', ''))
            if file_path.exists():
                valid_tracks.append(track)
            else:
                logger.warning(f"File missing during listing: {file_path}")
                # Remove from database immediately
                db.remove(doc_ids=[track.doc_id])
        
        valid_tracks.sort(key=lambda x: x.get('download_date', ''), reverse=True)
        limited_tracks = valid_tracks[:limit]
        
        formatted_tracks = []
        for track in limited_tracks:
            formatted_tracks.append({
                'id': track.doc_id,
                'title': track.get('title', 'Unknown'),
                'artist': track.get('artist', 'Unknown')
            })
        
        result = {
            'total_tracks': len(valid_tracks),
            'showing': len(limited_tracks),
            'tracks': formatted_tracks,
            'cleanup_performed': cleanup_stats
        }
        
        logger.info(f"Retrieved {len(limited_tracks)} valid tracks from library")
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Error listing music library: {str(e)}")
        return f"Error listing music library: {str(e)}"

@mcp.tool()
async def play_song(identifier: Union[int, str]) -> str:
    """	Play a song from the music library by ID or title search.
        The song will play in the background and you may resume the
        chat upon the success of this tool.
    
    Args:
        identifier: Database ID (integer)
        
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
                return f"Error: indentifier must be an integer"
                
            file_path = Path(track['file_path'])
            if not file_path.exists():
                # Remove from database since file doesn't exist
                db.remove(doc_ids=[track.doc_id])
                return f"Audio file not found: {file_path}. Removed from database."
            
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

if __name__ == "__main__":
    # Perform startup cleanup
    logger.info("Performing startup database cleanup...")
    startup_stats = cleanup_missing_files()
    if startup_stats['removed'] > 0:
        logger.info(f"Startup cleanup removed {startup_stats['removed']} missing files from database")
    else:
        logger.info("No missing files found during startup cleanup")
    
    mcp.run(transport="stdio")