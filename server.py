# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "yt-dlp",
#     "fastmcp",
# ]
# ///

import asyncio
import json
import sys
import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

import yt_dlp
from fastmcp import FastMCP

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

logger.info(f"Starting LLM Jukebox MCP Server")
logger.info(f"Download path: {download_path}")

YT_DLP_BASE_OPTS = {
    'no_warnings': False,
    'audioquality': '0',  # Best quality
    'outtmpl': str(download_path / '%(title)s.%(ext)s'),
    'noplaylist': True,
}

@mcp.tool()
async def test_ytdlp() -> str:
    """	Test if yt-dlp Python module is working and accessible.
    
    Returns:
        yt-dlp version info or error message
    """
    logger.info("Testing yt-dlp Python module accessibility")
    try:
        def get_version():
            return yt_dlp.version.__version__
        
        version = await asyncio.get_event_loop().run_in_executor(None, get_version)
        logger.info(f"yt-dlp version: {version}")
        return f"yt-dlp Python module is working! Version: {version}"
        
    except Exception as e:
        logger.error(f"Error testing yt-dlp: {str(e)}")
        return f"yt-dlp Python module error: {str(e)}"

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
    """	Search YouTube for music and download the first result and convert to mp3.
    
    Args:
        query: Search query for music (artist, song, album, etc.)
        
    Returns:
        Success message with file path, or error message if download failed
    """
    logger.info(f"Starting download for query: {query}")
    yt_query = f'ytsearch1:{query}'
    def perform_download():
        downloaded_files = []

        def progress_hook(d):
            if d['status'] == 'finished':
                downloaded_files.append(d['filename'])
                logger.info(f"Downloaded: {d['filename']}")
        
        ydl_opts = {
            **YT_DLP_BASE_OPTS,
            #'extract_flat': 'discard_in_playlist',
            'final_ext': 'mp3',
            'format': 'ba[acodec^=mp3]/ba/b',
            #'ignoreerrors': 'only_download',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'nopostoverwrites': False, 'preferredcodec': 'mp3', 'preferredquality': '0'}, {'key': 'FFmpegConcat', 'only_multi_video': True, 'when': 'playlist'}],
            'progress_hooks': [progress_hook], 
            #'retries': 10 
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.download([yt_query])
                return downloaded_files
            except Exception as e:
                logger.error(f"Download error: {str(e)}")
                raise
    
    try:
        start_time = datetime.now()
        downloaded_files = await asyncio.get_event_loop().run_in_executor(None, perform_download)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.info(f"Download completed in {duration:.2f} seconds")
        
        if downloaded_files:
            files_list = '\n'.join(downloaded_files)
            return f"Successfully downloaded audio for: {query}\nFiles:\n{files_list}"
        else:
            return f"Download completed for: {query}, but no files were reported"
            
    except yt_dlp.DownloadError as e:
        logger.error(f"yt-dlp download error: {str(e)}")
        return f"Download failed: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected download error: {str(e)}")
        return f"Download error: {str(e)}"

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